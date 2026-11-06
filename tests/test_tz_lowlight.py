"""[tz-lowlight] F3/F9: the time zone in the setup wizard (and the same list in Settings); F2: the low-light frame rate value.

- the wizard asks for a time zone (browser zone preselected, POSIX string posted), validates it server side and writes it where
  Settings keeps it (config/timezone.conf, first line that is not a comment); Settings' settz uses the same check;
- every zone of www/scripts/tzlist.js is a valid POSIX string for that check;
- daynight.conf LOWLIGHT_FPS_VALUE (10/15/20) goes Settings -> video.sh -> state.cgi -> rtsp-launch.sh -> RTSP_LOWLIGHT_FPS_VALUE
  -> tc100_rtsp (the exposure limit scaled with the rate; 10 fps stays what it was).
"""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


def validator_awk(path):
    """the awk program of the TZ check as written in a file (wizard.cgi tz_valid, action.d/system.sh settz)"""
    s = text(path)
    m = re.search(r"awk 'BEGIN \{\n(.*?END \{ exit ok \? 0 : 1 \})'", s, re.S)
    assert m, path
    return "BEGIN {\n" + m.group(1)


def run_valid(awk_prog, value):
    r = subprocess.run(SH + ['-c', 'printf "%s\\n" "$1" | awk \'' + awk_prog + "'", '_', value], capture_output=True, text=True)
    return r.returncode == 0


GOOD = ['UTC0', 'CET-1CEST,M3.5.0,M10.5.0/3', 'GMT0BST,M3.5.0/1,M10.5.0', 'EST5EDT,M3.2.0,M11.1.0', '<+0530>-5:30',
        '<-04>4<-03>,M9.1.6/24,M4.1.6/24', 'IST-2IDT,M3.4.4/26,M10.5.0', 'NST3:30NDT,M3.2.0,M11.1.0', 'AEST-10AEDT,M10.1.0,M4.1.0/3',
        'JST-9', 'HST10', 'EET-2EEST,M4.5.5/0,M10.5.4/24', 'MSK-3']
BAD = ['', 'UTC', 'CET-1CEST,M3.5.0', '1CET', 'UT0', 'CET-1;reboot', 'CET-1 CEST', '$(id)0', 'CET-1\"', '<a b>1', '<+03-3',
       'CET-1CEST,M3.5.0,M10.5.0/3,extra', 'A' * 70 + '0', 'Europe/Paris', 'CET-1`id`']


class TzCheck(unittest.TestCase):
    def test_wizard_and_settz_use_the_same_check(self):
        a, b = validator_awk('www/cgi-bin/wizard.cgi'), validator_awk('scripts/action.d/system.sh')
        norm = lambda s: re.sub(r'\s+', ' ', s).strip()
        self.assertEqual(norm(a), norm(b))

    def test_vectors(self):
        prog = validator_awk('www/cgi-bin/wizard.cgi')
        for v in GOOD:
            self.assertTrue(run_valid(prog, v), v)
        for v in BAD:
            self.assertFalse(run_valid(prog, v), v)

    def test_settz_refuses_a_bad_string_and_keeps_the_stored_one(self):
        s = text('scripts/action.d/system.sh')
        i = s.index('    settz)')
        body = s[i:s.index(';;', i) if ';;' in s[i:i + 4000] else i + 3000]
        self.assertIn('Invalid time zone', body)
        self.assertIn("tz=$(cat /mnt/config/timezone.conf 2>/dev/null)", body)
        # the invalid text is shown without < > (it goes into an HTML answer)
        self.assertIn("s/[^A-Za-z0-9,.:+\\/-]//g", body)


class ZoneTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which('node')
        if not node:
            raise unittest.SkipTest('node missing')
        js = ("global.window={};require(%r);const T=window.TC100_TZ;"
              "console.log(JSON.stringify({zones:T.zones,paris:T.find('Europe/Paris'),kiev:T.find('Europe/Kiev'),"
              "none:T.find('Mars/Base'),utc:T.browser()&&1,px:T.byPosix('UTC0')}))" % str(ROOT / 'www/scripts/tzlist.js'))
        out = subprocess.run([node, '-e', js], capture_output=True, text=True, check=True).stdout
        cls.t = json.loads(out)

    def test_table(self):
        z = self.t['zones']
        self.assertGreaterEqual(len(z), 90)
        self.assertEqual(self.t['paris'], ['Europe/Paris', 'CET-1CEST,M3.5.0,M10.5.0/3'])
        self.assertEqual(self.t['kiev'][0], 'Europe/Kyiv')           # an alias the browser may report
        self.assertIsNone(self.t['none'])
        self.assertEqual(self.t['px'], ['UTC', 'UTC0'])
        ids = [x[0] for x in z]
        self.assertEqual(len(ids), len(set(ids)))
        for prefix in ('Europe/', 'America/', 'Asia/', 'Australia/', 'Africa/'):
            self.assertTrue(any(i.startswith(prefix) for i in ids), prefix)

    def test_every_zone_is_a_valid_posix_string(self):
        prog = validator_awk('www/cgi-bin/wizard.cgi')
        for name, posix in self.t['zones']:
            self.assertTrue(run_valid(prog, posix), (name, posix))


