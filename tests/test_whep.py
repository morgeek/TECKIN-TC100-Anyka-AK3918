"""Item 35, the WebRTC (WHEP) gateway: what runs on the host without mbedTLS or a browser.
- src/whep/whep_test.c: the STUN vectors of RFC 5769, the binding response, the SDP offer and answer (needs gcc);
- the wiring: boot.conf keys (WHEP on by default) and their validators, the exchange table, the controlscript, the service
  switch, the Buildroot package and the mbedTLS option, the user space image;
- www/cgi-bin/whep.cgi under a shell with a stub curl: off, status, offer, stop.
The daemon against a real WebRTC client is tests/whep_interop.py (tests/docker/whep-interop.sh)."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class Proto(unittest.TestCase):
    def test_host_vectors(self):
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t, 'whep_test')
            subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-o', str(exe),
                            str(ROOT / 'src/whep/whep_test.c')], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('whep_test: all ok', r.stdout)


class Wiring(unittest.TestCase):
    def test_on_by_default_and_validated(self):
        dist = read('config/boot.conf.dist')
        for line in ('WHEP=1', 'WHEP_STREAM=sub', 'WHEP_MAX=2', 'WHEP_AUDIO=1'):   # WHEP on by default since the rc28
            self.assertRegex(dist, r'(?m)^' + line + r'$')
        tx = read('scripts/config-transaction.sh')
        for key, typ in (('WHEP', 'bool'), ('WHEP_STREAM', 'whep_stream'), ('WHEP_MAX', 'u:1:2'), ('WHEP_AUDIO', 'bool')):
            self.assertIn(f'tc_check_flat "$_tc_file" {key} {typ} "$_tc_rel"', tx)
        self.assertRegex(tx, r'whep_stream\) case "\$_tc_value" in sub\|main\)')
        rows = [l for l in read('www/cgi-bin/config_exchange.cgi').splitlines() if l.strip().startswith('row("boot.conf"')]
        keys = [re.search(r'"root";"([A-Z_0-9]+)"', l).group(1) for l in rows]
        pos = [i for i, k in enumerate(keys) if k.startswith('WHEP')]
        self.assertEqual(keys[pos[0]:pos[-1] + 1], ['WHEP', 'WHEP_STREAM', 'WHEP_MAX', 'WHEP_AUDIO'], 'same-prefix rows are contiguous')

    def test_service(self):
        self.assertIn('whep)             SW_FILE=$_sw_d/boot.conf; SW_KEY=WHEP; SW_DEF=1', read('scripts/service-switch.sh'))
        self.assertRegex(read('v3/autorun-linux66.sh'), r'(?m)^for n in sound-detection .* telegram-bot; do')
        self.assertIn('sh /mnt/controlscripts/whep start', read('www/cgi-bin/whep.cgi'))
        cs = read('controlscripts/whep')
        self.assertIn('BIN=/mnt/ext/bin/tc100-whep', cs)
        for key in ('WHEP_STREAM', 'WHEP_MAX', 'WHEP_AUDIO'):
            self.assertIn(key, cs)
        self.assertTrue(os.access(ROOT / 'controlscripts/whep', os.X_OK) or os.name == 'nt')
        subprocess.run(SHELL + ['-n', str(ROOT / 'controlscripts/whep')], check=True)
        subprocess.run(SHELL + ['-n', str(ROOT / 'www/cgi-bin/whep.cgi')], check=True)

    def test_base_image(self):
        mk = read('v3/buildroot/external.mk')
        self.assertIn('MBEDTLS_POST_PATCH_HOOKS += MBEDTLS_ENABLE_DTLS_SRTP', mk)
        self.assertIn('MBEDTLS_SSL_DTLS_SRTP', mk)
        self.assertIn('include $(sort $(wildcard $(BR2_EXTERNAL_TC100_PATH)/package/*/*.mk))', mk)
        self.assertIn('BR2_PACKAGE_TC100_WHEP=y', read('v3/buildroot/configs/tc100_defconfig'))
        self.assertIn('package/tc100-whep/Config.in', read('v3/buildroot/Config.in'))
        pk = read('v3/buildroot/package/tc100-whep/tc100-whep.mk')
        self.assertIn('TC100_WHEP_SITE_METHOD = local', pk)
        self.assertIn('TC100_WHEP_DEPENDENCIES = mbedtls', pk)
        self.assertIn('usr/bin/tc100-whep', read('v3/initramfs-prune.txt').split())
        self.assertIn('usr/bin/tc100-whep', read('v3/build-stack.sh'))
        self.assertIn("'src/whep/**'", read('.github/workflows/build-base-rootfs.yml'))


@unittest.skipIf(os.name == 'nt', 'needs a POSIX shell')
class Cgi(unittest.TestCase):
    """www/cgi-bin/whep.cgi with its paths moved into a temporary directory and curl replaced by a stub."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / 'run').mkdir()
        # the daemon stand-in: the CGI only trusts a pid whose process name is tc100-whep
        shutil.copy(shutil.which('sleep'), self.tmp / 'tc100-whep')
        self.sleeper = subprocess.Popen([str(self.tmp / 'tc100-whep'), '60'])
        self.other = subprocess.Popen(['sleep', '60'])
        src = read('www/cgi-bin/whep.cgi')
        src = src.replace('/var/run/', f'{self.tmp}/run/').replace('CURL=/mnt/ext/bin/curl', f'CURL={self.tmp}/curl').replace('T=/tmp/', f'T={self.tmp}/')
        self.cgi = self.tmp / 'whep.cgi'
        self.cgi.write_text(src)
        # the stub: GET /status -> JSON, POST /whep -> 201 with a Location, DELETE -> the code in $STUB_DELETE
        (self.tmp / 'curl').write_text(r'''#!/bin/sh
out=; hdr=; url=; method=GET
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift ;;
    -D) hdr=$2; shift ;;
    -X) method=$2; shift ;;
    -w) shift ;;
    --data-binary) method=POST; cp "${2#@}" "$STUB_BODY"; shift ;;
    http://*) url=$1 ;;
  esac
  shift
done
case "$method $url" in
  "GET "*/status) printf '{"viewers":1,"max":2}\n' > "$out" ;;
  "POST "*/whep) printf 'HTTP/1.1 %s X\r\nLocation: /whep/0123456789abcdef\r\nContent-Length: 6\r\n\r\n' "${STUB_CODE:-201}" > "$hdr"; printf 'v=0 OK' > "$out" ;;
  "DELETE "*) printf '%s' "${STUB_DELETE:-200}" ;;
esac
''')
        os.chmod(self.tmp / 'curl', 0o755)

    def tearDown(self):
        for p in (self.sleeper, self.other):
            p.kill()
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cgi(self, method='GET', query='', body='', **env):
        e = {'PATH': os.environ['PATH'], 'REQUEST_METHOD': method, 'QUERY_STRING': query, 'CONTENT_LENGTH': str(len(body)),
             'STUB_BODY': str(self.tmp / 'body.seen')}
        e.update(env)
        r = subprocess.run(SHELL + [str(self.cgi)], input=body.encode(), capture_output=True, env=e, timeout=20)
        head, _, rest = r.stdout.decode().partition('\r\n\r\n')
        return head, rest

    def pid(self, value):
        (self.tmp / 'run/whep.pid').write_text(f'{value}\n')

    def test_off(self):
        head, body = self.run_cgi()
        self.assertTrue(head.startswith('Status: 503'), head)
        self.assertIn('"enabled":0', body)
        self.pid(2 ** 22 + 5)				# a pid nobody has
        head, body = self.run_cgi()
        self.assertTrue(head.startswith('Status: 503'), head)

    def test_reused_pid_is_not_the_daemon(self):
        """after the daemon's idle exit its pid may belong to anything: not tc100-whep = not running, stale file removed"""
        self.pid(self.other.pid)
        head, body = self.run_cgi()
        self.assertTrue(head.startswith('Status: 503') or head.startswith('Status: 200'), head)
        self.assertFalse((self.tmp / 'run/whep.pid').exists())
        self.pid(self.other.pid)
        head, _ = self.run_cgi('POST', body='v=0\r\n')
        self.assertTrue(head.startswith('Status: 503'), head)
        self.assertFalse((self.tmp / 'run/whep.pid').exists())

    def test_status(self):
        self.pid(self.sleeper.pid)
        head, body = self.run_cgi()
        self.assertTrue(head.startswith('Status: 200'), head)
        self.assertIn('"viewers":1', body)

    def test_offer(self):
        self.pid(self.sleeper.pid)
        offer = 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
        head, body = self.run_cgi('POST', body=offer)
        self.assertTrue(head.startswith('Status: 201 X'), head)
        self.assertIn('Content-Type: application/sdp', head)
        self.assertIn('Location: /cgi-bin/whep.cgi?stop=0123456789abcdef', head)
        self.assertEqual(body.strip(), 'v=0 OK')
        self.assertEqual((self.tmp / 'body.seen').read_bytes().decode(), offer, 'the offer reaches the daemon unchanged')
        head, body = self.run_cgi('POST', body=offer, STUB_CODE='429')
        self.assertTrue(head.startswith('Status: 429'), head)
        head, _ = self.run_cgi('POST', body='')
        self.assertTrue(head.startswith('Status: 413') or head.startswith('Status: 400'), head)
        # a real browser offer: Chrome 157 sends 7607 bytes (video + audio recvonly, host candidates); 6000 refused it
        big = offer + 'a=x-pad:' + 'y' * 7600 + '\r\n'
        head, _ = self.run_cgi('POST', body=big)
        self.assertTrue(head.startswith('Status: 201 X'), head)
        head, _ = self.run_cgi('POST', body='x' * 13000)
        self.assertTrue(head.startswith('Status: 413'), head)
        head, _ = self.run_cgi('PUT', body='x')
        self.assertTrue(head.startswith('Status: 405'), head)

    def test_stop(self):
        self.pid(self.sleeper.pid)
        for method in ('POST', 'DELETE'):
            head, _ = self.run_cgi(method, 'stop=0123456789abcdef')
            self.assertTrue(head.startswith('Status: 200'), head)
        head, _ = self.run_cgi('POST', 'stop=0123456789abcdef', STUB_DELETE='404')
        self.assertTrue(head.startswith('Status: 404'), head)
        for bad in ('stop=', 'stop=zz', 'stop=0123', 'stop=0123456789abcdef0', 'stop=../../x'):
            head, _ = self.run_cgi('POST', bad)
            self.assertTrue(head.startswith('Status: 400'), (bad, head))
        head, _ = self.run_cgi('GET', 'stop=0123456789abcdef')
        self.assertTrue(head.startswith('Status: 405'), head)


