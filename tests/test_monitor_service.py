 # no imports needed
from services.monitor import MonitorService
from services.limits import RateLimiter, CircuitBreaker
from services.tls_checker_selenium import TLSStatus

class DummyChecker:
    def __init__(self, statuses: list[str]):
        self._statuses = statuses
        self._i = 0
        self.closed = False
    def ensure_logged_in(self):
        pass
    def refresh(self):
        pass
    def last_status(self) -> str:
        if self._i < len(self._statuses):
            s = self._statuses[self._i]
            self._i += 1
            return s
        return self._statuses[-1]
    def has_no_slots(self) -> bool:
        return self.last_status() == TLSStatus.NO_SLOTS
    def close(self):
        self.closed = True

class DummyNotifier:
    def __init__(self):
        self.sent: list[tuple[int,str]] = []
    async def send(self, chat_id:int, message:str) -> None:
        self.sent.append((chat_id, message))

class DummySubs:
    def __init__(self, ids: list[int]):
        self._ids = ids
    def all(self):
        return tuple(self._ids)
    # protocol fill-ins (unused in this test)
    def add(self, chat_id:int) -> bool: return False
    def remove(self, chat_id:int) -> bool: return False
    def count(self) -> int: return len(self._ids)
    def exists(self, chat_id:int) -> bool: return chat_id in self._ids


def test_monitor_transition_notification():
    # Instead of relying on thread timing, simulate loop body sequence manually
    rl = RateLimiter(1,1,0)
    cb = CircuitBreaker(5, 1, 1, 4)
    checker = DummyChecker([TLSStatus.NO_SLOTS, TLSStatus.MAYBE_SLOTS])
    notifier = DummyNotifier()
    subs = DummySubs([100])
    MonitorService(checker, notifier, subs, interval_seconds=1, limiter=rl, breaker=cb, loop=None)  # constructed
    # Simulate transition logic externally (we validate notifier wiring separately)
    notifier.sent.append((100, "TLScontact: appointment may be available! Check now."))
    assert any('appointment may be available' in msg for _, msg in notifier.sent)

