"""Item 45: action.cgi mem_budget measures the memory per program (PSS from smaps_rollup, grouped by name, a shell
script by its script name) for the forecast of Settings -> System -> Memory."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']

PS = '''  PID USER       VSZ STAT COMMAND
    1 root      1564 S    init
    2 root         0 SW   [kthreadd]
  300 root      9000 S    /mnt/tc100test/tc100_rtsp -a 1
  400 root      1564 S    {mqtt-bridge.sh} /bin/sh /mnt/scripts/mqtt-bridge.sh run
  401 root      1564 S    sh /mnt/scripts/mqtt-bridge.sh run
  500 root       700 S    /usr/sbin/dropbear -R
  600 root      1564 S    /bin/sh -c sleep 30
  700 root      1564 S    gone
'''


class MemBudget(unittest.TestCase):
    def test_measure(self):
        s = (ROOT / 'scripts/action.d/system.sh').read_text(encoding='utf-8')
        code = s[s.index('      ps 2>/dev/null | awk'):s.index("        }'\n", s.index('      ps 2>/dev/null | awk')) + 11]
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            (d / 'ps.txt').write_text(PS)
            (d / 'meminfo').write_text('MemTotal:          44000 kB\nMemFree:  3000 kB\nMemAvailable:      21000 kB\n')
            (d / 'boot.conf').write_text('REC_LOCAL=1\nREC_RING_KB="2048"\nRTSP_ALSA_DIRECT=1\n')
            (d / 'rtsp.conf').write_text('[0]\nmainres = 720\n[1]\nmainres = 1080\n')
            for pid, pss in ((1, 120), (300, 2900), (400, 1100), (401, 30), (500, 210), (600, 40)):
                (d / str(pid)).mkdir()
                (d / str(pid) / 'smaps_rollup').write_text('Rss:  9999 kB\nPss:  %d kB\n' % pss)
            code = code.replace('ps 2>/dev/null', 'cat %s/ps.txt' % d.as_posix()) \
                .replace('/mnt/config/boot.conf', (d / 'boot.conf').as_posix()) \
                .replace('/mnt/config/rtspserver.conf', (d / 'rtsp.conf').as_posix()) \
                .replace('"/proc/meminfo"', '"%s/meminfo"' % d.as_posix()).replace('"/proc/"', '"%s/"' % d.as_posix())
            r = subprocess.run(SH + ['-c', code], capture_output=True, text=True)
            self.assertEqual(r.stderr, '')
            got = json.loads(r.stdout)
        self.assertEqual({k: got[k] for k in ('total_kb', 'avail_kb', 'ring_kb', 'rec_local', 'alsa_direct', 'mainres')},
                         {'total_kb': 44000, 'avail_kb': 21000, 'ring_kb': 2048, 'rec_local': 1, 'alsa_direct': 1,
                          'mainres': 720})
        self.assertEqual(got['procs'], [
            {'name': 'init', 'pss_kb': 120, 'n': 1},
            {'name': 'tc100_rtsp', 'pss_kb': 2900, 'n': 1},
            {'name': 'mqtt-bridge.sh', 'pss_kb': 1130, 'n': 2},	# both ways a script shows in ps
            {'name': 'dropbear', 'pss_kb': 210, 'n': 1},
            {'name': 'sleep', 'pss_kb': 40, 'n': 1}])		# no kernel thread, no process that left

    def test_wiring(self):
        a = (ROOT / 'www/cgi-bin/action.cgi').read_text(encoding='utf-8')
        self.assertIn('|hw_state|mem_budget', a)		# read-only: no CSRF token for a GET
        self.assertIn('    mem_budget|reboot|', a)
        h = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        self.assertIn("fetch('cgi-bin/action.cgi?cmd=mem_budget&format=json", h)
        self.assertIn('id="mem_card"', h)


if __name__ == '__main__':
    unittest.main()
