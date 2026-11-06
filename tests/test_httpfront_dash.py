"""Item 55, second native route: httpfront answers GET /cgi-bin/dash.cgi itself (src/httpfront/dash.h).

Same method as tests/test_httpfront_native.py: dash.cgi runs under busybox ash against a fixture tree, the native handler
reads a twin of that tree through TC100_STATUS_ROOT; the two bodies must be identical byte for byte, polled several times
with the counters moving. What the native code cannot print exactly as the shell does must reach the stub httpd untouched.
Skipped without the ARM compiler and qemu-arm (`sh tests/docker/local-ci.sh tests` has both).
"""
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import test_httpfront_native as tn  # noqa: E402
import test_statusline as ts  # noqa: E402

PATH = '/cgi-bin/dash.cgi'

BASE = {
    'proc/loadavg': '0.42 0.30 0.20 1/80 1234\n',
    'proc/net/dev': 'Inter-|   Receive                                                |  Transmit\n'
                    ' face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n'
                    '    lo:    1000      10    0    0    0     0          0         0     1000      10    0    0    0     0       0          0\n'
                    ' wlan0: 123456789  4000    0    0    0     0          0         0 987654321    5000    0    0    0     0       0          0\n',
    'proc/net/tcp': '  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n'
                    '   0: 0100007F:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1\n'
                    '   1: 0B00A8C0:022A 0A00A8C0:C350 01 00000000:00000000 00:00000000 00000000     0        0 2 1\n'
                    '   2: 0B00A8C0:022a 0B00A8C0:C351 01 00000000:00000000 00:00000000 00000000     0        0 3 1\n'
                    '   3: 0B00A8C0:022A 0C00A8C0:C352 06 00000000:00000000 00:00000000 00000000     0        0 4 1\n'
                    '   4: 0B00A8C0:0050 0C00A8C0:C353 01 00000000:00000000 00:00000000 00000000     0        0 5 1\n',
    'proc/net/wireless': 'Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n'
                         ' face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n'
                         ' wlan0: 0000   86.  -60.  -256        0      0      0      0      0        0\n',
    'tmp/sd-health': 'state=ok\n',
}

PW = ' wlan0: 0000   %s  %s  -256        0      0      0      0      0        0\n'

