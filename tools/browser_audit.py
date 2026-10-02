"""Verify the current-app redirect and functional preserved source in headless Chrome.

The destination is intercepted to test navigation without depending on a deployment.
The archived application is served locally with its actual committed data and scripts.
"""
import functools
import http.server
import json
import os
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT.name == "mtxtato-catalogue"
DESTINATION = ("https://lolstar123.github.io/smoothtato-preview/cosmetics/" if CATALOGUE
               else "https://lolstar123.github.io/quant-research-scraper/backtesting/")
OUTPUT = ROOT / "output" / "browser-audit"
OUTPUT.mkdir(parents=True, exist_ok=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


server = http.server.ThreadingHTTPServer(
    ("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "examples/portfolio")),
)
threading.Thread(target=server.serve_forever, daemon=True).start()
checks = []
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({"channel": "chrome"} if os.name == "nt" else {}))
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        local = f"http://127.0.0.1:{server.server_port}"
        page.route(DESTINATION, lambda route: route.fulfill(body="<html><title>Navigation fixture</title><p>Controlled redirect destination</p></html>", content_type="text/html"))
        page.goto(os.environ.get("AUDIT_URL", local), wait_until="domcontentloaded")
        page.wait_for_url(DESTINATION)
        assert page.url == DESTINATION
        checks.append("Public index redirects to the exact current-app URL (controlled destination)")
        page.goto(local + "/legacy.html", wait_until="networkidle")
        if CATALOGUE:
            page.wait_for_function("window.__mtx?.ready === true")
            assert page.evaluate("window.__mtx.total") == 1489
            page.locator("#search").fill("celestial")
            assert 0 < page.evaluate("window.__mtx.filtered") < 1489
            page.locator(".effect").first.click()
            page.locator("#add").click()
            assert page.locator("#loadout-count").inner_text() == "1"
            with page.expect_download() as downloaded:
                page.locator("#export").click()
            code = Path(downloaded.value.path()).read_text()
            assert code.startswith("STATO1-")
            page.locator("details").filter(has=page.locator("#import-code")).locator("summary").click()
            page.locator("#import-code").fill(code)
            page.locator("#import").click()
            assert "Loaded 1 skill effects" in page.locator("#status").inner_text()
            page.locator("#import-code").fill("STATO1-broken")
            page.locator("#import").click()
            assert "failed" in page.locator("#status").inner_text().lower()
            page.locator("#search").fill("")
            page.locator("#skill").select_option(index=2)
            assert 0 < page.evaluate("window.__mtx.filtered") < 1489
            checks.append("Actual catalogue: search, skill filter, selection, exported/imported code and damaged-code error")
        else:
            page.wait_for_selector("#windows tr")
            assert page.locator("#windows tr").count() > 1
            before = page.locator("#stats").inner_text()
            page.locator("#cost").fill("50")
            page.locator("#run").click()
            assert page.locator("#stats").inner_text() != before
            with page.expect_download() as downloaded:
                page.locator("#download").click()
            rows = Path(downloaded.value.path()).read_text().splitlines()
            assert rows[0] == "date,equity,benchmark,position,period,return"
            assert len(rows) > 4000
            page.locator('[data-tab="archive"]').click()
            assert page.locator("#strategies tr").count() == 50
            page.locator("#search").fill("Risk Parity")
            assert 0 < page.locator("#strategies tr").count() < 50
            page.locator("#search").fill("")
            page.locator('[data-tab="experiment"]').click()
            checks.append("Actual prices: training table, changed-cost rerun, CSV export and searchable 50-run archive")
        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=str(OUTPUT / f"legacy-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Overflow at {width}"
            checks.append(f"No document overflow at {width}px; full-page rendering saved")
        assert not errors, errors
        checks.append("No browser runtime exceptions")
        (OUTPUT / "receipt.json").write_text(json.dumps({"checks": checks, "errors": errors}, indent=2))
        print("PASS: " + "; ".join(checks))
        browser.close()
finally:
    server.shutdown()
