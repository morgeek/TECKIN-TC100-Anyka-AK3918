"""www/cgi-bin/statusline.cgi answers with exactly the JSON of state.cgi?cmd=statusline, but sources only statelib.cgi.

Both scripts run under busybox ash (as on the camera) against the same fixture tree: every /mnt, /tmp, /proc and
/var/run path of the scripts is moved into a temporary directory, `df` is a stub. `python3 tests/test_statusline.py bench`
prints what sourcing costs (lines, bytes, time of 50 calls each).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CGI = ROOT / 'www/cgi-bin'
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
PATHS = re.compile(r'/(mnt|tmp|proc|var/run)/')

SCENARIOS = {
    'full': {
        'proc/stat': 'cpu  4000 10 1500 90000 300 20 70 0 0 0\nbtime 1700000000\n',
        'proc/uptime': '86400.55 80000.10\n',
        'proc/meminfo': 'MemTotal:       45000 kB\nMemFree:         5000 kB\nMemAvailable:   12000 kB\nBuffers: 300 kB\nCached: 4000 kB\n',
        'proc/net/wireless': ' wlan0: 0000   86.   78.    0.       0      0      0      0      0        0\n',
        'proc/sys/kernel/hostname': 'cam-garage\n',
        'proc/mounts': 'rootfs / rootfs rw 0 0\n/dev/mmcblk0p1 /mnt/sd vfat rw 0 0\n',
        'var/run/lum': '77\n',
        'var/run/awb': 'r1.00 b0.90\n',
        'tmp/csrf_token': '0123456789abcdef0123456789ABCDEF\n',
        'tmp/update_status.json': '{"update_available":1,"latest_version":"3.1.0"}\n',
        'tmp/sd-health': 'state=ok\n',
        'tmp/sd-card': 'kind=sd\nprompt=1\nid=ab12\n',
        'tmp/web-fallback': 'http\n',
        'tmp/cfg-persist.status': 'state=failed\nmsg=flash "busy" \\ retry\n',
        'tmp/mqtt_last_pub.status': '1700000100 ok\n',
        'mnt/VERSION': '3.0.7\n',
        'mnt/config/boot.conf': 'WEB_MODE=ultra-lite\nLOW_CPU_PROFILE=1\nSECURITY_HARDENING_MODE=1\n',
        'mnt/config/mqtt.conf': 'MQTT_ENABLE=1\nMQTT_HA_DISCOVERY_ENABLE=0\n',
        'mnt/config/rtspserver.conf': 'USERNAME=root\nUSERPASSWORD=pass\n',
        'mnt/config/frigate_live.conf': 'FRIGATE_URL=http://10.0.0.5:5000\nFRIGATE_CAMERA=garage\n',
    },
    'minimal': {
        'proc/stat': 'cpu  1 0 1 1 0 0 0 0 0 0\nbtime 1700000000\n',
        'proc/uptime': '10.00 8.00\n',
        'proc/meminfo': 'MemTotal:       45000 kB\nMemFree:        20000 kB\n',
        'tmp/csrf_token': 'aabbccdd\n',
    },
    'flash': {
        'proc/stat': 'cpu  400 10 150 9000 30 2 7 0 0 0\nbtime 1700000000\n',
        'proc/uptime': '600.00 500.00\n',
        'proc/meminfo': 'MemTotal:       45000 kB\nMemFree:         5000 kB\nMemAvailable:   12000 kB\n',
        'proc/net/wireless': ' wlan1: 0000   40.   30.    0.       0      0      0      0      0        0\n',
        'tmp/csrf_token': 'deadbeef\n',
        'tmp/flashmode': '',
        'tmp/state_perfprofile.cache': '1700000598 rtsp-only\n',
        'tmp/state_pwd.cache': '1700000000 0\n',
        'mnt/config/service_trim.conf': 'SERVICE_TRIM=1\n',
    },
}


def build(base, scenario, files):
    """Fixture tree under base: the CGIs listed in files, rewritten, and the scenario's data files."""
    base = Path(base)
    cgi = base / 'mnt/www/cgi-bin'
    cgi.mkdir(parents=True)
    for name in files:
        text = PATHS.sub(lambda m: str(base) + '/' + m.group(1) + '/', (CGI / name).read_text())
        text = text.replace('df -k ', str(base) + '/bin/df -k ')   # by path: busybox ash would run its own df applet
        (cgi / name).write_text(text)
    for rel, body in SCENARIOS[scenario].items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    for d in ('tmp', 'mnt/config', 'proc'):
        (base / d).mkdir(parents=True, exist_ok=True)
    stub = base / 'bin'
    stub.mkdir()
    (stub / 'df').write_text('#!/bin/sh\necho "Filesystem 1K-blocks Used Available Use% Mounted on"\n'
                             'echo "/dev/mmcblk0p1 1000000 250000 750000 25% $2"\n')   # df -k <dir>: the mount point is the dir asked for
    (stub / 'df').chmod(0o755)
    return base


