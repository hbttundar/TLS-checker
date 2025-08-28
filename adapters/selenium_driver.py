import os
import tempfile
import uuid
import logging
from typing import Any
from selenium import webdriver  # type: ignore
from selenium.webdriver.chrome.service import Service  # type: ignore
from webdriver_manager.chrome import ChromeDriverManager  # type: ignore

class ChromeDriverFactory:
    def __init__(
        self,
        user_data_dir: str,
        headless: bool,
        window_size: str,
        stealth: bool = True,
        remote_debug_port: int | None = None,
        user_agent: str | None = None,
    ):
        self._user_data_dir = user_data_dir
        self._headless = headless
        self._window_size = window_size
        self._stealth = stealth
        self._remote_debug_port = remote_debug_port
        self._user_agent = user_agent

    def create(self) -> Any:  # returns selenium webdriver instance
        logger = logging.getLogger("selenium_driver")
        profile_dir = self._user_data_dir
        os.makedirs(profile_dir, exist_ok=True)

        def _build_options(using_dir: str):
            opts = webdriver.ChromeOptions()
            chrome_bin = os.environ.get("CHROME_BIN")
            if chrome_bin:
                opts.binary_location = chrome_bin  # type: ignore
            opts.add_argument(f"--user-data-dir={using_dir}")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-gpu")
            opts.add_argument(f"--window-size={self._window_size}")
            if self._headless:
                opts.add_argument("--headless=new")
            if self._stealth:
                opts.add_argument("--disable-blink-features=AutomationControlled")
                opts.add_experimental_option("excludeSwitches", ["enable-automation"])  # remove infobar
                opts.add_experimental_option("useAutomationExtension", False)
            if self._user_agent:
                opts.add_argument(f"--user-agent={self._user_agent}")
            if self._remote_debug_port:
                opts.add_argument(f"--remote-debugging-port={self._remote_debug_port}")
            # Reduce fingerprint / resource issues
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-infobars")
            opts.add_argument("--disable-extensions")
            return opts

        def _make_driver(using_dir: str):
            opts = _build_options(using_dir)
            chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
            if chromedriver_path and os.path.exists(chromedriver_path):
                service = Service(executable_path=chromedriver_path)  # type: ignore[arg-type]
            else:
                service = Service(ChromeDriverManager().install())  # type: ignore[arg-type]
            return webdriver.Chrome(service=service, options=opts)  # type: ignore

        try:
            driver = _make_driver(profile_dir)
        except Exception as e:  # broad to catch SessionNotCreatedException without hard selenium import path
            msg = str(e).lower()
            if "user data directory is already in use" in msg:
                # Fallback: ephemeral unique profile (CI parallelism or stale lock)
                tmp_dir = os.path.join(tempfile.gettempdir(), f"tlsprofile-{uuid.uuid4().hex}")
                os.makedirs(tmp_dir, exist_ok=True)
                logger.warning(
                    "profile directory locked; using temporary directory instead",
                    extra={"original": profile_dir, "temp": tmp_dir},
                )
                driver = _make_driver(tmp_dir)
            else:
                raise

        if self._stealth:
            try:
                driver.execute_cdp_cmd(  # type: ignore[attr-defined]
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
                )
            except Exception:
                pass
        return driver