SCEN = {
    'full': {},
    'rtsp_clients': {},
    'wifi_dbm_from_proc': {},
    'wifi_avg_fresh': {'tmp/wifi-signal.avg': '86400 -45\n'},
    'wifi_avg_180s': {'tmp/wifi-signal.avg': '86220 -45\n'},
    'wifi_avg_181s': {'tmp/wifi-signal.avg': '86219 -45\n'},
    'wifi_avg_future': {'tmp/wifi-signal.avg': '86500 -45\n'},
    'wifi_avg_bad': {'tmp/wifi-signal.avg': '86400 -45.5\n'},
    'wifi_avg_110': {'tmp/wifi-signal.avg': '86400 -110\n'},
    'wifi_avg_no_uptime': {'tmp/wifi-signal.avg': '5 -45\n', 'proc/uptime': None},
    'wifi_dbm_unknown': {'proc/net/wireless': PW % ('90.', '-256.')},
    'wifi_dbm_zero': {'proc/net/wireless': PW % ('90.', '0.')},
    'wifi_dbm_100': {'proc/net/wireless': PW % ('90.', '-100.')},
    'wifi_dbm_111': {'proc/net/wireless': PW % ('90.', '-111.')},
    'wifi_qual_text': {'proc/net/wireless': PW % ('xx', '-61.')},
    'wifi_only_wlan1': {'proc/net/wireless': ' wlan1: 0000   55.   -70.  -256\n'},
    'wifi_no_file': {'proc/net/wireless': None},
    'wifi_no_script': {'mnt/scripts/wifi-signal.sh': None},
    'wifi_wlan0_twice': {'proc/net/wireless': PW % ('10.', '-50.') + PW % ('20.', '-40.')},
    'eth0': {'proc/net/dev': 'Inter-|\n face |\n  eth0: 500 5 0 0 0 0 0 0 600 6 0 0 0 0 0 0\n    lo: 1 1 0 0 0 0 0 0 1 1 0 0 0 0 0 0\n'},
    'eth0_then_wlan0': {'proc/net/dev': '  eth0: 500 5 0 0 0 0 0 0 600 6 0 0 0 0 0 0\n wlan0: 7 1 0 0 0 0 0 0 8 1 0 0 0 0 0 0\n eth0: 9 9 0 0 0 0 0 0 9 9\n'},
    'wlan0_then_eth0': {'proc/net/dev': ' wlan0: 7 1 0 0 0 0 0 0 8 1 0 0 0 0 0 0\n  eth0: 500 5 0 0 0 0 0 0 600 6 0 0 0 0 0 0\n'},
    'veth0': {'proc/net/dev': 'veth0: 500 5 0 0 0 0 0 0 600 6 0 0 0 0 0 0\n'},
    'net_short': {'proc/net/dev': ' wlan0: 5 1 2\n'},
    'net_none': {'proc/net/dev': 'lo: 1 1 0 0 0 0 0 0 1 1\n'},
    'net_missing': {'proc/net/dev': None},
    'port_8554': {'mnt/config/rtspserver.conf': 'USERNAME=root\nPORT=8554\n'},
    'port_80': {'mnt/config/rtspserver.conf': 'PORT=80\n'},
    'port_quoted': {'mnt/config/rtspserver.conf': 'PORT="80"\n'},
    'port_leading0': {'mnt/config/rtspserver.conf': 'PORT=0554\n'},
    'port_junk': {'mnt/config/rtspserver.conf': 'PORT=abc\n'},
    'port_empty': {'mnt/config/rtspserver.conf': 'PORT=\nPORT\n'},
    'port_twice': {'mnt/config/rtspserver.conf': 'PORT=80\nPORT=554\n'},
    'port_last_no_newline': {'mnt/config/rtspserver.conf': 'PORT=80\nPORT=554'},
    'no_conf': {'mnt/config/rtspserver.conf': None},
    'no_tcp': {'proc/net/tcp': None},
    'tcp_odd': {'proc/net/tcp': '  sl\n   1: 0B00A8C0 x 01 a\n   2: zz:zz 1 01\n   3: 0B00A8C0:022A 1 01 1\n   4: 0:0 0 01\n'},
    'sd_health_bad': {'tmp/sd-health': 'state=Bad1\n'},
    'sd_health_last': {'tmp/sd-health': 'state=warn\nx=1\nstate=failed\n'},
    'sd_health_none': {'tmp/sd-health': None},
    'cpu_short': {'proc/stat': 'cpu  1 2 3 4\ncpu0 9 9 9 9\n'},
    'cpu_later': {'proc/stat': 'intr 5\ncpu  4000 10 1500 90000\nbtime 5\n'},
    'cpu_missing': {'proc/stat': 'btime 1\n'},
    'cpu_nofile': {'proc/stat': None},
    'mem_total_only': {'proc/meminfo': 'MemTotal: 45000 kB\nMemFree: 1 kB\n'},
    'mem_avail_first': {'proc/meminfo': 'MemAvailable: 100 kB\nMemTotal: 45000 kB\n'},
    'mem_none': {'proc/meminfo': None},
    'uptime_missing': {'proc/uptime': None},
    'loadavg_missing': {'proc/loadavg': None},
    'loadavg_empty': {'proc/loadavg': ''},
    # the encoded frame rate (owner 2026-11-06): tenths of fps from tc100_rtsp.stat while tc100_rtsp is alive
    'vfps': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured 50\nmain_bytes 1\n'},
    'vfps_round_down': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 6\ncaptured 125\n'},
    'vfps_last_wins': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'captured 5\ninterval_s 5\ncaptured 111\n'},
    'vfps_no_newline': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured 50'},
    'vfps_no_interval': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'captured 50\n'},
    'vfps_zero_interval': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 0\ncaptured 50\n'},
    'vfps_no_captured': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\n'},
    'vfps_text': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured lots\n'},
    'vfps_dead': {'var/run/v4l2rtspserver.pid': '4321\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured 50\n'},
    'vfps_pid_text': {'var/run/v4l2rtspserver.pid': 'abc\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured 50\n'},
    'vfps_no_stat': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': 'x\n'},
}
# the viewers scenario is the base one: two established connections to 554 (one with a lower-case hex port)

