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
import shutil
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

    def test_slimmed_applets_are_not_called(self):
        """v3/buildroot/board/tc100/busybox.fragment switches applets off; none of them may be called by the V3
        scripts, CGIs, init and install scripts (command position: line start, after ; & | { ` $( or busybox)."""
        frag = (ROOT / 'v3/buildroot/board/tc100/busybox.fragment').read_text()
        off = {m.group(1).lower() for m in re.finditer(r'^# CONFIG_([A-Z0-9_]+) is not set$', frag, re.M)
               if not m.group(1).startswith('FEATURE_')}
        off = {a for a in off if a not in APPLETS}
        self.assertGreater(len(off), 50)
        # the applet list in the fixture is the list after slimming: nothing switched off may still be in it
        self.assertEqual(sorted(a for a in off if a in APPLETS), [])
        files = list(runtime_files()) + [(ROOT / 'v3/S39tc100-linux66', (ROOT / 'v3/S39tc100-linux66').read_text())]
        bad = []
        for f, text in files:
            if f.name == 'collect-platform-dump.sh':
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith('#'):
                    continue
                line = re.sub(r'"[^"]*"|\x27[^\x27]*\x27', '""', line)	# words inside quotes are text, not commands
                for a in off:
                    if re.search(r'(?:^|[;&|`{]|\$\()\s*(?:/mnt/bin/busybox\s+|run_busybox\s+|busybox\s+)?' + re.escape(a) + r'(?=\s|$|;)', line):
                        bad.append((a, str(f.relative_to(ROOT)), n))
        self.assertEqual(bad, [])

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

    def test_moved_programs_come_with_the_user_space(self):
        """What leaves the RAM initramfs for ext/ (initramfs-prune.txt, "3.0 (2026-10-30)") must be in the user space
        tree, and still be found by name (links in the initramfs, S50dropbear search path)."""
        prune = [l.strip() for l in (ROOT / 'v3/initramfs-prune.txt').read_text().splitlines()
                 if l.strip() and not l.startswith('#')]
        stack = (ROOT / 'v3/build-stack.sh').read_text()
        rootfs = (ROOT / 'v3/build-rootfs66.sh').read_text()
        for b in ('usr/bin/aplay', 'usr/bin/arecord', 'usr/bin/amixer', 'usr/sbin/dropbear'):
            self.assertIn(b, prune)
            self.assertIn(b, stack)
        self.assertIn('usr/lib/libasound.so.2', prune)
        self.assertIn('usr/share/alsa', prune)
        self.assertIn('ext/share/alsa', stack)
        self.assertIn('for b in aplay arecord amixer; do ln -sf /mnt/ext/bin/$b usr/bin/$b; done', rootfs)
        self.assertIn('ln -sfn /mnt/ext/share/alsa usr/share/alsa', rootfs)
        self.assertIn('S50dropbear-linux66', rootfs)
        self.assertIn('/mnt/ext/lib', rootfs)       # musl search path baked in the initramfs
        # the initramfs boot needs wpa_supplicant and its libraries: they must stay
        for keep in ('usr/sbin/wpa_supplicant', 'usr/lib/libnl-3.so.200', 'usr/lib/libnl-genl-3.so.200', 'bin/busybox', 'lib/libc.so'):
            self.assertNotIn(keep, prune)
        # nobody calls the moved programs by their old absolute path
        for f, text in runtime_files():
            for old in ('/usr/bin/aplay', '/usr/bin/arecord', '/usr/bin/amixer', '/usr/sbin/dropbear', '/usr/share/alsa'):
                self.assertNotIn(old, text, (old, str(f.relative_to(ROOT))))

    def test_dropbear_start_script(self):
        s = (ROOT / 'v3/S50dropbear-linux66').read_text()
        self.assertIn('/mnt/ext/bin/dropbear', s)
        self.assertIn('/mnt/sd/ext/bin/dropbear', s)    # SD mode: the card is at /mnt/sd before autorun mounts /mnt
        self.assertIn('--exec $DB', s)
        sh = shutil.which('busybox')
        cmd = [sh, 'ash', '-n', str(ROOT / 'v3/S50dropbear-linux66')] if sh else (['sh', '-n', str(ROOT / 'v3/S50dropbear-linux66')])
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)

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
