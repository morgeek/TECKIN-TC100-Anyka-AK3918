"""Item 28: scripts/log-cap.sh keeps the last lines of a RAM log above LOG_CAP_KB, in place (same inode), and leaves
tc100_rtsp.log, rotated copies and small files alone."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


class LogCap(unittest.TestCase):
    def test_caps_in_place(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = t / 'log'
            d.mkdir()
            (t / 'boot.conf').write_text('LOG_CAP_KB=8\n')
            big = d / 'big.log'
            big.write_text(''.join('line %05d\n' % i for i in range(3000)))      # 33 KB
            ino = os.stat(big).st_ino
            fd = os.open(big, os.O_WRONLY | os.O_APPEND)                            # a writer holding it open
            (d / 'small.log').write_text('x\n')
            (d / 'tc100_rtsp.log').write_text('y' * 20000)
            (d / 'old.log.1').write_text('z' * 20000)
            env = dict(os.environ, LC_CONF=str(t / 'boot.conf'))
            r = subprocess.run(SH + [str(ROOT / 'scripts/log-cap.sh'), str(d)], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = big.read_text().splitlines()
            self.assertEqual(len(lines), 200)
            self.assertEqual(lines[-1], 'line 02999')
            self.assertEqual(os.stat(big).st_ino, ino)                              # same file
            os.write(fd, b'after\n'); os.close(fd)
            self.assertEqual(big.read_text().splitlines()[-1], 'after')             # the writer still reaches it
            self.assertEqual((d / 'small.log').read_text(), 'x\n')
            self.assertEqual(len((d / 'tc100_rtsp.log').read_text()), 20000)
            self.assertEqual(len((d / 'old.log.1').read_text()), 20000)
            self.assertFalse(any(p.name.endswith('.tmp') for p in d.iterdir()))

    def test_registered_by_autorun(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text()
        self.assertIn('housekeeper.sh job add log-cap bg 600 600 - sh /mnt/scripts/log-cap.sh', a)


if __name__ == '__main__':
    unittest.main()
