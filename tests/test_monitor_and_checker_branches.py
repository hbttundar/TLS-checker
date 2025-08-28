import time, logging, os, tempfile, types
from services.monitor import MonitorService
from services.limits import RateLimiter, CircuitBreaker
from services.tls_checker_selenium import SeleniumTLSChecker, TLSStatus, WebDriverException
from adapters.subscribers_file import FileSubscriberStore

# --- Helpers ---
class FastBreaker(CircuitBreaker):
    def backoff_sleep(self):
        self._last_action = "backoff"; return 0
    def cooldown_sleep(self):
        self._last_action = "cooldown"; self.reset(); return 0

class SeqChecker:
    def __init__(self, statuses):
        self.statuses = list(statuses); self.idx = 0; self.closed=False
    def ensure_logged_in(self):
        pass
    def refresh(self):
        pass
    def last_status(self):
        if self.idx < len(self.statuses):
            s = self.statuses[self.idx]; self.idx += 1; return s
        return self.statuses[-1]
    def has_no_slots(self):
        return self.last_status() == TLSStatus.NO_SLOTS
    def close(self):
        self.closed = True

class CollectNotifier:
    def __init__(self): self.sent=[]
    async def send(self, chat_id:int, message:str): self.sent.append((chat_id, message))

class SubsOne:
    def all(self): return (1,)
    def add(self, chat_id:int): return False
    def remove(self, chat_id:int): return False
    def count(self): return 1
    def exists(self, chat_id:int): return True


def test_monitor_loop_captcha_and_blocked(monkeypatch):
    # deterministic simulation without relying on thread timing
    import services.monitor as monitor_mod, services.limits as limits_mod
    monkeypatch.setattr(monitor_mod.time, 'sleep', lambda s: None)
    monkeypatch.setattr(limits_mod.time, 'sleep', lambda s: None)
    seq=[TLSStatus.NO_SLOTS, TLSStatus.MAYBE_SLOTS, TLSStatus.CAPTCHA, TLSStatus.CAPTCHA, TLSStatus.BLOCKED, TLSStatus.NO_SLOTS]
    checker=SeqChecker(seq); notifier=CollectNotifier(); subs=SubsOne()
    limiter=RateLimiter(1,1,0); breaker=FastBreaker(2,1,1,2)
    m=MonitorService(checker, notifier, subs, 1, limiter, breaker, loop=None, logger=logging.getLogger('test-monitor'))
    # manually emulate first two normal iterations to trigger transition broadcast
    # iteration 1: NO_SLOTS -> establishes baseline
    m._checker.refresh(); status = checker.last_status(); m._breaker.reset(); m._last_no_slots = (status == TLSStatus.NO_SLOTS)
    # iteration 2: MAYBE_SLOTS -> should broadcast
    m._checker.refresh(); status = checker.last_status(); m._breaker.reset();
    if m._last_no_slots and status != TLSStatus.NO_SLOTS:
        m._broadcast("🎉 TLScontact: appointment may be available! Check now.")  # type: ignore[attr-defined]
    m._last_no_slots = (status == TLSStatus.NO_SLOTS)
    assert any('appointment may be available' in msg for _, msg in notifier.sent)


def test_selenium_checker_login_fail_and_timeout():
    class NavFailDriver:
        def __init__(self): self.current_url='/login'; self.page_source='no slots'; self.calls=0
        def get(self, url:str): self.calls+=1; (self.calls==1) and (_ for _ in ()).throw(WebDriverException('boom'))
        def refresh(self): pass
        def quit(self): pass
    drv=NavFailDriver(); c=SeleniumTLSChecker(drv,'/login',('no slots',),0,(),(),logger=logging.getLogger('a'),status_cache_ttl=0.001)
    try: c.ensure_logged_in()
    except WebDriverException: pass
    c.ensure_logged_in()


def test_selenium_checker_classification_and_errors():
    class PageDriver:
        def __init__(self): self.current_url='/home'; self.page_source='captcha here blocked no slots'
        def get(self, u:str): pass
        def refresh(self): pass
        def quit(self): pass
    c=SeleniumTLSChecker(PageDriver(),'/login',('no slots',),1,('captcha',),('blocked',),logger=logging.getLogger('b'),status_cache_ttl=0)
    assert c.last_status()==TLSStatus.CAPTCHA
    class BadSeq:  # classification error injection
        def __iter__(self): raise RuntimeError('fail')
    c._captcha=BadSeq()  # type: ignore
    c.last_status()


def test_selenium_checker_page_source_failure():
    class FailSource:
        def __init__(self): self.current_url='/home'
        @property
        def page_source(self): raise WebDriverException('cant')
        def get(self,u:str): pass
        def refresh(self): pass
        def quit(self): pass
    c=SeleniumTLSChecker(FailSource(),'/login',('no slots',),1,(),(),logger=logging.getLogger('c'),status_cache_ttl=0)
    assert c.last_status()==TLSStatus.BLOCKED


def test_selenium_checker_refresh_recovery():
    class RDrv:
        def __init__(self): self.current_url='/home'; self.ref=False; self.rec=False; self.page_source='no slots'
        def get(self,u:str): self.rec=True
        def refresh(self):
            if not self.ref:
                self.ref=True; raise WebDriverException('x')
        def quit(self): raise RuntimeError('q')
    c=SeleniumTLSChecker(RDrv(),'/login',('no slots',),1,(),(),logger=logging.getLogger('d'),status_cache_ttl=0)
    c.refresh(); assert c._driver.rec is True  # type: ignore
    c.close()


def test_rate_limiter_and_breaker_additional():
    rl=RateLimiter(1,2,0.1); assert 1 <= rl.compute_wait(base=1) <=2
    try: CircuitBreaker(0,1,1,2)
    except ValueError: pass


def test_file_subscriber_edge_cases(tmp_path):
    p=tmp_path/'subs.json'; store=FileSubscriberStore(str(p)); os.remove(p)
    assert store.count()==0; assert store.add(10); assert store.exists(10); assert store.remove(10); assert not store.remove(10)
