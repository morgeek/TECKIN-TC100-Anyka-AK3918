"""Item 55: httpfront answers GET /cgi-bin/statusline.cgi itself (src/httpfront/status.h, TC100_NATIVE_STATUS=1).

httpfront (freestanding ARM) is built with arm-linux-gnueabi-gcc and run under qemu-arm (skipped without them; `sh
tests/docker/local-ci.sh cross` has both and busybox). The CGI runs under busybox ash against a copy of the same fixture
tree (tests/test_statusline.py: every /mnt, /tmp, /proc and /var/run path moved into a directory); the native handler
reads the same tree through TC100_STATUS_ROOT. The two JSON answers must be identical, key by key, byte by byte, and so
must the cache files each leaves behind. A stub "httpd" (an ARM program echoing the request it receives) stands for
busybox httpd: what the native handler does not answer must reach it untouched.
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import test_statusline as ts  # noqa: E402

CC = shutil.which('arm-linux-gnueabi-gcc')
QEMU = shutil.which('qemu-arm') or shutil.which('qemu-arm-static')
BUSYBOX = shutil.which('busybox')
FLAGS = ['-Os', '-Wall', '-Werror', '-marm', '-march=armv5te', '-nostdlib', '-static', '-fno-builtin', '-fno-pic',
         '-no-pie', '-Wl,--build-id=none', '-s']
# "pass" with salt "abcdefgh" (openssl passwd -1 -salt abcdefgh pass)
CONF = '/:root:$1$abcdefgh$1s0bv7.OjNizlrMAOIQD7.\n.mp4:video/mp4\n'

FAKE_HTTPD = r'''
static long sc(long n, long a, long b, long c)
{
	register long r7 __asm__("r7") = n, r0 __asm__("r0") = a, r1 __asm__("r1") = b, r2 __asm__("r2") = c;
	__asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
	return r0;
}
int run(void)
{
	static char buf[4096];
	long n = sc(3, 0, (long)buf, sizeof buf);
	sc(4, 1, (long)"HTTPD:", 6);
	if (n > 0) sc(4, 1, (long)buf, n);
	return 0;
}
__attribute__((naked, noreturn)) void _start(void)
{
	__asm__ volatile ("bl run\n mov r7, #1\n svc 0\n");
}
'''

NOW = 1700000000 + 86400            # btime + uptime of the 'full' fixture


def sc_fixture(name):
    """(scenario of test_statusline, files to add or replace); a None body removes the file"""
    S = {
        'full': ('full', {}),
        'minimal': ('minimal', {}),
        'flash': ('flash', {}),
        # /mnt is the card itself (no /mnt/sd mount): df names /mnt
        'sd_is_mnt': ('full', {'proc/mounts': 'rootfs / rootfs rw 0 0\n/dev/mmcblk0p1 /mnt vfat rw 0 0\n'}),
        'flash_with_card': ('flash', {'proc/mounts': '/dev/mmcblk0p1 /mnt/sd exfat rw 0 0\n',
                                      'tmp/state_perfprofile.cache': None}),
        'storage_flash': ('full', {'tmp/tc100-storage': 'flash\n'}),
        'storage_sd': ('full', {'tmp/tc100-storage': 'sd\n'}),
        # blanks around values, tabs, a last line without newline, defaults of every conf_get
        'quirks': ('full', {
            'var/run/lum': '  \t88 \n', 'var/run/awb': '', 'proc/sys/kernel/hostname': '\n',
            'mnt/VERSION': '\n', 'tmp/update_status.json': '{"update_available":0,"latest_version":""}\n',
            'mnt/config/boot.conf': 'LOW_CPU_PROFILE=1\n# SECURITY_HARDENING_MODE=1\n\nSECURITY_HARDENING_MODE=yes',
            'mnt/config/mqtt.conf': 'MQTT_ENABLE=enabled\nMQTT_ENABLE=0\n',
            'tmp/mqtt_last_pub.status': '1700086000 fail 3\n', 'mnt/config/user.pwd': 'pass\n',
            'tmp/sd-health': 'foo=bar\nstate=Bad1\n', 'tmp/sd-card': 'kind=sd\nprompt=0\nid=ab12\n',
            'tmp/cfg-persist.status': 'state=ok\nmsg=all saved\n',
            'mnt/config/frigate_live.conf': 'FRIGATE_URL=http://nvr:5000\nFRIGATE_CAMERA=\n',
            'var/run/sound_level': '%d -42.5 x\n' % (NOW - 3),
            'proc/net/wireless': ' wlan1: 0000   55.   0.    0.   0\n wlan2: 0000   70.   0.    0.   0\n'}),
        'wifi_fallback': ('full', {'proc/net/wireless': 'Inter-| sta\n face | tus\n wlan1: 0000  150.  0.  0.\n'
                                   ' wlan2: 0000   10.  0.  0.\n lo: 0 0 0\n',
                                   'var/run/sound_level': '%d -3\n' % (NOW - 30), 'tmp/update_status.json':
                                   '{"update_available":1,"latest_version":"v\\"x"}\n'.replace('\\"', "'")}),
        'wifi_override': ('full', {'proc/net/wireless': ' wlan1: 0000   55.   0.    0.   0\n wlan0: 0000   0.   0.    0.   0\n'}),
        'frigate_bad': ('full', {'mnt/config/frigate_live.conf': 'FRIGATE_URL=http://a b\nFRIGATE_CAMERA=x\n',
                                 'tmp/sd-card': 'kind=SD\nprompt=1\nid=a b\n', 'tmp/sd-health': 'state=\n'}),
        'frigate_cam': ('full', {'mnt/config/frigate_live.conf': 'FRIGATE_URL=https://f.lan\nFRIGATE_CAMERA=porch_1\n'
                                 'FRIGATE_URL=https://g.lan:8971\n'}),
        'fresh_caches': ('full', {'tmp/state_usage.cache': '%d 7 20000 45000 44\n' % (NOW - 1),
                                  'tmp/state_perfprofile.cache': '%d low-cpu\n' % (NOW - 3),
                                  'tmp/state_pwd.cache': '%d 1\n' % (NOW - 100)}),
        'stale_caches': ('full', {'tmp/state_usage.cache': '%d 7 20000 45000 44\n' % (NOW - 3),
                                  'tmp/state_perfprofile.cache': '%d low-cpu\n' % (NOW - 6),
                                  'tmp/state_pwd.cache': '%d 1\n' % (NOW - 121),
                                  'tmp/state_cpu_usage.state': '10 20 30\n'}),
        'cpu_delta': ('full', {'tmp/state_cpu_usage.state': '1000 90000 12\n'}),
        'cpu_close': ('full', {'tmp/state_cpu_usage.state': '5590 95890 17\n'}),
        'cpu_back': ('full', {'tmp/state_cpu_usage.state': '9000 999999 12\n'}),
        'no_mem_available': ('full', {'proc/meminfo': 'MemTotal: 45000 kB\nMemFree: 5000 kB\nBuffers: 300 kB\n'
                                      'Cached: 4000 kB\nShmem: 100 kB\nSReclaimable: 700 kB\n'}),
        'mem_over': ('full', {'proc/meminfo': 'MemTotal: 100 kB\nMemAvailable: 400 kB\n'}),
    }
    return S[name]


NAMES = ['full', 'minimal', 'flash', 'sd_is_mnt', 'flash_with_card', 'storage_flash', 'storage_sd', 'quirks',
         'wifi_fallback', 'wifi_override', 'frigate_bad', 'frigate_cam', 'fresh_caches', 'stale_caches', 'cpu_delta', 'cpu_close',
         'cpu_back', 'no_mem_available', 'mem_over']

DF_STUB = '''#!/bin/sh
# df -k <dir> of busybox on the fixture, the mount point named as the real df names it
B=%(base)s
mp=/
if grep -q ' /mnt/sd ' $B/proc/mounts 2>/dev/null; then mp=$2
elif grep -q ' /mnt ' $B/proc/mounts 2>/dev/null; then mp=/mnt; fi
echo "Filesystem 1K-blocks Used Available Use%% Mounted on"
%(bb)s df -k "$2" | tail -n +2 | { read -r a b c d e f; echo "$a $b $c $d $e $mp"; }
'''


def fixture(base, name, root_files=None):
    sname, extra = sc_fixture(name)
    ts.build(base, sname, ['statelib.cgi', 'statusline.cgi'])
    base = Path(base)
    for rel, body in extra.items():
        p = base / rel
        if body is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    lib = base / 'mnt/www/cgi-bin/statelib.cgi'     # the path rewrite of test_statusline also hit "/mnt/sd vfat" of a case
    lib.write_text(lib.read_text().replace('%s/mnt/sd vfat' % base, '/mnt/sd vfat').replace('%s/mnt/sd exfat' % base, '/mnt/sd exfat'))
    cp = base / 'tmp/cfg-persist.status'
    if cp.exists() and chr(92) in cp.read_text():   # a backslash is the one thing the native code leaves to the CGI
        cp.write_text(cp.read_text().replace(chr(92) + ' ', ''))
    (base / 'mnt/sd').mkdir(parents=True, exist_ok=True)
    (base / 'bin/df').write_text(DF_STUB % {'base': base, 'bb': BUSYBOX or 'df'})
    return base


def cgi_json(base):
    r = ts.run_cgi(base, 'statusline.cgi')
    assert r.returncode == 0, r.stderr
    return ts.split(r.stdout)[1]


def tree(base):
    """the cache files the two paths share"""
    out = {}
    for f in sorted(Path(base, 'tmp').glob('state_*')):
        out[f.name] = f.read_text()
    return out


def ask(port, req, host='127.0.0.1', timeout=8):
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(req)
        data = b''
        while True:
            try:
                d = s.recv(4096)
            except ConnectionResetError:
                break
            if not d:
                break
            data += d
        return data
    finally:
        s.close()


def get(port, path='/cgi-bin/statusline.cgi', cred=b'root:pass', host='127.0.0.1'):
    req = b'GET ' + path.encode() + b' HTTP/1.1\r\nHost: cam\r\n'
    if cred is not None:
        req += b'Authorization: Basic ' + base64.b64encode(cred) + b'\r\n'
    return ask(port, req + b'Connection: close\r\n\r\n', host), req + b'Connection: close\r\n\r\n'


@unittest.skipUnless(CC and QEMU, 'needs arm-linux-gnueabi-gcc and qemu-arm')
class Native(unittest.TestCase):
    port = 18640

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'httpfront')
        subprocess.run([CC] + FLAGS + [str(ROOT / 'src/httpfront/httpfront.c'), '-o', cls.bin], check=True)
        Path(cls.tmp, 'fake.c').write_text(FAKE_HTTPD)
        cls.httpd = os.path.join(cls.tmp, 'httpd')
        subprocess.run([CC] + FLAGS + [os.path.join(cls.tmp, 'fake.c'), '-o', cls.httpd], check=True)
        cls.conf = os.path.join(cls.tmp, 'httpd.conf')
        Path(cls.conf).write_text(CONF)
        cls.lock = os.path.join(cls.tmp, 'lock')
        os.makedirs(cls.lock)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def start(self, root, native='1', allow=None, **extra):
        Native.port += 1
        env = {'TC100_HTTPD_CONF': self.conf, 'TC100_LOCK_DIR': self.lock, 'TC100_HTTPD_BIN': self.httpd}
        if root:
            env['TC100_STATUS_ROOT'] = str(root)
        if native is not None:
            env['TC100_NATIVE_STATUS'] = native
        if allow is not None:
            env['TC100_NET_ALLOW'] = allow
        env.update(extra)
        proc = subprocess.Popen([QEMU, self.bin, '-p', str(self.port), '-h', self.tmp], env=env)
        self.addCleanup(lambda: (proc.kill(), proc.wait(5)))
        for _ in range(60):
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=1).close()
                return proc
            except OSError:
                time.sleep(0.1)
        self.fail('httpfront did not start')

    def native_json(self):
        # the first connection of a server can be the probe of start(): answers 0 bytes or a closed socket, so retry
        for _ in range(3):
            resp, _ = get(self.port)
            if resp:
                return resp
            time.sleep(0.3)
        return b''

    def compare(self, name, steps=3):
        """CGI against native on twin fixtures, `steps` polls with the clock and the CPU counters moving"""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            fa, fb = fixture(a, name), fixture(b, name)
            self.start(fb)
            for step in range(steps):
                if step == 1:           # 30 s later, the CPU did some work: every cache is stale
                    for f in (fa, fb):
                        (f / 'proc/uptime').write_text('86430.55 80000.10\n')
                        (f / 'proc/stat').write_text('cpu  4400 10 1900 90900 300 20 70 0 0 0\nbtime 1700000000\n')
                body = cgi_json(fa)
                resp = self.native_json()
                head, _, nbody = resp.partition(b'\r\n\r\n')
                self.assertTrue(head.startswith(b'HTTP/1.0 200 OK\r\n'), (name, step, resp[:200]))
                self.assertIn(b'Content-Type: application/json\r\n', head)
                self.assertIn(b'Cache-Control: max-age=0, no-store, no-cache\r\n', head)
                self.assertIn(b'Content-Length: %d' % len(nbody), head + b'\r\n')
                kn = json.loads(nbody, object_pairs_hook=list)
                kc = json.loads(body, object_pairs_hook=list)
                dn, dc = dict(kn), dict(kc)
                # the card is a live filesystem: its used space moves between the two reads (the files of this very
                # test), the rest is exact
                self.assertEqual(dn['sd_total_kb'], dc['sd_total_kb'], (name, step))
                self.assertLessEqual(abs(dn['sd_used_kb'] - dc['sd_used_kb']), 512, (name, step))
                self.assertLessEqual(abs(dn['sd_percent'] - dc['sd_percent']), 1, (name, step))
                for d in (kn, kc, dn, dc):
                    for k in ('sd_used_kb', 'sd_percent'):
                        if isinstance(d, dict):
                            d[k] = 0
                self.assertEqual(dn, dc, (name, step))
                live = re.compile(r'"sd_(used_kb|percent)":[0-9]+')
                self.assertEqual(live.sub('', nbody.decode()), live.sub('', body), (name, step))   # byte for byte
                self.assertEqual([k for k, _ in kn], [k for k, _ in kc])                           # same order
                self.assertEqual(tree(fa), tree(fb), (name, step))   # same caches, same format
            return kc

    def test_parity_with_the_cgi(self):
        for name in NAMES:
            with self.subTest(name):
                self.compare(name)

    def test_parity_values_are_what_the_fixture_says(self):
        """not just equal: spot-check the native answer (a shared bug in a fixture would hide behind equality)"""
        got = dict(self.compare('quirks', 1))
        self.assertEqual(got['lum'], '88')
        self.assertEqual(got['security_hardening_mode'], 0)          # the last line has no newline: ignored (read)
        self.assertEqual(got['perfprofile'], 'low-cpu')
        self.assertEqual(got['mqtt_enabled'], 1)
        self.assertEqual((got['mqtt_last_pub_ok'], got['mqtt_refused']), (0, 3))
        self.assertEqual(got['default_password_active'], 1)
        self.assertEqual(got['sound_db'], -42.5)
        self.assertEqual((got['wifi_qual'], got['wifi_iface']), (55, 'wlan1'))
        self.assertEqual(got['hostname'], 'tc100')
        self.assertEqual(got['current_version'], 'n/a')
        self.assertEqual(got['frigate_live'], 'http://nvr:5000/')

    @unittest.skipUnless(BUSYBOX, 'needs busybox')
    def test_df_formula_is_the_one_of_busybox(self):
        """status.h computes `df -k` from statfs: total, used and percent as busybox rounds them (the same formula in
        Python on os.statvfs, against the applet, on several filesystems)"""
        seen = 0
        for d in ('/', '/tmp', '/dev', '/dev/shm', '/proc', '/sys', str(ROOT)):
            for _ in range(5):                 # the used space may move between the two reads
                out = subprocess.run([BUSYBOX, 'df', '-k', d], capture_output=True, text=True).stdout.splitlines()
                if len(out) < 2 or not out[1].strip():
                    break
                f = out[1].split()
                if len(f) < 6:                 # a long device name wraps: not what the camera has
                    break
                v = os.statvfs(d)
                bs = v.f_bsize
                used = v.f_blocks - v.f_bfree
                den = used + v.f_bavail
                want = ((v.f_blocks * bs + 512) >> 10, (used * bs + 512) >> 10,
                        (used * 100 + den // 2) // den if den else 0)
                if want == (int(f[1]), int(f[2]), int(f[4].rstrip('%'))):
                    seen += 1
                    break
            else:
                self.fail('%s: busybox says %s, formula says %s' % (d, f, want))
        self.assertGreater(seen, 2)

    def test_sd_numbers_come_from_the_filesystem(self):
        got = dict(self.compare('full', 1))
        self.assertGreater(got['sd_total_kb'], 0)
        self.assertEqual(got['storage'], 'sd')
        self.assertEqual(dict(self.compare('minimal', 1))['sd_total_kb'], 0)

    def test_falls_through_when_it_cannot_answer_exactly(self):
        """a missing csrf token (the CGI creates it), a backslash (busybox echo would turn it into an escape), an
        unreadable CPU file: the request reaches httpd untouched"""
        for name, files in (('csrf', {'tmp/csrf_token': None}), ('csrf_empty', {'tmp/csrf_token': ''}),
                            ('backslash', {'proc/sys/kernel/hostname': 'ca\\\\m\n'}),
                            ('nostat', {'proc/stat': None}),
                            ('lead0', {'proc/meminfo': 'MemTotal: 045000 kB\nMemAvailable: 100 kB\n'})):
            with self.subTest(name), tempfile.TemporaryDirectory() as b:
                fb = fixture(b, 'full')
                for rel, body in files.items():
                    if body is None:
                        (fb / rel).unlink()
                    else:
                        (fb / rel).write_text(body)
                self.start(fb)
                resp, req = get(self.port)
                if not resp:
                    resp, req = get(self.port)
                self.assertEqual(resp, b'HTTPD:' + req, name)

    def test_switch_off_is_the_old_path_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            for native in (None, '0', ''):
                with self.subTest(native=native):
                    self.start(fb, native=native)
                    for path in ('/cgi-bin/statusline.cgi', '/cgi-bin/statusline.cgi?x=1', '/cgi-bin/state.cgi?cmd=statusline'):
                        resp, req = get(self.port, path)
                        if not resp:
                            resp, req = get(self.port, path)
                        self.assertEqual(resp, b'HTTPD:' + req, path)
            self.assertFalse((fb / 'tmp/state_usage.cache').exists())      # the native code never ran

    def test_only_that_route_and_only_get(self):
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            self.start(fb)
            self.assertIn(b'200 OK', self.native_json()[:20])
            for req in (b'GET /cgi-bin/statusline.cgi.bak HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n',
                        b'GET /cgi-bin/state.cgi?cmd=statusline HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n',
                        b'POST /cgi-bin/statusline.cgi HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n',
                        b'HEAD /cgi-bin/statusline.cgi HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n'):
                req = req % base64.b64encode(b'root:pass')
                self.assertEqual(ask(self.port, req), b'HTTPD:' + req, req)
            q = b'GET /cgi-bin/statusline.cgi?uid=1 HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n' % base64.b64encode(b'root:pass')
            self.assertTrue(ask(self.port, q).startswith(b'HTTP/1.0 200 OK'))

    def test_login_still_applies(self):
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            self.start(fb)
            self.assertIn(b'200 OK', self.native_json()[:20])
            for cred in (None, b'root:wrong', b'admin:pass', b'root:', b'root'):
                resp, req = get(self.port, cred=cred)
                self.assertEqual(resp, b'HTTPD:' + req, cred)         # httpd decides (401): never the JSON
                self.assertNotIn(b'csrf_token', resp)
            # a header that only looks like the login does not count
            req = b'GET /cgi-bin/statusline.cgi HTTP/1.1\r\nX-Authorization: Basic %s\r\n\r\n' % base64.b64encode(b'root:pass')
            self.assertEqual(ask(self.port, req), b'HTTPD:' + req)
            # no password configured at all: httpd keeps serving the open pages itself
            Path(self.conf).write_text('.mp4:video/mp4\n')
            try:
                self.start(fb)
                resp, req = get(self.port, cred=None)
                self.assertEqual(resp, b'HTTPD:' + req)
            finally:
                Path(self.conf).write_text(CONF)

    def test_lan_filter_still_applies(self):
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.connect(('192.0.2.1', 9))
            me = u.getsockname()[0]
        except OSError:
            me = '127.0.0.1'
        finally:
            u.close()
        if me.startswith('127.'):
            self.skipTest('no address but loopback')
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            self.start(fb, allow='203.0.113.0/24')
            self.assertIn(b'200 OK', self.native_json()[:20])           # loopback always
            resp, _ = get(self.port, host=me)
            self.assertEqual(resp, b'')                                  # closed before anything, right login or not
            self.start(fb, allow='')
            resp, _ = get(self.port, host=me)
            if not resp:
                resp, _ = get(self.port, host=me)
            self.assertTrue(resp.startswith(b'HTTP/1.0 200 OK'))

    def test_failed_logins_are_still_counted(self):
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            self.start(fb, TC100_WEB_LOCKOUT='1')
            self.assertIn(b'200 OK', self.native_json()[:20])
            self.assertEqual(len(Path(self.lock, 'ok').read_text()), 32)    # the right login is remembered
            get(self.port, cred=b'root:wrong')
            time.sleep(0.3)
            self.assertEqual(Path(self.lock, 'fail').stat().st_size, 4)    # one failure noted for 127.0.0.1

    def test_slow_request_line_is_waited_for(self):
        """the headers arrive in two pieces: the native path needs all of them (the login)"""
        with tempfile.TemporaryDirectory() as b:
            fb = fixture(b, 'full')
            self.start(fb)
            self.native_json()
            s = socket.create_connection(('127.0.0.1', self.port), timeout=8)
            try:
                s.sendall(b'GET /cgi-bin/statusline.cgi HTTP/1.1\r\n')
                time.sleep(0.4)
                s.sendall(b'Authorization: Basic ' + base64.b64encode(b'root:pass') + b'\r\n\r\n')
                data = b''
                while True:
                    d = s.recv(4096)
                    if not d:
                        break
                    data += d
            finally:
                s.close()
            self.assertTrue(data.startswith(b'HTTP/1.0 200 OK'), data[:100])


if __name__ == '__main__':
    unittest.main()
