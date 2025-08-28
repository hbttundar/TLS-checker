"""Monitoring service.

Extracted into its own module to keep the thread + retry logic decoupled
from the bot wiring. The design is intentionally small (KISS) while
exposing clear extension points (checker, notifier, subscribers, limiter,
breaker) which aligns with SRP / DIP from SOLID.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from ports.checker import TLSChecker
from ports.notifier import Notifier
from ports.subscribers import SubscriberStore
from services.limits import RateLimiter, CircuitBreaker
from services.tls_checker_selenium import TLSStatus


class MonitorService:
    """Run periodic TLS status checks and notify subscribers.

    Public methods: start(), stop(), is_running().
    Remaining helpers are internal and covered by tests to ensure behavior.
    """

    def __init__(
        self,
        checker: TLSChecker,
        notifier: Notifier,
        subscribers: SubscriberStore,
        interval_seconds: int,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
        loop: asyncio.AbstractEventLoop | None = None,
        logger: logging.Logger | None = None,
        max_driver_restarts: int = 2,  # reserved for future driver recycle feature
    ) -> None:
        self._checker = checker
        self._notifier = notifier
        self._subs = subscribers
        self._interval = interval_seconds
        self._limiter = limiter
        self._breaker = breaker
        self._loop = loop
        self._log = logger or logging.getLogger("monitor")
        self._max_driver_restarts = max_driver_restarts
        self._driver_restarts = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_no_slots: bool | None = None

    # --- lifecycle -------------------------------------------------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        """Join the monitor thread (graceful shutdown helper)."""
        if self._thread and self._thread.is_alive():  # pragma: no branch
            self._thread.join(timeout=timeout)

    # --- notification ----------------------------------------------
    def _broadcast(self, text: str) -> None:
        for cid in self._subs.all():
            if self._loop:
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._notifier.send(cid, text), self._loop
                    )

                    def _cb(f: Any) -> None:
                        try:
                            exc = f.exception()
                        except Exception as cb_e:  # pragma: no cover
                            self._log.warning(
                                "notify callback failure",
                                exc_info=cb_e,
                                extra={"chat_id": cid},
                            )
                            return
                        if exc:
                            self._log.warning(
                                "notify error", exc_info=exc, extra={"chat_id": cid}
                            )

                    fut.add_done_callback(_cb)
                except Exception as e:  # scheduling failure
                    self._log.warning(
                        "failed to schedule notification",
                        exc_info=e,
                        extra={"chat_id": cid},
                    )
            else:  # blocking fallback
                try:
                    asyncio.run(self._notifier.send(cid, text))
                except Exception as e:  # pragma: no cover - rare
                    self._log.warning(
                        "notify error (fallback)",
                        exc_info=e,
                        extra={"chat_id": cid},
                    )

    # --- cycle helpers ---------------------------------------------
    def _obtain_status(self) -> str:
        fn = getattr(self._checker, "last_status", None)
        if callable(fn):
            status = fn()
            if isinstance(status, str):
                return status
        return TLSStatus.NO_SLOTS if self._checker.has_no_slots() else TLSStatus.MAYBE_SLOTS

    def _handle_special_status(self, status: str) -> bool:
        if status not in (TLSStatus.CAPTCHA, TLSStatus.BLOCKED):
            return False
        self._log.info("special status detected", extra={"status": status})
        self._breaker.record_failure()
        if status == TLSStatus.CAPTCHA and self._breaker.should_cooldown():
            self._broadcast("⚠️ CAPTCHA / anti-bot detected. Pausing checks for a while.")
            self._breaker.cooldown_sleep()
        else:
            self._breaker.backoff_sleep()
        return True

    def _update_transition_and_wait(self, status: str) -> None:
        self._breaker.reset()
        is_no = status == TLSStatus.NO_SLOTS
        if self._last_no_slots is True and not is_no:
            self._log.info("transition to maybe slots detected")
            self._broadcast("🎉 TLScontact: appointment may be available! Check now.")
        self._last_no_slots = is_no
        self._limiter.sleep_with_jitter(max(self._interval, 1))

    def _single_cycle(self) -> None:
        try:
            self._checker.refresh()
            time.sleep(5)  # DOM settle
            status = self._obtain_status()
            if not self._handle_special_status(status):
                self._update_transition_and_wait(status)
        except Exception as e:  # broad resilience
            self._log.error("check error", exc_info=e)
            self._breaker.record_failure()
            self._breaker.backoff_sleep()

    # --- thread loop -----------------------------------------------
    def _run(self) -> None:
        try:
            self._checker.ensure_logged_in()
            while not self._stop.is_set():
                self._single_cycle()
        finally:
            self._checker.close()
