import pytest
from services.limits import RateLimiter, CircuitBreaker


def test_rate_limiter_bounds():
    rl = RateLimiter(5, 10, 0.2)
    for _ in range(50):
        w = rl.compute_wait()
        assert 1 <= w <= 12  # 10 + jitter 20%


def test_rate_limiter_custom_base():
    rl = RateLimiter(5, 10, 0.5)
    w = rl.compute_wait(base=8)
    assert 4 <= w <= 12


def test_circuit_breaker_states_and_backoff(monkeypatch):
    cb = CircuitBreaker(3, cooldown_seconds=2, backoff_base=1, backoff_max=8)
    # patch random to deterministic for backoff jitter
    monkeypatch.setattr('random.randint', lambda a,b: a)

    assert not cb.should_cooldown()
    cb.record_failure(); cb.record_failure();
    assert not cb.should_cooldown()
    cb.record_failure()
    assert cb.should_cooldown()
    # compute backoff after 3 failures -> base * 2^(fails-1) = 1*2^2=4 + jitter(0)
    assert cb.compute_backoff() == 4
    state = cb.state()
    assert state.failures == 3 and state.open
    cb.reset()
    assert not cb.should_cooldown()


def test_circuit_breaker_backoff_growth(monkeypatch):
    cb = CircuitBreaker(10, cooldown_seconds=5, backoff_base=1, backoff_max=20)
    monkeypatch.setattr('random.randint', lambda a,b: a)
    values = []
    for i in range(1,6):
        cb.record_failure()
        values.append(cb.compute_backoff())
    # expected sequence with jitter=0: 1,2,4,8,16
    assert values == [1,2,4,8,16]

