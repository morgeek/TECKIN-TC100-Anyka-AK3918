"""Review of 2026-11-06 (owner's decisions):
- P1 #1: without an SD card the web update cannot save the flash first; it writes only after the user confirmed an
  install without a backup (update.cgi error "nobackup", then &nobackup=1 -> UPDATE66_NOBACKUP=1), checked by
  update66.sh before anything is stopped; with a card the backup is mandatory (flashw -b, a failed backup = no write).
- P1 #2: the first-install hook is the one sanctioned writer of the U-Boot environment; nothing else may write it."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class UpdateWithoutBackup(unittest.TestCase):
    def test_cgi_refuses_without_a_card_until_confirmed(self):
        cgi = text('www/cgi-bin/update.cgi')
        body = cgi[cgi.index('POST:install)'):cgi.index('POST:discard)')]
        self.assertIn('"error":"nobackup"', body)
        self.assertIn('*"&nobackup=1&"*) _nb=1', body)
        self.assertLess(body.index('"error":"nobackup"'), body.index(': > /tmp/update66.running'))
        self.assertIn('UPDATE66_NOBACKUP=$_nb sh $U apply "$WORK"', body)

    def test_update66_checks_before_stopping_anything(self):
        s = text('v3/install/update66.sh')
        guard = s.index('[ -z "$LOG" ] && [ "${UPDATE66_NOBACKUP:-0}" != 1 ]')
        self.assertLess(guard, s.index('exec /bin/sh $R/update66.sh apply-ram'))
        self.assertLess(guard, s.index('stopping the services'))
        self.assertIn('BK=; [ -n "$LOG" ] && BK="-b /mnt/sd/tc100-3/backup"', s)   # with a card: backup on every write

    def test_flashw_backup_failure_writes_nothing(self):
        f = text('v3/linux66-sd/flashw')
        bk = f.index('if [ -n "$BK" ]; then')
        self.assertIn('exit 7', f[bk:f.index('flashcp -v')])
        self.assertLess(bk, f.index('flashcp -v'))

    def test_page_asks_and_sends_the_confirmation(self):
        html = text('www/settings.html')
        self.assertIn("d.error === 'nobackup' && !extra", html)
        self.assertIn("run(cmd, confirmText, msg, '&nobackup=1')", html)


class OneUbootEnvironmentWriter(unittest.TestCase):
    def test_only_the_first_install_hook_writes_it(self):
        r = subprocess.run(['git', '-C', str(ROOT), 'grep', '-l', '-E', r'envtool"? set|fw_setenv|saveenv',
                            '--', 'scripts', 'controlscripts', 'www', 'v3', 'src'], capture_output=True, text=True)
        writers = set()
        for rel in r.stdout.split():
            code = re.sub(r'(?m)^\s*(#|//|\*).*$', '', text(rel))      # mentions in comments do not write
            if re.search(r'envtool"? set|fw_setenv|saveenv', code):
                writers.add(rel)
        writers.discard('v3/install/envtool.c')                         # the tool itself
        self.assertEqual(writers, {'v3/install/stock-hook.sh'})
        self.assertIn('The one sanctioned exception', text('AGENTS.md'))


if __name__ == '__main__':
    unittest.main()
