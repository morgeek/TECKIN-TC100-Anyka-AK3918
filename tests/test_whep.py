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
        self.assertRegex(read('v3/autorun-linux66.sh'), r'(?m)^for n in sound-detection .* telegram-bot whep; do')
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
        self.sleeper = subprocess.Popen(['sleep', '60'])
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
        self.sleeper.kill()
        self.sleeper.wait()
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


if __name__ == '__main__':
    unittest.main()
