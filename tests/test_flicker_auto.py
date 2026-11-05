"""Item 16 of the implementer list: POWER_HZ=auto takes the mains frequency of the Wi-Fi country (tc100_rtsp
mains_hz), accepted by the page, the validators, the export and the ISP state JSON."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class MainsHz(unittest.TestCase):
    def test_country_table(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        fn = re.search(r'^static int mains_hz\(const char \*cc\)\n\{.*?^}', src, re.M | re.S).group(0)
        prog = ('#include <string.h>\n#include <stdio.h>\n' + fn +
                '\nint main(int c, char **v) { for (int i = 1; i < c; i++) printf("%s=%d ", v[i], mains_hz(v[i])); return 0; }\n')
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'm.c').write_text(prog)
            subprocess.run(['gcc', '-o', str(Path(t, 'm')), str(Path(t, 'm.c'))], check=True)
            out = subprocess.run([str(Path(t, 'm')), 'FR', 'fr', 'US', 'ca', 'BR', 'KR', 'TW', 'PH', 'SA', 'VG',
                                  'DE', 'GB', 'CN', 'AU', 'JP', '', 'F', 'FRA', '1X'], capture_output=True, text=True).stdout
        self.assertEqual(out.split(), ['FR=50', 'fr=50', 'US=60', 'ca=60', 'BR=60', 'KR=60', 'TW=60', 'PH=60', 'SA=60',
                                       'VG=60', 'DE=50', 'GB=50', 'CN=50', 'AU=50', 'JP=0', '=0', 'F=0', 'FRA=0', '1X=0'])


class Wiring(unittest.TestCase):
    def test_auto_accepted_everywhere(self):
        self.assertIn('POWER_HZ)\n      case "$_itn_v" in \'\'|50|60|auto)', text('scripts/isp-tune.sh'))
        self.assertIn("isp_power_hz) case \"$_tc_value\" in ''|50|60|auto)", text('scripts/config-transaction.sh'))
        self.assertIn('<option value="auto">Automatic (from the Wi-Fi country)</option>', text('www/settings.html'))
        self.assertIn('} else if (v == "auto" && t == "isp_power_hz") {', text('www/cgi-bin/config_exchange.cgi'))
        src = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('p_hz = cfg_get(CONF "boot.conf", "", "WIFI_COUNTRY", cc, sizeof cc) ? mains_hz(cc) : 0;', src)

    def test_state_json_reports_auto(self):
        r = subprocess.run(SHELL + ['-c', re.search(r'^_isp_num\(\).*$', text('scripts/isp-tune.sh'), re.M).group(0) +
                                    '\n_isp_num auto; echo; _isp_num 50; echo; _isp_num ""; echo'], capture_output=True, text=True)
        self.assertEqual(r.stdout.split('\n')[:3], ['"auto"', '50', 'null'])


if __name__ == '__main__':
    unittest.main()
