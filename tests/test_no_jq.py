"""Audit 2026-11-06, S1 (owner: remove jq everywhere): the two scripts that used jq read JSON with scripts/jsonflat.awk,
and neither the flash image nor the Buildroot base carries jq, libjq or oniguruma any more."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
JSONFLAT = str(ROOT / 'scripts/jsonflat.awk')


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', (ROOT / path).read_text(), re.M | re.S)
    if not m:
        raise AssertionError((path, name))
    return m.group(0)


class TelegramWithoutJq(unittest.TestCase):
    def parse(self, doc):
        code = function('scripts/telegram-bot-daemon.sh', 'tg_parse') + '''
tg_parse "$1"; rc=$?
printf 'rc=%s\\nok=%s\\nchat=%s\\ncmd=%s\\nupd=%s\\nuser=%s\\nfirst=%s\\n' "$rc" "$ok" "$chatId" "$cmd" "$updateId" "$username" "$firstName"
'''
        with tempfile.TemporaryDirectory() as t:
            r = subprocess.run(SH + ['-c', code, '_', doc], capture_output=True, text=True, timeout=20,
                               env=dict(os.environ, JSONFLAT=JSONFLAT), cwd=t)
            self.assertEqual(r.stderr, '')
            return dict(l.split('=', 1) for l in r.stdout.splitlines())

    def test_a_message(self):
        doc = json.dumps({'ok': True, 'result': [{'update_id': 815, 'message': {
            'chat': {'id': 123456789}, 'text': '/snapshot', 'from': {'username': 'owner', 'first_name': 'Ann'}}}]})
        self.assertEqual(self.parse(doc), {'rc': '0', 'ok': 'true', 'chat': '123456789', 'cmd': '/snapshot',
                                           'upd': '815', 'user': 'owner', 'first': 'Ann'})

    def test_no_update_and_errors(self):
        d = self.parse('{"ok":true,"result":[]}')
        self.assertEqual((d['rc'], d['chat']), ('0', ''))           # nothing new: main() returns 0
        self.assertEqual(self.parse('{"ok":false,"error_code":401}')['rc'], '1')
        self.assertEqual(self.parse('not json')['rc'], '1')
        self.assertEqual(self.parse('')['rc'], '1')

    def test_text_from_the_network_is_never_run(self):
        # jq's @sh + eval became a plain read: a hostile message stays a string
        evil = '$(touch /tmp/tc100-pwned); `id`; x=1'
        doc = json.dumps({'ok': True, 'result': [{'update_id': 1, 'message': {'chat': {'id': 5}, 'text': evil}}]})
        if os.path.exists('/tmp/tc100-pwned'):
            os.remove('/tmp/tc100-pwned')
        self.assertEqual(self.parse(doc)['cmd'], evil)
        self.assertFalse(os.path.exists('/tmp/tc100-pwned'))
        src = (ROOT / 'scripts/telegram-bot-daemon.sh').read_text()
        self.assertNotIn('eval', re.sub(r'(?m)^\s*#.*$', '', src))


class UpdateCheckWithoutJq(unittest.TestCase):
    def test_tag_name(self):
        src = (ROOT / 'scripts/update-check.sh').read_text()
        line = next(l for l in src.splitlines() if l.startswith('LATEST_TAG='))
        doc = json.dumps({'url': 'x', 'assets': [{'name': 'a', 'tag_name': 'nested-not-this'}], 'tag_name': 'v3.0.1',
                          'body': 'notes "quoted" \\ and\ttab'})
        r = subprocess.run(SH + ['-c', '_response=$1\n' + line + '\nprintf "%s" "$LATEST_TAG"', '_', doc],
                           capture_output=True, text=True, timeout=20, env=dict(os.environ, JSONFLAT=JSONFLAT))
        self.assertEqual(r.stdout, 'v3.0.1')


class NoJqShipped(unittest.TestCase):
    def test_build_and_base_have_no_jq(self):
        stack = (ROOT / 'v3/build-stack.sh').read_text()
        self.assertNotIn('usr/bin/jq', stack)
        self.assertRegex(stack, r'(?m)^for b in curl; do')
        self.assertNotIn('BR2_PACKAGE_JQ', (ROOT / 'v3/buildroot/configs/tc100_defconfig').read_text())
        for rel in ('scripts/telegram-bot-daemon.sh', 'scripts/update-check.sh', 'scripts/common_functions.sh'):
            code = re.sub(r'(?m)^\s*#.*$', '', (ROOT / rel).read_text())
            self.assertNotRegex(code, r'/mnt/bin/jq|\bjq\b', rel)


if __name__ == '__main__':
    unittest.main()