# what the native code leaves to the CGI (the shell would print something it does not reproduce)
FALL = {
    'cpu_text': {'proc/stat': 'cpu  4000 x 1500 90000 1 2 3\n'},
    'cpu_empty_field': {'proc/stat': 'cpu  4000\n'},
    'mem_text': {'proc/meminfo': 'MemTotal: abc kB\nMemAvailable: 1 kB\n'},
    'mem_empty': {'proc/meminfo': 'MemTotal:\nMemAvailable: 1 kB\n'},
    'uptime_empty': {'proc/uptime': ''},
    'uptime_text': {'proc/uptime': 'soon\n'},
    'net_text': {'proc/net/dev': ' wlan0: abc 1 2 3 4 5 6 7 8 9\n'},
    'iface_odd': {'proc/net/dev': ' we"rd: 1 wlan0: 1 0 0 0 0 0 0 0 1 1\n'},
    'load_odd': {'proc/loadavg': '"x" 1 2 3\n'},
    'port_ends_equal': {'mnt/config/rtspserver.conf': 'PORT=80=\n'},
    'port_long': {'mnt/config/rtspserver.conf': 'PORT=1234567890123456789012345\n'},
    'tcp_hex_long': {'proc/net/tcp': ' 1: 0B00A8C0:0123456789abcdef0123 1 01 1\n'},
    'avg_octal_ts': {'tmp/wifi-signal.avg': '086400 -45\n', 'proc/net/wireless': PW % ('86.', '-60.')},
    'vfps_octal': {'var/run/v4l2rtspserver.pid': '4321\n', 'proc/4321/stat': '4321 (tc100_rtsp) S\n', 'var/run/tc100_rtsp.stat': 'interval_s 5\ncaptured 050\n'},
}


def build(base, name, extra_over):
    """a dash.cgi tree (scenario 'full' of test_statusline, plus the files dash.cgi reads), then the overrides"""
    ts.build(base, 'full', ['dash.cgi'])
    base = Path(base)
    for rel, body in dict(BASE, **extra_over).items():
        p = base / rel
        if body is None:
            p.unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return base


def dash_body(base):
    r = ts.run_cgi(base, 'dash.cgi')
    assert r.returncode == 0, r.stderr
    return ts.split(r.stdout)[1]


def mover(base, step):
    """the counters of a later poll: clock, CPU, memory, bytes, a viewer less"""
    base = Path(base)
    if step == 1:
        (base / 'proc/uptime').write_text('86405.10 80000.10\n') if (base / 'proc/uptime').exists() else None
        (base / 'proc/stat').write_text('cpu  4010 10 1510 90100 301 20 71 0 0 0\nbtime 1700000000\n') \
            if (base / 'proc/stat').exists() and (base / 'proc/stat').read_text().startswith('cpu  4000 10 1500 90000 300') else None
        (base / 'proc/loadavg').write_text('0.55 0.31 0.20 2/80 1300\n') if (base / 'proc/loadavg').exists() else None
    if step == 2:
        p = base / 'proc/net/tcp'
        if p.exists():
            p.write_text(p.read_text().replace('0B00A8C0:022a 0B00A8C0:C351 01', '0B00A8C0:022a 0B00A8C0:C351 08'))