def run_cgi(base, name, query=''):
    env = {'PATH': str(Path(base) / 'bin') + os.pathsep + os.environ['PATH'], 'REQUEST_METHOD': 'GET',
           'QUERY_STRING': query, 'REMOTE_ADDR': '192.0.2.7', 'SCRIPT_NAME': '/cgi-bin/' + name}
    r = subprocess.run(SHELL + [str(Path(base) / 'mnt/www/cgi-bin' / name)], env=env, capture_output=True, text=True,
                       cwd=str(base))
    return r


def split(out):
    head, _, body = out.partition('\n\n')
    return head, body


class StatuslineCgi(unittest.TestCase):

    def both(self, scenario):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            old = build(a, scenario, ['func.cgi', 'statelib.cgi', 'state.cgi'])
            new = build(b, scenario, ['statelib.cgi', 'statusline.cgi'])   # no func.cgi, no state.cgi at all
            ro = run_cgi(old, 'state.cgi', 'cmd=statusline&uid=123')
            rn = run_cgi(new, 'statusline.cgi', 'uid=123')
            return ro, rn

    def test_same_bytes_as_state_cgi(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario):
                ro, rn = self.both(scenario)
                self.assertEqual(ro.returncode, 0, ro.stderr)
                self.assertEqual(rn.returncode, 0, rn.stderr)
                ho, bo = split(ro.stdout)
                hn, bn = split(rn.stdout)
                self.assertEqual(bn, bo)
                self.assertTrue(bn.startswith('{"sysusage":"CPU: '), bn)
                d = json.loads(bn)
                self.assertEqual(len(d), 35)
                self.assertIn('Content-type: application/json', hn)
                self.assertIn('Cache-Control: max-age=0, no-store, no-cache', hn)
                self.assertIn('Pragma: no-cache', hn)
                self.assertNotIn('Status:', hn)

    def test_values_come_from_the_fixture(self):
        _, rn = self.both('full')
        d = json.loads(split(rn.stdout)[1])
        self.assertEqual(d['hostname'], 'cam-garage')
        self.assertEqual(d['current_version'], '3.0.7')
        self.assertEqual(d['update_available'], 1)
        self.assertEqual(d['update_latest_version'], '3.1.0')
        self.assertEqual(d['csrf_token'], '0123456789abcdef0123456789ABCDEF')
        self.assertEqual(d['wifi_qual'], 86)
        self.assertEqual(d['perfprofile'], 'low-cpu')
        self.assertEqual(d['ui_ultralite_mode'], 1)
        self.assertEqual(d['sd_percent'], 25)
        self.assertEqual(d['sd_card'], 'sd')
        self.assertEqual(d['sd_prompt'], 'ab12')
        self.assertEqual(d['cfg_save'], 'failed')
        self.assertEqual(d['cfg_save_msg'], 'flash "busy" \\ retry')   # escaped in the JSON text, valid after the parse
        self.assertEqual(d['frigate_live'], 'http://10.0.0.5:5000/#garage')
        self.assertEqual(d['mqtt_enabled'], 1)
        self.assertEqual(d['default_password_active'], 1)
        self.assertEqual(d['storage'], 'sd')

    def test_mqtt_refusal_code(self):
        # mqtt-bridge.sh writes "<time> fail <CONNACK code>" when the broker refuses the login (rc7, IPCAM2: code 5)
        for status, ok, refused in (('1700000100 ok\n', 1, 0), ('1700000100 fail\n', 0, 0),
                                    ('1700000100 fail 5\n', 0, 5), ('1700000100 fail 4\n', 0, 4),
                                    ('1700000100 fail x\n', 0, 0)):
            with self.subTest(status), tempfile.TemporaryDirectory() as b:
                base = build(b, 'full', ['statelib.cgi', 'statusline.cgi'])
                (base / 'tmp/mqtt_last_pub.status').write_text(status)
                d = json.loads(split(run_cgi(base, 'statusline.cgi').stdout)[1])
                self.assertEqual((d['mqtt_last_pub_ok'], d['mqtt_refused']), (ok, refused))

    def test_flash_mode_storage(self):
        _, rn = self.both('flash')
        d = json.loads(split(rn.stdout)[1])
        self.assertEqual(d['storage'], 'flash')
        self.assertEqual(d['perfprofile'], 'rtsp-only')

    def test_token_is_created_once_when_missing(self):
        with tempfile.TemporaryDirectory() as b:
            base = build(b, 'minimal', ['statelib.cgi', 'statusline.cgi'])
            (base / 'tmp/csrf_token').unlink()
            r = run_cgi(base, 'statusline.cgi')
            tok = json.loads(split(r.stdout)[1])['csrf_token']
            self.assertRegex(tok, r'^[0-9a-f]{32}$')
            self.assertEqual((base / 'tmp/csrf_token').read_text(), tok)
            self.assertEqual(json.loads(split(run_cgi(base, 'statusline.cgi').stdout)[1])['csrf_token'], tok)

    def test_sources_only_the_small_helper_file(self):
        s = (CGI / 'statusline.cgi').read_text()
        self.assertEqual(re.findall(r'^\. (\S+)', s, re.M), ['/mnt/www/cgi-bin/statelib.cgi'])
        lib = (CGI / 'statelib.cgi').read_text()
        self.assertNotRegex(lib, r'(?m)^\. ')
        self.assertLess(len(lib.splitlines()) + len(s.splitlines()), 650)
        # same policy as state.cgi: authentication by the web server, no rate limit, no CSRF check on this GET
        for text in (s, (CGI / 'state.cgi').read_text()):
            self.assertNotRegex(text, r'(?m)^\s*(rate_limit_check|csrf_guard|mutation_guard)\b')

    def test_state_cgi_keeps_the_statusline_command_and_the_helpers(self):
        st = (CGI / 'state.cgi').read_text()
        self.assertIn('. /mnt/www/cgi-bin/statelib.cgi', st)
        self.assertRegex(st, r'(?m)^  statusline\)\n(    #.*\n)*    statusline_json\n    ;;\n')
        lib = (CGI / 'statelib.cgi').read_text()
        for fn in ('statusline_json', 'json_esc_to', 'json_escape', 'get_wifi_quality', 'get_sd_usage',
                   'compute_default_password_flag', 'get_perf_profile', 'load_or_compute_usage_metrics'):
            self.assertRegex(lib, r'(?m)^' + fn + r'\(\) \{', fn)
            self.assertNotRegex(st, r'(?m)^' + fn + r'\(\) \{', fn + ' must live in one place')

    def test_conf_get_copy_matches_func_cgi(self):
        def body(path):
            return re.search(r'(?m)^conf_get\(\) \{.*?^\}', (CGI / path).read_text(), re.S).group(0)
        self.assertEqual(body('statelib.cgi'), body('func.cgi'))

    def test_every_poller_uses_the_small_cgi(self):
        for f in ('src/webui/index/40-polling.js', 'www/scripts/index.bundle.min.js', 'www/scripts/view_records.bundle.min.js'):
            t = (ROOT / f).read_text()
            self.assertNotIn('cmd=statusline', t, f)
            self.assertIn('cgi-bin/statusline.cgi', t, f)

    def test_exec_bits_in_git(self):
        out = subprocess.run(['git', 'ls-files', '-s', 'www/cgi-bin/statusline.cgi', 'www/cgi-bin/statelib.cgi'],
                             cwd=ROOT, capture_output=True, text=True).stdout
        if out.strip():
            for line in out.splitlines():
                self.assertTrue(line.startswith('100755'), line)


def bench(n=50):
    def size(names):
        t = ''.join((CGI / x).read_text() for x in names)
        return len(t.splitlines()), len(t.encode())
    for label, files, script, query in (
            ('state.cgi?cmd=statusline', ['func.cgi', 'statelib.cgi', 'state.cgi'], 'state.cgi', 'cmd=statusline&uid=1'),
            ('statusline.cgi', ['statelib.cgi', 'statusline.cgi'], 'statusline.cgi', 'uid=1')):
        with tempfile.TemporaryDirectory() as b:
            base = build(b, 'full', files)
            run_cgi(base, script, query)   # warm the caches as on a running camera
            t0 = time.time()
            for _ in range(n):
                run_cgi(base, script, query)
            dt = (time.time() - t0) / n * 1000
        lines, nbytes = size(files)
        print('%-26s parsed: %5d lines %7d bytes   %6.1f ms per call (%d calls, %s)' % (label, lines, nbytes, dt, n, ' '.join(SHELL)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'bench':
        bench()
    else:
        unittest.main()
