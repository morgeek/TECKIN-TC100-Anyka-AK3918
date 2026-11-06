"""R20, the rest after the rc30 (web UI audit docs/linux-port/webui-audit-2026-11-06.md): D1-D6 (one control plus a link or
an explanation at the other place), U2, U4 (boot.conf keys without a reader: commented out once, never deleted), U5-U9.
Static wiring of the pages and, where a script is involved, a run under busybox ash with fixtures."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def tab(html, tab_id):
    i = html.index('id="%s"' % tab_id)
    m = re.search(r'\n        <!-- [A-Za-z/ ]+ -->\n        <div class="tab-content', html[i:])
    return html[i:i + m.start()] if m else html[i:]


SETTINGS = read('www/settings.html')
FR = read('www/i18n/fr.js')


class Duplicates(unittest.TestCase):
    def test_d1_day_night_controls_only_under_the_live_picture(self):
        dn = tab(SETTINGS, 'tab-daynight')
        self.assertNotIn('data-cam-panel', dn)
        self.assertNotIn('data-cam-mode', dn)
        self.assertNotIn('data-cam-control', dn)
        self.assertIn('data-home-view="live"', dn)            # the link to the controls
        self.assertIn('id="formDayNight"', dn)                # the thresholds stay
        index = read('www/index.html')
        for c in ('auto', 'day', 'night'):
            self.assertIn('data-cam-mode="%s"' % c, index)
        for c in ('ir-led', 'ir-cut', 'black-white'):
            self.assertIn('data-cam-control="%s"' % c, index)
        self.assertNotIn("EliteUI.initCamPanel", SETTINGS)

    def test_d2_leds_say_start_up_state(self):
        self.assertIn('LEDs at start-up', SETTINGS)
        self.assertIn('every time the camera starts', SETTINGS)
        self.assertIn('id="formLeds"', SETTINGS)
        self.assertIn('data-cam-control="front-led"', read('www/index.html'))        # the live buttons stay

    def test_d3_one_reboot(self):
        self.assertNotIn('btnReboot', SETTINGS)
        self.assertNotIn('Hard Reboot', SETTINGS)
        self.assertNotIn('btnReboot', read('src/webui/index/95-settings-page.js'))
        index = read('www/index.html')
        self.assertEqual(index.count('cmd=reboot'), 1)                                # Tools -> Reboot
        self.assertIn('Tools, then Reboot', SETTINGS)
        self.assertRegex(read('scripts/action.d/system.sh'), r'(?m)^\s*reboot\)|\|reboot\|')

    def test_d4_four_mechanisms_kept_and_explained(self):
        b = tab(SETTINGS, 'tab-backup')
        guide = b[b.index('Which one to use?'):b.index('Presets and restore point')]
        for word in ('Full backup', 'JSON exchange', 'Presets', 'Restore point'):
            self.assertIn('<strong>%s</strong>' % word, guide)
        self.assertEqual(guide.count('<li>'), 4)
        order = [guide.index('<strong>%s</strong>' % w) for w in ('Full backup', 'JSON exchange', 'Presets', 'Restore point')]
        self.assertEqual(order, sorted(order))                                        # whole camera first
        # nothing deleted: restore point, presets (load, save, export, import) and the two cards of backup.html
        for i in ('save_known_good_profile', 'restore_known_good_profile', 'btn_load_preset', 'btn_save_preset',
                  'btn_export_config', 'btn_import_config', 'btn_refresh_presets', 'backup_slot'):
            self.assertIn(i, b)
        bk = read('www/backup.html')
        for i in ('json_export_btn', 'archive_download_btn', 'archive_restore_btn', 'cmd=push'):
            self.assertIn(i, bk)
        # the preset export/import is NOT a duplicate of the JSON exchange: it captures the form values in the browser
        js = read('src/webui/index/95-settings-page.js')
        self.assertIn('captureCurrentConfig()', js[js.index('btnExportConfig.onclick'):])
        self.assertNotIn('config_exchange', js)
        self.assertIn('Export current and Import file only handle', b)

    def test_d5_services_page_says_stop_turns_the_setting_off(self):
        s = read('www/cgi-bin/scripts.cgi')
        self.assertIn('Stop turns that setting off for good', s)
        for name in ('recording', 'syslog-forward', 'memory-guard', 'whep', 'wifi-rescue'):
            self.assertIn(name, s[s.index('Stop turns that setting off for good') - 300:s.index('Stop turns that setting off for good')])
        sw = read('scripts/service-switch.sh')
        for name in ('recording', 'syslog-forward', 'memory-guard', 'whep', 'wifi-rescue', 'mqtt-bridge', 'telegram-bot'):
            self.assertRegex(sw, r'\b%s\)' % name)

    def test_d6_telegram_linked_both_ways(self):
        n = tab(SETTINGS, 'tab-notify')
        self.assertRegex(n, r'data-goto-tab="tab-integrations" data-goto-focus="telegram_token"')
        i = tab(SETTINGS, 'tab-integrations')
        self.assertRegex(i, r'data-goto-tab="tab-notify" data-goto-focus="telegram_notify_enable"')
        for field in ('telegram_notify_enable', 'telegram_token', 'telegram_chat_id', 'telegram_enable'):
            self.assertIn('id="%s"' % field, SETTINGS)                                # every control stays
        # the handler that follows the links
        self.assertIn("closest('[data-goto-tab]')", SETTINGS)


class Useless(unittest.TestCase):
    def test_u2_no_clear_cache_button_command_kept(self):
        self.assertNotIn('btnFreeRam', SETTINGS)
        self.assertNotIn('btnFreeRam', read('src/webui/index/95-settings-page.js'))
        self.assertNotIn('Clear Page Cache', SETTINGS)
        self.assertRegex(read('scripts/action.d/system.sh'), r'(?m)^\s*clear_mem\)')  # still usable from a script

    def test_u5_entity_count_is_measured(self):
        self.assertNotIn('25+ Discovery Nodes', SETTINGS)
        self.assertIn('id="ha_discovery_count"', SETTINGS)
        self.assertIn('cmd=ha_discovery_info', SETTINGS)
        a = read('www/cgi-bin/action.cgi')
        self.assertRegex(a, r'(?m)^\s*refresh_ha_discovery\|ha_discovery_info\|set_mqtt_config')
        self.assertIn('|ha_discovery_info) ;;', a)                                    # read-only: no CSRF token needed

    def test_u5_handler_counts_the_records_with_a_payload(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            fake = d / 'mqttd'
            # the daemon's -D file: P<retain><topic> NUL <payload> NUL; two entities and one removal (empty payload)
            fake.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -D ] && out=$2; shift; done\n'
                            'printf "P1ha/sensor/n/cpu/config\\0{\\"a\\":1}\\0P1ha/sensor/n/old/config\\0\\0'
                            'P1ha/switch/n/ir/config\\0{\\"b\\":2}\\0" > "$out"\n')
            fake.chmod(0o755)
            (d / 'bridge.sh').write_text('#!/bin/sh\n')
            code = 'F_cmd=ha_discovery_info; . "%s/scripts/action.d/integrations.sh"' % ROOT.as_posix()
            env = {'PATH': '/usr/bin:/bin', 'TC100_MQTTD_BIN': fake.as_posix(), 'TC100_MQTTB_SH': (d / 'bridge.sh').as_posix()}
            r = subprocess.run(SH + ['-c', code], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.stdout.strip(), '{"status":"success","count":2}', r.stderr)
            # no daemon: -1, and the page shows "--"
            env['TC100_MQTTD_BIN'] = (d / 'missing').as_posix()
            r = subprocess.run(SH + ['-c', code], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.stdout.strip(), '{"status":"success","count":-1}')

    def test_u6_wifi_scan_signal_in_dbm_without_decimals(self):
        n = read('scripts/action.d/network.sh')
        self.assertIn('<th>Signal (dBm)</th>', n)
        self.assertNotIn('<th>Quality</th>', n)
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            iw = d / 'iw'
            iw.write_text('#!/bin/sh\nprintf "BSS aa:bb:cc:dd:ee:ff(on wlan0)\\n\\tsignal: -54.00 dBm\\n\\tSSID: Home\\n\\tRSN:\\t * Version: 1\\n"\n')
            iw.chmod(0o755)
            code = 'wants_json_response() { return 1; }; F_cmd=wifi_scan; . "%s/scripts/action.d/network.sh"' % ROOT.as_posix()
            r = subprocess.run(SH + ['-c', code], env={'PATH': '%s:/usr/bin:/bin' % d.as_posix()}, capture_output=True, text=True, timeout=60)
            if 'Signal (dBm)' not in r.stdout:
                self.skipTest('no usable awk/iw stand-in here: ' + r.stdout + r.stderr)
            self.assertIn('<td>Home</td><td>-54</td><td>Yes</td>', r.stdout)
            self.assertNotIn('-54.00', r.stdout)

    def test_u7_web_server_age_is_the_one_of_httpfront(self):
        s = read('www/cgi-bin/scripts.cgi')
        i = s.index('    web-server)\n      # R20-U7')
        branch = s[i:s.index('*) return 1', i)]
        self.assertIn('*"(httpfront)"*) _ft_on=1; _ft_pid="${_ft_p#/proc/}"; _ft_fb=""; break', branch)
        self.assertIn('*"(httpd)"*) [ -n "$_ft_fb" ] || _ft_fb=', branch)              # httpd only as the fallback
        self.assertNotIn('*"(httpd)"*|*"(httpfront)"*', branch)
        self.assertIn('_svc_pid_uptime "$_ft_pid"', s)
        # the slow path takes the pid of httpfront from the status of the control script
        self.assertIn('pidof httpfront', read('controlscripts/web-server'))

    def test_u8_only_the_thresholds_of_the_selected_method(self):
        dn = tab(SETTINGS, 'tab-daynight')
        for field, method in (('daynightlum', 'luma'), ('nightdaylum', 'luma'), ('ae_night_above', 'ae'), ('ae_day_below', 'ae')):
            self.assertRegex(dn, r'<div class="field" data-dn-method="%s"><label class="label is-small" for="%s"' % (method, field))
        self.assertRegex(dn, r'<div class="columns" data-dn-method="vendor">\s*<div class="column is-half"><div class="field"><label class="label is-small" for="dn_vendor_night"')
        for field in ('dn_night_hold', 'dn_day_hold'):                                 # hold times belong to every method
            self.assertNotRegex(dn, r'data-dn-method="[a-z]+"><label class="label is-small" for="%s"' % field)
        for v in ('luma', 'ae', 'isp', 'vendor'):
            self.assertIn('<option value="%s">' % v, dn)
        js = read('src/webui/index/80-camera-controls.js')
        self.assertIn('function dayNightMethodFields()', js)
        self.assertIn('el.getAttribute("data-dn-method") !== sel.value', js)
        self.assertIn('addEventListener("change", dayNightMethodFields)', js)
        self.assertIn('dayNightMethodFields();', js[js.index('put("dn_source", d.source);'):])   # after the saved value is put
        self.assertIn('function dayNightMethodFields()', read('www/scripts/index.bundle.min.js'))
        # hidden, not removed: the form still posts every threshold
        self.assertNotIn('disabled', dn[dn.index('data-dn-method="luma"'):dn.index('data-dn-method="luma"') + 200])

    def test_u9_default_password_alert_links_to_the_password_form(self):
        warn = SETTINGS[SETTINGS.index('id="security_warning"'):SETTINGS.index('settings-layout')]
        self.assertIn('data-goto-tab="tab-system" data-goto-focus="all_password"', warn)
        self.assertIn('id="all_password"', tab(SETTINGS, 'tab-system'))
        self.assertIn('id="formPassword"', tab(SETTINGS, 'tab-system'))


class UnusedBootConfKeys(unittest.TestCase):
    SCRIPT = ROOT / 'scripts/migrate-rc32-unused-keys.sh'
    EXACT = ('WEB_MODE', 'ULTRALITE_HTTP_PORT', 'UI_ULTRALITE_MODE', 'LIGHTWEIGHT_MODE', 'RTSP_SERVER', 'RTSP_VENDOR_PORT',
             'RTSP_FPS_LOCK', 'FIRMWARE_IMAGE', 'TAMPER_DETECTION')
    PREFIX = ('CPU_SCALER_', 'RTSP_PROC_', 'STORAGE_CLEANUP_')
    # the places that mention a key without acting on it: reports / exports it, or only checks its value when imported
    ALLOWED = {
        'LIGHTWEIGHT_MODE': {'www/cgi-bin/state.cgi', 'www/cgi-bin/config_exchange.cgi'},
        'RTSP_FPS_LOCK': {'scripts/config-transaction.sh'},
    }

    def sources(self):
        skip_dirs = {'.git', 'docs', 'tests', 'css', 'mock', 'node_modules', 'i18n'}
        for p in ROOT.rglob('*'):
            rel = p.relative_to(ROOT)
            if not p.is_file() or set(rel.parts) & skip_dirs or rel.name in ('CHANGELOG.md', 'migrate-rc32-unused-keys.sh'):
                continue
            if p.suffix in ('.png', '.jpg', '.gz', '.so', '.sqfs', '.bin', '.wav', '.ico', '.woff', '.woff2', '.pdf'):
                continue
            try:
                yield rel.as_posix(), p.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue

    def test_nothing_reads_these_keys_on_3_0(self):
        pats = {k: re.compile(r'(?<![A-Za-z0-9_])%s(?![A-Za-z0-9])' % k) for k in self.EXACT}
        pats.update({k: re.compile(r'(?<![A-Za-z0-9_])%s' % k) for k in self.PREFIX})
        pats['RTSP_LITE_(not TALK)'] = re.compile(r'(?<![A-Za-z0-9_])RTSP_LITE_(?!TALK)')
        pats['TAMPER_DETECTION'] = re.compile(r'(?<![A-Za-z0-9_])TAMPER_DETECTION')
        found = {}
        for rel, text in self.sources():
            for k, pat in pats.items():
                if pat.search(text) and rel not in self.ALLOWED.get(k, ()):
                    found.setdefault(k, []).append(rel)
        self.assertEqual(found, {}, 'a key of the migration list has a reader')
        # and the exceptions only report the key / check its value: no shell code reads it into a variable
        for k, files in self.ALLOWED.items():
            for rel in files:
                for line in read(rel).splitlines():
                    if k in line:
                        self.assertNotRegex(line, r'BC_%s|\$%s\b|\$\{%s' % (k, k, k), (rel, line))

    def test_the_dist_file_holds_none_of_them(self):
        dist = read('config/boot.conf.dist')
        for k in self.EXACT:
            self.assertNotRegex(dist, r'(?m)^#?\s*%s=' % k)
        for k in self.PREFIX:
            self.assertNotRegex(dist, r'(?m)^#?\s*%s' % k)
        self.assertIn('\nRTSP_LITE_TALK=1\n', dist)             # read by tc100_rtsp, onvifd and Settings: stays

    def test_called_at_boot_before_boot_conf_is_read(self):
        a = read('v3/autorun-linux66.sh')
        self.assertIn('sh /mnt/scripts/migrate-rc32-unused-keys.sh </dev/null', a)
        self.assertLess(a.index('migrate-rc28-defaults.sh'), a.index('migrate-rc32-unused-keys.sh'))
        self.assertLess(a.index('migrate-rc32-unused-keys.sh'), a.index('BC_$_k'))
        self.assertNotIn('BC_LIGHTWEIGHT_MODE', a)

    def run_migration(self, c):
        return subprocess.run(SH + [str(self.SCRIPT)], env={'MU_CONF_DIR': str(c), 'PATH': '/usr/bin:/bin'},
                              capture_output=True, text=True, timeout=60)

    def test_migration_comments_out_once_and_logs(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            boot = ('# Boot settings\nNET_GUARD=1\nWEB_MODE=https\nULTRALITE_HTTP_PORT="8080"\nUI_ULTRALITE_MODE=0\n'
                    'LIGHTWEIGHT_MODE=0\nCPU_SCALER_MIN=240\nCPU_SCALER_MAX=\nRTSP_SERVER=lite\nRTSP_VENDOR_PORT=8554\n'
                    'RTSP_LITE_PORT=554\nRTSP_LITE_TALK=1\nRTSP_PROC_NICE=-5\nRTSP_FPS_LOCK=1\nFIRMWARE_IMAGE=/x.img\n'
                    'STORAGE_CLEANUP_DAYS=30\nTAMPER_DETECTION=1\nWHEP=1\nWEB_MODE_X=keep\nREC_LOCAL=1')   # no final newline
            (c / 'boot.conf').write_text(boot)
            r = self.run_migration(c)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = (c / 'boot.conf').read_text().splitlines()
            gone = ['WEB_MODE', 'ULTRALITE_HTTP_PORT', 'UI_ULTRALITE_MODE', 'LIGHTWEIGHT_MODE', 'CPU_SCALER_MIN', 'CPU_SCALER_MAX',
                    'RTSP_SERVER', 'RTSP_VENDOR_PORT', 'RTSP_LITE_PORT', 'RTSP_PROC_NICE', 'RTSP_FPS_LOCK', 'FIRMWARE_IMAGE',
                    'STORAGE_CLEANUP_DAYS', 'TAMPER_DETECTION']
            for k in gone:
                self.assertFalse([l for l in out if l.startswith(k + '=')], k)          # no longer active
                self.assertTrue([l for l in out if l.startswith('#[rc32: unused on 3.0] ' + k + '=')], k)   # kept, commented
            self.assertIn('#[rc32: unused on 3.0] ULTRALITE_HTTP_PORT="8080"', out)      # the value is kept as it was
            for keep in ('# Boot settings', 'NET_GUARD=1', 'RTSP_LITE_TALK=1', 'WHEP=1', 'WEB_MODE_X=keep', 'REC_LOCAL=1'):
                self.assertIn(keep, out)                                                 # everything else untouched
            self.assertEqual(len(out), len(boot.splitlines()))                           # no line lost
            log = (c / 'migrations.log').read_text().splitlines()
            self.assertEqual(len(log), len(gone))
            self.assertTrue(all('boot.conf: commented out ' in l for l in log))
            self.assertTrue((c / '.migrated-rc32-unused-keys').exists())
            # a key put back by the owner after the migration stays: it runs once
            (c / 'boot.conf').write_text('\n'.join(out) + '\nWEB_MODE=back\n')
            self.run_migration(c)
            self.assertIn('\nWEB_MODE=back\n', (c / 'boot.conf').read_text())
            self.assertEqual(len((c / 'migrations.log').read_text().splitlines()), len(gone))

    def test_migration_without_anything_to_do(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t)
            (c / 'boot.conf').write_text('NET_GUARD=1\nRTSP_LITE_TALK=1\n')
            self.assertEqual(self.run_migration(c).returncode, 0)
            self.assertEqual((c / 'boot.conf').read_text(), 'NET_GUARD=1\nRTSP_LITE_TALK=1\n')
            self.assertFalse((c / 'migrations.log').exists())
            self.assertTrue((c / '.migrated-rc32-unused-keys').exists())
        with tempfile.TemporaryDirectory() as t:                                         # no boot.conf at all
            c = Path(t)
            self.assertEqual(self.run_migration(c).returncode, 0)
            self.assertFalse((c / 'boot.conf').exists())
        self.assertEqual(self.run_migration(Path('/nonexistent-dir-r20')).returncode, 0)


class Translations(unittest.TestCase):
    def test_every_ui_string_has_its_french(self):
        r = subprocess.run(['python3' if shutil.which('python3') else 'python', str(ROOT / 'src/webui/i18n-strings.py'), '--missing'],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.stdout.strip(), '', 'untranslated strings')
        for s in ('LEDs at start-up', 'Open Alerts, Telegram', 'Open the controls under the live picture',
                  'Entities announced to Home Assistant with the current settings',
                  'Four ways to keep settings, from the whole camera to one setting page:'):
            self.assertIn('"%s":' % s, FR)
        self.assertIn('Stop turns that setting off for good', FR)

    def test_stamps_and_bundle_are_current(self):
        for script in ('stamp-assets.sh', 'build-index.sh'):
            r = subprocess.run(['sh', str(ROOT / 'src/webui' / script), '--check'], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
