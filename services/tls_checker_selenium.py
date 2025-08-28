"""Selenium-based TLScontact checker.

Responsibilities:
 - Maintain a logged-in browser session (heuristic login detection).
 - Classify current page HTML into semantic statuses (NO_SLOTS, MAYBE_SLOTS, CAPTCHA, BLOCKED, OK).
 - Provide lightweight refresh & status access for the monitor.

Improvements over earlier version:
 - Structured logging instead of prints.
 - Error handling around driver operations (WebDriverException resilience).
 - Caches last status & timestamp to avoid excessive DOM parsing.
 - Safer login loop with timeout and exception suppression.
"""
import time
import logging
from dataclasses import dataclass
from typing import Optional, Protocol
from ports.checker import TLSChecker


class Browser(Protocol):  # minimal protocol to decouple from selenium stubs
    current_url: str
    page_source: str
    def get(self, url: str) -> None: ...
    def refresh(self) -> None: ...
    def quit(self) -> None: ...

class WebDriverException(Exception):  # generic placeholder; real selenium exception will subclass Exception
    """Local stand-in for selenium.webdriver.WebDriverException when selenium not imported in tests."""
    pass

class TLSStatus:
    OK = "OK"
    NO_SLOTS = "NO_SLOTS"
    MAYBE_SLOTS = "MAYBE_SLOTS"
    CAPTCHA = "CAPTCHA"
    BLOCKED = "BLOCKED"

@dataclass
class StatusSnapshot:
    status: str
    at: float
    raw_length: int


class SeleniumTLSChecker(TLSChecker):
    def __init__(self, driver: Browser, login_url: str,
                 negative_markers: tuple[str, ...],
                 login_wait_seconds: int,
                 captcha_markers: tuple[str, ...] = (),
                 block_markers: tuple[str, ...] = (),
                 logger: Optional[logging.Logger] = None,
                 status_cache_ttl: float = 2.0):
        self._driver = driver
        self._login_url = login_url
        self._neg = negative_markers
        self._login_wait = login_wait_seconds
        self._captcha = captcha_markers
        self._block = block_markers
        self._logged_in = False
        self._log = logger or logging.getLogger("tls_checker")
        self._status_cache_ttl = status_cache_ttl
        self._last_snapshot: Optional[StatusSnapshot] = None

    def ensure_logged_in(self) -> None:
        if self._logged_in:
            return
        try:
            self._driver.get(self._login_url)
        except WebDriverException as e:
            self._log.error("initial navigation failed", exc_info=e)
            raise
        self._log.info("waiting for manual login / captcha solve", extra={"timeout": self._login_wait})
        deadline = time.time() + self._login_wait
        poll = 2
        while time.time() < deadline:
            time.sleep(poll)
            try:
                current = self._driver.current_url
            except WebDriverException:
                # transient, continue
                continue
            if "/login" not in current:
                self._logged_in = True
                self._log.info("login heuristically confirmed", extra={"current_url": current})
                return
        self._log.warning("login not confirmed after timeout; proceeding anyway")

    def _classify(self, html: str) -> str:
        html_lower = (html or "").lower()
        try:
            if any(m in html_lower for m in self._captcha):
                return TLSStatus.CAPTCHA
            if any(m in html_lower for m in self._block):
                return TLSStatus.BLOCKED
            if any(m in html_lower for m in self._neg):
                return TLSStatus.NO_SLOTS
            # baseline living page; MAYBE_SLOTS is optimistic when negatives absent
            return TLSStatus.MAYBE_SLOTS
        except Exception as e:  # defensive classification failure
            self._log.error("classification error", exc_info=e)
            return TLSStatus.OK

    def has_no_slots(self) -> bool:
        # kept for backward compat if used elsewhere
        return self.last_status() == TLSStatus.NO_SLOTS

    def last_status(self) -> str:
        # Serve from cache if fresh
        now = time.time()
        snap = self._last_snapshot
        if snap and (now - snap.at) < self._status_cache_ttl:
            return snap.status
        try:
            html = (self._driver.page_source or "")
        except WebDriverException as e:
            self._log.warning("page_source failed", exc_info=e)
            return TLSStatus.BLOCKED  # treat as blocked / error
        status = self._classify(html)
        self._last_snapshot = StatusSnapshot(status=status, at=now, raw_length=len(html))
        return status

    def refresh(self) -> None:
        try:
            self._driver.refresh()
        except WebDriverException as e:
            self._log.warning("refresh failed, attempting recovery", exc_info=e)
            # attempt lightweight recovery: navigate back to login/root
            try:
                self._driver.get(self._login_url)
            except Exception:
                self._log.error("driver recovery navigation failed", exc_info=True)

    def close(self) -> None:
        try:
            self._driver.quit()
        except Exception as e:
            self._log.debug("driver quit error ignored", exc_info=e)
