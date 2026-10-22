import os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'scripts', 'flash_budget.py')

def run(*args):
    return subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True, text=True)

class FlashBudget(unittest.TestCase):
    def mk(self, d, name, size):
        p = os.path.join(d, name)
        with open(p, 'wb') as f:
            f.truncate(size)
        return p

    def test_layout_covers_flash(self):
        r = run()
        self.assertEqual(r.returncode, 0)
        self.assertIn('protected', r.stdout)

    def test_fit_and_overflow(self):
        with tempfile.TemporaryDirectory() as d:
            ok = self.mk(d, 'k', 0x200000 - 64)       # exactly fits with the uImage header
            big = self.mk(d, 'k2', 0x200000 - 63)     # one byte too much
            self.assertEqual(run('--kernel', ok).returncode, 0)
            r = run('--kernel', big)
            self.assertEqual(r.returncode, 1)
            self.assertIn('DOES NOT FIT', r.stdout)

    def test_rootfs_region(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run('--rootfs', self.mk(d, 'r', 5976064)).returncode, 0)
            self.assertEqual(run('--rootfs', self.mk(d, 'r2', 5976065)).returncode, 1)

if __name__ == '__main__':
    unittest.main()
