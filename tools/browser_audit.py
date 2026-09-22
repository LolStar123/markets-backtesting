"""Exercise the complete commute calculator locally or against its public deployment."""
import functools
import http.server
import os
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(ROOT/'examples/portfolio')))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(**({'channel':'chrome'} if os.name=='nt' else {}))
        page=browser.new_page(viewport={'width':1280,'height':1000},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(os.environ.get('AUDIT_URL',f'http://127.0.0.1:{server.server_port}'),wait_until='networkidle')
        page.wait_for_function('window.__backtest?.ready')
        before=page.evaluate('__backtest.result.stats.total')
        page.locator('#cost').fill('50');page.locator('#run').click()
        assert page.evaluate('__backtest.result.stats.total')!=before
        assert page.locator('#chart polyline').count()==2
        page.locator('[data-tab="archive"]').click()
        assert page.locator('#strategies tr').count()==50
        page.locator('#search').fill('parity')
        assert 0<page.locator('#strategies tr').count()<50
        page.locator('[data-tab="experiment"]').click()
        with page.expect_download() as dl:page.locator('#download').click()
        assert dl.value.suggested_filename=='walk-forward-returns.csv'
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(ROOT/'examples/portfolio/preview.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'mobile overflow'
        assert not errors,errors
        print('PASS: historical rerun, changed costs, two equity curves, 50 real strategies, search and export')
        browser.close()
finally: server.shutdown()
