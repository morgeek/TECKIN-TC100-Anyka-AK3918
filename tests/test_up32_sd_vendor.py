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

    def test_onboard_packaging_and_config_switches(self):
        bc = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('SD_FLASH_WIFI=1', bc)
        tpl = ROOT / 'v3/install/wifi.txt.dist'
        self.assertTrue(tpl.is_file())
        tpl_txt = tpl.read_text()
        self.assertIn('SSID=\n', tpl_txt)
        self.assertIn('PASSWORD=\n', tpl_txt)
        br = (ROOT / 'v3/build-release.sh').read_text()
        self.assertIn('v3/install/wifi.txt.dist', br)
        self.assertIn('ESSAI.txt.example', br)
        bs = (ROOT / 'v3/build-stack.sh').read_text()
        self.assertIn('v3/install/wifi.txt.dist', bs)

    def test_sd_flash_wifi_fallback_and_ssh_key_persistence(self):
        s39 = (ROOT / 'v3/S39tc100-linux66').read_text()
        s50 = (ROOT / 'v3/S50dropbear-linux66').read_text()
        wg = (ROOT / 'scripts/web-guard.sh').read_text()
        for rel in ('v3/S39tc100-linux66', 'v3/S50dropbear-linux66', 'scripts/web-guard.sh'):
            r = subprocess.run(['sh', '-n', str(ROOT / rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{rel}: {r.stderr}')
        self.assertIn('SD_FLASH_WIFI', s39)
        self.assertIn('$RS settings /tmp/sd-flash-cfg', s39)
        self.assertIn('rm -rf /tmp/sd-flash-cfg', s39)
        self.assertIn('/mnt/sd/config/dropbear_ed25519_host_key', s39)
        self.assertIn('dropbearkey', s50)
        self.assertIn('/mnt/config/dropbear_ed25519_host_key', wg)

        # Exercise the S39tc100 WF fallback snippet with a stubbed initrd-rescue
        a = s39.index('WF=\n')
        b = s39.index('H=$(grep')
        snippet = s39[a:b]
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / 'sd' / 'config').mkdir(parents=True)
            (d / 'sd' / 'tc100test').mkdir(parents=True)
            (d / 'flashcfg' / 'config').mkdir(parents=True)
            (d / 'flashcfg' / 'config' / 'wpa_supplicant.conf').write_text('network={\n\tssid="FlashNet"\n}\n')
            rs = d / 'rs'
            rs.write_text(f'#!/bin/sh\n[ "$1" = settings ] && mkdir -p "$2" && cp -r {d / "flashcfg/config"} "$2/"\n')
            rs.chmod(0o755)

            def run_wf(boot_conf='', card_wpa=False):
                out_wpa = d / 'out_wpa.conf'
                if out_wpa.exists():
                    out_wpa.unlink()
                cwpa = d / 'sd' / 'config' / 'wpa_supplicant.conf'
                if card_wpa:
                    cwpa.write_text('network={\n\tssid="CardNet"\n}\n')
                elif cwpa.exists():
                    cwpa.unlink()
                (d / 'sd' / 'config' / 'boot.conf').write_text(boot_conf)
                code = snippet
                for old, new in (
                    ('/mnt/sd', str(d / 'sd')),
                    ('/etc/wpa_supplicant.conf', str(out_wpa)),
                    ('/tmp/sd-flash-cfg', str(d / 'tmp_sfc')),
                ):
                    code = code.replace(old, new)
                script = (
                    f'FM=0; RESCUE=; CFGD={d / "sd" / "config"}; RS={rs}\n'
                    'log() { :; }\n'
                    + code
                )
                subprocess.run(['sh', '-c', script], check=True)
                return out_wpa.read_text() if out_wpa.exists() else None

            self.assertIn('ssid="FlashNet"', run_wf(''))
            self.assertFalse((d / 'tmp_sfc').exists())
            self.assertIsNone(run_wf('SD_FLASH_WIFI=0\n'))
            self.assertIn('ssid="CardNet"', run_wf('', card_wpa=True))


if __name__ == '__main__':
    unittest.main()
