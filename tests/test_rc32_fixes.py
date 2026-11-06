"""Implementer fixes for the rc32 (owner: "do everything", 2026-11-06), from the tester's rc31 reports (R22-R26) and the
cleanup list of a-faire-implementeur.md."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', (ROOT / path).read_text(encoding='utf-8'), re.M | re.S)
    if not m:
        raise AssertionError((path, name))
    return m.group(0)


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


class BrowserCacheAfterUpdate(unittest.TestCase):
    """R22: busybox httpd sends no Cache-Control; its Last-Modified let Chrome reuse index.html for hours by heuristic
    freshness, so the rc29 interface stayed after the rc31 update. Without Last-Modified every page is revalidated by
    ETag (304), and the stamped assets change URL."""

    def test_no_last_modified_etag_kept(self):
        frag = text('v3/buildroot/board/tc100/busybox.fragment')
        self.assertIn('# CONFIG_FEATURE_HTTPD_LAST_MODIFIED is not set', frag)
        self.assertNotIn('CONFIG_FEATURE_HTTPD_LAST_MODIFIED=y', frag)
        self.assertIn('CONFIG_FEATURE_HTTPD_ETAG=y', frag)
        self.assertIn('CONFIG_FEATURE_HTTPD_GZIP=y', frag)


class MultiviewBusyIsQuiet(unittest.TestCase):
    """R24: live.cgi serves one MP4 viewer; a 503 in Multi-view goes back to the still pictures without a warning."""

    def test_503_handled(self):
        html = text('www/multiview.html')
        self.assertIn('if (res.status === 503) { var busy = new Error("busy"); busy.busy = true; throw busy; }', html)
        self.assertIn('if (e && e.busy) {', html)
        self.assertIn('"The smooth video is already open elsewhere (one viewer at a time).":', text('www/i18n/fr.js'))


class MqttDiagReadsTc100Rtsp(unittest.TestCase):
    """The MQTT diag read the 2.x lite server's /var/run/tc100rtsp (absent on 3.0): clients came from /proc/net/tcp (TCP
    only) and drops were always 0. It reads tc100_rtsp's own /var/run/tc100_rtsp.stat now."""

    def test_reads_the_stat_file(self):
        src = text('scripts/mqtt-bridge.sh')
        i = src.index('  _dg_rc=null; _dg_rd=null\n')
        block = src[i:src.index('  # Why the camera last started', i)]
        self.assertNotIn('/var/run/tc100rtsp ', block)
        with tempfile.TemporaryDirectory() as t:
            st = Path(t, 'stat')
            st.write_text('interval_s 5\ncaptured 125\nmain_bytes 800000\nsub_bytes 90000\nclients 3\ndropped 7\n')
            code = block.replace('/var/run/tc100_rtsp.stat', str(st)).replace('/proc/net/tcp', str(Path(t, 'none')))
            r = subprocess.run(SH + ['-c', code + '\necho "$_dg_rc $_dg_rd"'], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.stdout.strip(), '3 7', r.stderr)
        self.assertIn('wfile("/var/run/tc100_rtsp.stat"', text('src/tc100rtsp/tc100_rtsp.c'))


