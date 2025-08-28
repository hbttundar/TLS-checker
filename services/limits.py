"""Rate limiting & circuit breaker utilities.

Design goals:
 - Side-effect free duration computation helpers (facilitates unit testing & async usage).
 - Simple blocking helpers retained for current threaded monitor.
 - Explicit state exposure for breaker (supports /status reporting).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass


class RateLimiter:
    """Computes jittered wait durations within a min/max window.

    Jitter keeps probing pattern less predictable; choose full jitter strategy (+/- percentage).
    """

    def __init__(self, min_interval: int, max_interval: int, jitter_ratio: float):
        if min_interval <= 0 or max_interval < min_interval:
            raise ValueError("invalid interval bounds")
        self._min = min_interval
        self._max = max_interval
        self._jitter = jitter_ratio

    def compute_wait(self, base: int | None = None) -> int:
        """Return a jittered wait duration in seconds (integer)."""
        if base is None:
            base = random.randint(self._min, self._max)
        delta = int(base * self._jitter)
        return random.randint(max(1, base - delta), base + delta)

    def sleep_with_jitter(self, base: int | None = None) -> int:
        wait = self.compute_wait(base)
        time.sleep(wait)
        return wait


@dataclass
class BreakerState:
    failures: int
    threshold: int
    open: bool
    last_action: str | None = None  # 'backoff' | 'cooldown' | None


class CircuitBreaker:
    """Minimal failure-count breaker with exponential backoff & cooldown.

    States:
      - CLOSED (failures < threshold)
      - OPEN   (failures >= threshold) triggers full cooldown on certain conditions
    """

    def __init__(self, failure_threshold: int, cooldown_seconds: int, backoff_base: int, backoff_max: int):
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._fails = 0
        self._last_action: str | None = None

    # --- state ---
    def state(self) -> BreakerState:
        return BreakerState(
            failures=self._fails,
            threshold=self._threshold,
            open=self.should_cooldown(),
            last_action=self._last_action,
        )

    # --- events ---
    def reset(self):
        self._fails = 0
        self._last_action = None

    def record_failure(self):
        self._fails += 1

    def should_cooldown(self) -> bool:
        return self._fails >= self._threshold

    # --- timing helpers ---
    def compute_backoff(self) -> int:
        exp = min(self._backoff_base * (2 ** max(0, self._fails - 1)), self._backoff_max)
        jitter = random.randint(0, max(0, int(self._backoff_base / 2)))
        return int(exp + jitter)

    def backoff_sleep(self) -> int:
        dur = self.compute_backoff()
        time.sleep(dur)
        self._last_action = "backoff"
        return dur

    def cooldown_sleep(self) -> int:
        time.sleep(self._cooldown)
        self._last_action = "cooldown"
        self.reset()
        return self._cooldown
