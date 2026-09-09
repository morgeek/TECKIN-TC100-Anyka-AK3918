"""Bounded host regressions. No camera, network or root privileges required.
Run: python3 -m unittest discover -s tests -v
Uses Bash for BusyBox ash extensions; does not certify ARM/BusyBox compatibility.
"""
from pathlib import Path
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MQTT = 'scripts/mqtt-bridge.sh'

def function(path, name):
    match = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}',
                      (ROOT / path).read_text(), re.M | re.S)
    if not match:
        raise AssertionError((path, name))
    return match.group(0)

def run(code, data=None, env=None, timeout=8):
    return subprocess.run(['/bin/bash', '-c', code], input=data,
                          capture_output=True, timeout=timeout, env=env)

def varint(n):
    result = bytearray()
    while True:
        d, n = n % 128, n // 128
        result.append(d | (128 if n else 0))
        if not n:
            return bytes(result)

def publish(payload, topic=b'camera/command'):
    body = len(topic).to_bytes(2, 'big') + topic + payload
    return b'\x30' + varint(len(body)) + body

def packets(data):
    result = []
    while data:
        header, data = data[0], data[1:]
        length, mult = 0, 1
        while True:
            d, data = data[0], data[1:]
            length += (d & 127) * mult
            mult *= 128
            if not d & 128:
                break
        if len(data) < length:
            raise AssertionError('truncated packet')
        result.append((header, data[:length]))
        data = data[length:]
    return result

class Regressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='tc100-test-')
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_shell_and_javascript_syntax(self):
        shells, scripts = 0, 0
        for path in ROOT.rglob('*'):
            if '.git' in path.parts or not path.is_file():
                continue
            if path.read_bytes().startswith(b'#!/bin/sh'):
                r = subprocess.run(['/bin/sh', '-n', str(path)], capture_output=True)
                self.assertEqual(r.returncode, 0, (path, r.stderr))
                shells += 1
        for path in (ROOT / 'www/scripts').glob('*.js'):
            r = subprocess.run(['node', '--check', str(path)], capture_output=True)
            self.assertEqual(r.returncode, 0, (path, r.stderr))
            scripts += 1
        self.assertGreaterEqual(shells, 88)
        self.assertGreaterEqual(scripts, 5)

    def test_frontend_behaviour(self):
        r = subprocess.run(['node', str(ROOT / 'tests/frontend.test.js')], capture_output=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_settings_save_contract(self):
        r = subprocess.run(['node', str(ROOT / 'tests/settings-save.test.js')], capture_output=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_profile_reply_reports_real_restart_result(self):
        code = function('www/cgi-bin/action.cgi', 'ui_finalize_stream_apply')
        code += '''\nwants_json_response() { return 0; }; json_body_err() { printf '{"ok":false,"error":"%s"}\\n' "$1"; };\n'''
        for rc in [0, 1]:
            r = run(code + 'finalize_stream_apply() { echo "diagnostic"; return ' + str(rc) + '; }; ui_finalize_stream_apply test')
            result = json.loads(r.stdout)
            self.assertEqual(result['ok'], rc == 0)
            self.assertEqual(r.returncode, rc)
            if rc == 0:
                self.assertEqual(result['restart'], 'verified')

    def test_video_audio_write_failure_never_reports_success(self):
        source = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        for command, following in [('set_video_params', 'conf_audioin'), ('conf_audioin', 'isp_pro')]:
            a = source.index('    ' + command + ')')
            b = source.index('    ' + following + ')', a)
            block = source[a:b].replace('/mnt/bin/rwconf', 'rwconf')
            code = function('www/cgi-bin/action.cgi', 'sanitize_int_range') + '\n'
            code += 'rwconf() { return 1; }; wants_json_response() { return 0; }; schedule_rtsp_restart() { echo RESTART; };\n'
            code += '''json_body_err() { printf '{"ok":false,"error":"%s"}\\n' "$1"; }; json_body_ok() { echo SUCCESS; };\n'''
            r = run(code + 'case ' + command + ' in\n' + block + '\nesac')
            self.assertFalse(json.loads(r.stdout)['ok'], r.stdout)
            self.assertNotIn(b'RESTART', r.stdout)

    def test_ini_loader_preserves_sections_and_literal_values(self):
        ini = self.base / 'rtsp.conf'
        ini.write_text('volume=7\nsamplerate=16000\n[0]\ncodec=2\nfps=19\n[1]\ncodec=0\nfps=6\n[2]\ncodec=4\n[3]\ncodec=17\n')
        plain = self.base / 'boot.conf'
        plain.write_text('VALUE=$(printf unsafe)\nPORT=555')
        code = function('www/cgi-bin/state.cgi', 'load_conf_file') + '\n' + function('www/cgi-bin/state.cgi', 'get_cfg')
        code += '\nload_conf_file ' + shlex.quote(str(ini)) + '\nload_conf_file ' + shlex.quote(str(plain))
        code += '\nprintf "%s|%s|%s|%s|%s|%s|%s" "$C_volume" "$C_0_codec" "$C_1_fps" "$C_2_codec" "$C_3_codec" "$C_VALUE" "$C_PORT"'
        self.assertEqual(run(code).stdout, b'7|2|6|4|17|$(printf unsafe)|555')

    def test_fullconfig_reads_actual_ini_video_and_audio(self):
        cfg = self.base / 'config'
        cfg.mkdir()
        data = (ROOT / 'config/rtspserver.conf.dist').read_text().replace('volume=10', 'volume=7').replace('fps=16', 'fps=19').replace('brmode=1', 'brmode=0')
        (cfg / 'rtspserver.conf').write_text(data)
        source = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        a = source.index('  fullconfig)')
        b = source.index('  perfprofile)', a)
        body = source[a:b].replace('/mnt/config', str(cfg)).replace('/proc/sys/kernel/hostname', str(self.base / 'hostname'))
        helpers = '\n'.join(function('www/cgi-bin/state.cgi', name) for name in ['load_conf_file', 'get_cfg', 'read_rtsp_stream_summary', 'sanitize_int', 'truthy_flag'])
        helpers += '\n' + function('www/cgi-bin/func.cgi', 'json_escape')
        helpers += '\ndetect_primary_ip() { :; }; read_reboot_epoch() { :; }; get_perf_profile() { echo balanced; }; hostname() { echo fixture; };\n'
        r = run(helpers + 'case fullconfig in\n' + body + '\nesac')
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result['video']['main']['fps'], 19)
        self.assertEqual(result['video']['main']['format'], '0')
        self.assertEqual(result['video']['main']['codec'], 2)
        self.assertEqual(result['video']['sub']['height'], 200)
        self.assertEqual(result['audio']['volume'], 7)
        self.assertEqual(result['audio']['codec_main'], 4)
        self.assertEqual(result['audio']['codec_sub'], 17)

    def test_audio_write_targets_audio_not_video(self):
        source = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        a = source.index('    conf_audioin)'); b = source.index('    isp_pro)', a)
        block = source[a:b].replace('/mnt/bin/rwconf', 'rwconf')
        args = self.base / 'rwconf-args'
        code = function('www/cgi-bin/action.cgi', 'sanitize_int_range') + '\n'
        code += 'rwconf() { printf "%s\\n" "$@" > ' + shlex.quote(str(args)) + '; };\n'
        code += 'wants_json_response() { return 0; }; schedule_rtsp_restart() { :; }; json_body_ok() { echo OK; };\n'
        code += 'F_samplerate=16000; F_audioinVol=7; F_audioCodec0=17;\ncase conf_audioin in\n' + block + '\nesac'
        r = run(code)
        self.assertEqual(r.stdout, b'OK\n', r.stderr)
        values = args.read_text().splitlines()[2:]
        writes = [tuple(values[i:i+3]) for i in range(0, len(values), 3)]
        self.assertEqual(writes, [(' ', 'samplerate', '16000'), (' ', 'volume', '7'), ('2', 'samplerate', '16000'), ('2', 'codec', '17')])

    def test_bundled_binaries_unchanged(self):
        count = 0
        for line in (ROOT / 'config/packages.lock.dist').read_text().splitlines():
            if not line.startswith('#') and '|' in line:
                name, digest = line.split('|')
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)
                count += 1
        self.assertEqual(count, 25)

    def test_install_config_missing_and_existing(self):
        cfg = self.base / 'test.conf'
        cfg.with_suffix('.conf.dist').write_text('VALUE=1\n')
        code = function('scripts/common_functions.sh', 'install_config') + '\n'
        code += function('scripts/common_functions.sh', 'install_config_cached') + '\n'
        code += 'install_config_cached ' + shlex.quote(str(cfg))
        self.assertEqual(run(code).returncode, 0)
        cfg.write_text('CUSTOM=2\n')
        stamp = cfg.stat().st_mtime_ns
        self.assertEqual(run(code).returncode, 0)
        self.assertEqual(cfg.read_text(), 'CUSTOM=2\n')
        self.assertEqual(cfg.stat().st_mtime_ns, stamp)

    def test_config_rewrite_noop_and_duplicate_keys(self):
        cfg = self.base / 'test.conf'
        code = function('scripts/common_functions.sh', 'rewrite_config')
        code += '\nsync() { echo SYNC; }; rewrite_config ' + shlex.quote(str(cfg)) + ' KEY 1'
        cfg.write_text('# unchanged comment\n  KEY=1\nOTHER=2\n')
        stamp = cfg.stat().st_mtime_ns
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'')
        self.assertEqual(cfg.stat().st_mtime_ns, stamp)
        cfg.write_text('KEY=1\nKEY=2\n')
        r = run(code)
        self.assertEqual(r.stdout, b'SYNC\n')
        self.assertEqual(cfg.read_text(), 'KEY=1\nKEY=1\n')

    def guard_code(self):
        token = self.base / 'csrf_token'
        token.write_text('aabbcc\n')
        return function('www/cgi-bin/func.cgi', 'csrf_guard').replace('/tmp/csrf_token', str(token)) + '\n' + function('www/cgi-bin/func.cgi', 'mutation_guard')

    def test_mutations_require_post_and_token(self):
        for method, token, marker in [('GET', 'aabbcc', b'405'), ('POST', '', b'403'), ('POST', 'aabbcc', b'PASSED')]:
            with self.subTest(method=method, token=token):
                r = run(self.guard_code() + '\nREQUEST_METHOD=' + method + '; HTTP_X_CSRF_TOKEN=' + shlex.quote(token) + '; mutation_guard; echo PASSED')
                self.assertIn(marker, r.stdout)
                if marker != b'PASSED':
                    self.assertNotIn(b'PASSED', r.stdout)

    def editor(self, data, length=None, method='POST'):
        s = (ROOT / 'www/cgi-bin/configeditor.cgi').read_text()
        a, b = s.index('if [ -r /mnt/www/cgi-bin/func.cgi ]'), s.index('CONFIG_ROOT=')
        prelude = 'timeout() { :; }; . ' + shlex.quote(str(ROOT / 'www/cgi-bin/func.cgi')) + '\n'
        prelude += 'rate_limit_check() { :; }; audit_log_event() { :; }; sync() { :; };\n'
        prelude += self.guard_code() + '\n'
        s = s[:a] + prelude + s[b:]
        s = s.replace('/mnt/config', str(self.base)).replace('/tmp/configeditor-', str(self.base / 'configeditor-'))
        env = dict(os.environ, REQUEST_METHOD=method, QUERY_STRING='cmd=save&file=boot.conf',
                   CONTENT_LENGTH=str(len(data) if length is None else length), HTTP_X_CSRF_TOKEN='aabbcc')
        return run(s, data, env)

    def test_editor_preserves_exact_body_and_bounded_backup(self):
        cfg = self.base / 'boot.conf'
        cfg.write_text('ORIGINAL=1\n')
        body = b'# comment\nLIGHTWEIGHT_MODE=1\n'
        r = self.editor(body)
        self.assertIn(b'"ok":true', r.stdout, (r.stdout, r.stderr))
        self.assertEqual(cfg.read_bytes(), body)
        self.assertEqual((self.base / 'configeditor-backup-boot.conf').read_bytes(), b'ORIGINAL=1\n')
        stamp = cfg.stat().st_mtime_ns
        r = self.editor(body)
        self.assertIn(b'Unchanged', r.stdout)
        self.assertEqual(cfg.stat().st_mtime_ns, stamp)
        self.assertEqual(len(list(self.base.glob('configeditor-backup-*'))), 1)
        self.assertFalse(list(self.base.glob('*.lock')))

    def test_editor_rejects_truncation_invalid_syntax_get_and_oversize(self):
        cfg = self.base / 'boot.conf'
        original = b'ORIGINAL=1\n'
        for body, length, method, marker in [
            (b'NEW=2\n', 20, 'POST', b'Incomplete'),
            (b"KEY='unterminated\n", None, 'POST', b'Invalid configuration syntax'),
            (b'NEW=2\n', None, 'GET', b'405'),
            (b'NEW=2\n', 65537, 'POST', b'Content too large')]:
            with self.subTest(marker=marker):
                cfg.write_bytes(original)
                r = self.editor(body, length, method)
                self.assertIn(marker, r.stdout, (r.stdout, r.stderr))
                self.assertEqual(cfg.read_bytes(), original)

    def test_date_formatters(self):
        for path, name, pattern in [
            ('www/cgi-bin/configbackup.cgi', '_format_backup_tag', rb'\d{8}-\d{6}\n'),
            ('scripts/timelapse.sh', '_format_datetime', rb'\d{4}-\d\d-\d\d_\d{6}\n')]:
            r = run(function(path, name) + '\n' + name + ' 1788973200')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertRegex(r.stdout, pattern)

    def archive(self, name='config/boot.conf', size=8, kind=tarfile.REGTYPE):
        path = self.base / 'backup.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                member.size = size
                tar.addfile(member, io.BytesIO(b'A' * size))
            else:
                member.linkname = '/outside'
                tar.addfile(member)
        return path

    def test_archive_validation(self):
        code = function('www/cgi-bin/configbackup.cgi', 'list_archive_entries') + '\n'
        code += function('www/cgi-bin/configbackup.cgi', 'validate_archive_entries') + '\n'
        for name, size, kind, allowed in [
            ('config/boot.conf', 8, tarfile.REGTYPE, True),
            ('config/../outside', 8, tarfile.REGTYPE, False),
            ('outside', 8, tarfile.REGTYPE, False),
            ('config/link', 0, tarfile.SYMTYPE, False),
            ('config/link', 0, tarfile.LNKTYPE, False),
            ('config/large', 2097153, tarfile.REGTYPE, False)]:
            with self.subTest(name=name, kind=kind, size=size):
                path = self.archive(name, size, kind)
                r = run(code + 'validate_archive_entries ' + shlex.quote(str(path)))
                self.assertEqual(r.returncode == 0, allowed, r.stderr)

    def test_package_backup_is_restorable(self):
        (self.base / 'bin').mkdir()
        (self.base / 'lib').mkdir()
        cfg = self.base / 'bin/fixture'
        cfg.write_text('original')
        env = dict(os.environ, PKG_ROOT=str(self.base))
        command = ['/bin/sh', str(ROOT / 'scripts/pkg-upgrade-safe.sh')]
        r = subprocess.run(command + ['backup'], env=env, capture_output=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
        backup = next((self.base / 'backup/package-upgrades').iterdir())
        cfg.write_text('replacement')
        r = subprocess.run(command + ['rollback', backup.name], env=env, capture_output=True, timeout=8)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(cfg.read_text(), 'original')

    def decoder(self, data):
        s = (ROOT / MQTT).read_text()
        dec = re.search(r"_mqtt_frame_decoder='(.*?)'\n", s, re.S).group(1)
        return subprocess.run(['awk', '-v', 'max_frame=4096', dec],
                              input=' '.join(str(b) for b in data).encode(),
                              capture_output=True, timeout=5, env=dict(os.environ, LC_ALL='C'))

    def test_mqtt_fragmentation_and_multiple_packets(self):
        one, two = publish(b'{"cmd":"front_led"}'), publish(b'{"cmd":"nightmode"}')
        self.assertIn(b'#CONSUMED 0', self.decoder(one[:-1]).stdout)
        r = self.decoder(b'\x20\x02\x00\x00' + one + two)
        self.assertEqual(r.stdout.count(b'#PAYLOAD'), 2)
        self.assertIn(('CONSUMED ' + str(4 + len(one) + len(two))).encode(), r.stdout)
        self.assertNotIn(b'#INVALID', r.stdout)

    def test_mqtt_rejects_bad_lengths_and_bounded_frames(self):
        for frame in [b'\x30\xff\xff\xff\xff', publish(b'x' * 4097), b'\x30\x01\x00', publish(b'\x00')]:
            with self.subTest(frame=frame[:8]):
                self.assertIn(b'#INVALID', self.decoder(frame).stdout)
        self.assertIn(b'#PAYLOAD {  "cmd":"x" }', self.decoder(publish(b'{\r\n"cmd":"x"\n}')).stdout)

    def mqtt_prefix(self):
        s = (ROOT / MQTT).read_text()
        start = s.index('MQTT_STREAM_RAW="/tmp/mqtt_stream.bin"')
        end = s.index('\nstream_mode_enabled()', start)
        code = s[start:end]
        code += '\nMQTT_STREAM_RAW=' + shlex.quote(str(self.base / 'spool')) + '\n'
        code += 'handle_command_payload() { printf "DELIVERED %s\\n" "$1"; }; log_msg() { :; };\n'
        return code

    def test_mqtt_session_offsets_and_unread_bytes(self):
        one, two = publish(b'{"cmd":"front_led"}'), publish(b'{"cmd":"nightmode"}')
        self.assertEqual(len(one), len(two))
        (self.base / 'spool.1').write_bytes(one)
        (self.base / 'spool.2').write_bytes(two)
        code = self.mqtt_prefix() + '''
        echo 1 > "${MQTT_STREAM_RAW}.session"
        drain_command_spool
        drain_command_spool
        echo 2 > "${MQTT_STREAM_RAW}.session"
        drain_command_spool
        drain_command_spool
        '''
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count(b'DELIVERED'), 2, r.stdout)
        self.assertIn(b'front_led', r.stdout)
        self.assertIn(b'nightmode', r.stdout)

    def test_mqtt_spool_batch_limit_and_partial_completion(self):
        frame = publish(b'X' * 2000)
        (self.base / 'spool.1').write_bytes(frame * 10 + frame[:10])
        (self.base / 'rest').write_bytes(frame[10:])
        code = self.mqtt_prefix() + '''
        echo 1 > "${MQTT_STREAM_RAW}.session"
        drain_command_spool
        echo OFFSET=$MQTT_STREAM_OFFSET
        drain_command_spool
        cat "''' + str(self.base / 'rest') + '''" >> "${MQTT_STREAM_RAW}.1"
        drain_command_spool
        drain_command_spool
        '''
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count(b'DELIVERED'), 11)
        offset = int(re.search(rb'OFFSET=(\d+)', r.stdout).group(1))
        self.assertLessEqual(offset, 16384)
        self.assertGreater(offset, 0)

    def test_mqtt_will_and_retained_online_packets(self):
        code = '\n'.join(function(MQTT, name) for name in ['_mqtt_str', '_mqtt_varint', 'mqtt_listener_packets'])
        for username in ['', 'user']:
            with self.subTest(username=username):
                env = dict(os.environ, MQTT_USER=username, MQTT_PASSWORD='pass', MQTT_CLIENT_ID='camera',
                           MQTT_TOPIC_ROOT='root', MQTT_TOPIC_COMMAND='root/command', MQTT_LISTENER_MAX_PINGS='0')
                r = run(code + '\nmqtt_listener_packets', env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                ps = packets(r.stdout)
                self.assertEqual([p[0] for p in ps], [0x10, 0x82, 0x31, 0xe0])
                self.assertEqual(ps[0][1][:7], b'\x00\x04MQTT\x04')
                self.assertEqual(ps[0][1][7], 0xe6 if username else 0x26)
                self.assertIn(b'\x00\x11root/availability\x00\x07offline', ps[0][1])
                self.assertTrue(ps[2][1].endswith(b'online'))
                self.assertEqual(ps[3][1], b'')

    def test_listener_captures_reply_and_cleans_children(self):
        nc = self.base / 'nc'
        nc.write_text('#!/bin/sh\ncat > "$CAPTURE"\nprintf "\\040\\002\\000\\000"\n')
        nc.chmod(0o755)
        code = self.mqtt_prefix()
        code += '\n' + function(MQTT, '_mqtt_str') + '\n' + function(MQTT, '_mqtt_varint')
        code += '\nmqtt_listener_once; result=$?; echo RESULT=$result; test ! -p "${MQTT_STREAM_RAW}.input"'
        env = dict(os.environ, PATH=str(self.base) + ':' + os.environ['PATH'], CAPTURE=str(self.base / 'sent'),
                   MQTT_USER='', MQTT_PASSWORD='', MQTT_CLIENT_ID='camera', MQTT_TOPIC_ROOT='root',
                   MQTT_TOPIC_COMMAND='root/command', MQTT_LISTENER_MAX_PINGS='0', MQTT_HOST='unused', MQTT_PORT='1883')
        r = run(code, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b'RESULT=0', r.stdout)
        self.assertEqual((self.base / 'spool.1').read_bytes(), b'\x20\x02\x00\x00')
        self.assertEqual(len(packets((self.base / 'sent').read_bytes())), 4)

    def test_listener_capture_file_size_is_bounded(self):
        nc = self.base / 'nc'
        nc.write_text('#!/bin/sh\nexec head -c 524288 /dev/zero\n')
        nc.chmod(0o755)
        code = self.mqtt_prefix()
        code += '\n' + function(MQTT, '_mqtt_str') + '\n' + function(MQTT, '_mqtt_varint')
        code += '\nmqtt_listener_once; test ! -p "${MQTT_STREAM_RAW}.input"'
        env = dict(os.environ, PATH=str(self.base) + ':' + os.environ['PATH'],
                   MQTT_USER='', MQTT_PASSWORD='', MQTT_CLIENT_ID='camera', MQTT_TOPIC_ROOT='root',
                   MQTT_TOPIC_COMMAND='root/command', MQTT_LISTENER_MAX_PINGS='100',
                   MQTT_KEEPALIVE_PING_SECONDS='30', MQTT_HOST='unused', MQTT_PORT='1883')
        r = run(code, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        size = (self.base / 'spool.1').stat().st_size
        self.assertGreater(size, 0)
        self.assertLessEqual(size, 131072)

    def test_raw_backup_upload_reaches_delegate_once(self):
        archive = self.archive()
        body = archive.read_bytes()
        s = (ROOT / 'www/cgi-bin/upload_backup.cgi').read_text()
        a = s.index('if [ -r /mnt/www/cgi-bin/func.cgi ]')
        b = s.index('MAX_UPLOAD_BYTES=')
        prelude = 'timeout() { :; }; . ' + shlex.quote(str(ROOT / 'www/cgi-bin/func.cgi')) + '\n'
        prelude += 'rate_limit_check() { :; };\n' + self.guard_code() + '\n'
        s = s[:a] + prelude + s[b:]
        delegate = self.base / 'delegate'
        delegate.write_text('#!/bin/sh\ncp "$F_archive_path" "$CAPTURE"\nprintf "%s %s" "$REQUEST_METHOD" "$CONTENT_LENGTH"\n')
        delegate.chmod(0o755)
        s = s.replace('TMP_ROOT="/tmp"', 'TMP_ROOT=' + shlex.quote(str(self.base)))
        s = s.replace('/mnt/www/cgi-bin/configbackup.cgi', str(delegate))
        env = dict(os.environ, REQUEST_METHOD='POST', QUERY_STRING='', CONTENT_LENGTH=str(len(body)),
                   HTTP_X_CSRF_TOKEN='aabbcc', CAPTURE=str(self.base / 'received'))
        r = run(s, body, env)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertIn(b'POST 0', r.stdout)
        self.assertEqual((self.base / 'received').read_bytes(), body)
        self.assertFalse(list(self.base.glob('config-upload-*')))

    def test_deep_health_failure_is_not_running(self):
        svc = self.base / 'rtsp-h26x'
        svc.write_text('#!/bin/sh\ncase "$1" in health) exit 1;; status) echo "PID: $$";; esac\n')
        svc.chmod(0o755)
        gate = self.base / 'gate'
        gate.write_text(str(os.getpid()))
        code = function('scripts/health-probe.sh', 'probe_service_fast').replace('/mnt/controlscripts', str(self.base)).replace('/var/run/v4l2rtspserver.pid', str(gate))
        r = run(code + '\nprobe_service_fast rtsp-h26x')
        self.assertEqual(r.stdout, b'unhealthy\n', r.stderr)

    def test_memory_estimate_subtracts_shmem(self):
        info = self.base / 'meminfo'
        info.write_text('MemTotal:     65536 kB\nMemFree:       2048 kB\nBuffers:  1024 kB\nCached:  16384 kB\nSReclaimable: 512 kB\nShmem: 8192 kB\n')
        for path in ['scripts/health-snapshot.sh', 'www/cgi-bin/health.cgi']:
            s = (ROOT / path).read_text()
            a = s.index('_memtotal=0;')
            b = s.index('read -r _loadavg', a)
            code = s[a:b].replace('/proc/meminfo', str(info))
            if path.endswith('health.cgi'):
                code = code[:code.rfind('_loadavg=')]
            r = run(code + '\necho "$_memavail"')
            self.assertEqual(r.stdout, b'11776\n', (path, r.stderr))

if __name__ == '__main__':
    unittest.main()
