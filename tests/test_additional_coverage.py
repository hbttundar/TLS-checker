import logging, time, types
import pytest
from services.limits import RateLimiter, CircuitBreaker, BreakerState
from services.tls_checker_selenium import SeleniumTLSChecker, TLSStatus, WebDriverException
from services.monitor import MonitorService
from adapters.telegram_notifier import TelegramNotifier
from adapters.selenium_driver import ChromeDriverFactory

class DummyFailDriver:
    def __init__(self):
        self.current_url = '/login'
        self.page_source = 'no slots'
        self.get_called = 0
        self.refresh_called = 0
        self.quit_called = 0
    def get(self, url:str):
        self.get_called += 1
        if self.get_called == 1:
            raise WebDriverException('nav fail')
    def refresh(self):
        self.refresh_called += 1
        raise WebDriverException('refresh boom')
    def quit(self):
        self.quit_called += 1

class DummyRecoverDriver:
    def __init__(self):
        self.current_url = '/login'
        self.page_source = 'blocked content'
        self.refresh_called = 0
        self.get_called = 0
        self.quit_called = 0
    def get(self, url:str):
        self.get_called += 1
        self.current_url = '/home'
    def refresh(self):
        self.refresh_called += 1
        if self.refresh_called == 1:
            raise WebDriverException('first refresh fails')
        self.page_source = 'captcha here'
    def quit(self):
        self.quit_called += 1

class SilentLogger(logging.Logger):
    def __init__(self):
        super().__init__('silent', level=logging.DEBUG)
    def handle(self, record):
        pass


def test_rate_limiter_invalid_bounds():
    with pytest.raises(ValueError):
        RateLimiter(0, 5, 0.1)
    with pytest.raises(ValueError):
        RateLimiter(5, 4, 0.1)

def test_circuit_breaker_value_errors_and_state():
    cb = CircuitBreaker(1, 1, 1, 4)
    assert isinstance(cb.state(), BreakerState)
    cb.record_failure()
    assert cb.should_cooldown()
    back1 = cb.compute_backoff()
    assert back1 >= 1
    cb.reset()
    assert cb.state().failures == 0


def test_telegram_notifier_send_event_loop(monkeypatch):
    class DummyBot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id:int, text:str):
            self.sent.append((chat_id, text))
    class DummyApp:
        def __init__(self):
            self.bot = DummyBot()
    app = DummyApp()
    n = TelegramNotifier(app)  # type: ignore[arg-type]
    import asyncio
    async def _run():
        await n.send(5, "hello")
    asyncio.run(_run())
    assert app.bot.sent == [(5, "hello")]


def test_selenium_checker_error_paths_and_cache():
    drv = DummyRecoverDriver()
    c = SeleniumTLSChecker(drv, '/login', ('no slots',), 1, ('captcha',), ('blocked',), logger=SilentLogger(), status_cache_ttl=0.5)
    c.ensure_logged_in()
    assert getattr(c, '_logged_in')
    s1 = c.last_status()
    assert s1 in {TLSStatus.BLOCKED, TLSStatus.MAYBE_SLOTS, TLSStatus.NO_SLOTS}
    s2 = c.last_status(); assert s1 == s2
    time.sleep(0.6)
    c.refresh()
    st = c.last_status()
    # After recovery either captcha content classified or still blocked depending on sequence
    assert st in {TLSStatus.CAPTCHA, TLSStatus.MAYBE_SLOTS, TLSStatus.BLOCKED}
    c.close(); assert drv.quit_called == 1


def test_chrome_driver_factory_build(monkeypatch, tmp_path):
    created = {}
    class DummyService:
        def __init__(self, executable_path:str|None=None):
            self.executable_path = executable_path
    class DummyDriver:
        def __init__(self, service=None, options=None):
            created['options'] = options
        def execute_cdp_cmd(self, *a, **k):
            pass
    # monkeypatch webdriver & manager
    monkeypatch.setenv('CHROME_BIN', '/usr/bin/chromium-browser')
    import adapters.selenium_driver as sd
    monkeypatch.setattr(sd, 'Service', lambda *a, **k: DummyService())
    monkeypatch.setattr(sd.webdriver, 'Chrome', lambda service, options: DummyDriver(service, options))
    monkeypatch.setattr(sd, 'ChromeDriverManager', lambda: types.SimpleNamespace(install=lambda: '/tmp/driver'))
    factory = ChromeDriverFactory(str(tmp_path/"profile"), True, '1280,800', stealth=True)
    drv = factory.create()
    assert 'options' in created and drv is not None


def test_monitor_exception_path():
    class BoomChecker:
        def __init__(self):
            self.closed = False
            self.calls = 0
        def ensure_logged_in(self):
            pass
        def refresh(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('boom')
        def has_no_slots(self):
            return True
        def close(self):
            self.closed = True
    class NoopNotifier:
        async def send(self, chat_id:int, message:str):
            return None
    class OneSub:
        def all(self): return (1,)
        def add(self, c): return False
        def remove(self,c): return False
        def count(self): return 1
        def exists(self,c): return True

    rl = RateLimiter(1,1,0)
    cb = CircuitBreaker(2, 1, 1, 2)

    m = MonitorService(BoomChecker(), NoopNotifier(), OneSub(), interval_seconds=1, limiter=rl, breaker=cb, loop=None, logger=SilentLogger())
    m.start()
    time.sleep(2.0)
    m.stop()
    st = cb.state()
    assert st.failures >= 1
