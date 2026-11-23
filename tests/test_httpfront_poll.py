"""Two more native routes of httpfront (src/httpfront/poll.h, TC100_NATIVE_STATUS=1): the Day/night page poll
GET /cgi-bin/state.cgi?cmd=daynight&format=json and the Hardware page poll GET /cgi-bin/action.cgi?cmd=hw_state&format=json.

Same method as tests/test_httpfront_native.py and test_httpfront_dash.py: the real CGI (state.cgi / action.cgi with
func.cgi, statelib.cgi, common_functions.sh, event-logger.sh and action.d/hardware.sh) runs under busybox ash against a
fixture tree; the native handler reads a twin of that tree through TC100_STATUS_ROOT; the two bodies must be identical
byte for byte. What the native code does not print exactly as the shell does must reach the stub httpd untouched.
Skipped without the ARM compiler and qemu-arm (`sh tests/docker/local-ci.sh tests` has both).
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import test_httpfront_native as tn  # noqa: E402
import test_statusline as ts  # noqa: E402

DN = '/cgi-bin/state.cgi?cmd=daynight&format=json'
HW = '/cgi-bin/action.cgi?cmd=hw_state&format=json'
RW = re.compile(r'/(mnt|tmp|proc|var/run|sys)/')        # test_statusline.PATHS plus /sys (the LEDs, the button)
FILES = {'www/cgi-bin': ['state.cgi', 'action.cgi', 'func.cgi', 'statelib.cgi'],
         'scripts': ['common_functions.sh', 'event-logger.sh', 'isp-tune.sh', 'action.d/hardware.sh']}


def build(base, over):
    """the 'full' tree of test_statusline, the CGIs and the scripts they source (paths moved into the tree), the overrides"""
    ts.build(base, 'full', [])
    base = Path(base)
    for src, names in FILES.items():
        for name in names:
            p = base / 'mnt' / src / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(RW.sub(lambda m: str(base) + '/' + m.group(1) + '/', (ROOT / src / name).read_text()))
    # state.cgi fills its 1 s answer cache with `sh "$0"`: the same shell as the outer one
    (base / 'bin/sh').write_text('#!/bin/sh\nexec %s "$@"\n' % ' '.join(ts.SHELL))
    (base / 'bin/sh').chmod(0o755)
    (base / 'tmp/log').mkdir(parents=True, exist_ok=True)
    for rel, body in over.items():
        p = base / rel
        if body is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body) if isinstance(body, bytes) else p.write_text(body)
    return base


def cgi(base, path, fresh=True):
    name, _, query = path.rpartition('/')[2].partition('?')
    if fresh:               # the fixture's clock stands still: without this the 1 s cache of state.cgi never ends
        for f in Path(base, 'tmp').glob('state-response-*'):
            f.unlink()
    r = ts.run_cgi(base, name, query)
    assert r.returncode == 0, r.stderr
    head, body = ts.split(r.stdout)
    assert 'Content-type: application/json' in head, r.stdout[:300]
    return body


AE = '120 1125 512 256 256 0 1125\n'      # lumi exp_time a_gain d_gain isp_d_gain dark_flag exp_max
DN_SCEN = {
    'nothing': {},
    'day_luma': {'tmp/cam_luma': '143\n', 'var/run/ircut': '1\n', 'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=luma\n'},
    'night_ae': {'tmp/cam_luma': '12\n', 'var/run/ircut': '0\n', 'tmp/cam_ae': '9 1125 4096 1024 300 1 1125\n',
                 'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=ae\nAE_NIGHT_ABOVE=20000\nAE_DAY_BELOW=2500\n'},
    'source_isp': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=isp\n', 'tmp/cam_ae': AE},
    'source_vendor': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=vendor\nVENDOR_NIGHT_LUM=4000\nVENDOR_DAY_LUM=1500\n'
                      'IR_LED_MAX_ON=3600\n', 'tmp/cam_ae': AE},
    'source_unknown': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=moon\n'},
    'source_empty': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=\n'},
    'source_odd': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=a"e\\x\n'},
    'source_cr': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=ae\r\nLUMA_NIGHT=30\r\n'},
    'source_long': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=' + 'v' * 60 + '\nIR_LED_MODE=' + 'o' * 60 + '\n'},
    'every_key': {'mnt/config/daynight.conf': 'DAYNIGHT_SOURCE=vendor\nLUMA_NIGHT=35\nLUMA_DAY=110\nAE_NIGHT_ABOVE=1\n'
                  'AE_DAY_BELOW=2\nNIGHT_HOLD=3\nDAY_HOLD=4\nVENDOR_NIGHT_LUM=5\nVENDOR_DAY_LUM=6\nIR_LED_MAX_ON=7\n'
                  'NIGHT_STYLE=2\nLOWLIGHT_FPS=0\nNIGHT_720P=1\nLOWLIGHT_FPS_VALUE=15\nIR_LED_MODE=force\n'},
    'ints_bad': {'mnt/config/daynight.conf': 'LUMA_NIGHT=-4\nLUMA_DAY=1e3\nAE_NIGHT_ABOVE=\nAE_DAY_BELOW= 3000\nNIGHT_HOLD=10 \n'
                 'DAY_HOLD="60"\nNIGHT_STYLE=x\nLOWLIGHT_FPS=0x1\nNIGHT_720P=yes\n'},
    'ints_leading_zero': {'mnt/config/daynight.conf': 'LUMA_NIGHT=007\nLUMA_DAY=0\nNIGHT_HOLD=00\n'},
    'ints_long': {'mnt/config/daynight.conf': 'IR_LED_MAX_ON=12345678901234567890123\n'},
    'fps_values': {'mnt/config/daynight.conf': 'LOWLIGHT_FPS_VALUE=20\n'},
    'fps_other': {'mnt/config/daynight.conf': 'LOWLIGHT_FPS_VALUE=12\n'},
    'fps_015': {'mnt/config/daynight.conf': 'LOWLIGHT_FPS_VALUE=015\n'},
    'ir_off': {'mnt/config/daynight.conf': 'IR_LED_MODE=off\n'},
    'ir_other': {'mnt/config/daynight.conf': 'IR_LED_MODE=Off\n'},
    'last_wins': {'mnt/config/daynight.conf': 'LUMA_NIGHT=1\nDAYNIGHT_SOURCE=ae\nLUMA_NIGHT=2\nDAYNIGHT_SOURCE=isp\n'},
    'last_empty_wins': {'mnt/config/daynight.conf': 'LUMA_NIGHT=55\nLUMA_NIGHT\nDAYNIGHT_SOURCE=ae\nDAYNIGHT_SOURCE=\n'},
    'last_line_no_newline': {'mnt/config/daynight.conf': 'LUMA_NIGHT=55\nDAYNIGHT_SOURCE=vendor'},
    'comments_blanks': {'mnt/config/daynight.conf': '# LUMA_NIGHT=1\n;LUMA_DAY=2\n\n LUMA_NIGHT=3\nLUMA_DAY =4\nNIGHT_HOLD=5=6\n'
                        'DAY_HOLD==7\nluma_night=8\n'},
    'section': {'mnt/config/daynight.conf': 'LUMA_NIGHT=1\n[DAYNIGHT]\nSOURCE=ae\nLUMA_NIGHT=2\n[IR_LED]\nMODE=off\nMAX_ON=9\n'
                '[LOWLIGHT_FPS]\nVALUE=20\n[LUMA]\nDAY=77\n'},
    'section_bad': {'mnt/config/daynight.conf': '[a b]\nLUMA_NIGHT=2\n[]\nLUMA_DAY=3\n[' + 'S' * 40 + ']\nNIGHT_HOLD=4\n[x]=1\n'
                    'DAY_HOLD=5\n[NIGHT\nSTYLE=2\n'},
    'section_then_plain_key': {'mnt/config/daynight.conf': '[LUMA]\nLUMA_NIGHT=2\nNIGHT=3\n'},
    'luma_blanks': {'tmp/cam_luma': ' \t88 \n'},
    'luma_no_newline': {'tmp/cam_luma': '91'},
    'luma_text': {'tmp/cam_luma': 'n/a\n'},
    'luma_empty': {'tmp/cam_luma': ''},
    'luma_two_words': {'tmp/cam_luma': '90 91\n'},
    'luma_zeros': {'tmp/cam_luma': '007\n200\n'},
    'ae_six_fields': {'tmp/cam_ae': '120 1125 512 256 256 0\n'},
    'ae_five_fields': {'tmp/cam_ae': '120 1125 512 256 256\n'},
    'ae_text': {'tmp/cam_ae': '120 1125 512 x 256 0 1125\n'},
    'ae_negative': {'tmp/cam_ae': '120 -1 512 256 256 0\n'},
    'ae_empty': {'tmp/cam_ae': ''},
    'ae_no_newline': {'tmp/cam_ae': '80 500 300 256 256 1 900'},
    'ae_tabs': {'tmp/cam_ae': '\t80\t500 300  256 256 1   900 \n'},
    'ae_max_zero': {'tmp/cam_ae': '80 500 300 256 256 1 0\n'},
    'ae_max_text': {'tmp/cam_ae': '80 500 300 256 256 1 x\n'},
    'ae_max_two_words': {'tmp/cam_ae': '80 500 300 256 256 1 900 7\n'},
    'ae_lumi_zero': {'tmp/cam_ae': '0 1125 512 256 256 0 1125\n'},
    'ae_zeros': {'tmp/cam_ae': '0 0 0 0 0 0 0\n'},
    'ae_long_field': {'tmp/cam_ae': '120 1234567890 512 256 256 0 1125\n'},
    'ae_nine_digits': {'tmp/cam_ae': '5 999999999 999999999 3 2 1 7\n'},
    'ae_dark_flag_odd': {'tmp/cam_ae': '120 1125 512 256 256 007 1125\n'},
    'cut_day': {'var/run/ircut': '1\n'},
    'cut_night': {'var/run/ircut': '0\n'},
    'cut_night_no_newline': {'var/run/ircut': '0'},
    'cut_empty': {'var/run/ircut': ''},
    'cut_text': {'var/run/ircut': 'night\n'},
    'cut_00': {'var/run/ircut': '00\n'},
    'manual_night': {'mnt/config/rtspserver.conf': 'USERNAME=root\ndaynight=3\n'},
    'auto_mode': {'mnt/config/rtspserver.conf': 'daynight=0\ndaynight=3\n'},
    'manual_first': {'mnt/config/rtspserver.conf': 'daynight=3\ndaynight=0\n'},
    'manual_no_newline': {'mnt/config/rtspserver.conf': 'USERNAME=root\ndaynight=3'},
    'manual_blank': {'mnt/config/rtspserver.conf': ' daynight=3\ndaynight = 3\ndaynight=3 \n'},
    'manual_no_equal': {'mnt/config/rtspserver.conf': 'daynight\ndaynight=3\n'},
    'manual_other_key': {'mnt/config/rtspserver.conf': 'daynightawb=3\nxdaynight=3\n'},
    'no_rtsp_conf': {'mnt/config/rtspserver.conf': None},
}
# printf %s prints a number of the files as it is written: 007 is not JSON, on both sides
NOT_JSON = ('ints_leading_zero', 'luma_zeros', 'ae_dark_flag_odd')
# what the native code leaves to the CGI
DN_FALL = {
    'ae_octal': {'tmp/cam_ae': '120 0700 512 256 256 0 1125\n'},
    'ae_octal_lumi': {'tmp/cam_ae': '012 700 512 256 256 0 1125\n'},
    'ae_octal_max': {'tmp/cam_ae': '120 700 512 256 256 0 0900\n'},
    'ae_overflow': {'tmp/cam_ae': '5 999999999 999999999 999999999 999999999 1 7\n'},
    'ae_lumi_long': {'tmp/cam_ae': '1234567890 700 512 256 256 0 1125\n'},
    'ae_flag_long': {'tmp/cam_ae': '120 700 512 256 256 ' + '1' * 30 + '\n'},
    'ae_line_long': {'tmp/cam_ae': '120 700 512 256 256 0 1125 ' + 'x' * 300 + '\n'},
    'conf_ends_equal': {'mnt/config/daynight.conf': 'LUMA_NIGHT=40=\n'},
    'conf_number_long': {'mnt/config/daynight.conf': 'LUMA_NIGHT=' + '1' * 40 + '\n'},
    'conf_line_long': {'mnt/config/daynight.conf': '# ' + 'x' * 3000 + '\nLUMA_NIGHT=4\n'},
    'luma_long': {'tmp/cam_luma': '1' * 40 + '\n'},
    'manual_ends_equal': {'mnt/config/rtspserver.conf': 'daynight=3=\n'},
}


def dead_pid():
    p = subprocess.Popen(['true'])
    p.wait()
    return p.pid


LEDS = {'sys/class/leds/blue_led/brightness': '1\n', 'sys/class/leds/red_led/brightness': '0\n',
        'sys/class/leds/ir/brightness': '0\n', 'var/run/ircut': '1\n', 'sys/class/gpio/gpio522/value': '1\n'}


def hw_scen():
    now = int(time.time())
    return {
        'nothing': {},
        'day': dict(LEDS),
        'night': dict(LEDS, **{'sys/class/leds/ir/brightness': '255\n', 'var/run/ircut': '0\n',
                               'var/run/auto-night-detection.pid': '%d\n' % os.getpid()}),
        'old_led_names': {'sys/class/leds/blue/brightness': '0\n', 'sys/class/leds/red/brightness': '1\n'},
        'both_led_names': {'sys/class/leds/blue_led/brightness': '0\n', 'sys/class/leds/blue/brightness': '1\n'},
        'led_empty_then_old': {'sys/class/leds/blue_led/brightness': '', 'sys/class/leds/blue/brightness': '1\n'},
        'led_no_newline_then_old': {'sys/class/leds/red_led/brightness': '1', 'sys/class/leds/red/brightness': '0\n'},
        'led_no_newline_alone': {'sys/class/leds/red_led/brightness': '1'},
        'led_no_newline_then_empty': {'sys/class/leds/red_led/brightness': '1', 'sys/class/leds/red/brightness': ''},
        'led_blank_line': {'sys/class/leds/blue_led/brightness': ' \n', 'sys/class/leds/blue/brightness': '1\n'},
        'led_values': {'sys/class/leds/blue_led/brightness': '00\n', 'sys/class/leds/red_led/brightness': 'on\n',
                       'sys/class/leds/ir/brightness': '-1\n'},
        'led_blanks': {'sys/class/leds/blue_led/brightness': ' 1 \n', 'sys/class/leds/ir/brightness': '1'},
        'cut_text': {'var/run/ircut': '2\n'},
        'cut_empty': {'var/run/ircut': ''},
        'cut_no_newline': {'var/run/ircut': '0'},
        'cut_odd': {'var/run/ircut': '"1"\n'},
        'auto_dead': {'var/run/auto-night-detection.pid': '%d\n' % dead_pid()},
        'auto_alive_no_newline': {'var/run/auto-night-detection.pid': '%d' % os.getpid()},
        'sound': {'var/run/sound_level': '%d -42.5 x\n' % (now - 2)},
        'sound_zero': {'var/run/sound_level': '%d 0\n' % (now - 2)},
        'sound_old': {'var/run/sound_level': '%d -42.5\n' % (now - 60)},
        'sound_future': {'var/run/sound_level': '%d -3\n' % (now + 600)},
        'sound_positive': {'var/run/sound_level': '%d 3\n' % (now - 2)},
        'sound_minus_text': {'var/run/sound_level': '%d -x\n' % (now - 2)},
        'sound_no_level': {'var/run/sound_level': '%d\n' % (now - 2)},
        'sound_ts_text': {'var/run/sound_level': 'now -3\n'},
        'sound_empty': {'var/run/sound_level': ''},
        'sound_no_newline': {'var/run/sound_level': '%d -7' % (now - 2)},
        # printf %s: what follows "-<digit>" is printed as it is, quotes and backslashes included (not valid JSON, and
        # the same bytes on both sides)
        'sound_needs_escaping': {'var/run/sound_level': '%d -3"\\n\\\\,"x":{}\n' % (now - 2)},
        'sound_utf8': {'var/run/sound_level': ('%d -3é\n' % (now - 2)).encode()},
        'button_pressed': {'sys/class/gpio/gpio522/value': '0\n'},
        'button_text': {'sys/class/gpio/gpio522/value': 'low\n'},
        'button_empty': {'sys/class/gpio/gpio522/value': ''},
        'token_upper': {'tmp/csrf_token': 'ABCDEF0123\n'},
        'token_no_newline': {'tmp/csrf_token': 'abc123'},
    }


HW_FALL = {
    'no_token': {'tmp/csrf_token': None},
    'token_empty': {'tmp/csrf_token': ''},
    'token_unclean': {'tmp/csrf_token': 'abc-123\n'},
    'no_hardware_script': {'mnt/scripts/action.d/hardware.sh': None},
    'no_log_dir': {'tmp/log/audit.log': None, 'tmp/log': 'not a directory'},
    'log_to_rotate': {'tmp/log/audit.log': '1700000000 cmd=hw_state ip=192.0.2.7\n' * 2000},
    'pid_empty': {'var/run/auto-night-detection.pid': ''},         # busybox kill takes "" as 0: its own group
    'pid_newline_only': {'var/run/auto-night-detection.pid': '\n'},
    'pid_text': {'var/run/auto-night-detection.pid': 'abc\n'},
    'pid_two': {'var/run/auto-night-detection.pid': '1\n2\n'},
    'pid_blank': {'var/run/auto-night-detection.pid': ' 1\n'},
    'pid_zero': {'var/run/auto-night-detection.pid': '0\n'},
    'pid_negative': {'var/run/auto-night-detection.pid': '-1\n'},
    'pid_long': {'var/run/auto-night-detection.pid': '1' * 40 + '\n'},
    'sound_octal': {'var/run/sound_level': '0%d -3\n' % (time.time() + 600)},
    'sound_control': {'var/run/sound_level': '%d -3\x01\n' % (time.time() + 600)},
    'sound_line_long': {'var/run/sound_level': '%d -3%s\n' % (time.time() + 600, '9' * 300)},
    'no_clock': {'proc/stat': None},
}


def build_fall(base, over):
    over = dict(over)
    notdir = over.pop('tmp/log', None)
    base = build(base, over)
    if notdir is not None:
        (base / 'tmp/log').rmdir()
        (base / 'tmp/log').write_text(notdir)
    return base


@unittest.skipUnless(tn.CC and tn.QEMU, 'needs arm-linux-gnueabi-gcc and qemu-arm')
class Poll(unittest.TestCase):
    port = 18840
    tearDownClass = classmethod(tn.Native.tearDownClass.__func__)
    start = tn.Native.start

    @classmethod
    def setUpClass(cls):
        tn.Native.setUpClass.__func__(cls)
        # the flags of the CI plus -Wextra: the new code must stay clean under both
        subprocess.run([tn.CC] + tn.FLAGS + tn.SSP + ['-Wextra', str(ROOT / 'src/httpfront/httpfront.c'), '-o', cls.bin], check=True)

    def ask(self, path):
        for _ in range(3):      # the first connection of a server can be the probe of start()
            resp, req = tn.get(self.port, path)
            if resp:
                return resp, req
            time.sleep(0.2)
        return b'', req

    def native(self, path, what):
        resp, _ = self.ask(path)
        head, _, body = resp.partition(b'\r\n\r\n')
        self.assertTrue(head.startswith(b'HTTP/1.0 200 OK\r\n'), (what, resp[:200]))
        self.assertIn(b'Content-Type: application/json\r\n', head)
        self.assertIn(b'Cache-Control: max-age=0, no-store, no-cache\r\n', head)
        self.assertIn(b'Content-Length: %d' % len(body), head + b'\r\n')
        return body

    # ---- daynight
    def test_daynight_parity_with_the_cgi(self):
        for name, over in DN_SCEN.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                fa, fb = build(a, over), build(b, over)
                self.start(fb)
                for step in range(2):
                    if step == 1:       # the light changed between two polls
                        for f in (fa, fb):
                            (f / 'tmp/cam_luma').write_text('31\n')
                            (f / 'var/run/ircut').write_text('0\n')
                    want = cgi(fa, DN)
                    body = self.native(DN + '&_=17000000%d' % step, (name, step))
                    self.assertEqual(body.decode(), want, (name, step))
                    if name not in NOT_JSON:
                        json.loads(body)
                self.assertEqual(sorted(p.name for p in (fb / 'tmp').glob('state-response*')), [])   # nothing written

    def test_daynight_values_are_what_the_fixture_says(self):
        """not just equal to the CGI: a bug shared by a fixture would hide behind equality"""
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, DN_SCEN['night_ae'])
            self.start(fb)
            d = json.loads(self.native(DN, 'night_ae'))
            self.assertEqual((d['source'], d['night'], d['auto'], d['luma']), ('ae', 1, 1, 12))
            self.assertEqual((d['ae_night_above'], d['ae_day_below'], d['luma_night'], d['luma_day']), (20000, 2500, 40, 100))
            self.assertEqual((d['ae_available'], d['lumi'], d['exp_time'], d['a_gain'], d['d_gain'], d['isp_d_gain'], d['dark_flag']),
                             (1, 9, 1125, 4096, 1024, 300, 1))
            self.assertEqual(d['index'], 1125 * 4096 // 256 * 1024 // 256 * 300 // 256)
            self.assertEqual(d['vendor_lum'], 1125 * (4096 * 1024 // 256 * 300 // 256) // 1125 * 40 // 9)
            self.assertEqual((d['ir_led_mode'], d['lowlight_fps_value'], d['night_720p']), ('auto', 10, 0))
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, DN_SCEN['section'])
            self.start(fb)
            d = json.loads(self.native(DN, 'section'))
            self.assertEqual((d['source'], d['luma_night'], d['ir_led_mode'], d['ir_max_on'], d['lowlight_fps_value'], d['luma_day']),
                             ('ae', 1, 'off', 9, 20, 77))
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, {})
            self.start(fb)
            d = json.loads(self.native(DN, 'nothing'))
            self.assertEqual((d['source'], d['night'], d['luma'], d['ae_available'], d['index'], d['vendor_lum']),
                             ('luma', 0, None, 0, None, None))

    def test_daynight_same_answer_as_the_cached_cgi(self):
        """state.cgi keeps its answer 1 s (state_response_cache): a second call within the second replays it, and that is
        still what the native route says while the files have not moved"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            fa, fb = build(a, DN_SCEN['night_ae']), build(b, DN_SCEN['night_ae'])
            self.start(fb)
            first = cgi(fa, DN)
            self.assertTrue((fa / 'tmp/state-response-daynight-json.cache').exists())
            self.assertEqual(cgi(fa, DN, fresh=False), first)
            self.assertEqual(self.native(DN, 'cached').decode(), first)

    def test_daynight_falls_through_when_it_cannot_answer_exactly(self):
        for name, over in DN_FALL.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as b:
                fb = build(b, over)
                self.start(fb)
                resp, req = self.ask(DN)
                self.assertEqual(resp, b'HTTPD:' + req, name)

    # ---- hw_state
    def test_hw_state_parity_with_the_cgi(self):
        for name in list(hw_scen()):
            over = hw_scen()[name]      # built now: the level of the microphone only counts for 10 s
            with self.subTest(name), tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                fa, fb = build(a, over), build(b, over)
                self.start(fb)
                for step in range(2):
                    if step == 1:       # somebody pressed the button, the filter moved
                        for f in (fa, fb):
                            (f / 'sys/class/gpio/gpio522').mkdir(parents=True, exist_ok=True)
                            (f / 'sys/class/gpio/gpio522/value').write_text('0\n')
                            (f / 'var/run/ircut').write_text('0\n')
                    want = cgi(fa, HW)
                    body = self.native(HW + '&_=%d' % step, (name, step))
                    self.assertEqual(body, want.encode(), (name, step))
                    if name not in ('sound_needs_escaping', 'sound_utf8'):       # printed as they are: not JSON, on both sides
                        json.loads(body)
                # the audit log of action.cgi: one line per request on both sides (the address is each client's own)
                la, lb = (fa / 'tmp/log/audit.log').read_text(), (fb / 'tmp/log/audit.log').read_text()
                self.assertEqual(la, '1700086400 cmd=hw_state ip=192.0.2.7\n' * 2, name)
                self.assertEqual(lb, la.replace('192.0.2.7', '127.0.0.1'), name)
                self.assertEqual(sorted(p.name for p in (fa / 'tmp/log').iterdir()), sorted(p.name for p in (fb / 'tmp/log').iterdir()))

    def test_hw_state_values_are_what_the_fixture_says(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, dict(hw_scen()['night'], **{'var/run/sound_level': '%d -42.5\n' % int(time.time())}))
            self.start(fb)
            d = json.loads(self.native(HW, 'night'))
            self.assertEqual(d, {'ok': True, 'front_led': True, 'red_led': False, 'ir_led': True, 'ir_cut': 0,
                                 'auto_daynight': True, 'sound_db': -42.5, 'button': False})
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, {})
            self.start(fb)
            d = json.loads(self.native(HW, 'nothing'))
            self.assertEqual(d, {'ok': True, 'front_led': None, 'red_led': None, 'ir_led': None, 'ir_cut': None,
                                 'auto_daynight': False, 'sound_db': None, 'button': None})

    def test_hw_state_falls_through_when_it_cannot_answer_exactly(self):
        for name, over in HW_FALL.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as b:
                fb = build_fall(b, over)
                log = fb / 'tmp/log/audit.log'
                before = log.read_text() if log.is_file() else None
                self.start(fb)
                resp, req = self.ask(HW)
                self.assertEqual(resp, b'HTTPD:' + req, name)
                self.assertEqual(log.read_text() if log.is_file() else None, before, name)   # the CGI writes its line itself

    def test_hw_state_a_get_needs_no_csrf_header(self):
        """action.cgi answers this read to a plain GET (ACTION_GET_READS, csrf_guard lets GET through): so does the native
        route, with or without the header"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            fa, fb = build(a, LEDS), build(b, LEDS)
            self.start(fb)
            want = cgi(fa, HW).encode()
            self.assertEqual(self.native(HW, 'plain'), want)
            req = (b'GET ' + HW.encode() + b' HTTP/1.1\r\nX-CSRF-Token: wrong\r\nAuthorization: Basic '
                   + base64.b64encode(b'root:pass') + b'\r\n\r\n')
            self.assertEqual(tn.ask(self.port, req).partition(b'\r\n\r\n')[2], want)

    # ---- the router
    def test_only_these_two_queries(self):
        """func.cgi's reading of the query: names before the first '=', the last value wins, %XX and + decoded (left to
        the CGI); every other command of the two CGIs goes to httpd"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            fa, fb = build(a, LEDS), build(b, LEDS)
            self.start(fb)
            for base, name in ((DN, 'daynight'), (HW, 'hw_state')):
                cgi_name = base.split('?')[0]
                for q in ('format=json&cmd=%s' % name, '_=1&cmd=x&cmd=%s&format=plain&format=json&x' % name,
                          'cmd=%s&format=json&&=3&a-b=4&val=%%41+b&=' % name, 'cmd=%s&format=json&cmdx=reboot&xcmd=y' % name):
                    with self.subTest(q):
                        want = cgi(fa, cgi_name + '?' + q)
                        self.assertEqual(self.native(cgi_name + '?' + q, q).decode(), want)
                for q in ('cmd=%s' % name, 'cmd=%s&format=plain' % name, 'cmd=%s&format=json&format=x' % name,
                          'cmd=%s&format=json&cmd=fullconfig' % name, 'cmd=%sx&format=json' % name, 'cmd=%s&format=jso%%6e' % name,
                          'cmd=%s+&format=json' % name, 'CMD=%s&format=json' % name, 'cmd=%s&format=json&cmd' % name,
                          'cmd=%s&format=json&format' % name, 'xcmd=%s&format=json' % name, '', 'cmd=&format=json',
                          'cmd=statusline&format=json', 'cmd=reboot&format=json', 'cmd=%s;format=json' % name):
                    with self.subTest(q):
                        resp, req = self.ask(cgi_name + '?' + q)
                        self.assertEqual(resp, b'HTTPD:' + req, q)
                for path in (cgi_name, cgi_name + 'x?cmd=%s&format=json' % name, cgi_name.replace('.cgi', '') + '?cmd=%s&format=json' % name,
                             '/cgi-bin/' + cgi_name + '?cmd=%s&format=json' % name):
                    resp, req = self.ask(path)
                    self.assertEqual(resp, b'HTTPD:' + req, path)
                for verb in (b'POST', b'HEAD'):
                    req = verb + b' ' + base.encode() + b' HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n' % base64.b64encode(b'root:pass')
                    self.assertEqual(tn.ask(self.port, req), b'HTTPD:' + req, verb)
            # the two commands are not swapped between the two CGIs
            for path in ('/cgi-bin/state.cgi?cmd=hw_state&format=json', '/cgi-bin/action.cgi?cmd=daynight&format=json'):
                resp, req = self.ask(path)
                self.assertEqual(resp, b'HTTPD:' + req, path)

    def test_switch_off(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, LEDS)
            for native in (None, '0'):
                self.start(fb, native=native)
                for path in (DN, HW):
                    with self.subTest(native=native, path=path):
                        resp, req = self.ask(path)
                        self.assertEqual(resp, b'HTTPD:' + req)
            self.assertFalse((fb / 'tmp/log/audit.log').exists())

    def test_login_still_applies(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, LEDS)
            self.start(fb, TC100_WEB_LOCKOUT='1')
            Path(self.lock, 'fail').unlink(missing_ok=True)
            for path, key in ((DN, b'luma_night'), (HW, b'front_led')):
                self.assertIn(key, self.native(path, path))
                for cred in (None, b'root:wrong', b'admin:pass', b'root:'):
                    resp, req = tn.get(self.port, path, cred=cred)
                    self.assertEqual(resp, b'HTTPD:' + req, cred)       # httpd decides (401): never the JSON
                    self.assertNotIn(key, resp.replace(req, b''))
            time.sleep(0.3)
            self.assertEqual(Path(self.lock, 'fail').stat().st_size % 4, 0)     # failed logins still noted for the lockout
            self.assertGreaterEqual(Path(self.lock, 'fail').stat().st_size, 4)
            # only the right login left a line in the audit log
            self.assertEqual((fb / 'tmp/log/audit.log').read_text().count('\n'), 1)

    def test_health_cache_hit_and_fallback(self):
        sample = '{"ok":true,"ts":1700000090,"services":{"rtsp-h26x":"running"},"system":{"uptime_sec":100}}\n'
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, {
                'proc/stat': 'cpu  0 0 0 0 0 0 0 0 0 0\nbtime 1700000000\n',
                'proc/uptime': '100.50 100.00\n',
                'tmp/health_snapshot.cache': '1700000090\n' + sample,
            })
            (fb / 'mnt/www/cgi-bin/health.cgi').write_text(
                RW.sub(lambda m: str(fb) + '/' + m.group(1) + '/', (ROOT / 'www/cgi-bin/health.cgi').read_text()))
            self.start(fb)
            # Fresh cache -> byte-for-byte identical to health.cgi
            expected = cgi(fb, '/cgi-bin/health.cgi')
            self.assertEqual(self.native('/cgi-bin/health.cgi', '/cgi-bin/health.cgi'), expected)
            self.assertEqual(self.native('/cgi-bin/health.cgi?_=123', '/cgi-bin/health.cgi?_=123'), expected)
            # Expired cache -> falls through to httpd
            (fb / 'tmp/health_snapshot.cache').write_text('1700000000\n' + sample)
            resp, req = self.ask('/cgi-bin/health.cgi')
            self.assertEqual(resp, b'HTTPD:' + req)
            # Missing cache -> falls through to httpd
            (fb / 'tmp/health_snapshot.cache').unlink()
            resp, req = self.ask('/cgi-bin/health.cgi')
            self.assertEqual(resp, b'HTTPD:' + req)

    def test_wiring(self):
        src = (ROOT / 'src/httpfront/httpfront.c').read_text()
        self.assertIn('#include "poll.h"', src)
        self.assertIn('pl_route(b)', src)
        self.assertIn('poll_response(route, st_root, ip, &len)', src)
        # the CGIs stay the fallback, and the pages poll exactly what the router knows
        self.assertIn('  daynight)', (ROOT / 'www/cgi-bin/state.cgi').read_text())
        self.assertIn('    hw_state)', (ROOT / 'scripts/action.d/hardware.sh').read_text())
        self.assertIn('"cgi-bin/state.cgi?cmd=daynight&format=json&_="', (ROOT / 'src/webui/index/80-camera-controls.js').read_text())
        self.assertIn("'cgi-bin/action.cgi?cmd=hw_state&format=json&_='", (ROOT / 'www/hardware.html').read_text())

    def test_isp_tune_and_fullconfig_parity(self):
        over = {
            'mnt/config/boot.conf': 'ISP_TUNE=1\nSERVICE_TRIM=0\nINTEGRATION_PROFILE=default\n',
            'mnt/config/isp_tune.conf': 'BRIGHTNESS=12\nCONTRAST=-5\nPOWER_HZ=50\nEXPOSURE_MAX_PCT=80\nMASK1=10,20,30,40\nMASK_COLOR=gray\n',
            'var/run/isp_tune.status': 'BRIGHTNESS=12\nPOWER_HZ=50\nEXPOSURE_NOW=1000\n',
            'mnt/config/hostname.conf': 'CAM-TEST\n',
            'mnt/config/timezone.conf': 'CET-1\n',
            'mnt/config/ntp_srv.conf': 'pool.ntp.org\n',
            'proc/net/route': 'Iface\tDestination\tGateway\tFlags\nwlan0\t00000000\t0101A8C0\t0003\n',
            'sys/class/leds/blue_led/brightness': '1\n',
            'sys/class/leds/red_led/brightness': '0\n',
        }
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, over)
            self.start(fb)
            it_path = '/cgi-bin/state.cgi?cmd=isp_tune&format=json'
            self.assertEqual(self.native(it_path, it_path), cgi(fb, it_path))
            fc_path = '/cgi-bin/state.cgi?cmd=fullconfig&_=1'
            self.assertEqual(self.native(fc_path, fc_path), cgi(fb, fc_path))


if __name__ == '__main__':
    unittest.main()
