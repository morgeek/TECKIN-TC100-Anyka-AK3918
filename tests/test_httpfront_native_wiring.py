"""Item 55: the switch of the native status line. boot.conf HTTPFRONT_NATIVE (off by default) -> TC100_NATIVE_STATUS for
httpfront, the way WEB_LOCKOUT -> TC100_WEB_LOCKOUT does. The behaviour itself is tests/test_httpfront_native.py (it
needs the ARM compiler and qemu-arm)."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(p):
    return (ROOT / p).read_text()


class Wiring(unittest.TestCase):

    def test_launchers_pass_the_switch(self):
        self.assertIn('TC100_NATIVE_STATUS="$BC_HTTPFRONT_NATIVE"', text('v3/autorun-linux66.sh'))
        cf = text('scripts/common_functions.sh')
        self.assertIn('TC100_NATIVE_STATUS="$(read_kv_config_value /mnt/config/boot.conf HTTPFRONT_NATIVE 0)"; '
                      'export TC100_NATIVE_STATUS', cf)
        self.assertLess(cf.index('export TC100_NATIVE_STATUS'), cf.index('exec /mnt/tc100test/httpfront'))

    def test_off_by_default_and_documented_once(self):
        dist = text('config/boot.conf.dist')
        self.assertEqual(dist.count('\nHTTPFRONT_NATIVE='), 1)
        self.assertIn('\nHTTPFRONT_NATIVE=0\n', dist)
        src = text('src/httpfront/httpfront.c')
        self.assertIn('native_status = (e = getenv_(envp, "TC100_NATIVE_STATUS")) && e[0] == \'1\';', src)

    def test_validator_and_exchange_row(self):
        ct = ROOT / 'scripts/config-transaction.sh'
        for v, rc in (('1', 0), ('0', 0), ('', 1), ('x', 1), ('1;x', 1)):
            r = subprocess.run(['sh', '-c', '. "$1"; tc_normalize_and_validate bool "$2"', 'x', str(ct), v],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, rc, (v, r.stderr))
        self.assertIn('tc_check_flat "$_tc_file" HTTPFRONT_NATIVE bool', ct.read_text())
        rows = [ln for ln in text('www/cgi-bin/config_exchange.cgi').splitlines() if ln.strip().startswith('row("')]
        mine = [n for n, ln in enumerate(rows) if '"HTTPFRONT_NATIVE"' in ln]
        self.assertEqual(len(mine), 1)
        self.assertIn('"bool";"general";.boot.httpfront_native', rows[mine[0]])
        i = [n for n, ln in enumerate(rows) if '"BOOT_STEALTH"' in ln][0]
        self.assertEqual({r.split('"')[1] for r in rows[i:mine[0] + 1]}, {'boot.conf'})   # boot.conf rows stay contiguous

    def test_the_cgi_stays_the_fallback(self):
        self.assertIn('statusline_json', text('www/cgi-bin/statusline.cgi'))


if __name__ == '__main__':
    unittest.main()
