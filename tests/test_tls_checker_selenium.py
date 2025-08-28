import time
import logging
from services.tls_checker_selenium import SeleniumTLSChecker, TLSStatus

class DummyDriver:
    def __init__(self, pages: list[str]):
        self._pages = pages
        self._idx = 0
        self.current_url = '/login'
        self.page_source = self._pages[self._idx]
        self.get_calls = 0
        self.refresh_calls = 0

    def get(self, url:str):
        self.get_calls += 1
        # simulate login page leaving
        self.current_url = url.replace('/login','/home') if 'login' in url else url
        self.page_source = self._pages[self._idx]

    def refresh(self):
        self.refresh_calls += 1
        # rotate pages
        self._idx = min(self._idx + 1, len(self._pages)-1)
        self.page_source = self._pages[self._idx]

    def quit(self):
        pass


def make_checker(pages: list[str]):
    return SeleniumTLSChecker(
        driver=DummyDriver(pages),
        login_url='/login',
        negative_markers=('no slots',),
        login_wait_seconds=1,
        captcha_markers=('captcha',),
        block_markers=('blocked',),
        logger=logging.getLogger('test'),
        status_cache_ttl=0.01
    )


def test_login_and_status_flow():
    c = make_checker(['welcome','no slots here','maybe something','captcha challenge','blocked message'])
    c.ensure_logged_in()
    assert getattr(c, "_logged_in")
    # initial status
    s1 = c.last_status()
    assert s1 in {TLSStatus.NO_SLOTS, TLSStatus.MAYBE_SLOTS}
    # cache path
    s2 = c.last_status()
    assert s1 == s2
    time.sleep(0.02)
    c.refresh(); time.sleep(0.02)
    assert c.last_status() in {TLSStatus.NO_SLOTS, TLSStatus.MAYBE_SLOTS}
    # advance until we reach CAPTCHA or BLOCKED
    seen = set()
    for _ in range(6):
        c.refresh(); time.sleep(0.02)
        seen.add(c.last_status())
        if TLSStatus.CAPTCHA in seen and TLSStatus.BLOCKED in seen:
            break
    assert TLSStatus.CAPTCHA in seen
    assert TLSStatus.BLOCKED in seen


def test_classification_priority():
    c = make_checker(['captcha text blocked no slots'])
    c.ensure_logged_in()
    # captcha should win over blocked & no_slots
    assert c.last_status() == TLSStatus.CAPTCHA

