"""Item 50: rendering cost of the interface (Pico look; until rc31 it compared it with the Classic look, Bulma). Same pages, same canned CGI answers (mock/), Chromium with the
CPU slowed down 4x (a mid-range phone), the cache cleared before each load. Per page and look, the median of RUNS loads:
first contentful paint, style recalculation, layout and total main-thread task time (Chrome DevTools Performance
metrics), plus the weight of the style sheet (raw, gzip, xz) and its number of rules. Writes bench.json.
Usage: python3 src/webui/screenshots/bench.py [out-dir] [runs]   (needs playwright; see engines.py for Docker)
"""
import gzip
import json
import lzma
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import mock  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else '/tmp/tc100-bench'
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
os.makedirs(OUT, exist_ok=True)
PORT = 8775
mock.start(PORT)
URL = 'http://127.0.0.1:%d/index.html' % PORT
CSS = os.path.join(mock.ROOT, 'css')
SHEETS = {'pico': 'ui.pico.min.css'}
PAGES = [('dashboard', ''),
         ('settings-video', "document.querySelector('a.onpage[data-tab=tab-video]').click()"),
         ('tools-services', "document.getElementById('services').click()"),
         ('tools-logs', "document.getElementById('logs').click()")]
METRICS = ('RecalcStyleDuration', 'LayoutDuration', 'TaskDuration', 'ScriptDuration')


def sheet_facts(name):
    raw = open(os.path.join(CSS, name), 'rb').read()
    text = raw.decode('utf-8')
    return {'file': name, 'raw_bytes': len(raw), 'gzip_bytes': len(gzip.compress(raw, 9)),
            'xz_bytes': len(lzma.compress(raw, preset=9)), 'rules': text.count('{') - text.count('@media')}


def load(browser, engine, js):
    ctx = browser.new_context(viewport={'width': 1280, 'height': 820})
    ctx.add_init_script("localStorage.setItem('tc100_lang','en');localStorage.setItem('elite_theme','light')")
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send('Network.enable')
    cdp.send('Network.setCacheDisabled', {'cacheDisabled': True})
    cdp.send('Emulation.setCPUThrottlingRate', {'rate': 4})
    cdp.send('Performance.enable')
    pg.goto(URL, wait_until='load')
    if js:
        pg.wait_for_timeout(1500)
        before = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
        pg.evaluate(js)
        pg.wait_for_timeout(2500)
    else:
        before = {k: 0 for k in METRICS}
        pg.wait_for_timeout(2500)
    after = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
    fcp = pg.evaluate("(performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0")
    r = {k: round((after.get(k, 0) - before.get(k, 0)) * 1000, 1) for k in METRICS}
    r['FirstContentfulPaint'] = round(fcp, 1)
    ctx.close()
    return r


res = {'runs': RUNS, 'cpu_throttling': 4, 'sheets': {e: sheet_facts(f) for e, f in SHEETS.items()}, 'pages': {}}
with sync_playwright() as p:
    b = p.chromium.launch()
    for page, js in PAGES:
        res['pages'][page] = {}
        for engine in SHEETS:
            load(b, engine, js)  # warm-up (fonts, the mock server)
            runs = [load(b, engine, js) for _ in range(RUNS)]
            res['pages'][page][engine] = {k: statistics.median(x[k] for x in runs) for k in runs[0]}
    b.close()
json.dump(res, open(os.path.join(OUT, 'bench.json'), 'w'), indent=1)

print('style sheet          raw      gzip     xz     rules')
for e, f in res['sheets'].items():
    print('%-8s %10d %9d %8d %8d' % (e, f['raw_bytes'], f['gzip_bytes'], f['xz_bytes'], f['rules']))
print('\nmedian of %d loads, CPU x4, ms   (page: dashboard = first load; others = opening the page in the app)' % RUNS)
print('%-16s %-6s %8s %8s %8s %8s %8s' % ('page', 'look', 'FCP', 'style', 'layout', 'script', 'tasks'))
for page, d in res['pages'].items():
    for e, m in d.items():
        print('%-16s %-6s %8.0f %8.1f %8.1f %8.1f %8.1f' % (page, e, m['FirstContentfulPaint'], m['RecalcStyleDuration'],
              m['LayoutDuration'], m['ScriptDuration'], m['TaskDuration']))
