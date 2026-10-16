"""Screenshots of the web UI for README (docs/screenshots/), against canned CGI
answers in mock/ (no camera; the live image is a test pattern).
Usage: python3 src/webui/screenshots/shots.py [out-dir]   (needs playwright)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import mock, time, json
OUT=os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else '/tmp/tc100-shots'
os.makedirs(OUT, exist_ok=True)
import shutil; shutil.copytree('mock', OUT + '/mock-run', dirs_exist_ok=True)
mock.MOCKDIR = OUT + '/mock-run'
from playwright.sync_api import sync_playwright
mock.STATUS['mqtt_last_pub_ts']=int(time.time())-20
mock.start(8772)
U='http://127.0.0.1:8772/index.html'
def page(b, theme='light', lang='en', w=1280, h=820, mobile=False):
    ctx=b.new_context(viewport={'width':w,'height':h}, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
    pg=ctx.new_page()
    pg.add_init_script("localStorage.setItem('elite_theme','%s');localStorage.setItem('tc100_lang','%s')"%(theme,lang))
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e))); pg.errs=errs
    pg.goto(U); pg.wait_for_timeout(2500)
    return pg
def settings(pg, tab):
    pg.evaluate("document.getElementById('status').click()"); pg.wait_for_timeout(1800)
    pg.evaluate("document.querySelector('[data-tab=%s]').click()"%tab); pg.wait_for_timeout(1500)
    pg.evaluate("window.scrollTo(0,0)")
with sync_playwright() as p:
    b=p.chromium.launch()
    pg=page(b,'dark'); pg.wait_for_timeout(40000); pg.screenshot(path=OUT+'/dashboard-dark.png')
    pg.evaluate("document.getElementById('home_nav').click()"); pg.wait_for_timeout(1500); pg.screenshot(path=OUT+'/live-view-dark.png')
    pg=page(b); pg.wait_for_timeout(12000); pg.screenshot(path=OUT+'/dashboard.png')
    pg.evaluate("document.getElementById('home_nav').click()"); pg.wait_for_timeout(1500); pg.screenshot(path=OUT+'/live-view.png')
    for tab,name in [('tab-image','settings-image'),('tab-integrations','settings-integrations'),('tab-record','settings-recording'),('tab-backup','settings-update'),('tab-system','settings-system')]:
        settings(pg,tab); pg.screenshot(path=OUT+'/%s.png'%name)
    for t,name in [('services','tools-services'),('diagnostics','tools-diagnostics')]:
        pg.evaluate("document.getElementById(%r).click()"%t); pg.wait_for_timeout(2500); pg.screenshot(path=OUT+'/%s.png'%name)
    print('errors light', pg.errs)
    pg=page(b,'dark','fr'); settings(pg,'tab-video'); pg.screenshot(path=OUT+'/settings-dark-fr.png'); print('errors dark', pg.errs)
    pg=page(b,'dark','en',390,844,True); pg.wait_for_timeout(11000); pg.screenshot(path=OUT+'/dashboard-mobile.png', full_page=True)
    settings(pg,'tab-image'); pg.screenshot(path=OUT+'/settings-mobile.png')
    # SD mode: install-to-flash card
    mock.STATUS['storage']='sd'
    json.dump({"ok":True,"state":"prepared","running":0,"log":"2026-10-16 09:12:03 prepare: flash checked, copying the original /usr (3.7 MB)…\n2026-10-16 09:12:41 prepare: DONE. Next: take the card out and run src/flash/build-flash-kit.sh on a computer (README).\n"},open(mock.MOCKDIR+'/flashinstall.cgi.status.json','w'))
    json.dump({"ok":True,"state":"idle","current":"2.0.0","staged":"","rollback_to":""},open(mock.MOCKDIR+'/update.cgi.status.json','w'))
    pg=page(b); settings(pg,'tab-backup'); pg.screenshot(path=OUT+'/settings-install-to-flash.png')
    b.close()
print(sorted(mock.unknown))
