import glob, os, re, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, 'scripts', 'flash_budget.py')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.dont_write_bytecode = True   # no __pycache__ in scripts/ (copied to the camera; test_flash_image reads it)
import flash_budget  # noqa: E402
sys.dont_write_bytecode = False


def run(*args):
    return subprocess.run([sys.executable, '-I', SCRIPT, *args], capture_output=True, text=True)


def text(p):
    with open(os.path.join(ROOT, p), encoding='utf-8') as f:
        return f.read()


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

    def test_stack_region(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run('--stack', self.mk(d, 's', 0x2b3000)).returncode, 0)
            self.assertEqual(run('--stack', self.mk(d, 's2', 0x2b3001)).returncode, 1)

    def test_regions_are_the_device_tree_partitions(self):
        """audit D6: the model is the 3.0 layout of the device tree, not the stock A/B/C split"""
        patch = text(glob.glob(os.path.join(ROOT, 'patches/kernel-6.6/series/0010-spi-*.patch'))[0])
        dt = re.findall(r'label = "([a-z]+)";.*?\n\+\s*reg = <0x([0-9a-f]+) 0x([0-9a-f]+)>;(\n\+\s*read-only;)?', patch)
        self.assertEqual([(n, int(o, 16), int(s, 16), not ro) for n, o, s, ro in dt], flash_budget.REGIONS)

    def test_build_limits_match(self):
        """the size limits of the build scripts are the partitions (and one INITRD_SIZE everywhere, audit D6)"""
        size = {n: s for n, _, s, _ in flash_budget.REGIONS}
        self.assertIn('STACK_MAX=${STACK_MAX:-%d}' % size['stack'], text('v3/build-stack.sh'))
        self.assertIn('KERNEL_MAX=%d' % size['kernel'], text('v3/build-release.sh'))
        m = re.search(r'INITRD_SIZE=\$\{INITRD_SIZE:-(\d+)\}', text('v3/build-rootfs66.sh'))
        initrd = int(m.group(1))
        self.assertLessEqual(initrd, size['initrd'])
        # the fixed size that U-Boot loads is written in these places; they must all agree
        self.assertIn('INITRD_SIZE=%d' % initrd, text('v3/build-release.sh'))
        self.assertIn('INITRD_SIZE=%d' % initrd, text('v3/install/stock-hook.sh'))
        self.assertIn('-eq %d ]' % initrd, text('v3/install/update66.sh'))
        for p in ('v3', 'scripts', 'controlscripts'):
            for f in glob.glob(os.path.join(ROOT, p, '**', '*'), recursive=True):
                if os.path.isfile(f) and not f.endswith(('.gz', '.pyc')):
                    with open(f, encoding='utf-8', errors='replace') as fh:
                        for n in re.findall(r'\b20\d{5}\b', fh.read()):
                            if n.startswith('201') and abs(int(n) - initrd) < 50000:
                                self.assertEqual(int(n), initrd, f)


if __name__ == '__main__':
    unittest.main()
