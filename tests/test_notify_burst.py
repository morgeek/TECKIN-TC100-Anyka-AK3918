"""Item 34: scripts/notify.sh: a fresh picture for an event without one, the burst for the chosen events, the PUT copy
off the camera, and a message with quotes passed as one argument (no eval)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


class NotifyBurst(unittest.TestCase):
    def run_notify(self, conf, event='tamper', message="it's tampered", snap=''):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'notify.conf').write_text(conf)
            calls = t / 'calls'
            # one write per call: the channels run in parallel and their lines must not interleave
            (t / 'curl').write_text('#!/bin/sh\nl=\nfor a; do l="$l[$a]"; done\necho "$l" >> %s\n' % calls)
            (t / 'telegram').write_text('#!/bin/sh\necho "telegram $*" >> %s\n' % calls)
            (t / 'snap').write_text('#!/bin/sh\necho JPEG > "$1"\necho "snap $1" >> %s\n' % calls)
            for f in ('curl', 'telegram', 'snap'):
                (t / f).chmod(0o755)
            env = dict(os.environ, NOTIFY_CONF=str(t / 'notify.conf'), NOTIFY_CURL=str(t / 'curl'),
                       NOTIFY_TELEGRAM=str(t / 'telegram'), NOTIFY_SNAPSHOT_CMD=str(t / 'snap'), NOTIFY_STATE_DIR=str(t))
            r = subprocess.run(SH + [str(ROOT / 'scripts/notify.sh'), event, message, snap], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return calls.read_text().splitlines() if calls.exists() else []

    def test_tamper_gets_a_picture_a_burst_and_the_upload(self):
        c = self.run_notify('NTFY_ENABLE=1\nNTFY_TOPIC=cam\nTELEGRAM_NOTIFY_ENABLE=1\nNOTIFY_BURST=2\n'
                            'NOTIFY_UPLOAD_URL="http://nas/webdav/tc100/"\nNOTIFY_UPLOAD_AUTH="u:p"\n')
        self.assertEqual(sum(1 for l in c if l.startswith('snap ')), 3)                    # 1 + burst of 2
        ntfy = [l for l in c if '[http://ntfy.sh/cam]' in l or 'ntfy.sh/cam' in l]
        self.assertEqual(len(ntfy), 3)
        self.assertTrue(all('[X-Message: it\'s tampered' in l for l in ntfy))              # one argument, quote kept
        self.assertEqual(sum(1 for l in c if l.startswith('telegram p ')), 3)
        up = [l for l in c if '[-u][u:p]' in l]
        self.assertEqual(len(up), 3)
        self.assertTrue(any('_tamper_0.jpg]' in l for l in up) and any('_tamper_2.jpg]' in l for l in up))

    def test_motion_no_burst_and_nothing_when_all_off(self):
        c = self.run_notify('NTFY_ENABLE=1\nNTFY_TOPIC=cam\nNOTIFY_BURST=3\n', event='motion', message='m')
        self.assertEqual(sum(1 for l in c if l.startswith('snap ')), 1)                    # the picture, no burst
        self.assertEqual(self.run_notify('NTFY_ENABLE=0\n'), [])

    def test_config_keys_validated_and_exported(self):
        t = (ROOT / 'scripts/config-transaction.sh').read_text()
        self.assertIn('tc_check_flat "$_tc_file" NOTIFY_BURST u:0:5', t)
        self.assertIn('tc_check_flat "$_tc_file" NOTIFY_UPLOAD_URL url_optional', t)
        e = (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text()
        # ntfy_auth since 2026-11-11: notify.conf is sourced, the value between double quotes must not hold $ ` " \
        self.assertIn('"NOTIFY_UPLOAD_AUTH";"ntfy_auth";"credential"', e)


if __name__ == '__main__':
    unittest.main()
