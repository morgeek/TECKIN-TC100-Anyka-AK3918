"""Item 48: the speaker's sounds. Custom clips on the SD card (www/cgi-bin/sounds.cgi) come before the built-in
ones of the same name everywhere (sound_path in scripts/common_functions.sh: dashboard, MQTT, startup)."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


def sound_path_code():
    s = text('scripts/common_functions.sh')
    return s[s.index('SOUNDS_SD=/mnt/sd/tc100-3/sounds'):]


class Sounds(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp())
        self.flash = self.t / 'flash'; self.flash.mkdir()
        self.sd = self.t / 'sd'
        self.conf = self.t / 'boot.conf'
        for n, size in (('chime', 16800), ('startup_complete', 6400), ('test-1k-m6', 48000)):
            (self.flash / (n + '.pcm')).write_bytes(b'\0' * size)

    def tearDown(self):
        shutil.rmtree(self.t)

    def common(self):
        return sound_path_code().replace('SOUNDS_SD=/mnt/sd/tc100-3/sounds', 'SOUNDS_SD=%s' % self.sd.as_posix()) \
            .replace('/mnt/sounds/', self.flash.as_posix() + '/')

    def cgi(self, cmd, name='', body=b'', sd=True):
        s = text('www/cgi-bin/sounds.cgi')
        s = s[s.index('MAX_BYTES='):].replace('/mnt/config/boot.conf', self.conf.as_posix()) \
            .replace('/mnt/sounds/', self.flash.as_posix() + '/') \
            .replace("grep -qE ' /mnt/sd (vfat|exfat) ' /proc/mounts 2>/dev/null", 'true' if sd else 'false') \
            .replace('${SOUNDS_TMP:-/tmp}', self.t.as_posix()) \
            .replace('sh /mnt/scripts/speaker-play.sh', 'echo played >%s/played; :' % self.t.as_posix())
        stubs = '''mutation_guard() { :; }
rate_limit_check() { :; }
audit_log_event() { :; }
install_config() { [ -f "$1" ] || : > "$1"; }
rewrite_config() { if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi; }
'''
        env = dict(os.environ, F_cmd=cmd, F_name=name, CONTENT_LENGTH=str(len(body)), REQUEST_METHOD='POST')
        r = subprocess.run(SH + ['-c', stubs + self.common() + s], input=body, capture_output=True, env=env)
        out = r.stdout.decode()
        status = out.split('\n', 1)[0].split(' ', 1)[1]
        return status, json.loads(out.split('\n\n', 1)[1])

    def test_sound_path_prefers_the_card(self):
        code = self.common() + 'sound_path "$1"'
        run = lambda n: subprocess.run(SH + ['-c', code, '_', n], capture_output=True, text=True)
        r = run('chime')
        self.assertEqual((r.returncode, r.stdout.strip()), (0, (self.flash / 'chime.pcm').as_posix()))
        self.sd.mkdir(); (self.sd / 'chime.pcm').write_bytes(b'\1\0')
        self.assertEqual(run('chime').stdout.strip(), (self.sd / 'chime.pcm').as_posix())
        self.assertNotEqual(run('../chime').returncode, 0)
        self.assertNotEqual(run('nothing').returncode, 0)

    def test_list_upload_delete_boot(self):
        self.conf.write_text('BOOT_SOUND=1\n')
        st, d = self.cgi('list')
        self.assertEqual(st, '200 OK')
        self.assertEqual(d, {'ok': True, 'sd': True, 'boot': {'on': 1, 'name': 'startup_complete'}, 'sounds': [
            {'name': 'chime', 'builtin': 1, 'custom': 0, 'bytes': 16800},
            {'name': 'startup_complete', 'builtin': 1, 'custom': 0, 'bytes': 6400}]})
        st, d = self.cgi('upload', 'chime', b'\1\0' * 100)
        self.assertEqual((st, d['ok']), ('200 OK', True))
        st, d = self.cgi('upload', 'door_bell', b'\1\0' * 50)
        self.assertEqual(d['ok'], True)
        self.assertEqual(sorted(p.name for p in self.sd.iterdir()), ['chime.pcm', 'door_bell.pcm'])   # no .part left
        st, d = self.cgi('list')
        self.assertEqual(d['sounds'], [
            {'name': 'chime', 'builtin': 1, 'custom': 1, 'bytes': 200},
            {'name': 'startup_complete', 'builtin': 1, 'custom': 0, 'bytes': 6400},
            {'name': 'door_bell', 'builtin': 0, 'custom': 1, 'bytes': 100}])
        self.assertEqual(self.cgi('upload', 'x', b'\1')[0], '400 Bad Request')                  # odd length
        self.assertEqual(self.cgi('upload', 'x', b'\0' * 480002)[0], '413 Payload Too Large')
        self.assertEqual(self.cgi('upload', 'a/b', b'\0\0')[0], '400 Bad Request')
        self.assertEqual(self.cgi('upload', 'a' * 33, b'\0\0')[0], '400 Bad Request')
        self.assertEqual(self.cgi('upload', 'x', b'\0\0', sd=False)[0], '409 Conflict')
        st, d = self.cgi('boot', 'door_bell')
        self.assertEqual(d['ok'], True)
        self.assertEqual(self.cgi('list')[1]['boot'], {'on': 1, 'name': 'door_bell'})
        self.assertEqual(self.cgi('boot', 'nothing')[0], '404 Not Found')
        self.cgi('boot', '0')
        self.assertEqual(self.cgi('list')[1]['boot'], {'on': 0, 'name': 'door_bell'})
        self.assertEqual(self.cgi('play', 'door_bell')[1]['ok'], True)
        self.assertEqual(self.cgi('delete', 'startup_complete')[0], '404 Not Found')          # built-in: kept
        self.assertEqual(self.cgi('delete', 'chime')[1]['ok'], True)
        self.assertEqual([s['custom'] for s in self.cgi('list')[1]['sounds'] if s['name'] == 'chime'], [0])

    def test_callers_use_sound_path(self):
        self.assertIn('_snd_file="$(sound_path "$_snd_name")"', text('scripts/action.d/audio.sh'))
        self.assertIn('_snd_path="$(sound_path "$_snd_to_play")"', text('scripts/mqtt-bridge.sh'))
        a = text('v3/autorun-linux66.sh')
        self.assertIn('"/mnt/sd/tc100-3/sounds/$BC_BOOT_SOUND_NAME.pcm" "/mnt/sounds/$BC_BOOT_SOUND_NAME.alaw" '
                      '"/mnt/sounds/$BC_BOOT_SOUND_NAME.pcm"', a)
        self.assertIn('sh /mnt/scripts/speaker-play.sh "$_bs" 60', a)
        self.assertIn('BOOT_SOUND_NAME=startup_complete', text('config/boot.conf.dist'))
        self.assertIn('tc_check_flat "$_tc_file" BOOT_SOUND_NAME identifier', text('scripts/config-transaction.sh'))
        cgi = text('www/cgi-bin/sounds.cgi')
        self.assertIn('upload|delete|play|boot|playnow) mutation_guard;', cgi)

    def test_card_is_a_real_file_system(self):
        # the RAM placeholder (tmpfs, 16 KiB) on /mnt/sd without a card is not a card: uploads went there and failed
        self.assertIn("sd_ok() { grep -qE ' /mnt/sd (vfat|exfat) ' /proc/mounts 2>/dev/null; }",
                      text('www/cgi-bin/sounds.cgi'))

    def test_playnow_without_a_card(self):
        # owner, 2026-11-06: no card on the cameras; a sound is played once from RAM, then deleted, never kept
        import time
        st, d = self.cgi('playnow', '', b'\1\0' * 400, sd=False)
        self.assertEqual((st, d), ('200 OK', {'ok': True, 'kept': False, 'bytes': 800}))
        for _ in range(50):
            if (self.t / 'played').exists() and not list(self.t.glob('sound-now.*')):
                break
            time.sleep(0.1)
        self.assertTrue((self.t / 'played').exists())
        self.assertEqual(list(self.t.glob('sound-now.*')), [])            # deleted after playing
        self.assertFalse(self.sd.exists())                                 # nothing written for the card
        self.assertEqual(self.cgi('playnow', '', b'\1', sd=False)[0], '400 Bad Request')
        self.assertEqual(self.cgi('playnow', '', b'\0' * 480002, sd=False)[0], '413 Payload Too Large')

    def test_settings_page_offers_play_now(self):
        html = text('www/settings.html')
        self.assertIn('id="sounds_now"', html)
        self.assertIn("'cmd=playnow'", html)
        self.assertNotIn('id="sounds_upload_box" class="mt-3" style="display:none"', html)


class BuiltInClipsAlaw(unittest.TestCase):
    """Audit 2026-11-06 S7 (owner): the built-in clips of the flash image are G.711 A-law (half the size); every reader
    takes them: speaker-play.sh, sound_path, the list of sounds.cgi, the startup sound, the audio test."""

    def test_codec_is_g711(self):
        import importlib.util, struct, sys
        # no __pycache__ in scripts/: the flash image tests read every file of that folder
        old, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            spec = importlib.util.spec_from_file_location('pcm2alaw', ROOT / 'scripts/pcm2alaw.py')
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        finally:
            sys.dont_write_bytecode = old
        # G.711 A-law reference values (silence, the largest values, the smallest steps)
        self.assertEqual([m.linear2alaw(v) for v in (0, -1, 32767, -32768, 8, -9)], [0xD5, 0x55, 0xAA, 0x2A, 0xD5, 0x55])
        for v in range(-32768, 32768, 37):          # round trip within the A-law step of the segment
            r = m.alaw2linear(m.linear2alaw(v))
            self.assertLessEqual(abs(r - v), max(16, abs(v) // 16), v)
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'chime.pcm').write_bytes(struct.pack('<4h', 0, 1000, -1000, 32767))
            Path(t, 'test-1k-m6.pcm').write_bytes(b'\0\0')
            m.main(t)
            self.assertEqual(sorted(os.listdir(t)), ['chime.alaw', 'test-1k-m6.pcm'])
            self.assertEqual(len(Path(t, 'chime.alaw').read_bytes()), 4)

    def test_readers_take_alaw(self):
        self.assertIn('*.alaw) aplay -q -D plughw:0,0 -t raw -f A_LAW -r 8000 -c 1 "$F" ;;', text('scripts/speaker-play.sh'))
        self.assertIn('"$SOUNDS_SD/$1.pcm" "/mnt/sounds/$1.alaw" "/mnt/sounds/$1.pcm"', text('scripts/common_functions.sh'))
        self.assertIn('/mnt/sounds/chime.alaw', text('www/cgi-bin/action.cgi'))
        self.assertIn('python3 scripts/pcm2alaw.py "$T/sounds"', text('v3/build-stack.sh'))
        self.assertIn('alsa', text('v3/buildroot/configs/tc100_defconfig').lower())
        self.assertRegex(text('v3/buildroot/configs/tc100_defconfig'), r'BR2_PACKAGE_ALSA_LIB_PCM_PLUGINS="[^"]*\balaw\b')


class SoundsListAlaw(Sounds):
    def setUp(self):
        super().setUp()
        (self.flash / 'chime.pcm').unlink()
        (self.flash / 'chime.alaw').write_bytes(b'\xd5' * 8400)     # 1.05 s of A-law: 16800 bytes as 16-bit

    def test_list_reports_16_bit_bytes(self):
        st, d = self.cgi('list')
        self.assertEqual(d['sounds'][0], {'name': 'chime', 'builtin': 1, 'custom': 0, 'bytes': 16800})
        # sound_path finds the built-in A-law clip, a custom one on the card first
        code = self.common() + 'sound_path chime'
        r = subprocess.run(SH + ['-c', code], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), (self.flash / 'chime.alaw').as_posix())

    # the inherited tests assume chime.pcm in the flash
    test_list_upload_delete_boot = None
    test_sound_path_prefers_the_card = None


if __name__ == '__main__':
    unittest.main()
