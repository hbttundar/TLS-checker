import os, asyncio, types
import bot as bot_module
from config import Config


def test_config_load_env(monkeypatch):
    monkeypatch.setenv('TELEGRAM_TOKEN', 'TESTTOKEN')
    monkeypatch.setenv('MIN_CHECK_INTERVAL', '10')
    monkeypatch.setenv('MAX_CHECK_INTERVAL', '20')
    monkeypatch.setenv('NEGATIVE_PATTERNS', 'no;none')
    monkeypatch.setenv('CAPTCHA_MARKERS', 'captcha')
    monkeypatch.setenv('BLOCK_MARKERS', 'blocked')
    monkeypatch.setenv('HEADLESS', 'true')
    monkeypatch.setenv('SUBSCRIBER_BACKEND', 'memory')
    cfg = Config.load()
    assert cfg.telegram_token == 'TESTTOKEN'
    assert 'no' in cfg.negative_patterns
    assert cfg.headless is True


def test_bot_main_offline(monkeypatch):
    monkeypatch.setenv('OFFLINE', 'true')
    monkeypatch.setenv('FAKE_DRIVER', '1')
    monkeypatch.setenv('TELEGRAM_TOKEN', 'TOKEN')
    monkeypatch.setenv('SUBSCRIBER_BACKEND', 'memory')
    monkeypatch.setenv('ENVIRONMENT', 'development')
    async def _noop(_):
        return None
    monkeypatch.setattr(bot_module.asyncio, 'sleep', _noop)
    async def run():
        return await bot_module.main()
    rc = asyncio.run(run())
    assert rc == 0


def test_bot_main_online_fast(monkeypatch):
    monkeypatch.delenv('OFFLINE', raising=False)
    monkeypatch.setenv('TELEGRAM_TOKEN', 'TOKEN')
    monkeypatch.setenv('SUBSCRIBER_BACKEND', 'memory')
    monkeypatch.setenv('START_MONITOR_AFTER_LOGIN', 'false')
    monkeypatch.setenv('HEADLESS', 'true')
    class FastEvent:
        def set(self): pass
        async def wait(self): return None
    monkeypatch.setattr(bot_module, 'ChromeDriverFactory', lambda *a, **k: types.SimpleNamespace(create=lambda : types.SimpleNamespace(current_url='u', page_source='html', get=lambda u: None, refresh=lambda : None, quit=lambda : None)))
    class DummyApp:
        def __init__(self): self.handlers=[]; self.bot=types.SimpleNamespace(send_message=lambda **k: None)
        def add_handler(self, h): self.handlers.append(h)
        async def start(self): return None
        async def stop(self): return None
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
    class Builder:
        def token(self, t): return self
        def build(self): return DummyApp()
    monkeypatch.setattr(bot_module.Application, 'builder', lambda : Builder())
    monkeypatch.setattr(bot_module.asyncio, 'Event', lambda : FastEvent())
    class DummyMonitor:
        def __init__(self, *a, **k): self._thread=None
        def start(self): pass
        def stop(self): pass
        def is_running(self): return True
    monkeypatch.setattr(bot_module, 'MonitorService', DummyMonitor)
    async def run():
        return await bot_module.main()
    rc = asyncio.run(run())
    assert rc == 0
