"""Audit 2026-11-04 W6: no secret in the read-only answers: the rescue password only with reveal=1 and the CSRF
check, no Telegram token in fullconfig, and an empty token field keeps the saved token."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class SecretsGet(unittest.TestCase):
    def test_rescue_password_on_request_only(self):
        s = text('scripts/action.d/network.sh')
        branch = s[s.index('    wifi_rescue_info)'):s.index('    wifi_country_info)')]
        self.assertIn('if [ "${F_reveal}" = 1 ]; then csrf_check; _wr_psk="$_wr_psk_val"; fi', branch)
        self.assertNotIn('_wr_psk_val', branch.split('printf')[1])               # not printed directly
        self.assertIn("cmd=wifi_rescue_info&format=json&reveal=1", text('www/settings.html'))

        # Functional check: reveal=0 omits psk; reveal=1 enforces csrf_check before exposing psk
        import json, os, shutil, subprocess
        sh_bin = shutil.which('dash') or shutil.which('sh') or '/bin/sh'
        body = branch.split('\n', 1)[1].rsplit(';;', 1)[0]
        body = body.replace(
            '$(sh /mnt/scripts/wifi-rescue.sh status 2>/dev/null)',
            "$(printf 'ap=1\\nssid=RescueAP\\npsk=TopSecret123\\n')",
        ).replace(
            '( . /mnt/scripts/service-switch.sh && svc_on wifi-rescue ) 2>/dev/null',
            'true',
        )
        script = 'csrf_check() { [ "${FAKE_CSRF_OK:-0}" = 1 ] || { echo "csrf_fail"; exit 1; }; }\n' + body

        def run_branch(reveal, csrf_ok):
            env = dict(os.environ, F_reveal=str(reveal), FAKE_CSRF_OK=str(csrf_ok))
            return subprocess.run([sh_bin, '-c', script], env=env, capture_output=True, text=True)

        r0 = run_branch(0, 0)
        self.assertEqual(r0.returncode, 0, r0.stderr)
        d0 = json.loads(r0.stdout)
        self.assertEqual(d0['psk'], '')
        self.assertEqual(d0['psk_set'], 1)
        self.assertNotIn('TopSecret123', r0.stdout)

        r1 = run_branch(1, 1)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        d1 = json.loads(r1.stdout)
        self.assertEqual(d1['psk'], 'TopSecret123')
        self.assertEqual(d1['psk_set'], 1)

        r_bad = run_branch(1, 0)
        self.assertNotEqual(r_bad.returncode, 0)
        self.assertNotIn('TopSecret123', r_bad.stdout)

    def test_no_telegram_token_in_fullconfig(self):
        s = text('www/cgi-bin/state.cgi')
        self.assertIn('"telegram":{"enabled":%s,"token":"%s","token_set":%s,"chat_id":"%s"}', s)
        self.assertNotIn('json_escape "$(get_cfg apiToken', s)

    def test_empty_token_field_keeps_the_token(self):
        s = text('scripts/action.d/system.sh')
        m = re.search(r'      case "\$telegram_token" in\n.*?      esac\n', s, re.S)
        with tempfile.TemporaryDirectory() as t:
            conf = Path(t, 'telegram.conf')
            for value, want in (('', 'apiToken=OLD'), ('-', 'apiToken='), ('NEW', 'apiToken=NEW')):
                conf.write_text('apiToken=OLD\n')
                code = ('rewrite_config() { sed -i.bak "s|^$2=.*|$2=$3|" "$1" && rm -f "$1.bak"; }\ntelegram_token=%r\n' % value) + \
                       m.group(0).replace('/mnt/config/telegram.conf', str(conf))
                subprocess.run(SH + ['-c', code], check=True)
                self.assertEqual(conf.read_text().strip(), want, value)


if __name__ == '__main__':
    unittest.main()
