"""Item 25: privacy mode. controlscripts/privacy sets / clears the flag and keeps PRIVACY_SCREEN in boot.conf; the
pictures are blackened with fill() (rows marked for the cache clean of the direct capture) before the encoder, the
snapshots and the recorder; motion detection pauses; MQTT gets a switch; autorun sets the flag before the video."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class ControlScript(unittest.TestCase):
    def test_start_stop_status(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            conf, flag = t / 'boot.conf', t / 'flag'
            conf.write_text('NET_GUARD=1\n')
            env = dict(os.environ, PV_TEST='1', PV_FLAG=str(flag), PV_CONF=str(conf))
            run = lambda a: subprocess.run(SH + [str(ROOT / 'controlscripts/privacy'), a], env=env, capture_output=True, text=True)
            self.assertEqual(run('status').stdout, '')
            run('start')
            self.assertTrue(flag.exists())
            self.assertIn('PRIVACY_SCREEN=1', conf.read_text())
            self.assertEqual(run('status').stdout.strip(), 'PID: on')
            run('stop')
            self.assertFalse(flag.exists())
            self.assertEqual(conf.read_text().count('PRIVACY_SCREEN='), 1)
            self.assertIn('PRIVACY_SCREEN=0', conf.read_text())


class Wiring(unittest.TestCase):
    def test_server_blackens_before_use(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('fill(p, w, h, 0, 0, w, h, 16);', src)                     # fill marks the rows for dm_clean
        sub = src[src.index('post_overlay(sp, SW, SH, 0);'):]
        self.assertLess(sub.index('if (priv_on) priv_black(sp, SW, SH);'), sub.index('dm_clean(sp, SW, SH'))
        main = src[src.index('post_overlay(cur, W, H, 1);'):]
        self.assertLess(main.index('if (priv_on) priv_black(cur, W, H);'), main.index('dm_clean(cur, W, H'))
        self.assertLess(src.index('if (priv_on) priv_black(cur, W, H);'), src.index('if ((n = jpeg_run(py, py + W * H, W, H, 35)))'))
        self.assertIn('if (!md_on || priv_on) {', src)
        self.assertIn('if (priv_on) s = 0;', src)

    def test_mqtt_switch_and_boot(self):
        m = text('scripts/mqtt-bridge.sh')
        self.assertIn('for cmd in ir_led front_led red_led motion_detection night_mode auto_night_mode privacy; do', m)
        self.assertIn('script="/mnt/controlscripts/privacy"', m)
        self.assertIn('"red_led_on":%s,"privacy_on":%s,"ir_led_on":%s,', m)
        self.assertIn('"$red_led_on" "$privacy_on" "$ir_led_on"', m)
        a = text('v3/autorun-linux66.sh')
        self.assertLess(a.index(": > /tmp/tc100_privacy"), a.index('sh $TB/rtsp-launch.sh'))


if __name__ == '__main__':
    unittest.main()
