"""Regression tests for UP32-SD-ESSAI: mount flash vendor read-only on SD trial boot."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Up32SdVendorTest(unittest.TestCase):
    def test_boot_conf_has_sd_flash_vendor_switch(self):
        bc = ROOT / 'config/boot.conf.dist'
        txt = bc.read_text()
        self.assertIn('SD_FLASH_VENDOR=1', txt)
        # Keep well under the 64 KiB config buffer in supervisord/onvifd
        self.assertLess(bc.stat().st_size, 65536)

    def test_autorun_and_rtsp_launch_mount_vendor_readonly_and_chmod_644(self):
        for rel in ('v3/autorun-linux66.sh', 'v3/linux66-sd/rtsp-launch.sh'):
            p = ROOT / rel
            r = subprocess.run(['sh', '-n', str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{rel}: {r.stderr}')
            txt = p.read_text()
            self.assertIn('mount -t squashfs -o ro "/dev/mtdblock${_vd##*/mtd}" /vendor', txt, rel)
            self.assertIn('SD_FLASH_VENDOR', txt, rel)
            self.assertIn('[ -s "$f" ]', txt, rel)
            self.assertIn('chmod 644 /lib/firmware/anyka/isp.conf', txt, rel)

    def test_rtsp_launch_sd_flash_vendor_parsing(self):
        txt = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text()
        snippet = None
        for line in txt.splitlines():
            if '_sd_fv=' in line:
                snippet = line.strip()
                break
        self.assertIsNotNone(snippet)

        cases = [
            ('', 'run'),
            ('SD_FLASH_VENDOR=1\n', 'run'),
            ('SD_FLASH_VENDOR="1"\n', 'run'),
            ('SD_FLASH_VENDOR=0\n', 'skip'),
            ("SD_FLASH_VENDOR='0'\n", 'skip'),
            ('SD_FLASH_VENDOR=0 # disabled\n', 'skip'),
            ('SD_FLASH_VENDOR=off\n', 'skip'),
            ('SD_FLASH_VENDOR=false\n', 'skip'),
            ('SD_FLASH_VENDOR=no\n', 'skip'),
            ('SD_FLASH_VENDOR=0\nSD_FLASH_VENDOR=1\n', 'run'),
        ]
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / 'boot.conf'
            script = (
                f"{snippet.replace('/mnt/config/boot.conf', str(conf))}\n"
                'case "${_sd_fv:-1}" in\n'
                '  0|no|off|false) echo skip ;;\n'
                '  *) echo run ;;\n'
                'esac\n'
            )
            for content, expected in cases:
                conf.write_text(content)
                r = subprocess.run(['sh', '-c', script], capture_output=True, text=True, check=True)
                self.assertEqual(r.stdout.strip(), expected, f'content={content!r}')


if __name__ == '__main__':
    unittest.main()