@unittest.skipIf(os.name == 'nt', 'needs a POSIX shell and /proc')
class StartRace(unittest.TestCase):
    """controlscripts/whep start with its paths in a temporary directory and a fake daemon: two starts at once"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        src = read('controlscripts/whep')
        src = src.replace('. /mnt/scripts/common_functions.sh', 'netacl_allow_list() { echo 127.0.0.0/8; }')
        src = src.replace('/var/run/whep.pid', f'{self.tmp}/whep.pid').replace('/tmp/logs', f'{self.tmp}/logs')
        src = src.replace('BIN=/mnt/ext/bin/tc100-whep', f'BIN={self.tmp}/tc100-whep').replace('/tmp/whep-start.lock', f'{self.tmp}/lock')
        src = src.replace('sleep 2\t', 'sleep 1\t')
        self.ctl = self.tmp / 'whep'
        self.ctl.write_text(src)
        # fake daemon: "binds" with an atomic mkdir, logs its start, runs; the second one fails like a busy port
        (self.tmp / 'tc100-whep').write_text(f"""#!/bin/sh
echo started >> {self.tmp}/starts
mkdir {self.tmp}/bound 2>/dev/null || exit 1
sleep 30
""")
        os.chmod(self.tmp / 'tc100-whep', 0o755)

    def tearDown(self):
        try:
            pid = int((self.tmp / 'whep.pid').read_text())
            os.kill(pid, 9)
        except (OSError, ValueError):
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_two_starts_make_one_daemon_and_keep_its_pid(self):
        env = {'PATH': os.environ['PATH']}
        ps = [subprocess.Popen(SHELL + [str(self.ctl), 'start'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
              for _ in range(2)]
        rcs = [p.wait(timeout=30) for p in ps]
        self.assertEqual(rcs, [0, 0])
        self.assertEqual((self.tmp / 'starts').read_text().split(), ['started'], 'only one daemon was launched')
        pid = int((self.tmp / 'whep.pid').read_text())
        self.assertIn('tc100-whep', Path(f'/proc/{pid}/cmdline').read_text())
        self.assertFalse((self.tmp / 'lock').exists(), 'the lock is released')

    def test_a_dead_daemon_never_writes_the_pid_file(self):
        (self.tmp / 'bound').mkdir()	# the port is taken: the fake daemon exits at once
        r = subprocess.run(SHELL + [str(self.ctl), 'start'], env={'PATH': os.environ['PATH']}, capture_output=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.tmp / 'whep.pid').exists())

    def test_a_lock_left_without_owner_is_taken_over(self):
        # a start killed between mkdir and writing its pid left a lock with no pid: before, every later start waited
        # 10 s and failed until a reboot (review 2026-11-13)
        (self.tmp / 'lock').mkdir()
        r = subprocess.run(SHELL + [str(self.ctl), 'start'], env={'PATH': os.environ['PATH']}, capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.tmp / 'starts').read_text().split(), ['started'])
        self.assertFalse((self.tmp / 'lock').exists(), 'the lock is released')

    def test_sources(self):
        cs = read('controlscripts/whep')
        self.assertIn('mkdir "$LOCKDIR"', cs)
        self.assertIn("trap 'unlock; exit 143' INT TERM", cs)
        self.assertIn('TC100_NET_ALLOW="$(netacl_allow_list 2>/dev/null)" "$BIN"', cs)
        self.assertNotIn('It starts at boot', cs)
        self.assertIn('/proc/$_pid/comm', read('www/cgi-bin/whep.cgi'))


class UdpReview20261112(unittest.TestCase):
    """read-only review of the UDP side of tc100-whep, 2026-11-12"""

    def setUp(self):
        src = (ROOT / 'src/whep/tc100_whep.c').read_text()
        self.udp = src[src.index('static int on_udp(void)'):src.index('static void http_reply(')]
        self.src = src

    def test_net_lan_only_covers_the_udp_port(self):
        self.assertIn('TC100_NET_ALLOW="$(netacl_allow_list 2>/dev/null)" "$BIN"', (ROOT / 'controlscripts/whep').read_text())
        self.assertIn('wh_nets_parse(&nets, getenv("TC100_NET_ALLOW"));', self.src)
        # checked first, before STUN, DTLS or any session lookup
        self.assertLess(self.udp.index('wh_nets_ok(&nets'), self.udp.index('on_stun('))

    def test_only_an_authenticated_consent_check_keeps_a_viewer(self):
        self.assertNotIn('s->last = now_ms()', self.udp)
        stun = self.src[self.src.index('static void on_stun('):self.src.index('static int on_udp(void)')]
        self.assertLess(stun.index('stun_check_integrity'), stun.index('s->last = now_ms()'))


if __name__ == '__main__':
    unittest.main()
