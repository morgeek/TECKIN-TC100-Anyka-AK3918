"""Item 50 / [ui-baseline]: the same pages in both looks of the interface (Classic = Bulma, Pico), light and dark, at
1280 px and 390 px (phone), against the canned CGI answers of mock/ (no camera). For each shot: JavaScript errors
(pageerror) and horizontal scrolling at the page width. Writes the PNGs and results.json to the output folder.
Usage: python3 src/webui/screenshots/engines.py [out-dir] [engine ...]   (needs playwright; engines: bulma pico)
In Docker: docker run --rm -v "$PWD:/src:ro" -v "$OUT:/out" mcr.microsoft.com/playwright/python:v1.47.0-jammy \
           sh -c 'cp -r /src /w && python3 /w/src/webui/screenshots/engines.py /out'
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import mock  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else '/tmp/tc100-engines'
ENGINES = sys.argv[2:] or ['bulma', 'pico']
os.makedirs(OUT, exist_ok=True)
shutil.copytree('mock', OUT + '/mock-run', dirs_exist_ok=True)
mock.MOCKDIR = OUT + '/mock-run'
PORT = 8773
mock.start(PORT)
URL = 'http://127.0.0.1:%d/index.html' % PORT

# (name, JavaScript that opens the page); settings tabs through the Settings button, tools through the menu ids
# a missing element is reported (results.json "missing"), not fatal
CLICK = "(function(id){var e=document.getElementById(id); if(e){e.click(); return ''} return id})"
PAGES = [('dashboard', ''), ('live', CLICK + "('home_nav')"), ('multiview', CLICK + "('multiview_nav')")]
for tab in ('image', 'overlay', 'daynight', 'video', 'detect', 'record', 'notify', 'network', 'integrations',
            'system', 'backup'):
    PAGES.append(('settings-' + tab, "(function(t){var e=document.querySelector('a.onpage[data-tab=tab-'+t+']');"
                  "if(e){e.click(); return ''} return 'menu tab-'+t})('%s')" % tab))
for tool in ('services', 'diagnostics', 'hardware', 'logs', 'configeditor'):
    PAGES.append(('tools-' + tool, CLICK + "('%s')" % tool))


def shoot(browser, engine, theme, width, results):
    mobile = width < 600
    ctx = browser.new_context(viewport={'width': width, 'height': 844 if mobile else 820},
                              device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
    ctx.add_init_script("localStorage.setItem('elite_theme','%s');localStorage.setItem('tc100_ui','%s');"
                        "localStorage.setItem('tc100_lang','en')" % (theme, engine))
    for name, js in PAGES:
        pg = ctx.new_page()
        errs = []
        pg.on('pageerror', lambda e, errs=errs: errs.append(str(e)))
        pg.goto(URL)
        pg.wait_for_timeout(2500)
        missing = ''
        if js:
            missing = pg.evaluate(js) or ''
            pg.wait_for_timeout(3200 if 'settings' in name else 2500)
        pg.evaluate('window.scrollTo(0, 0)')
        over = pg.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
        ui = pg.evaluate("document.documentElement.getAttribute('data-ui')")
        f = '%s-%s-%s-%d.png' % (engine, name, theme, width)
        pg.screenshot(path=os.path.join(OUT, f), full_page=False)
        results.append({'engine': engine, 'page': name, 'theme': theme, 'width': width, 'file': f,
                        'data_ui': ui, 'missing': missing, 'js_errors': errs, 'horizontal_overflow_px': over})
        pg.close()
    ctx.close()


results = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for engine in ENGINES:
        for theme in ('light', 'dark'):
            for width in (1280, 390):
                shoot(b, engine, theme, width, results)
    b.close()
with open(os.path.join(OUT, 'results.json'), 'w') as f:
    json.dump(results, f, indent=1)
bad = [r for r in results if r['missing'] or r['js_errors'] or r['horizontal_overflow_px'] > 0 or r['data_ui'] != r['engine']]
print('%d shots, %d with a JavaScript error, horizontal scrolling or the wrong look' % (len(results), len(bad)))
for r in bad:
    print(' ', r['engine'], r['page'], r['theme'], r['width'], 'overflow=%s' % r['horizontal_overflow_px'],
          'ui=%s' % r['data_ui'], 'missing=%s' % r['missing'], '; '.join(r['js_errors'])[:200])
