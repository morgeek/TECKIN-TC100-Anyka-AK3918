"""Boot trace of v3/autorun-linux66.sh (2026-11-14): a fork-free "step uptime" line per numbered step in
/tmp/boot-trace.txt, to find where the 12 s between network_ready and rtsp_launched go."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUTO = ROOT / 'v3/autorun-linux66.sh'


class BootTrace(unittest.TestCase):
    def test_every_numbered_step_has_a_marker(self):
        s = AUTO.read_text()
        steps = re.findall(r'^# ?([0-9]+[a-z0-9]*)\. ', s, re.M)
        marks = re.findall(r'^bt step_([0-9]+[a-z0-9]*)$', s, re.M)
        self.assertGreaterEqual(len(marks), 30)
        self.assertEqual(steps, marks)

    def test_bt_is_fork_free_and_writes_a_line(self):
        s = AUTO.read_text()
        fn = re.search(r'^bt\(\) \{.*\}$', s, re.M).group(0)
        self.assertNotIn('$(', fn)
        with tempfile.TemporaryDirectory() as t:
            up = Path(t, 'uptime'); up.write_text('12.34 5.00\n'); out = Path(t, 'trace')
            code = fn.replace('/proc/uptime', str(up)).replace('/tmp/boot-trace.txt', str(out)) + '\nbt step_4a\n'
            subprocess.run(['sh', '-c', code], check=True)
            self.assertEqual(out.read_text(), 'step_4a 12.34\n')


if __name__ == '__main__':
    unittest.main()
