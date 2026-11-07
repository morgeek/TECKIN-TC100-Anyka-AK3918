"""Wi-Fi rules per country (boot.conf WIFI_COUNTRY, scripts/wifi-country.sh) and the Wi-Fi start of the boot script
(v3/S39tc100-linux66: Wi-Fi first, the DHCP name of config/hostname.conf, no udhcpc restart by autorun)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
SCRIPT = str(ROOT / 'scripts/wifi-country.sh')
# `iw reg get` of a kernel with the database, world rules
IW_GET = 'global\ncountry %s: DFS-ETSI\n\t(2402 - 2482 @ 40), (N/A, 20), (N/A)\n'


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class WifiCountry(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.log = self.d / 'calls'
        # fake iw / wpa_cli / dmesg / pidof: record the calls; `iw reg get` prints the country of file "eff"
        for name, body in (('iw', 'echo "iw $*" >> %s\n[ "$1 $2" = "reg get" ] && printf "%s" "$(cat %s)"\nexit 0'
                            % (self.log, IW_GET.replace('\n', '\\n').replace('\t', '\\t'), self.d / 'eff')),
                           ('wpa_cli', 'echo "wpa_cli $*" >> %s' % self.log),
                           ('dmesg', 'cat %s 2>/dev/null' % (self.d / 'dmesg.txt')),
                           ('pidof', '[ -f %s ]' % (self.d / 'wpa.running'))):
            f = self.d / name
            f.write_text('#!/bin/sh\n' + body + '\n')
            f.chmod(0o755)
        self.conf = self.d / 'boot.conf'
        self.fw = self.d / 'regulatory.db'
        self.run_conf = self.d / 'wpa_supplicant.conf'
        self.env = dict(os.environ, WC_CONF=str(self.conf), WC_FW=str(self.fw), WC_RUNCONF=str(self.run_conf),
                        WC_MARK=str(self.d / 'mark'), WC_IW=str(self.d / 'iw'), WC_WPA_CLI=str(self.d / 'wpa_cli'),
                        WC_DMESG=str(self.d / 'dmesg'), WC_PIDOF=str(self.d / 'pidof'))
        (self.d / 'eff').write_text('00')

    def tearDown(self):
        self.tmp.cleanup()

    def run_wc(self, *args):
        r = subprocess.run(SHELL + [SCRIPT] + list(args), capture_output=True, text=True, timeout=20, env=self.env)
        return r

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_get_accepts_only_a_two_letter_code(self):
        for line, want in (('WIFI_COUNTRY=FR', 'FR'), ('WIFI_COUNTRY="BE"', 'BE'), ('WIFI_COUNTRY=', ''),
                           ('WIFI_COUNTRY=fr', ''), ('WIFI_COUNTRY=FRA', ''), ('WIFI_COUNTRY=$(id)', ''),
                           ('#WIFI_COUNTRY=FR', ''), ('WIFI_COUNTRY=DE\nWIFI_COUNTRY=CH', 'CH')):
            self.conf.write_text('WIFI_QUALITY=0\n' + line + '\n')
            self.assertEqual(self.run_wc('get').stdout.strip(), want, line)
        self.conf.unlink()
        self.assertEqual(self.run_wc('get').stdout.strip(), '')

    def test_conf_puts_the_country_first_and_drops_the_old_one(self):
        src = self.d / 'in.conf'
        src.write_text('ctrl_interface=/var/run/wpa_supplicant\n  country=US\nnetwork={\n\tssid="Home"\n\tpsk="secret-psk"\n}\n')
        self.conf.write_text('WIFI_COUNTRY=FR\n')
        self.assertEqual(self.run_wc('conf', str(src), str(self.d / 'out')).returncode, 0)
        out = (self.d / 'out').read_text()
        self.assertTrue(out.startswith('country=FR\nctrl_interface='), out)
        self.assertEqual(out.count('country='), 1)
        self.assertIn('psk="secret-psk"', out)
        # no country: no country line at all (wpa_supplicant keeps the kernel's world rules)
        self.conf.write_text('WIFI_COUNTRY=\n')
        self.run_wc('conf', str(src), str(self.d / 'out'))
        self.assertNotIn('country=', (self.d / 'out').read_text())

    def test_boot_reloads_the_database_once_and_sets_the_country(self):
        self.conf.write_text('WIFI_COUNTRY=FR\n')
        (self.d / 'dmesg.txt').write_text('cfg80211: failed to load regulatory.db\n')
        self.fw.write_text('db')
        self.run_wc('boot')
        self.assertEqual(self.calls(), ['iw reg reload', 'iw reg get', 'iw reg set FR'])
        self.log.unlink()
        (self.d / 'eff').write_text('FR')
        self.run_wc('boot')
        self.assertEqual(self.calls(), ['iw reg get'])        # read once per boot; already in force: nothing set

    def test_boot_without_database_or_country(self):
        (self.d / 'dmesg.txt').write_text('cfg80211: failed to load regulatory.db\n')
        self.conf.write_text('WIFI_COUNTRY=\n')
        self.run_wc('boot')
        self.assertEqual(self.calls(), [])                     # no file to reload, no country: nothing to do
        # the kernel read it at boot (no failure line): no reload
        self.fw.write_text('db')
        (self.d / 'dmesg.txt').write_text('cfg80211: Loading compiled-in X.509 certificates for regulatory database\n')
        self.conf.write_text('WIFI_COUNTRY=CH\n')
        self.run_wc('boot')
        self.assertEqual(self.calls(), ['iw reg get', 'iw reg set CH'])

    def test_apply_updates_the_copy_wpa_supplicant_and_the_kernel(self):
        self.fw.write_text('db')
        self.run_conf.write_text('country=US\nnetwork={\n\tssid="Home"\n}\n')
        (self.d / 'wpa.running').write_text('')
        self.conf.write_text('WIFI_COUNTRY=BE\n')
        self.assertEqual(self.run_wc('apply').returncode, 0)
        self.assertTrue(self.run_conf.read_text().startswith('country=BE\nnetwork={'))
        self.assertEqual(self.calls(), ['wpa_cli -i wlan0 set country BE', 'iw reg set BE'])
        # back to no country: the world rules ("00"), no country line in the copy
        self.log.unlink()
        (self.d / 'wpa.running').unlink()
        self.conf.write_text('WIFI_COUNTRY=\n')
        self.run_wc('apply')
        self.assertNotIn('country=', self.run_conf.read_text())
        self.assertEqual(self.calls(), ['iw reg set 00'])     # wpa_supplicant not running: not asked

    def test_status(self):
        self.conf.write_text('WIFI_COUNTRY=FR\n')
        (self.d / 'eff').write_text('FR')
        self.assertEqual(self.run_wc('status').stdout, 'configured=FR\neffective=FR\nregdb=0\n')
        self.fw.write_text('db')
        self.assertIn('regdb=1', self.run_wc('status').stdout)


class WifiCountrySources(unittest.TestCase):
    """One source (boot.conf WIFI_COUNTRY), read with the same pattern everywhere, and applied everywhere it matters."""

    def test_same_pattern_in_the_boot_script(self):
        pat = re.search(r"sed -n '(s/\^WIFI_COUNTRY=[^']*)'", text('scripts/wifi-country.sh')).group(1)
        self.assertIn(pat, text('v3/S39tc100-linux66'))

    def test_shipped_default_and_users(self):
        self.assertIn('\nWIFI_COUNTRY=\n', text('config/boot.conf.dist'))
        self.assertIn('BR2_PACKAGE_WIRELESS_REGDB=y', text('v3/buildroot/configs/tc100_defconfig'))
        self.assertIn('wifi-country.sh conf "$C" /etc/wpa_supplicant.conf.new', text('v3/linux66-sd/wifi-apply'))
        self.assertIn('wifi-country.sh boot', text('v3/autorun-linux66.sh'))
        self.assertIn('$(_wr_country)', text('scripts/wifi-rescue.sh'))
        self.assertIn('"WIFI_COUNTRY";"country_optional"', text('www/cgi-bin/config_exchange.cgi'))
        self.assertIn('WIFI_COUNTRY country_optional', text('scripts/config-transaction.sh'))
        net = text('scripts/action.d/network.sh')
        self.assertIn('rewrite_config /mnt/config/boot.conf WIFI_COUNTRY "$_wc_new"', net)
        self.assertIn('id="wifi_country_select"', text('www/settings.html'))

    def test_rescue_access_point_country_line(self):
        src = text('scripts/wifi-rescue.sh')
        fn = re.search(r'^_wr_kv\(\).*$', src, re.M).group(0) + '\n' + re.search(r'^_wr_country\(\).*$', src, re.M).group(0)
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / 'boot.conf'
            for value, want in (('FR', 'country_code=FR\nieee80211d=1'), ('', ''), ('fr', ''), ('"CH"', 'country_code=CH\nieee80211d=1')):
                conf.write_text('WIFI_COUNTRY=%s\n' % value)
                r = subprocess.run(SHELL + ['-c', 'CONF=%s\n%s\n_wr_country' % (conf, fn)], capture_output=True, text=True)
                self.assertEqual(r.stdout, want, value)


class WifiFirstAtBoot(unittest.TestCase):

    def test_wifi_starts_before_the_services_and_after_the_console(self):
        """The console and the password take milliseconds: they come first, so that a camera without network does not
        hold them for the 20-30 s of the DHCP attempts (audit 2026-11-04)."""
        s = text('v3/S39tc100-linux66')
        wpa = s.index('wpa_supplicant -B -i wlan0')
        self.assertGreater(wpa, s.index('/sbin/getty'))
        self.assertGreater(wpa, s.index('chpasswd'))
        self.assertGreater(wpa, s.index('flashmode-prep.sh'))                 # needs the settings
        self.assertLess(wpa, s.index('# 4. V3 services'))

    def test_dhcp_name_from_the_settings_and_no_needless_restart(self):
        s = text('v3/S39tc100-linux66')
        self.assertRegex(s, r'udhcpc -i wlan0 -b -t 20 -T 1 -A 5 .*?-x hostname:\$H')
        self.assertIn('echo "$H" > /tmp/dhcp-hostname', s)
        self.assertNotIn('hostname:tc100', s)
        a = text('v3/autorun-linux66.sh')
        # same rule for the name in both scripts
        rule = "grep -v '^[[:space:]]*$' | head -n 1 | tr -cd 'A-Za-z0-9-')"
        self.assertIn(rule, s)
        self.assertIn(rule, a)
        self.assertIn('[ "$H" = "$(cat /tmp/dhcp-hostname 2>/dev/null || echo tc100)" ] || killall udhcpc', a)
        self.assertIn('echo "$(hostname)" > /tmp/dhcp-hostname', text('v3/linux66-sd/net-apply'))

    def test_runtime_copy_is_private(self):
        s = text('v3/S39tc100-linux66')
        i = s.index('> /etc/wpa_supplicant.conf )')
        self.assertIn('chmod 600 /etc/wpa_supplicant.conf', s[i:i + 120])


if __name__ == '__main__':
    unittest.main()
