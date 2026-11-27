"""v3/check-needed.sh: the build-time check that every dynamically linked program of an image finds its NEEDED
libraries ([up-base]: a prune entry or a base image change must not leave wpa_supplicant or a daemon without one).
Uses a fake READELF (a shell script that prints what the file says), so it needs no ARM binutils."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SH = shutil.which('sh')


def run(root, dirs, skip=''):
    fake = Path(root).parent / 'fake-readelf'
    fake.write_text('#!/bin/sh\n# prints a NEEDED line for every word after "NEEDED:" on the second line of the file\n'
                    'sed -n "2s/^NEEDED: *//p" "$2" | tr " " "\\n" | sed "/^$/d; s/.*/ 0x1 (NEEDED) Shared library: [&]/"\n')
    fake.chmod(0o755)
    env = dict(os.environ, READELF=str(fake), CHECK_SKIP=skip)
    return subprocess.run([SH, str(ROOT / 'v3/check-needed.sh'), str(root), dirs], capture_output=True, text=True, env=env)


@unittest.skipIf(SH is None or os.name == 'nt', 'needs a POSIX shell')
class CheckNeeded(unittest.TestCase):
    def make(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name, 'rd')
        for name, body in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'\x7fELF' + b'\n' + body.encode())
        return root

    def test_resolved(self):
        root = self.make({'usr/sbin/wpa': 'NEEDED: libnl-3.so.200 libc.so', 'usr/lib/libnl-3.so.200': 'NEEDED: libc.so',
                          'lib/libc.so': ''})
        r = run(root, f'{root}/lib:{root}/usr/lib')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('3 ELF files, 3 NEEDED entries, 0 unresolved', r.stdout)

    def test_missing_library_fails(self):
        root = self.make({'usr/sbin/wpa': 'NEEDED: libnl-3.so.200 libc.so', 'lib/libc.so': ''})
        r = run(root, f'{root}/lib:{root}/usr/lib')
        self.assertEqual(r.returncode, 1)
        self.assertIn('usr/sbin/wpa needs libnl-3.so.200', r.stderr)

    def test_dangling_link_and_skip(self):
        root = self.make({'bin/busybox': 'NEEDED: libold.so', 'usr/bin/tool': 'NEEDED: libc.so', 'lib/libc.so': ''})
        os.symlink('/mnt/ext/lib/libx.so', root / 'usr/lib-x')
        os.symlink('/nowhere/libc2.so', root / 'lib/libc2.so')
        (root / 'usr/bin/t2').write_bytes(b'\x7fELF\nNEEDED: libc2.so')
        r = run(root, f'{root}/lib', skip='bin/busybox')
        self.assertEqual(r.returncode, 1)
        self.assertIn('t2 needs libc2.so', r.stderr)          # a dangling link is not a library
        self.assertNotIn('busybox', r.stderr)                  # skipped on request

    def test_wired_into_the_builds(self):
        self.assertIn('check-needed.sh', (ROOT / 'v3/build-rootfs66.sh').read_text())
        self.assertIn('check-needed.sh', (ROOT / 'v3/build-stack.sh').read_text())


if __name__ == '__main__':
    unittest.main()