class WizardTimeZone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        (d / 'config').mkdir()
        (d / 'config/boot.conf').write_text('REC_LOCAL=0\n')
        (d / 'config/timezone.conf').write_text('# comment\nUTC0\n')
        (d / 'first').write_text('')
        (d / 'csrf').write_text('0123456789abcdef0123456789abcdef')
        self.env = dict(os.environ, WZ_CSRF_FILE=str(d / 'csrf'), WZ_FIRST_BOOT_FLAG=str(d / 'first'), WZ_CONFIG=str(d / 'config'),
                        WZ_CARD=str(d), WZ_SCRIPTS=str(d), WZ_WIFI_CONF=str(d / 'w'), TC100_STORAGE_FILE=str(d / 'st'),
                        WZ_FLASHMODE=str(d / 'fm'))

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, body, shell=None):
        env = dict(self.env, REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(body)), QUERY_STRING='',
                   HTTP_X_CSRF_TOKEN='0123456789abcdef0123456789abcdef')
        r = subprocess.run((shell or SH) + [str(ROOT / 'www/cgi-bin/wizard.cgi')], input=body.encode(), capture_output=True, env=env)
        return json.loads(r.stdout.decode().split('\n\n', 1)[1])

    def tz(self):
        return (self.d / 'config/timezone.conf').read_text()

    def test_zone_is_saved_where_settings_keeps_it(self):
        r = self.post('profile=standalone&rec=off&tz=CET-1CEST%2CM3.5.0%2CM10.5.0%2F3')
        self.assertEqual(r, {'ok': True, 'wifi': 'unchanged', 'flash': 'no', 'password': 'unchanged', 'tz': 'applied'})
        self.assertEqual(self.tz(), 'CET-1CEST,M3.5.0,M10.5.0/3\n')
        self.assertFalse(list((self.d / 'config').glob('*wztmp*')))

    def test_plus_sign_zone_and_same_zone_again(self):
        self.assertEqual(self.post('profile=standalone&tz=%3C%2B0530%3E-5%3A30')['tz'], 'applied')
        self.assertEqual(self.tz(), '<+0530>-5:30\n')
        (self.d / 'first').write_text('')
        self.assertEqual(self.post('profile=standalone&tz=%3C%2B0530%3E-5%3A30')['tz'], 'unchanged')

    def test_invalid_zone_writes_nothing(self):
        for tz in ('Europe%2FParis', 'CET-1%3Breboot', '%24%28id%29', 'UTC', 'CET-1CEST%2CM3.5.0'):
            r = self.post('profile=standalone&rec=off&tz=' + tz)
            self.assertEqual(r, {'ok': False, 'error': 'invalid_tz'}, tz)
        self.assertEqual(self.tz(), '# comment\nUTC0\n')
        self.assertTrue((self.d / 'first').exists())
        self.assertFalse((self.d / 'config/.wizard3_done').exists())

    def test_no_zone_leaves_the_file_and_the_answer_alone(self):
        r = self.post('profile=standalone&rec=off')
        self.assertEqual(r, {'ok': True, 'wifi': 'unchanged', 'flash': 'no', 'password': 'unchanged'})
        self.assertEqual(self.tz(), '# comment\nUTC0\n')

    def test_works_under_dash_too(self):
        if not shutil.which('dash'):
            self.skipTest('no dash')
        self.assertEqual(self.post('profile=standalone&tz=JST-9', shell=['dash'])['tz'], 'applied')
        self.assertEqual(self.tz(), 'JST-9\n')

    def test_info_reports_the_zone_in_force(self):
        def info():
            env = dict(self.env, REQUEST_METHOD='GET', QUERY_STRING='info', PATH='/nonexistent:/usr/bin:/bin')
            out = subprocess.run(SH + [str(ROOT / 'www/cgi-bin/wizard.cgi')], capture_output=True, text=True, env=env).stdout
            return json.loads(out.split('\n\n', 1)[1])
        self.assertEqual(info()['tz'], 'UTC0')
        (self.d / 'config/timezone.conf').write_text('GMT0BST,M3.5.0/1,M10.5.0\n')
        self.assertEqual(info()['tz'], 'GMT0BST,M3.5.0/1,M10.5.0')
        (self.d / 'config/timezone.conf').write_text('rm -rf /\n')
        self.assertEqual(info()['tz'], '')

    def test_page_wiring(self):
        w = text('www/cgi-bin/wizard.cgi')
        for k in ('id="wp-tz"', 'id="wzTz"', 'TC100_TZ.browser()',
                  "f('tz', tzPosix())", 'invalid_tz:', '/scripts/tzlist.js?v=', 'tzOK()'):
            self.assertIn(k, w)
        # no Intl, no table: the step is left out and no tz is sent (the camera keeps its zone)
        self.assertIn("if (tzOK()) p.push('tz')", w)
        self.assertIn("if (tzOK()) body +=", w)
        # the browser zone is read inside try/catch, in the table file
        tz = text('www/scripts/tzlist.js')
        self.assertRegex(tz, r'try \{ id = Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone \|\| ""; \} catch')
        self.assertIn('/scripts/tzlist.js?v=', w)
        self.assertRegex(w, r'/scripts/tzlist\.js\?v=[0-9a-f]{8}')
        self.assertRegex(text('www/index.html'), r'scripts/tzlist\.js\?v=[0-9a-f]{8}')


