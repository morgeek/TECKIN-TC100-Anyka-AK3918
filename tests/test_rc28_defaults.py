"""The features of 2026-11-05 on by default for the next RC (owner): the .dist files of new installs, and
scripts/migrate-rc28-defaults.sh for cameras already installed (their config files are never replaced by a .dist):
a key missing or still at the old default gets the new value, once; any other value stays."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def table():
    s = (ROOT / 'scripts/migrate-rc28-defaults.sh').read_text(encoding='utf-8')
    body = s[s.index('<<EOF\n') + 6:s.index('\nEOF\n')]
    return [l.split() for l in body.splitlines() if l.strip()]


class Rc28Defaults(unittest.TestCase):
    def test_dist_files_hold_the_new_defaults(self):
        for f, k, old, new in table():
            s = (ROOT / 'config' / (f + '.dist')).read_text(encoding='utf-8')
            self.assertRegex(s, r'(?m)^%s=%s$' % (re.escape(k), re.escape(new)), (f, k))

    def test_migration_once_keeps_choices(self):
        rows = table()
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            for f in {r[0] for r in rows}:
                shutil.copy(ROOT / 'config' / (f + '.dist'), c / (f + '.dist'))
            # an installed camera: old defaults written, one key chosen by the owner, one key missing
            (c / 'boot.conf').write_text('SUPERVISOR_IMPL=sh\nWHEP=0\nWEB_LOCKOUT="0"\nMDNS_INFO=7\nNET_GUARD_SOFT=0\n')
            (c / 'onvif.conf').write_text('ONVIF_IMPL=monvifd\nONVIF_PORT=8081\n')
            (c / 'mqtt.conf').write_text('MQTT_ENABLE=1\nMQTT_BRIDGE_IMPL=shell\n')
            run = lambda: subprocess.run(SH + [str(ROOT / 'scripts/migrate-rc28-defaults.sh')], check=True,
                                         env={'MR_CONF_DIR': str(c), 'PATH': '/usr/bin:/bin'})
            run()
            boot = (c / 'boot.conf').read_text()
            self.assertIn('SUPERVISOR_IMPL=c\n', boot)
            self.assertIn('WHEP=1\n', boot)
            self.assertIn('WEB_LOCKOUT=1\n', boot)              # quoted old default too
            self.assertIn('MDNS_INFO=7\n', boot)                # a value chosen by someone stays
            self.assertIn('HTTPFRONT_NATIVE=1\n', boot)          # missing: added
            self.assertIn('ONVIF_IMPL=c\n', (c / 'onvif.conf').read_text())
            self.assertIn('ONVIF_PORT=8081', (c / 'onvif.conf').read_text())
            mq = (c / 'mqtt.conf').read_text()
            self.assertIn('MQTT_BRIDGE_IMPL=c\n', mq)
            self.assertIn('MQTT_DISCOVERY_IMPL=c\n', mq)
            self.assertTrue((c / '.migrated-rc28-defaults').exists())
            # the owner turns WHEP off afterwards: a second boot does not turn it on again
            (c / 'boot.conf').write_text(boot.replace('WHEP=1', 'WHEP=0'))
            run()
            self.assertIn('WHEP=0\n', (c / 'boot.conf').read_text())

    def test_wiring(self):
        a = (ROOT / 'v3/autorun-linux66.sh').read_text(encoding='utf-8')
        self.assertLess(a.index('migrate-rc28-defaults.sh'), a.index('BC_$_k'))   # before boot.conf is read
        r = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text(encoding='utf-8')
        i = r.index('RTSP_ALSA_DIRECT="${RTSP_ALSA_DIRECT:-1}"')
        self.assertLess(i, r.index('. /mnt/config/rtsp.env'))                    # rtsp.env can still say 0
        for v in ('RTSP_AUDIO_HPF', 'RTSP_AUDIO_AGC', 'RTSP_AUDIO_DUCK', 'RTSP_ABR', 'RTSP_MD_ENC', 'RTSP_REC_AAC'):
            self.assertIn('%s="${%s:-1}"' % (v, v), r)
        self.assertIn('RTSP_AUDIO_AEC="${RTSP_AUDIO_AEC:-0}"', r)                 # echo cancellation: off until measured


if __name__ == '__main__':
    unittest.main()
