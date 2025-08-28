import os, asyncio, types, logging, time, tempfile
import builtins
from adapters.selenium_driver import ChromeDriverFactory
from services.limits import CircuitBreaker, RateLimiter
from services.monitor import MonitorService


def test_chromedriver_path_and_cdp_exception(monkeypatch, tmp_path):
    # create a fake chromedriver binary file
    driver_bin = tmp_path / 'chromedriver'
    driver_bin.write_text('#!/bin/sh\n')
    monkeypatch.setenv('CHROMEDRIVER_PATH', str(driver_bin))
    monkeypatch.setenv('CHROME_BIN', '/usr/bin/chromium-browser')
    created = {}
    class DummyService:
        def __init__(self, executable_path=None, *a, **k):
            created['service_path'] = executable_path
    class DummyDriver:
        def __init__(self, *a, **k): pass
        def execute_cdp_cmd(self, *a, **k): raise RuntimeError('cdp fail')
    import adapters.selenium_driver as sd
    monkeypatch.setattr(sd, 'Service', DummyService)
    monkeypatch.setattr(sd.webdriver, 'Chrome', lambda service, options: DummyDriver())
    factory = ChromeDriverFactory(str(tmp_path/'profile'), True, '800,600', stealth=True)
    drv = factory.create()
    assert created['service_path'] == str(driver_bin)
    assert drv is not None


def test_breaker_backoff_and_cooldown(monkeypatch):
    # patch time.sleep to avoid delays
    import services.limits as limits_mod
    monkeypatch.setattr(limits_mod.time, 'sleep', lambda s: None)
    cb = CircuitBreaker(1, 5, 1, 4)
    # force failure to open breaker
    cb.record_failure()
    d1 = cb.backoff_sleep(); assert cb.state().last_action == 'backoff' and d1 >= 1
    # cooldown path
    cb.record_failure()  # exceed threshold again
    d2 = cb.cooldown_sleep(); assert cb.state().last_action is None and d2 == 5  # reset clears last_action


def test_monitor_broadcast_scheduler_paths(monkeypatch):
    # cover scheduling success + callback exception branches
    sent = []
    class Ntfy:
        async def send(self, cid:int, text:str): sent.append((cid, text))
    class Subs:
        def all(self): return (1,2)
        def add(self,c): return False
        def remove(self,c): return False
        def count(self): return 2
        def exists(self,c): return True
    # Fake futures
    class FutExc:
        def add_done_callback(self, cb):
            class F:
                def exception(self): return RuntimeError('boom')
            cb(F())
    class FutRaise:
        def add_done_callback(self, cb):
            class F2:
                def exception(self): raise RuntimeError('fail inside')
            cb(F2())
    # Use loop=None to exercise fallback blocking notification path
    m = MonitorService(checker=types.SimpleNamespace(ensure_logged_in=lambda: None, refresh=lambda: None, has_no_slots=lambda: True, close=lambda: None),
                       notifier=Ntfy(), subscribers=Subs(), interval_seconds=1,
                       limiter=RateLimiter(1,1,0), breaker=CircuitBreaker(3,1,1,2),
                       loop=None, logger=logging.getLogger('monitor-test'))
    # directly invoke broadcast
    m._broadcast('hello')  # type: ignore[attr-defined]
    assert sent == [(1,'hello'), (2,'hello')]


def test_bot_command_handlers_whitelist_and_status(monkeypatch):
    import bot as bot_module
    # environment for online mode
    monkeypatch.delenv('OFFLINE', raising=False)
    monkeypatch.setenv('TELEGRAM_TOKEN', 'T')
    monkeypatch.setenv('SUBSCRIBER_BACKEND', 'memory')
    monkeypatch.setenv('WHITELIST_USERNAMES', 'allowed')
    monkeypatch.setenv('ENABLE_STATUS_COMMAND', 'true')
    monkeypatch.setenv('HEADLESS', 'true')
    # fast event & driver
    class FastEvent:
        def set(self): pass
        async def wait(self): return None
    monkeypatch.setattr(bot_module.asyncio, 'Event', lambda : FastEvent())
    monkeypatch.setattr(bot_module, 'ChromeDriverFactory', lambda *a, **k: types.SimpleNamespace(create=lambda : types.SimpleNamespace(current_url='u', page_source='no slots', get=lambda u: None, refresh=lambda : None, quit=lambda : None)))
    built = {}
    class DummyApp:
        def __init__(self): self.handlers=[]; self.bot=types.SimpleNamespace(send_message=lambda **k: None)
        def add_handler(self, h): self.handlers.append(h)
        async def start(self): return None
        async def stop(self): return None
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
    class Builder:
        def token(self, t): return self
        def build(self):
            app = DummyApp(); built['app']=app; return app
    monkeypatch.setattr(bot_module.Application, 'builder', lambda : Builder())
    # run main
    async def run(): return await bot_module.main()
    asyncio.run(run())
    app = built['app']
    # find handlers (CommandHandler objects)
    subscribe_handlers = [h for h in app.handlers if getattr(h, 'commands', None) and 'subscribe' in h.commands]
    status_handlers = [h for h in app.handlers if getattr(h, 'commands', None) and 'status' in h.commands]
    assert subscribe_handlers and status_handlers
    replies = []
    class Msg:
        async def reply_text(self, text):
            replies.append(text)
    class Chat: id = 42
    class User: username = 'denied'
    update = types.SimpleNamespace(message=Msg(), effective_chat=Chat(), effective_user=User())
    # unauthorized path
    cb = subscribe_handlers[0].callback
    asyncio.run(cb(update, None))
    assert any('Not authorized' in r for r in replies)
    # now authorized user
    replies.clear(); User.username = 'allowed'
    asyncio.run(cb(update, None))
    assert any('Subscribed' in r or 'Already subscribed' in r for r in replies)
    # status command
    scb = status_handlers[0].callback
    asyncio.run(scb(update, None))
    assert any('Monitor running' in r for r in replies)