class SettingsTimeZone(unittest.TestCase):
    def test_settings_shows_the_list_and_keeps_the_text_field(self):
        h = text('www/settings.html')
        self.assertIn('id="timezone_preset"', h)
        self.assertNotRegex(h, r'<select id="timezone_preset"[^>]*name=')   # never posted: the TZ string is the one value
        self.assertIn('name="tz" id="timezone"', h)
        self.assertIn('window.tcTzSync', h)
        self.assertIn('window.tcTzSync', text('src/webui/index/95-settings-page.js'))
        self.assertIn('window.tcTzSync', text('www/scripts/index.bundle.min.js'))

    def test_french_for_every_new_string(self):
        fr = text('www/i18n/fr.js')
        for k in ('Time zone', 'Time zone of the camera', 'Other (TZ string below)', 'Low-light frame rate', '15 fps', '20 fps',
                  'The time zone is not valid: choose another one in the list.',
                  'This browser did not tell its time zone (or it is not in the list): UTC is selected, choose yours.'):
            self.assertIn('"%s":' % k, fr)
        r = subprocess.run(['python3' if shutil.which('python3') else 'python', str(ROOT / 'src/webui/i18n-strings.py'), '--missing'],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '')


class LowLightFps(unittest.TestCase):
    def video_fragment(self):
        s = text('scripts/action.d/video.sh')
        a = s.index('_lv0=$(_dn_get LOWLIGHT_FPS_VALUE)')
        return s[a:s.index('\n', s.index('_lv=$_lv0', a))]

    def lv(self, stored, posted):
        t = Path(tempfile.mkdtemp())
        try:
            (t / 'daynight.conf').write_text(('LOWLIGHT_FPS_VALUE=%s\n' % stored) if stored is not None else 'LUMA_NIGHT=40\n')
            code = '_dn_get() { sed -n "s/^$1=//p" %s/daynight.conf | tail -n 1; }\n' % t.as_posix() + self.video_fragment() + '\nprintf %s "$_lv"'
            r = subprocess.run(SH + ['-c', code], capture_output=True, text=True,
                               env=dict(os.environ, **({'F_dn_lowlight_fps': posted} if posted is not None else {})))
            return r.stdout
        finally:
            shutil.rmtree(t)

    def test_value_is_10_unless_15_or_20(self):
        self.assertEqual(self.lv(None, None), '10')          # nothing stored: today's behaviour
        self.assertEqual(self.lv('15', None), '15')          # a form without the field keeps the stored value
        self.assertEqual(self.lv('15', '20'), '20')
        self.assertEqual(self.lv('20', '10'), '10')
        self.assertEqual(self.lv('20', '12'), '20')          # not one of the three: the stored value stays
        self.assertEqual(self.lv('garbage', '$(id)'), '10')

    def test_saved_in_daynight_conf_and_restarts_the_video(self):
        v = text('scripts/action.d/video.sh')
        self.assertIn('LOWLIGHT_FPS_VALUE=%s', v)
        self.assertIn('"$_lf" "$_lv" "$_irm"', v)
        self.assertIn('[ "$_lv0" = "$_lv" ]', v)

    def test_launch_exports_only_15_or_20(self):
        s = text('v3/linux66-sd/rtsp-launch.sh')
        i = s.index('dnc() {')
        frag = s[i:s.index('\n', s.index('RTSP_LOWLIGHT_FPS_VALUE', i))]
        self.assertIn('15|20) export RTSP_LOWLIGHT_FPS_VALUE=', frag)
        for stored, want in ((None, ''), ('10', ''), ('15', '15'), ('20', '20'), ('12', ''), ('abc', ''), ('1520', '')):
            t = Path(tempfile.mkdtemp())
            try:
                (t / 'daynight.conf').write_text('LOWLIGHT_FPS=1\n' + ('LOWLIGHT_FPS_VALUE=%s\n' % stored if stored else ''))
                code = frag.replace('/mnt/config/daynight.conf', (t / 'daynight.conf').as_posix()) + '\nprintf %s "${RTSP_LOWLIGHT_FPS_VALUE:-}|${RTSP_LOWLIGHT_FPS:-}"'
                env = {k: v for k, v in os.environ.items() if not k.startswith('RTSP_')}
                out = subprocess.run(SH + ['-c', code], capture_output=True, text=True, env=env).stdout
                self.assertEqual(out, want + '|1', stored)
            finally:
                shutil.rmtree(t)

    def test_state_validation_and_exchange_know_the_key(self):
        st = text('www/cgi-bin/state.cgi')
        self.assertIn('cfg_int _dn_lv LOWLIGHT_FPS_VALUE 10', st)
        self.assertIn('"lowlight_fps_value":%s', st)
        ct = text('scripts/config-transaction.sh')
        self.assertIn('LOWLIGHT_FPS_VALUE lowlight_fps_value', ct)
        self.assertIn('lowlight_fps_value) case "$_tc_value" in 10|15|20)', ct)
        self.assertIn('"LOWLIGHT_FPS_VALUE";"lowlight_fps_value"', text('www/cgi-bin/config_exchange.cgi'))
        self.assertIn('put("dn_lowlight_fps", d.lowlight_fps_value)', text('src/webui/index/80-camera-controls.js'))
        self.assertIn('put("dn_lowlight_fps", d.lowlight_fps_value)', text('www/scripts/index.bundle.min.js'))
        self.assertIn('name="dn_lowlight_fps"', text('www/settings.html'))

    def test_tc100_rtsp_reads_the_value_and_scales_the_exposure(self):
        c = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('getenv("RTSP_LOWLIGHT_FPS_VALUE")', c)
        self.assertIn('lowlight_fps = n;', c)
        self.assertNotIn('atoi(v)', c)   # uClibc: see test_tc100rtsp test_no_uclibc_missing_imports
        self.assertIn('lowlight_exp = (unsigned int)(LOWLIGHT_EXP * 10 / lowlight_fps);', c)
        self.assertIn('a[0] = enter ? lowlight_exp : ae0[0];', c)
        self.assertIn('if (lowlight_on && !p_expct) a[0] = lowlight_exp;', c)
        self.assertNotIn('f == 10', c[c.index('static void lowlight_check'):c.index('static void ispx_ae_report')])
        # the limits the Settings help quotes: 2812 lines at 10 fps (unchanged), 1874 at 15, 1406 at 20
        self.assertEqual([2812 * 10 // r for r in (10, 15, 20)], [2812, 1874, 1406])
        self.assertIn('2812 lines at 10 fps, 1874 at 15, 1406 at 20', text('www/settings.html'))

    def test_the_parsing_compiles_and_gives_the_documented_numbers(self):
        """the parsing and scaling lines of lowlight_check, compiled by the host C compiler (the ARM cross build compiles the whole file)"""
        cc = shutil.which('gcc') or shutil.which('cc')
        if not cc:
            self.skipTest('no C compiler')
        c = text('src/tc100rtsp/tc100_rtsp.c')
        parse = '\n'.join(re.search(r'^\s*(' + re.escape(k) + r'[^\n]*)$', c, re.M).group(1)
                          for k in ('int n = v && v[0]', 'lowlight_fps = n;', 'lowlight_exp = (unsigned int)'))
        prog = ('#include <stdio.h>\n#include <stdlib.h>\n#define LOWLIGHT_EXP 2812\nstatic int lowlight_fps = 10;\n'
                'static unsigned int lowlight_exp;\nint main(int argc, char **argv) { const char *v = argc > 1 ? argv[1] : NULL;\n'
                + parse + '\nprintf("%d %u\\n", lowlight_fps, lowlight_exp); return 0; }\n')
        t = Path(tempfile.mkdtemp())
        try:
            (t / 'p.c').write_text(prog)
            subprocess.run([cc, '-Wall', '-Werror', '-o', str(t / 'p'), str(t / 'p.c')], check=True, capture_output=True)
            for arg, want in ((None, '10 2812'), ('10', '10 2812'), ('15', '15 1874'), ('20', '20 1406'), ('12', '10 2812'), ('x', '10 2812')):
                out = subprocess.run([str(t / 'p')] + ([arg] if arg is not None else []), capture_output=True, text=True).stdout.strip()
                self.assertEqual(out, want, arg)
        finally:
            shutil.rmtree(t)


if __name__ == '__main__':
    unittest.main()
