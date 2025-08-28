"""Bot entrypoint.

Responsibilities:
 - Load configuration & dotenv
 - Wire adapters (Telegram notifier, subscriber store, Selenium checker)
 - Start monitoring background thread
 - Expose Telegram commands: /start, /subscribe, /unsubscribe, /status
"""
from __future__ import annotations

import asyncio
import logging
import signal
import os
from contextlib import suppress

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import Config
from ports.subscribers import SubscriberStore
from adapters.subscribers_file import FileSubscriberStore
from adapters.selenium_driver import ChromeDriverFactory
from adapters.telegram_notifier import TelegramNotifier
from services.tls_checker_selenium import SeleniumTLSChecker
from services.limits import RateLimiter, CircuitBreaker
from services.monitor import MonitorService


def setup_logging(cfg: Config):
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
            if cfg.log_format == "text"
            else '{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        ),
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def build_subscriber_store(cfg: Config) -> SubscriberStore:
    backend = cfg.subscriber_backend.lower()
    if backend == "file":
        return FileSubscriberStore(cfg.subscribers_file)
    # memory fallback
    class MemoryStore(SubscriberStore):  # simple ephemeral store
        def __init__(self):
            self._s: set[int] = set()

        def add(self, chat_id: int) -> bool:
            if chat_id in self._s:
                return False
            self._s.add(chat_id)
            return True

        def remove(self, chat_id: int) -> bool:
            if chat_id not in self._s:
                return False
            self._s.remove(chat_id)
            return True

        def all(self):
            return tuple(self._s)

        def count(self):
            return len(self._s)

        def exists(self, chat_id: int) -> bool:
            return chat_id in self._s
    return MemoryStore()


async def main() -> int:
    load_dotenv()  # .env if present
    cfg = Config.load()
    setup_logging(cfg)
    log = logging.getLogger("bot")
    log.info("starting bot")

    offline = os.getenv("OFFLINE", "").lower() in ("1", "true", "yes", "on")

    if offline:
        class DummyApp:  # minimal surface to avoid AttributeError
            bot: object | None = None

            def add_handler(self, *args: object, **kwargs: object) -> None:  # noqa: D401 - simple stub
                return None

            async def start(self) -> None:  # pragma: no cover - trivial
                return None

            async def stop(self) -> None:  # pragma: no cover - trivial
                return None

            async def __aenter__(self) -> "DummyApp":
                return self

            async def __aexit__(self, *exc_info: object) -> bool:  # noqa: D401
                return False

        class DummyNotifier:
            async def send(self, chat_id: int, message: str) -> None:  # pragma: no cover - logging side effect
                log.info("[offline notifier] %s -> %s", chat_id, message)

        app = DummyApp()  # type: ignore[assignment]
        notifier = DummyNotifier()  # type: ignore[assignment]
    else:
        # Telegram application (async)
        app = Application.builder().token(cfg.telegram_token).build()
        notifier = TelegramNotifier(app)

    # Subscribers
    subscribers = build_subscriber_store(cfg)

    # Selenium checker (could be replaced with alternative implementation)
    fake_driver = os.getenv("FAKE_DRIVER", "").lower() in ("1","true","yes","on")
    if fake_driver:
        class FakeDriver:
            current_url = "https://example.com/app"
            page_source = "<html>No appointment available</html>"
            def get(self, url: str):
                self.current_url = url
            def refresh(self):
                pass
            def quit(self):
                pass
        driver = FakeDriver()
    else:
        driver_factory = ChromeDriverFactory(
            cfg.user_data_dir,
            cfg.headless,
            cfg.window_size,
            cfg.stealth_mode,
            cfg.remote_debug_port,
            cfg.custom_user_agent,
        )
        driver = driver_factory.create()

    checker = SeleniumTLSChecker(
        driver=driver,
        login_url=cfg.tls_login_url,
        negative_markers=cfg.negative_patterns,
        login_wait_seconds=cfg.login_wait_seconds,
        captcha_markers=cfg.captcha_markers,
        block_markers=cfg.block_markers,
    )

    limiter = RateLimiter(cfg.min_check_interval, cfg.max_check_interval, cfg.jitter_ratio)
    breaker = CircuitBreaker(
        cfg.failure_threshold,
        cfg.cooldown_on_captcha,
        cfg.error_backoff_base,
        cfg.error_backoff_max,
    )
    loop = asyncio.get_running_loop()
    monitor = MonitorService(
        checker=checker,
        notifier=notifier,
        subscribers=subscribers,
        interval_seconds=cfg.check_interval,
        limiter=limiter,
        breaker=breaker,
        loop=loop,
        logger=logging.getLogger("monitor"),
    )

    # Optionally ensure login (solve Cloudflare / CAPTCHA) before monitor starts refreshing.
    if not offline and not fake_driver and cfg.start_monitor_after_login:
        try:
            checker.ensure_logged_in()
        except Exception as e:
            log.error("login phase failed", exc_info=e)
    monitor.start()

    # ---- Telegram command handlers ----
    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
        if not update.message:
            return
        await update.message.reply_text("Hi. Use /subscribe to get notifications.")

    async def cmd_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
        if not update.message or not update.effective_chat:
            return
        cid = update.effective_chat.id
        user = update.effective_user
        if cfg.whitelist_usernames and user and user.username:
            if user.username.lower() not in cfg.whitelist_usernames:
                await update.message.reply_text("Not authorized.")
                return
        added = subscribers.add(cid)
        if added:
            await update.message.reply_text("Subscribed. You'll receive notifications when slots appear.")
        else:
            await update.message.reply_text("Already subscribed.")

    async def cmd_unsub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
        if not update.message or not update.effective_chat:
            return
        cid = update.effective_chat.id
        removed = subscribers.remove(cid)
        if removed:
            await update.message.reply_text("Unsubscribed.")
        else:
            await update.message.reply_text("You were not subscribed.")

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG001
        if not cfg.enable_status_command or not update.message:
            return
        last_status = getattr(checker, "last_status", lambda: "?")()
        breaker_state = breaker.state()
        lines = [
            f"Monitor running: {monitor.is_running()}",
            f"Subscribers: {subscribers.count()}",
            f"Last status: {last_status}",
            f"Failures: {breaker_state.failures}/{breaker_state.threshold}",
            f"Breaker open: {breaker_state.open}",
            f"Last breaker action: {breaker_state.last_action or '-'}",
        ]
        await update.message.reply_text("\n".join(lines))

    if not offline:
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("subscribe", cmd_sub))
        app.add_handler(CommandHandler("sub", cmd_sub))
        app.add_handler(CommandHandler("unsubscribe", cmd_unsub))
        app.add_handler(CommandHandler("unsub", cmd_unsub))
        if cfg.enable_status_command:
            app.add_handler(CommandHandler("status", cmd_status))

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _handle_sig(*_siginfo: object) -> None:
        log.info("signal received, shutting down")
        stop_event.set()

    with suppress(NotImplementedError):
        loop.add_signal_handler(signal.SIGTERM, _handle_sig)
        loop.add_signal_handler(signal.SIGINT, _handle_sig)

    if offline:
        log.warning("running in OFFLINE mode (no Telegram connection, fake driver=%s)", fake_driver)
        await asyncio.sleep(5)  # demo window
        stop_event.set()
    else:
        async with app:  # real mode
            await app.start()
            log.info("bot started")
            await stop_event.wait()
            log.info("stopping bot")
            await app.stop()
    monitor.stop()
    # attempt to join thread briefly (public API)
    monitor.join(timeout=5)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