class RefusedCardNeverReadWrite(unittest.TestCase):
    """R25 (IPCAM1, rc31): a refused card stayed mounted read-write. The card is mounted read-only first, switched to
    read-write only when it has no boot file; one caller at a time (lock)."""

    def run_mount(self, t, boot_file, parallel=1):
        t = Path(t)
        mnt = t / 'sd'; mnt.mkdir()
        card = t / 'card'; card.mkdir()
        if boot_file:
            (card / boot_file).mkdir()
        (t / 'mounts').write_text('')
        dev = t / 'mmcblk0p1'
        log = t / 'log'
        stubs = f"""
mount() {{
  echo "mount $*" >> {log}
  case "$*" in
    *remount,rw*) sed -i "s| {mnt} vfat ro| {mnt} vfat rw|" {t}/mounts; return 0 ;;
    *remount,ro*) sed -i "s| {mnt} vfat rw| {mnt} vfat ro|" {t}/mounts; return 0 ;;
    *"-t vfat -o ro"*) sleep 0.2; cp -r {card}/. {mnt}/; echo "{dev} {mnt} vfat ro 0 0" >> {t}/mounts; return 0 ;;
    *"-t tmpfs"*) return 0 ;;
  esac
  return 1
}}
umount() {{ echo "umount $*" >> {log}; rm -rf {mnt}/*; : > {t}/mounts; return 0; }}
logger() {{ :; }}
"""
        rs = text('scripts/rec-storage.sh')
        fns = '\n'.join(function('scripts/rec-storage.sh', n) for n in
                        ('_boot_file', '_mounted', '_refuse_card', '_mount_card_locked', '_mount_card'))
        fns = fns.replace('[ -b "$_d" ] || continue', '[ -e "$_d" ] || continue')
        head = re.search(r'(?m)^SD_BOOT_FILES=.*$', rs).group(0)
        code = (stubs + head + f'\nL66=1; MNT_SD={mnt}; DEVS={dev}; PROC_MOUNTS={t}/mounts; REC_LOCK={t}/lock; '
                f'REC_DIAG_STATUS={t}/diag\n_placeholder() {{ :; }}\n' + fns)
        dev.write_text('')
        runs = ' '.join(['( _mount_card; echo "rc=$?" >> ' + str(t / 'rcs') + ' ) &'] * parallel) + ' wait'
        r = subprocess.run(SH + ['-c', code + '\n' + runs], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (log.read_text() if log.exists() else ''), (t / 'mounts').read_text(), (t / 'rcs').read_text()

    def test_boot_card_never_mounted_read_write(self):
        with tempfile.TemporaryDirectory() as t:
            log, mounts, rcs = self.run_mount(t, 'wifitest', parallel=2)
            self.assertNotIn('remount,rw', log)
            self.assertNotIn(' rw', mounts)
            self.assertNotIn('rc=0', rcs)

    def test_clean_card_ends_read_write(self):
        with tempfile.TemporaryDirectory() as t:
            log, mounts, rcs = self.run_mount(t, None, parallel=2)
            self.assertIn('vfat rw', mounts)
            self.assertEqual(log.count('-t vfat -o ro'), 1)             # the second caller found it mounted
            self.assertEqual(rcs.count('rc=0'), 2)


class StaleUpdatePackage(unittest.TestCase):
    """R26 (IPCAM1, rc31): a package left on the card by an earlier session (rc28) was shown as staged and could be
    installed. Staged = uploaded since the camera started (RAM mark); an older version needs a confirmation."""

    def ver_older(self, a, b):
        fn = function('www/cgi-bin/update.cgi', 'ver_older')
        return subprocess.run(SH + ['-c', fn + '\nver_older "$1" "$2"', '_', a, b], timeout=10).returncode == 0

    def test_version_order(self):
        self.assertTrue(self.ver_older('3.0.1-rc28', '3.0.1-rc31'))
        self.assertTrue(self.ver_older('3.0.1-rc9', '3.0.1-rc10'))
        self.assertTrue(self.ver_older('3.0.1-rc31', '3.0.1'))
        self.assertTrue(self.ver_older('3.0.0', '3.0.1-rc1'))
        self.assertFalse(self.ver_older('3.0.1-rc31', '3.0.1-rc31-dev'))
        self.assertFalse(self.ver_older('3.0.1-rc32', '3.0.1-rc31'))
        self.assertFalse(self.ver_older('3.0.1', '3.0.1'))

    def test_staged_needs_the_ram_mark_and_older_needs_a_confirmation(self):
        cgi = text('www/cgi-bin/update.cgi')
        self.assertIn('staged_ok() { [ -f "$WORK/ok" ] && [ -f "$WORK/VERSION" ] && [ "$(cat "$STAGED_MARK" 2>/dev/null)" = "$WORK" ]; }', cgi)
        self.assertIn('STAGED_MARK=${UPDATE_STAGED_MARK:-/tmp/update66.staged}', cgi)
        self.assertIn('elif staged_ok; then st=staged', cgi)
        install = cgi[cgi.index('POST:install)'):cgi.index('POST:discard)')]
        self.assertTrue(install.lstrip().startswith('POST:install)\n\tstaged_ok ||'))
        self.assertLess(install.index('"error":"older"'), install.index(': > /tmp/update66.running'))
        self.assertIn('*"&older=1&"*)', install)
        html = text('www/settings.html')
        self.assertIn("(d.error === 'older' && extra.indexOf('&older=1') < 0 && '&older=1')", html)


class No2xStoragePaths(unittest.TestCase):
    """Nothing on 3.0 writes /tmp/tc100-storage (2.x): the /etc/jffs2 branches behind it were dead (the rescue Wi-Fi
    password, the reboot history, the Wi-Fi settings and the MQTT diag); /mnt/config is the one place."""

    def test_gone(self):
        for rel in ('scripts/wifi-rescue.sh', 'scripts/reboot-tracker.sh', 'scripts/mqtt-bridge.sh'):
            code = re.sub(r'(?m)^\s*#.*$', '', text(rel))
            self.assertNotIn('/etc/jffs2', code, rel)
        self.assertIn('echo "${WR_PSK_FILE:-/mnt/config/wifi_rescue.psk}"', text('scripts/wifi-rescue.sh'))
        self.assertNotIn('/etc/jffs2/tc100/wpa_supplicant.conf', text('scripts/action.d/network.sh'))
        self.assertFalse((ROOT / 'www/cgi-bin/clip_thumb.cgi').exists())     # ffmpeg-based, not on 3.0


if __name__ == '__main__':
    unittest.main()
