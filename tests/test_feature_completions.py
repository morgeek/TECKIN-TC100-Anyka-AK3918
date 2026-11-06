"""Roadmap items completed on 2026-11-05 (docs/linux-port/a-faire-implementeur.md): 20 picture on events over MQTT,
22 full backup / restore (.tar.gz), 26 chime / alert / siren buttons, 27 metrics (video server, card, version,
/metrics), 29 asset stamps so that a browser never keeps an old script after an update."""
import io
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', text(path), re.M | re.S)
    assert m, (path, name)
    return m.group(0)


def tgz(entries):
    """entries: list of (name, bytes or None for a directory, or ('link', target))"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.mtime = int(time.time())
            if data is None:
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            elif isinstance(data, tuple):
                info.type = tarfile.SYMTYPE
                info.linkname = data[1]
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class SoundButtons(unittest.TestCase):

    def test_dashboard_buttons_and_wiring(self):
        index = text('www/index.html')
        # owner 2026-11-06: the Siren button only (chime and alert removed)
        self.assertIn('data-sound="siren"', index)
        self.assertTrue((ROOT / 'sounds/siren.pcm').is_file())
        for name in ('chime', 'alert'):
            self.assertNotIn('data-sound="%s"' % name, index)
        js = text('src/webui/index/70-audio-diagnostics.js')
        self.assertIn('function initSoundButtons()', js)
        self.assertIn('if (name === "siren" && !confirm(', js)
        self.assertIn('csrfFetch("cgi-bin/action.cgi?cmd=play_sound&format=json&sound="', js)
        self.assertIn('initSoundButtons();', text('src/webui/index/90-startup.js'))
        self.assertIn('function initSoundButtons()', text('www/scripts/index.bundle.min.js'))


class Metrics(unittest.TestCase):

    def run_metrics(self, files):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, value in files.items():
                (d / name).write_text(value)
            code = text('www/cgi-bin/metrics.cgi')
            for path, name in (('/var/run/tc100_rtsp.stat', 'stat'), ('/tmp/sd-card', 'sd-card'), ('/mnt/VERSION', 'VERSION')):
                code = code.replace(path, str(d / name))
            r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            body = r.stdout.split('\n\n', 1)[1]                 # text mode reads the header's \r\n as \n
            for line in body.splitlines():
                if line.startswith('#') or not line:
                    continue
                self.assertRegex(line, r'^tc100_[a-z0-9_]+(\{[a-z]+="[^"]*"\})? -?[0-9.]+$', line)
            return dict(l.split(' ', 1) for l in body.splitlines() if l and not l.startswith('#'))

    def test_video_server_card_and_version(self):
        m = self.run_metrics({'stat': 'interval_s 5\ncaptured 125\nmain_bytes 1250000\nsub_bytes 250000\nclients 2\ndropped 7\n',
                              'sd-card': 'present=1\nid=x\nsize_mb=30436\nfs=vfat\nkind=sd\nmounted=1\nfree_mb=1024\nprompt=0\n',
                              'VERSION': '3.0.1-rc26\n'})
        self.assertEqual(m['tc100_rtsp_capture_fps'], '25')
        self.assertEqual(m['tc100_rtsp_main_kbps'], '2000')
        self.assertEqual(m['tc100_rtsp_sub_kbps'], '400')
        self.assertEqual(m['tc100_rtsp_clients_playing'], '2')
        self.assertEqual(m['tc100_rtsp_dropped_frames'], '7')
        self.assertEqual(m['tc100_sdcard_present'], '1')
        self.assertEqual(m['tc100_sdcard_free_bytes'], str(1024 * 1048576))
        self.assertEqual(m['tc100_sdcard_size_bytes'], str(30436 * 1048576))
        self.assertEqual(m['tc100_info{version="3.0.1-rc26"}'], '1')
        self.assertIn('tc100_memory_available_bytes', m)

    def test_no_server_no_card(self):
        m = self.run_metrics({})
        self.assertNotIn('tc100_rtsp_capture_fps', m)                  # no fake values
        self.assertEqual(m['tc100_sdcard_present'], '0')
        self.assertNotIn('tc100_sdcard_free_bytes', m)
        self.assertEqual(m['tc100_info{version="unknown"}'], '1')

    def test_server_writes_the_stat_file_and_metrics_path(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('wfile("/var/run/tc100_rtsp.stat", sb, (size_t)sn);', src)
        self.assertIn('interval_s %ld\\ncaptured %lu\\nmain_bytes %lu\\nsub_bytes %lu\\nclients %d\\ndropped %lu\\n', src)
        hf = text('src/httpfront/httpfront.c')
        self.assertIn('if (pfx(b, "GET /metrics ") || pfx(b, "GET /metrics?") || pfx(b, "HEAD /metrics ")) redirect(c, "/cgi-bin/metrics.cgi");', hf)
        self.assertIn('"HTTP/1.0 302 Found\\r\\nLocation: "', hf)


class AssetStamps(unittest.TestCase):

    def test_stamps_are_current(self):
        r = subprocess.run(['sh', str(ROOT / 'src/webui/stamp-assets.sh'), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_versioned_asset_has_a_hash_stamp(self):
        refs = []
        for f in list((ROOT / 'www').glob('*.html')) + [ROOT / 'www/cgi-bin/wizard.cgi']:
            refs += re.findall(r'([A-Za-z0-9_./-]+\.(?:js|css))\?v=([A-Za-z0-9._-]*)', f.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(refs), 6)
        for path, v in refs:
            self.assertRegex(v, r'^[0-9a-f]{8}$', path)
        self.assertRegex(text('www/scripts/i18n.js'), r'var VERSION = "[0-9a-f]{8}";')
        self.assertIn('sh "$root/src/webui/stamp-assets.sh"', text('src/webui/build-index.sh'))


class SnapshotOnEvent(unittest.TestCase):

    def test_mode_switch_and_callers(self):
        bridge = text('scripts/mqtt-bridge.sh')
        fn = function('scripts/mqtt-bridge.sh', 'snapshot_event_mode')
        self.assertIn('is_truthy_local "$MQTT_SNAPSHOT_ON_EVENT" || exit 0', fn)
        self.assertIn('take_snapshot "$_se_path" || exit 0', fn)
        self.assertIn('mqtt_publish_file "${MQTT_TOPIC_ROOT}/snapshot/image" "$_se_path" 1', fn)
        self.assertIn('[ $((_se_now - _se_last)) -ge "$_se_cd" ] || exit 0', fn)
        self.assertIn('  snapshot-event)\n    snapshot_event_mode "$2"', bridge)
        self.assertIn('if is_truthy_local "$MQTT_HA_CAMERA_ENTITY_ENABLE" || is_truthy_local "$MQTT_SNAPSHOT_ON_EVENT"; then', bridge)
        dist = text('config/mqtt.conf.dist')
        self.assertIn('\nMQTT_SNAPSHOT_ON_EVENT=0\n', dist)
        self.assertIn('\nMQTT_SNAPSHOT_COOLDOWN_SECONDS=10\n', dist)
        for f, kind in (('scripts/motion-event.sh', 'motion'), ('controlscripts/sound-detection', 'sound'),
                        ('scripts/tamper-detect.sh', 'tamper')):
            self.assertIn("grep -q '^MQTT_SNAPSHOT_ON_EVENT=1' /mnt/config/mqtt.conf 2>/dev/null && "
                          "{ /mnt/scripts/mqtt-bridge.sh snapshot-event %s </dev/null >/dev/null 2>&1 & }" % kind, text(f))
        self.assertIn('"MQTT_SNAPSHOT_ON_EVENT";"bool"', text('www/cgi-bin/config_exchange.cgi'))
        self.assertIn('MQTT_SNAPSHOT_ON_EVENT bool', text('scripts/config-transaction.sh'))


class FullBackup(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cfg = self.base / 'config'
        self.cfg.mkdir()
        (self.cfg / 'boot.conf').write_text('BOOT_GUARD=1\nWIFI_COUNTRY=\n')
        (self.cfg / 'hostname.conf').write_text('IPCAM2\n')

    def tearDown(self):
        self.tmp.cleanup()

    def restore(self, body, length=None):
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh')) + '\n'
        code += 'json_body_err() { printf \'{"ok":false,"error":"%s","message":"%s"}\\n\' "$1" "$2"; }\n'
        code += function('www/cgi-bin/config_exchange.cgi', '_ce_restore') + '\n_ce_restore\n'
        env = dict(os.environ, CONFIG_ROOT=str(self.cfg), CONTENT_LENGTH=str(len(body) if length is None else length))
        r = subprocess.run(['/bin/bash', '-c', code], input=body, capture_output=True, timeout=30, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        return json.loads(r.stdout.decode())

    def test_restores_files_and_markers_in_one_transaction(self):
        body = tgz([('config', None), ('config/boot.conf', b'BOOT_GUARD=0\nWIFI_COUNTRY=FR\n'),
                    ('config/motion_zones.conf', b'10,10,50,50\n'), ('config/.wizard3_done', b''),
                    ('config/presets', None), ('config/presets/night.json', b'{"a":1}\n')])
        res = self.restore(body)
        self.assertTrue(res.get('ok'), res)
        self.assertEqual(res['files'], 4)
        self.assertIn('WIFI_COUNTRY=FR', (self.cfg / 'boot.conf').read_text())
        self.assertEqual((self.cfg / 'presets/night.json').read_text(), '{"a":1}\n')
        self.assertTrue((self.cfg / '.wizard3_done').exists())
        self.assertEqual((self.cfg / 'hostname.conf').read_text(), 'IPCAM2\n')     # not in the archive: kept

    def test_refuses_anything_but_plain_config_files(self):
        before = {p.name: p.read_bytes() for p in self.cfg.iterdir()}
        for entries in ([('config/../evil.sh', b'x\n')], [('/etc/passwd', b'x\n')], [('other/boot.conf', b'X=1\n')],
                        [('config/boot.conf', ('link', '/etc/shadow'))], [('config/a b.conf', b'x\n')],
                        [('config/./boot.conf', b'X=1\n')]):
            res = self.restore(tgz(entries))
            self.assertEqual(res.get('error'), 'INVALID_ARCHIVE', entries)
        self.assertEqual(self.restore(b'not a gzip file')['error'], 'INVALID_ARCHIVE')
        self.assertEqual(self.restore(b'', length=0)['error'], 'INVALID_SIZE')
        self.assertEqual(self.restore(b'x', length=300000)['error'], 'INVALID_SIZE')
        self.assertEqual({p.name: p.read_bytes() for p in self.cfg.iterdir()}, before)
        self.assertFalse((self.base / 'evil.sh').exists())

    def test_invalid_file_leaves_everything_unchanged(self):
        before = (self.cfg / 'boot.conf').read_text()
        res = self.restore(tgz([('config/boot.conf', b'BOOT_GUARD=(\n'), ('config/motion_zones.conf', b'1,1,2,2\n')]))
        self.assertEqual(res.get('error'), 'TRANSACTION_FAILED', res)
        self.assertEqual((self.cfg / 'boot.conf').read_text(), before)
        self.assertFalse((self.cfg / 'motion_zones.conf').exists())

    def test_cfg_persist_archive_holds_only_what_changed(self):
        defaults = self.base / 'defaults'
        defaults.mkdir()
        (defaults / 'hostname.conf').write_text('IPCAM2\n')                     # unchanged shipped default: left out
        (self.cfg / 'mqtt.conf.dist').write_text('MQTT_ENABLE=0\n')            # .dist: left out
        env = dict(os.environ, CFG=str(self.cfg), DEFAULTS=str(defaults))
        r = subprocess.run(['sh', str(ROOT / 'v3/linux66-sd/cfg-persist'), 'archive'], capture_output=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        with tarfile.open(fileobj=io.BytesIO(r.stdout), mode='r:gz') as t:
            self.assertEqual(sorted(t.getnames()), ['config/boot.conf'])
        # and the restore takes that archive as it is
        self.assertTrue(self.restore(r.stdout).get('ok'))
        (self.cfg / 'boot.conf').unlink()
        r = subprocess.run(['sh', str(ROOT / 'v3/linux66-sd/cfg-persist'), 'archive'], capture_output=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 3)                                       # nothing differs from the defaults

    def test_backup_page_and_commands(self):
        page = text('www/backup.html')
        self.assertIn('href="cgi-bin/config_exchange.cgi?cmd=archive"', page)
        self.assertIn("fetch('cgi-bin/config_exchange.cgi?cmd=restore', { method: 'POST', headers: headers, body: file", page)
        ce = text('www/cgi-bin/config_exchange.cgi')
        self.assertIn('  restore)\n    mutation_guard\n', ce)
        self.assertIn('if sh /mnt/v3/linux66-sd/cfg-persist archive > "$_ce_ar"', ce)


if __name__ == '__main__':
    unittest.main()
