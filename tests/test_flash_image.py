"""What the flash image (v3/build-stack.sh) leaves out must not be missed on the camera.

- bin/busybox (the 2.x uClibc busybox) is replaced in the image by a link to the system busybox of the 6.6
  initramfs: every applet the 3.0 scripts call through /mnt/bin/busybox or run_busybox must be in that busybox
  (tests/fixtures/busybox-6.6-applets.txt, from `busybox --list` of the CI initramfs; refresh it when the
  Buildroot busybox configuration changes).
- the build and development files left out of the image are not used by anything that runs on the camera.
- httpfront is freestanding (no C library) and small.
Run: python3 -m unittest tests.test_flash_image -v
"""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPLETS = set((ROOT / 'tests/fixtures/busybox-6.6-applets.txt').read_text().split())
RUNTIME = ['scripts', 'controlscripts', 'www/cgi-bin', 'v3/linux66-sd', 'bin/setconf', 'v3/autorun-linux66.sh',
           'v3/install/install66.sh', 'v3/install/update66.sh', 'v3/install/inventory.sh', 'v3/install/hwcheck.sh',
           'v3/install/collect-vendor.sh', 'v3/install/restore-stock.sh']


def runtime_files():
    for p in RUNTIME:
        q = ROOT / p
        files = [q] if q.is_file() else sorted(f for f in q.rglob('*') if f.is_file() and not f.name.endswith('.gz'))
        for f in files:
            try:
                yield f, f.read_text(errors='replace')
            except OSError:
                pass


def excluded():
    src = (ROOT / 'v3/build-stack.sh').read_text()
    cmd = src[src.index('mksquashfs "$T" "$OUT/stack.sqfs"'):src.index('n=$(wc -c < "$OUT/stack.sqfs")')]
    return re.split(r'\s-e\s', cmd.replace('\\\n', ' '), maxsplit=1)[1].split()


class FlashImage(unittest.TestCase):
    def test_busybox_link_has_the_applets(self):
        calls = set()
        for f, text in runtime_files():
            if f.name == 'collect-platform-dump.sh':	# stock firmware only, left out of the image
                continue
            for m in re.finditer(r'(?:/mnt/bin/busybox|run_busybox)\s+([a-z][a-z0-9_.-]*)', text):
                calls.add(m.group(1))
        calls -= {'return', 'then', 'else', 'fi', 'do', 'done', 'esac'}
        self.assertTrue(calls)
        self.assertEqual(sorted(c for c in calls if c not in APPLETS), [])

    def test_image_links_busybox(self):
        src = (ROOT / 'v3/build-stack.sh').read_text()
        self.assertIn('-p "bin/busybox s 777 0 0 /bin/busybox"', src)
        self.assertIn('bin/busybox', excluded())

    def test_left_out_files_are_not_used_on_the_camera(self):
        for name in excluded():
            if name in ('bin/busybox', 'ext/bin/mksquashfs'):
                continue
            base = Path(name).name
            for f, text in runtime_files():
                if f.name == base:
                    continue
                self.assertNotIn(base, text, (name, str(f.relative_to(ROOT))))

    def test_httpfront_is_freestanding(self):
        src = (ROOT / 'src/httpfront/httpfront.c').read_text()
        self.assertNotIn('#include', src)
        b = ROOT / 'src/httpfront/httpfront'
        if b.exists():
            self.assertLess(b.stat().st_size, 16384)
            out = subprocess.run(['file', str(b)], capture_output=True, text=True).stdout
            self.assertIn('statically linked', out)


if __name__ == '__main__':
    unittest.main()
