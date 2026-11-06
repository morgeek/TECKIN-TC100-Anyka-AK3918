"""Review of 2026-11-06 (P3): `flashw -r` ended with exit 0 whatever dd and md5sum did, so a failed or truncated dump
looked like a good one. It now succeeds only with a complete dump (the size of the partition)."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
FLASHW = str(ROOT / 'v3/linux66-sd/flashw')


class FlashwRead(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.sys = self.t / 'sys'; self.dev = self.t / 'dev'
        for d in (self.sys / 'mtd5', self.dev):
            d.mkdir(parents=True)
        (self.sys / 'mtd5' / 'name').write_text('cfga\n')
        (self.sys / 'mtd5' / 'size').write_text('8192\n')
        (self.dev / 'mtd5ro').write_bytes(bytes(range(256)) * 32)          # 8192 bytes

    def tearDown(self):
        shutil.rmtree(self.t)

    def run_r(self, part, out):
        env = dict(os.environ, FLASHW_SYS=str(self.sys), FLASHW_DEV=str(self.dev))
        return subprocess.run(SH + [FLASHW, '-r', part, str(out)], capture_output=True, text=True, timeout=20, env=env)

    def test_complete_dump(self):
        r = self.run_r('cfga', self.t / 'out.bin')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.t / 'out.bin').read_bytes(), (self.dev / 'mtd5ro').read_bytes())

    def test_truncated_or_failed_dump_is_an_error(self):
        (self.dev / 'mtd5ro').write_bytes(b'\0' * 4096)                     # the device gives half the partition
        r = self.run_r('cfga', self.t / 'out.bin')
        self.assertEqual(r.returncode, 7, r.stdout)
        (self.dev / 'mtd5ro').unlink()                                      # unreadable
        self.assertEqual(self.run_r('cfga', self.t / 'out2.bin').returncode, 7)
        self.assertEqual(self.run_r('cfga', self.t / 'nodir' / 'x.bin').returncode, 7)   # output not writable

    def test_unknown_partition(self):
        self.assertEqual(self.run_r('boot', self.t / 'out.bin').returncode, 1)


if __name__ == '__main__':
    unittest.main()