@unittest.skipUnless(tn.CC and tn.QEMU, 'needs arm-linux-gnueabi-gcc and qemu-arm')
class Dash(unittest.TestCase):
    port = 18740
    setUpClass = classmethod(tn.Native.setUpClass.__func__)
    tearDownClass = classmethod(tn.Native.tearDownClass.__func__)
    start = tn.Native.start

    def dash(self, path=PATH):
        for _ in range(3):
            resp, req = tn.get(self.port, path)
            if resp:
                return resp, req
        return b'', req

    def test_parity_with_the_cgi(self):
        for name, over in SCEN.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                fa, fb = build(a, name, over), build(b, name, over)
                self.start(fb)
                for step in range(3):
                    mover(fa, step)
                    mover(fb, step)
                    resp, _ = self.dash()
                    head, _, body = resp.partition(b'\r\n\r\n')
                    self.assertTrue(head.startswith(b'HTTP/1.0 200 OK\r\n'), (name, step, resp[:200]))
                    self.assertIn(b'Content-Type: application/json\r\n', head)
                    self.assertIn(b'Cache-Control: no-store\r\n', head)
                    self.assertIn(b'Content-Length: %d' % len(body), head + b'\r\n')
                    self.assertEqual(body.decode(), dash_body(fa), (name, step))
                    json.loads(body)

    def test_values_are_what_the_fixture_says(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, 'full', {'tmp/wifi-signal.avg': '86400 -45\n'})
            self.start(fb)
            resp, _ = self.dash()
            d = json.loads(resp.partition(b'\r\n\r\n')[2])
            self.assertEqual(d['up'], 86400)
            self.assertEqual(d['load'], '0.42')
            self.assertEqual(d['cpu'], [4000, 10, 1500, 90000, 300, 20, 70])
            self.assertEqual(d['mem'], [45000, 12000])
            self.assertEqual((d['iface'], d['net']), ('wlan0', [123456789, 987654321]))
            self.assertEqual(d['wifi'], [86, -45])
            self.assertEqual(d['rtsp_clients'], 2)
            self.assertEqual(d['sd_health'], 'ok')
            self.assertIsNone(d['vfps'])                    # no video server in this fixture
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, 'vfps', SCEN['vfps'])
            self.start(fb)
            resp, _ = self.dash()
            self.assertEqual(json.loads(resp.partition(b'\r\n\r\n')[2])['vfps'], 100)   # 50 frames in 5 s

    def test_falls_through_when_it_cannot_answer_exactly(self):
        for name, over in FALL.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as b:
                fb = build(b, 'full', over)
                self.start(fb)
                resp, req = tn.get(self.port, PATH)
                if not resp:
                    resp, req = tn.get(self.port, PATH)
                self.assertEqual(resp, b'HTTPD:' + req, name)

    def test_switch_off_and_other_paths(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, 'full', {})
            for native in (None, '0'):
                with self.subTest(native=native):
                    self.start(fb, native=native)
                    resp, req = tn.get(self.port, PATH + '?_=1')
                    if not resp:
                        resp, req = tn.get(self.port, PATH + '?_=1')
                    self.assertEqual(resp, b'HTTPD:' + req)
            self.start(fb)
            self.assertIn(b'200 OK', self.dash(PATH + '?_=170')[0][:20])        # the page polls with a query
            for path in ('/cgi-bin/dash.cgi.bak', '/cgi-bin/dashx.cgi', '/cgi-bin/dash.cgix', '/cgi-bin/dash'):
                resp, req = tn.get(self.port, path)
                self.assertEqual(resp, b'HTTPD:' + req, path)
            for verb in (b'POST', b'HEAD'):
                req = verb + b' ' + PATH.encode() + b' HTTP/1.1\r\nAuthorization: Basic %s\r\n\r\n' % base64.b64encode(b'root:pass')
                self.assertEqual(tn.ask(self.port, req), b'HTTPD:' + req, verb)

    def test_login_still_applies(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, 'full', {})
            self.start(fb)
            self.assertIn(b'200 OK', self.dash()[0][:20])
            for cred in (None, b'root:wrong', b'admin:pass', b'root:'):
                resp, req = tn.get(self.port, PATH, cred=cred)
                self.assertEqual(resp, b'HTTPD:' + req, cred)
                self.assertNotIn(b'rtsp_clients', resp)

    def test_failed_logins_still_counted(self):
        with tempfile.TemporaryDirectory() as b:
            fb = build(b, 'full', {})
            self.start(fb, TC100_WEB_LOCKOUT='1')
            self.assertIn(b'200 OK', self.dash()[0][:20])
            tn.get(self.port, PATH, cred=b'root:wrong')
            import time
            time.sleep(0.3)
            self.assertEqual(Path(self.lock, 'fail').stat().st_size, 4)

    def test_lan_filter_still_applies(self):
        import socket
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
            fb = build(b, 'full', {})
            self.start(fb, allow='203.0.113.0/24')
            resp, _ = tn.get(self.port, PATH, host=me)
            self.assertEqual(resp, b'')


if __name__ == '__main__':
    unittest.main()
