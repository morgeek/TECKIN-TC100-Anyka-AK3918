"""Item 43: action.cgi cmd=nvr_latency: target chosen (host=, Frigate address, REC_CLIENT, router), loss / delay / jitter
from the ping output, bad host names refused."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']

PING = '''PING x (192.168.1.20): 56 data bytes
64 bytes from 192.168.1.20: seq=0 ttl=64 time=10.0 ms
64 bytes from 192.168.1.20: seq=1 ttl=64 time=14.0 ms
64 bytes from 192.168.1.20: seq=2 ttl=64 time=12.0 ms
64 bytes from 192.168.1.20: seq=4 ttl=64 time=20.0 ms
64 bytes from 192.168.1.20: seq=5 ttl=64 time=10.0 ms
64 bytes from 192.168.1.20: seq=6 ttl=64 time=10.0 ms
64 bytes from 192.168.1.20: seq=7 ttl=64 time=10.0 ms
64 bytes from 192.168.1.20: seq=8 ttl=64 time=10.0 ms
'''


def branch():
    s = (ROOT / 'scripts/action.d/network.sh').read_text()
    m = re.search(r'^    nvr_latency\)\n(.*?)^    ;;\n', s, re.M | re.S)
    return m.group(1)


class NvrLatency(unittest.TestCase):
    def run_branch(self, host='', frigate=''):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'ping.out').write_text(PING)
            code = branch().replace('/mnt/config/frigate_live.conf', str(t / 'frigate')).replace('/mnt/config/boot.conf', str(t / 'boot'))
            (t / 'frigate').write_text('FRIGATE_URL=%s\n' % frigate if frigate else '')
            (t / 'boot').write_text('')
            stubs = ('json_body_err() { printf \'{"ok":false,"error":"%%s"}\\n\' "$1"; }\n'
                     'ping() { for a; do last=$a; done; echo "$last" > %s/target; cat %s/ping.out; }\n'
                     'ip() { echo "default via 192.168.1.1 dev wlan0"; }\n' % (t, t))
            r = subprocess.run(SH + ['-c', stubs + 'F_host=%s\n' % host + code], capture_output=True, text=True)
            target = (t / 'target').read_text().strip() if (t / 'target').exists() else ''
            return json.loads(r.stdout.strip().splitlines()[-1]), target

    def test_frigate_address_and_numbers(self):
        d, target = self.run_branch(frigate='http://192.168.1.20:5000')
        self.assertEqual(target, '192.168.1.20')
        self.assertEqual((d['received'], d['loss_pct']), (8, 20))
        self.assertEqual((d['min_ms'], d['max_ms'], d['avg_ms']), (10.0, 20.0, 12.0))
        self.assertEqual(d['jitter_ms'], round((4 + 2 + 8 + 10 + 0 + 0 + 0) / 7, 1))

    def test_fallbacks_and_refusal(self):
        self.assertEqual(self.run_branch()[1], '192.168.1.1')                  # the router
        self.assertEqual(self.run_branch(host='nas.local')[1], 'nas.local')
        d, target = self.run_branch(host="'x;reboot'")
        self.assertEqual((d['ok'], target), (False, ''))


if __name__ == '__main__':
    unittest.main()
