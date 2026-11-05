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
        self.assertIn('if [ "${F_reveal}" = 1 ]; then csrf_check; _wr_psk="$(_wr_v psk)"; fi', branch)
        self.assertNotIn('"$(_wr_v psk)"\n', branch.split('printf')[1])               # not printed directly
        self.assertIn("cmd=wifi_rescue_info&format=json&reveal=1", text('www/settings.html'))

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
                code = ('rewrite_config() { sed -i "s|^$2=.*|$2=$3|" "$1"; }\ntelegram_token=%r\n' % value) + \
                       m.group(0).replace('/mnt/config/telegram.conf', str(conf))
                subprocess.run(SH + ['-c', code], check=True)
                self.assertEqual(conf.read_text().strip(), want, value)


if __name__ == '__main__':
    unittest.main()
