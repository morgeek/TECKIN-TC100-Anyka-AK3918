import io
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'www/cgi-bin/supportbundle.cgi'


def pick_shell():
    if shutil.which('busybox'):
        return ['busybox', 'sh']
    if Path('/bin/dash').exists():
        return ['/bin/dash']
    return ['/bin/sh']


class SupportBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='sb_test_'))
        self.proc = self.tmp / 'proc'
        self.sys = self.tmp / 'sys'
        self.tdir = self.tmp / 'tmp'
        self.var = self.tmp / 'var'
        self.cfg = self.tmp / 'config'
        self.mlog = self.tmp / 'mnt_log'
        self.bin = self.tmp / 'bin'
        for d in (
            self.proc / 'net',
            self.sys / 'module/ak_isp/parameters',
            self.sys / 'module/ak39_vi/parameters',
            self.sys / 'module/rtl8xxxu/parameters',
            self.tdir / 'logs',
            self.tdir / 'log',
            self.var / 'log',
            self.var / 'run',
            self.cfg / 'log',
            self.mlog,
            self.bin,
        ):
            d.mkdir(parents=True, exist_ok=True)

        for name, out in (
            ('uname', 'Linux IPCAM 6.6.0 armv5tejl\n'),
            ('uptime', ' 01:23:45 up 1 day,  2:00,  load average: 0.25, 0.20, 0.15\n'),
            ('ps', '  1 root     init\n'),
            ('df', '/dev/mtdblock3 6.0M 4.5M 1.5M 75% /\n'),
            ('dmesg', '[    0.000000] Booting Linux\n[   12.345678] ak39_vi ready\n'),
        ):
            p = self.bin / name
            p.write_text(f'#!/bin/sh\nprintf %s "{out}"\n')
            p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collects_diagnostics_and_redacts_secrets(self):
        # Proc & sysfs snapshots
        (self.proc / 'meminfo').write_text('MemTotal:          61440 kB\nMemAvailable:      20480 kB\n')
        (self.proc / 'cmdline').write_text('console=ttySAK0,115200 flashroot=1\n')
        (self.proc / 'mtd').write_text('dev:    size   erasesize  name\n')
        (self.proc / 'interrupts').write_text('           CPU0\n')
        (self.proc / 'net/wireless').write_text('wlan0: 0000   70.  -49.  -256\n')
        (self.proc / 'net/snmp').write_text('Ip: Forwarding DefaultTTL\n')

        (self.sys / 'module/ak_isp/parameters/awb_live').write_text('0\n')
        (self.sys / 'module/ak39_vi/parameters/nr3d').write_text('1\n')
        (self.sys / 'module/ak39_vi/parameters/nr3d_overflow').write_text('2\n')
        (self.sys / 'module/ak39_vi/parameters/sub_channel').write_text('1\n')
        (self.sys / 'module/ak39_vi/parameters/main_scale').write_text('1920x1080\n')
        (self.sys / 'module/rtl8xxxu/parameters/ampdu_rx').write_text('N\n')
        (self.sys / 'module/rtl8xxxu/parameters/tx_atten').write_text('0\n')

        # Logs & runtime snapshots
        (self.var / 'log/messages').write_text('syslog line\n')
        (self.var / 'run/tc100_rtsp.stat').write_text('clients=1\n')
        (self.tdir / 'logs/tc100_rtsp.log').write_text('STAT fps=15\n')
        (self.tdir / 'logs/daynight.log').write_text('2026-11-13 day -> night\n')
        (self.cfg / 'log/daynight-last.log').write_text('prev night\n')
        (self.tdir / 'log/audit.log').write_text('1000 action=save\n')
        (self.tdir / 'log/service-watchdog.log').write_text('ok\n')
        (self.tdir / 'log/mqtt-bridge.log').write_text('connected\n')
        (self.tdir / 'log/nightmode.log').write_text('ircut=0\n')
        (self.tdir / 'log/stability.pending').write_text('clean\n')
        (self.cfg / 'log/reboot-history.log').write_text('1000 normal\n')
        (self.tdir / 'boot-milestones.txt').write_text('wifi_up=4\n')
        (self.cfg / 'log/boot-milestones.log').write_text('boot=1\n')
        (self.tdir / 'wifi-quality').write_text('rssi=-49\n')
        (self.tdir / 'wifi-quality.log').write_text('1000 -49 0 0 0\n')
        (self.tdir / 'cam_awb').write_text('300000 0 0 0 0 0 0 0 0 0 1\n')
        (self.tdir / 'last-reboot-reason').write_text('power\n')
        (self.tdir / 'safemode').write_text('0\n')

        # Configs with sensitive fields + raw user.pwd that must not be bundled
        (self.cfg / 'user.pwd').write_text('supersecretrootpw\n')
        (self.cfg / 'boot.conf').write_text('NR3D=auto\nWIFI_RESCUE_PSK=RescueSecret99\n')
        (self.cfg / 'mqtt.conf').write_text('MQTT_USER=cam1\nMQTT_PASSWORD=\'MqttSecret!\'\n')
        (self.cfg / 'rtspserver.conf').write_text('USERNAME=admin\nUSERPASSWORD=RtspSecret42\n')
        (self.cfg / 'wpa_supplicant.conf').write_text(
            'ctrl_interface=/var/run/wpa_supplicant\n'
            'network={\n'
            '\tssid="HomeWiFi"\n'
            '\tkey_mgmt=WPA-PSK\n'
            '\tpsk="WifiPassphrase123"\n'
            '\twep_key0="WepSecret"\n'
            '}\n'
        )
        (self.cfg / 'telegram.conf').write_text(
            'apiToken="999:BotSecretToken"\n'
            'userChatId="123456789"\n'
        )
        (self.cfg / 'notify.conf').write_text(
            'NTFY_URL="https://myuser:NtfyUrlPass@ntfy.example"\n'
            'NTFY_TOPIC="SecretNtfyTopic"\n'
            'NTFY_AUTH="Bearer SecretBearer"\n'
            'WEBHOOK_URL="https://hooks.example/services/secret/hook"\n'
            'NOTIFY_UPLOAD_URL="https://dav.example/secret-folder"\n'
            'NOTIFY_UPLOAD_AUTH="davuser:DavPass99"\n'
        )

        env = os.environ.copy()
        env['PATH'] = f"{self.bin}:{env.get('PATH', '/usr/bin:/bin')}"
        env['REQUEST_METHOD'] = 'GET'
        env['QUERY_STRING'] = ''
        env['SB_PROC_DIR'] = str(self.proc)
        env['SB_SYS_DIR'] = str(self.sys)
        env['SB_TMP_DIR'] = str(self.tdir)
        env['SB_VAR_DIR'] = str(self.var)
        env['SB_CONFIG_DIR'] = str(self.cfg)
        env['SB_MNT_LOG_DIR'] = str(self.mlog)

        res = subprocess.run(pick_shell() + [str(SCRIPT)], env=env, capture_output=True)
        self.assertEqual(res.returncode, 0, res.stderr.decode('utf-8', 'replace'))

        sep = b'\r\n\r\n'
        self.assertIn(sep, res.stdout)
        hdr, payload = res.stdout.split(sep, 1)
        hdr_s = hdr.decode('utf-8')
        self.assertIn('Content-Type: application/gzip', hdr_s)
        self.assertIn('Content-Disposition: attachment; filename="tc100-support-', hdr_s)

        members = {}
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as tf:
            for m in tf.getmembers():
                if m.isfile():
                    name = m.name.lstrip('./')
                    members[name] = tf.extractfile(m).read().decode('utf-8', 'replace')

        for expected in (
            'system/uname.txt',
            'system/meminfo.txt',
            'system/net-wireless.txt',
            'system/net-snmp.txt',
            'system/driver-params.txt',
            'logs/dmesg.txt',
            'logs/tc100_rtsp.log',
            'logs/daynight.log',
            'logs/daynight-last.log',
            'logs/audit.log',
            'logs/service-watchdog.log',
            'logs/mqtt-bridge.log',
            'logs/nightmode.log',
            'logs/stability.pending',
            'logs/reboot-history.log',
            'logs/boot-milestones.txt',
            'logs/boot-milestones.log',
            'logs/wifi-quality',
            'logs/wifi-quality.log',
            'logs/cam_awb',
            'logs/last-reboot-reason',
            'logs/safemode',
            'logs/tc100_rtsp.stat',
        ):
            self.assertIn(expected, members, f'missing {expected} in bundle')

        self.assertIn('parameters/awb_live=0', members['system/driver-params.txt'])
        self.assertIn('parameters/nr3d_overflow=2', members['system/driver-params.txt'])
        self.assertIn('parameters/ampdu_rx=N', members['system/driver-params.txt'])

        self.assertNotIn('config/user.pwd', members)
        all_cfg_text = '\n'.join(v for k, v in members.items() if k.startswith('config/'))
        for secret in (
            'supersecretrootpw',
            'RescueSecret99',
            'MqttSecret!',
            'RtspSecret42',
            'WifiPassphrase123',
            'WepSecret',
            'BotSecretToken',
            '123456789',
            'NtfyUrlPass',
            'SecretNtfyTopic',
            'SecretBearer',
            'hooks.example',
            'secret-folder',
            'DavPass99',
        ):
            self.assertNotIn(secret, all_cfg_text, f'leaked secret: {secret}')

        self.assertIn('NR3D=auto', members['config/boot.conf'])
        self.assertIn('USERNAME=admin', members['config/rtspserver.conf'])
        self.assertIn('ssid="HomeWiFi"', members['config/wpa_supplicant.conf'])
        self.assertIn('key_mgmt=WPA-PSK', members['config/wpa_supplicant.conf'])
        self.assertIn('apiToken="********"', members['config/telegram.conf'])

        # Temp workdir and tarball must be cleaned up on exit
        self.assertEqual(list(self.tdir.glob('support.*')), [])


if __name__ == '__main__':
    unittest.main()
