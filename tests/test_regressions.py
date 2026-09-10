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
        data = (ROOT / 'config/rtspserver.conf.dist').read_text().replace('volume=10', 'volume=7').replace('fps=16', 'fps=19').replace('brmode=1', 'brmode=0').replace('imageflip=0', 'imageflip=1')
        (cfg / 'rtspserver.conf').write_text(data)
        (cfg / 'hostname.conf').write_text('# comment\ncam-test\n')
        (cfg / 'timezone.conf').write_text('UTC+2\n')
        (cfg / 'ntp_srv.conf').write_text('ntp.example.net\n')
        (cfg / 'recording.conf').write_text('rec_postrecord_sec=7\nrec_file_duration_sec=90\nrec_reserverd_disk_mb=512\nrec_motion_activated=1\n')
        source = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        a = source.index('  fullconfig)')
        b = source.index('  perfprofile)', a)
        body = source[a:b].replace('/mnt/config', str(cfg)).replace('/proc/sys/kernel/hostname', str(self.base / 'hostname'))
        helpers = '\n'.join(function('www/cgi-bin/state.cgi', name) for name in ['load_conf_file', 'read_single_config', 'get_cfg', 'read_rtsp_stream_summary', 'sanitize_int', 'truthy_flag', 'codec_name'])
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
        self.assertEqual(result['video']['flip'], 1)
        self.assertEqual(result['recording']['postrec'], 7)
        self.assertEqual(result['recording']['maxduration'], 90)
        self.assertEqual(result['system']['hostname'], 'cam-test')
        self.assertEqual(result['system']['timezone'], 'UTC+2')
        self.assertEqual(result['system']['ntp_server'], 'ntp.example.net')

    def test_stream_summary_exposes_codec_names(self):
        code = function('www/cgi-bin/state.cgi', 'read_rtsp_stream_summary')
        code += '\n' + function('www/cgi-bin/state.cgi', 'sanitize_int')
        code += '\n' + function('www/cgi-bin/state.cgi', 'codec_name')
        code += '\nget_cfg() { case "$1" in 0_codec) echo 2 ;; 1_codec) echo 0 ;; *) echo "$3" ;; esac; }'
        code += '\nread_rtsp_stream_summary; printf "%s|%s" "$codec0_name" "$codec1_name"'
        self.assertEqual(run(code).stdout, b'H265|H264')

    def test_mqtt_health_flags_always_include_discovery_boolean(self):
        cfg = self.base / 'config'
        cfg.mkdir()
        (cfg / 'boot.conf').write_text('SECURITY_HARDENING_MODE=0\n')
        (cfg / 'mqtt.conf').write_text('MQTT_ENABLE=1\nMQTT_HA_DISCOVERY_ENABLE=1\n')
        code = function('www/cgi-bin/func.cgi', 'read_conf_value') + '\n'
        flags = function('www/cgi-bin/state.cgi', 'get_security_and_mqtt_flags')
        flags = flags.replace('/mnt/config', str(cfg)).replace('/tmp/mqtt_last_pub.status', str(self.base / 'missing-status'))
        code += flags + '\nget_security_and_mqtt_flags; printf "%s|%s" "$mqtt_enabled" "$mqtt_discovery"'
        self.assertEqual(run(code).stdout, b'1|1')

    def test_service_status_fails_when_pidfile_is_absent(self):
        missing = shlex.quote(str(self.base / 'missing.pid'))
        for path in ['controlscripts/mqtt-bridge', 'controlscripts/onvif']:
            code = function(path, 'status') + '\nPIDFILE=' + missing + '; status'
            result = run(code)
            self.assertEqual(result.returncode, 1, path)
            self.assertEqual(result.stdout, b'', path)

    def test_rtsp_probe_accepts_digest_challenge(self):
        reply = self.base / 'rtsp-reply'
        reply.write_bytes(b'RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm="LIVE555"\r\n\r\n')
        code = function('www/cgi-bin/state.cgi', 'rtsp_describe_local_ok')
        code += '\nRTSP_REPLY=' + shlex.quote(str(reply)) + '; export RTSP_REPLY; nc() { cat "$RTSP_REPLY"; }; rtsp_describe_local_ok video0_unicast 554 root pass 2'
        self.assertEqual(run(code).returncode, 0)

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
        code = '\n'.join(function('www/cgi-bin/configbackup.cgi', name) for name in [
            'archive_to_plain', 'list_plain_entries', 'list_plain_verbose', 'validate_archive_entries']) + '\n'
        code += 'TMP_ROOT=' + shlex.quote(str(self.base)) + '\n'
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

    def test_config_transaction_rejects_all_files_before_commit(self):
        stage, target, backup = (self.base / name for name in ('stage', 'target', 'backup'))
        stage.mkdir(); target.mkdir()
        (stage / 'boot.conf').write_text((ROOT / 'config/boot.conf.dist').read_text().replace('WEB_MODE=full', 'WEB_MODE=ultra-lite'))
        (stage / 'mqtt.conf').write_text((ROOT / 'config/mqtt.conf.dist').read_text().replace('MQTT_QOS=0', 'MQTT_QOS=9'))
        original_boot = 'WEB_MODE=full\n'
        original_mqtt = 'MQTT_ENABLE=0\nMQTT_PORT=1883\nMQTT_QOS=0\n'
        (target / 'boot.conf').write_text(original_boot)
        (target / 'mqtt.conf').write_text(original_mqtt)
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh'))
        code += '; tc_commit_config_files ' + ' '.join(map(shlex.quote, [str(stage), str(target), str(backup), 'boot.conf mqtt.conf']))
        r = run(code)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((target / 'boot.conf').read_text(), original_boot)
        self.assertEqual((target / 'mqtt.conf').read_text(), original_mqtt)

    def test_config_transaction_commits_valid_candidates_and_ini_sections(self):
        stage, target, backup = (self.base / name for name in ('stage', 'target', 'backup'))
        stage.mkdir(); target.mkdir()
        for name in ('boot.conf', 'mqtt.conf'):
            (stage / name).write_text((ROOT / ('config/' + name + '.dist')).read_text())
            (target / name).write_text((ROOT / ('config/' + name + '.dist')).read_text())
        rtsp = self.base / 'rtsp.conf'
        rtsp.write_text((ROOT / 'config/rtspserver.conf.dist').read_text())
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh'))
        code += '; tc_set_flat ' + shlex.quote(str(stage / 'boot.conf')) + ' WEB_MODE ultra-lite'
        code += '; tc_set_ini ' + shlex.quote(str(rtsp)) + ' 0 fps 12'
        code += '; tc_set_ini ' + shlex.quote(str(rtsp)) + ' root imageflip 1'
        code += '; tc_validate_candidate rtspserver.conf ' + shlex.quote(str(rtsp))
        code += '; tc_commit_config_files ' + ' '.join(map(shlex.quote, [str(stage), str(target), str(backup), 'boot.conf mqtt.conf']))
        code += '; printf "%s" "$TC_COMMIT_COUNT"'
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'1')
        self.assertIn('WEB_MODE=ultra-lite', (target / 'boot.conf').read_text())
        data = rtsp.read_text()
        self.assertNotIn('0_fps=', data)
        self.assertRegex(data, r'(?s)\[0\].*?\nfps=12\n')
        self.assertIn('\nimageflip=1\n', data)

    def test_json_import_uses_real_config_keys_and_transaction(self):
        source = (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text()
        self.assertIn('FUNC_CGI_SKIP_BODY=1', source)
        self.assertIn('tc_commit_config_files', source)
        for expected in [
            '"0";"codec"', '"1";"fps"', '"2";"codec"', '"3";"codec"',
            '"imageflip"', '"RTSPLOGENABLED"', '"rec_postrecord_sec"',
            '"rec_file_duration_sec"', '"rec_reserverd_disk_mb"']:
            self.assertIn(expected, source)
        for obsolete in ['"0_codec"', '"audioCodec0"', '"postrec";"record_post"']:
            self.assertNotIn(obsolete, source)
        self.assertIn('res && res.ok === true', (ROOT / 'www/backup.html').read_text())

    def config_exchange_code(self):
        names = ['_ce_cleanup', '_ce_fail', '_ce_truthy', '_ce_add_file',
                 '_ce_prepare_file', '_ce_build_rows', '_ce_import']
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh')) + '\n'
        code += function('www/cgi-bin/func.cgi', 'urldecode') + '\n'
        code += 'json_body_err() { printf \'{"ok":false,"error":"%s","message":"%s"}\\n\' "$1" "$2"; }\n'
        code += '\n'.join(function('www/cgi-bin/config_exchange.cgi', name) for name in names)
        return code + '\n_ce_import'

    def test_json_import_applies_sections_and_rejects_whole_invalid_batch(self):
        cfg = self.base / 'config'; cfg.mkdir()
        for name in ('boot.conf', 'rtspserver.conf', 'recording.conf', 'telegram.conf'):
            (cfg / name).write_text((ROOT / ('config/' + name + '.dist')).read_text())
        env = dict(os.environ, CONFIG_ROOT=str(cfg), TC_CONFIG_ROOT=str(cfg), JQ_BIN='/usr/bin/jq',
                   F_exclude_network='0', F_exclude_credentials='0')
        good = json.dumps({'video': {'main': {'fps': 12, 'bitrate': 1000}},
                           'recording': {'postrec': 8},
                           'telegram': {'token': '123:abc$def'}}).encode()
        env['CONTENT_LENGTH'] = str(len(good))
        r = run(self.config_exchange_code(), good, env, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)['transactional'])
        rtsp = (cfg / 'rtspserver.conf').read_text()
        self.assertRegex(rtsp, r'(?s)\[0\].*?\nbps=1000\n.*?\nfps=12\n')
        self.assertIn('rec_postrecord_sec=8', (cfg / 'recording.conf').read_text())
        self.assertIn("apiToken='123:abc$def'", (cfg / 'telegram.conf').read_text())

        before_rtsp = rtsp
        bad = json.dumps({'video': {'main': {'fps': 10}},
                          'recording': {'maxduration': 2}}).encode()
        env['CONTENT_LENGTH'] = str(len(bad))
        r = run(self.config_exchange_code(), bad, env, timeout=15)
        self.assertEqual(json.loads(r.stdout)['error'], 'VALIDATION_FAILED')
        self.assertEqual((cfg / 'rtspserver.conf').read_text(), before_rtsp)

    def test_legacy_import_is_transactional(self):
        cfg = self.base / 'config'; cfg.mkdir()
        for name in ('boot.conf', 'mqtt.conf'):
            (cfg / name).write_text((ROOT / ('config/' + name + '.dist')).read_text())
        before = (cfg / 'boot.conf').read_bytes()
        body = b'## tc100-boot-mqtt-export v1\n##[SECTION:boot.conf]##\nWEB_MODE=ultra-lite\n##[SECTION:mqtt.conf]##\nMQTT_QOS=9\n'
        source = (ROOT / 'www/cgi-bin/conf-import.cgi').read_text().replace('/tmp/csrf_token', str(self.base / 'csrf'))
        env = dict(os.environ, REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(body)),
                   TC_CONFIG_ROOT=str(cfg), CONFIG_TX_LIB=str(ROOT / 'scripts/config-transaction.sh'))
        r = run(source, body, env, timeout=15)
        response = json.loads(r.stdout.split(b'\r\n\r\n', 1)[1])
        self.assertEqual(response['error'], 'validation_failed')
        self.assertEqual((cfg / 'boot.conf').read_bytes(), before)

    def test_backup_restore_commits_staged_archive(self):
        mnt = self.base / 'mnt'; cfg = mnt / 'config'; cfg.mkdir(parents=True)
        src = self.base / 'source'; (src / 'config').mkdir(parents=True)
        for name in ('boot.conf', 'mqtt.conf'):
            original = (ROOT / ('config/' + name + '.dist')).read_text()
            (cfg / name).write_text(original)
            (src / 'config' / name).write_text(original)
        changed = (src / 'config/boot.conf').read_text().replace('WEB_MODE=full', 'WEB_MODE=ultra-lite')
        (src / 'config/boot.conf').write_text(changed)
        archive = self.base / 'restore.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(src / 'config', arcname='config')
        names = ['_format_backup_tag', 'html_header', 'is_truthy', 'create_archive',
                 'archive_to_plain', 'extract_plain_archive', 'restore_backup']
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh')) + '\n'
        code += '\n'.join(function('www/cgi-bin/configbackup.cgi', name) for name in names)
        code += '\n_read_ts() { now_ts=1; }\nrestore_backup "$ARCHIVE" 0'
        env = dict(os.environ, ARCHIVE=str(archive), TMP_ROOT=str(self.base), MNT_ROOT=str(mnt),
                   CONFIG_ROOT=str(cfg), TC_MNT_ROOT=str(mnt), TC_CONFIG_ROOT=str(cfg))
        r = run(code, env=env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b'transactionally (1 changed file(s))', r.stdout)
        self.assertIn('WEB_MODE=ultra-lite', (cfg / 'boot.conf').read_text())
        self.assertTrue(list(self.base.glob('config-rollback-*.tar.gz')))

    def test_frigate_light_profile_matches_ak3918_budget(self):
        code = function('www/cgi-bin/action.cgi', 'select_compat_profile_values')
        code += '\nselect_compat_profile_values frigate-light-ak3918'
        code += '\nprintf "%s|%s|%s|%s|%s|%s|%s|%s|%s" "$codec0" "$width0" "$height0" "$fps0" "$bps0" "$codec1" "$fps1" "$bps1" "$rtsp_audio"'
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'2|1280|720|12|1000|2|8|320|0')
        self.assertIn('value="frigate-light-ak3918"', (ROOT / 'www/settings.html').read_text())

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
