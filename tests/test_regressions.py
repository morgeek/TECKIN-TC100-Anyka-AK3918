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
import shutil
import struct
import subprocess
import sys
import threading
import time
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MQTT = 'scripts/mqtt-bridge.sh'

def state_text(path):
    """A CGI's text; state.cgi's helpers shared with statusline.cgi live in statelib.cgi."""
    t = (ROOT / path).read_text()
    if path.endswith('cgi-bin/state.cgi'):
        t += '\n' + (ROOT / 'www/cgi-bin/statelib.cgi').read_text()
    return t


def function(path, name):
    match = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}',
                      state_text(path), re.M | re.S)
    if not match:
        raise AssertionError((path, name))
    return match.group(0)

def action_cgi_text():
    """action.cgi and its command files (scripts/action.d), as one text."""
    parts = [(ROOT / 'www/cgi-bin/action.cgi').read_text()]
    parts += [f.read_text() for f in sorted((ROOT / 'scripts/action.d').glob('*.sh'))]
    return '\n'.join(parts)

def action_arm(name):
    """The text of one action.cgi command arm, up to the next arm."""
    for f in sorted((ROOT / 'scripts/action.d').glob('*.sh')):
        lines = f.read_text().split('\n')
        heads = [i for i, l in enumerate(lines) if re.match(r'^ {4,5}[^ #()][^()]*\)\s*$', l)]
        for k, i in enumerate(heads):
            if name in lines[i].strip()[:-1].split('|'):
                end = heads[k + 1] if k + 1 < len(heads) else len(lines)
                return '\n'.join(lines[i:end])
    raise AssertionError(name)

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
            # .claude/ holds local agent worktrees (not in git): their copies are checked where they come from
            if '.git' in path.parts or '.claude' in path.parts or not path.is_file():
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
        for command in ('set_video_params', 'conf_audioin'):
            block = action_arm(command).replace('/mnt/bin/rwconf', 'rwconf')
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
        data = (ROOT / 'config/rtspserver.conf.dist').read_text().replace('volume=10', 'volume=7').replace('fps=15', 'fps=19').replace('brmode=1', 'brmode=0').replace('imageflip=0', 'imageflip=1')
        (cfg / 'rtspserver.conf').write_text(data)
        (cfg / 'hostname.conf').write_text('# comment\ncam-test\n')
        (cfg / 'timezone.conf').write_text('UTC+2\n')
        (cfg / 'ntp_srv.conf').write_text('ntp.example.net\n')
        (cfg / 'recording.conf').write_text('rec_postrecord_sec=7\nrec_file_duration_sec=90\nrec_reserverd_disk_mb=512\nrec_motion_activated=1\n')
        source = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        a = source.index('  fullconfig)')
        b = source.index('  perfprofile)', a)
        body = source[a:b].replace('/mnt/config', str(cfg)).replace('/proc/sys/kernel/hostname', str(self.base / 'hostname'))
        helpers = '\n'.join(function('www/cgi-bin/state.cgi', name) for name in ['load_conf_file', 'read_single_config', 'get_cfg', 'read_rtsp_stream_summary', 'sanitize_int', 'truthy_flag', 'codec_name', 'cfg_int', 'codec_name_to'])
        helpers += '\n' + function('www/cgi-bin/func.cgi', 'json_escape')
        helpers += '\ndetect_primary_ip() { :; }; read_reboot_epoch() { :; }; get_perf_profile() { echo balanced; }; hostname() { echo fixture; };\n'
        r = run(helpers + 'case fullconfig in\n' + body + '\nesac')
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result['video']['main']['fps'], 15)        # 19 is not one of 10/12/15/20/25: 15
        self.assertEqual(result['video']['sub']['fps'], 15)
        self.assertEqual(result['video']['main']['format'], '0')
        self.assertEqual(result['video']['main']['codec'], 2)
        self.assertEqual(result['video']['sub']['height'], 360)
        self.assertEqual(result['audio']['volume'], 7)
        self.assertEqual(result['audio']['codec_main'], 17)
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
        code += '\n' + function('www/cgi-bin/state.cgi', 'codec_name') + '\n' + function('www/cgi-bin/state.cgi', 'cfg_int')
        code += '\n' + function('www/cgi-bin/state.cgi', 'codec_name_to')
        code += '\nC_0_codec=2; C_1_codec=0'
        code += '\nread_rtsp_stream_summary; printf "%s|%s" "$codec0_name" "$codec1_name"'
        self.assertEqual(run(code).stdout, b'H265|H264')

    def test_mqtt_health_flags_always_include_discovery_boolean(self):
        cfg = self.base / 'config'
        cfg.mkdir()
        (cfg / 'boot.conf').write_text('SECURITY_HARDENING_MODE=0\n')
        (cfg / 'mqtt.conf').write_text('MQTT_ENABLE=1\nMQTT_HA_DISCOVERY_ENABLE=1\n')
        code = function('www/cgi-bin/func.cgi', 'read_conf_value') + '\n' + function('www/cgi-bin/func.cgi', 'conf_get') + '\n'
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

    def test_service_start_does_not_capture_daemon_output_through_a_pipe(self):
        # A service that backgrounds a daemon inherits a $(...) pipe and keeps it
        # open; scripts.cgi then never returned (seen on ftp-server, 2026-10-11).
        s = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        start = s[s.index('      start)'):s.index('      disable)')]
        self.assertNotIn('$(sh "$SCRIPT_HOME/$script" start', start)
        self.assertIn('</dev/null >"$_start_out" 2>&1', start)
        svc = self.base / 'svc'
        svc.write_text('#!/bin/sh\nsleep 30 &\necho started\n')
        out = self.base / 'start.out'
        code = 'sh ' + shlex.quote(str(svc)) + ' start </dev/null >' + shlex.quote(str(out)) + ' 2>&1; cat ' + shlex.quote(str(out))
        result = subprocess.run(['sh', '-c', code], capture_output=True, timeout=10)
        self.assertEqual(result.stdout, b'started\n')


    def test_isp_tune_helpers_validate_and_report(self):
        conf, boot, status = self.base / 'isp_tune.conf', self.base / 'boot.conf', self.base / 'status'
        conf.write_text((ROOT / 'config/isp_tune.conf.dist').read_text())
        boot.write_text('ISP_TUNE=1\n')
        status.write_text('BRIGHTNESS=20\nPOWER_HZ=50\nEXPOSURE_NOW=450\nEXPOSURE_ORIG=1125\n')
        env = 'ISP_TUNE_CONF=%s ISP_TUNE_BOOT=%s ISP_TUNE_STATUS=%s\n' % tuple(shlex.quote(str(x)) for x in (conf, boot, status))
        lib = env + function('scripts/common_functions.sh', 'rewrite_config') + '\nsync() { :; }\n' + (ROOT / 'scripts/isp-tune.sh').read_text()
        for key, val, ok in [('BRIGHTNESS', '20', '20'), ('BRIGHTNESS', '-50', '-50'), ('BRIGHTNESS', '51', None),
                             ('BRIGHTNESS', '1x', None), ('HUE', '', '0'), ('POWER_HZ', '60', '60'), ('POWER_HZ', '55', None),
                             ('EXPOSURE_MAX_PCT', '0', ''), ('EXPOSURE_MAX_PCT', '9', None), ('EXPOSURE_MAX_PCT', '40', '40'),
                             ('MASK1', '', ''), ('MASK2', '05,0,50,40', '5,0,50,40'), ('MASK3', '50,0,10,40', None),
                             ('MASK4', '0,0,101,40', None), ('MASK1', '0,0,50', None), ('MASK1', '1,2,3,4;reboot', None),
                             ('MASK_COLOR', 'white', 'white'), ('MASK_COLOR', 'mosaic', None)]:
            r = run(lib + '\nisp_tune_norm %s %s; echo "rc=$?"' % (key, shlex.quote(val)))
            out = r.stdout.decode().split('\n')
            if ok is None:
                self.assertIn('rc=1', out, (key, val))
            else:
                self.assertEqual(out[0], ok, (key, val)); self.assertIn('rc=0', out)
        self.assertEqual(run(lib + '\nisp_tune_set CONTRAST -12; isp_tune_set EXPOSURE_MAX_PCT 30; isp_tune_set HUE 99; echo "rc=$?"').stdout.strip(), b'rc=1')
        data = json.loads(run(lib + '\nisp_tune_json').stdout)
        self.assertEqual(data['enabled'], 1)
        self.assertEqual(data['conf']['CONTRAST'], -12)
        self.assertEqual(data['conf']['EXPOSURE_MAX_PCT'], 30)
        self.assertIsNone(data['conf']['POWER_HZ'])
        self.assertEqual(data['applied'], {'BRIGHTNESS': 20, 'POWER_HZ': 50, 'EXPOSURE_NOW': 450, 'EXPOSURE_ORIG': 1125})

    def test_isp_tune_mqtt_discovery_is_valid_json(self):
        s = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        block = s[s.index('  # Live image tuning (number/select/switch).'):s.index('  # Maintenance Entities (Buttons/Select)')]
        json_escape = function('www/cgi-bin/func.cgi', 'json_escape')
        code = (json_escape + '\nisp_tune_json() { :; }\nout=' + shlex.quote(str(self.base / 'disc')) +
                '\npublish_discovery_config() { printf "%s\\t%s\\n" "$1" "$2" >> "$out"; }\n'
                'MQTT_TOPIC_ROOT=cam/x; discovery_prefix=homeassistant; node_id=cam_x; device_name_json=Cam; device_id_json=cam_x\n'
                'cmd_json=cam/x/command; avail_topic_json=cam/x/availability\n')
        r = run(code + block)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = (self.base / 'disc').read_text().strip().split('\n')
        self.assertEqual(len(lines), 8)   # 6 numbers + anti-flicker removal + switch
        for line in lines:
            topic, payload = line.split('\t', 1)
            if '/select/' in topic:
                # anti-flicker is not applied on 3.0: an empty retained payload removes the old entity
                self.assertTrue(topic.endswith('/isp_power_hz/config'), topic)
                self.assertEqual(payload, '')
                continue
            d = json.loads(payload)
            self.assertEqual(d['stat_t'], 'cam/x/isp/state', topic)
            if '/number/' in topic:
                cmd = d['cmd_tpl'].replace('{{ value | int }}', '7')
                self.assertTrue(json.loads(cmd)['cmd'].startswith('isp_'))
        sw = json.loads([l for l in lines if '/switch/' in l][0].split('\t', 1)[1])
        self.assertEqual(json.loads(sw['pl_on']), {'cmd': 'isp_tune', 'value': 'on'})

    def test_diagnostic_discovery_is_valid_json(self):
        s = (ROOT / 'scripts/mqtt-bridge.sh').read_text()
        block = s[s.index('  # --- Diagnostics (value_json.diag'):s.index('  # --- Elite Integration Entities ---')]
        code = ('out=' + shlex.quote(str(self.base / 'diag')) +
                '\npublish_discovery_config() { printf "%s\\t%s\\n" "$1" "$2" >> "$out"; }\n'
                'discovery_prefix=homeassistant; node_id=cam_x; device_name_json=Cam; device_id_json=cam_x\n'
                'health_topic_json=cam/x/health; avail_topic_json=cam/x/availability\n')
        r = run(code + block)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = (self.base / 'diag').read_text().strip().split('\n')
        self.assertEqual(len(lines), 17)   # 14 sensors + 3 binary sensors
        for line in lines:
            topic, payload = line.split('\t', 1)
            d = json.loads(payload)
            self.assertEqual(d['stat_t'], 'cam/x/health', topic)
            self.assertIn('value_json.diag.', d['val_tpl'])
            self.assertEqual(d['dev']['ids'], ['cam_x'])
        ur = json.loads([l for l in lines if 'unexpected_restart/' in l][0].split('\t', 1)[1])
        self.assertEqual(ur['val_tpl'], '{{ "ON" if value_json.diag.last_boot == "unexpected" else "OFF" }}')
        self.assertEqual(ur['dev_cla'], 'problem')
        sd = json.loads([l for l in lines if 'sd_problem' in l][0].split('\t', 1)[1])
        self.assertEqual(sd['val_tpl'], '{{ "ON" if value_json.diag.sd_problem == 1 else "OFF" }}')

    def test_diag_payload_is_valid_json(self):
        fn = function('scripts/mqtt-bridge.sh', 'build_diag_payload')
        prelude = 'wifi_signal_read() { WIFI_DBM=-45; WIFI_QUAL=70; }; mock_meminfo="MemAvailable: 21500 kB"; '
        r = run(prelude + fn + '\nnow_ts=$(date +%s); build_diag_payload; printf "%s" "$diag_payload"')
        d = json.loads(r.stdout)
        for k in ('wifi_rssi_dbm', 'mem_available_kb', 'sound_db', 'light_level', 'sd_problem', 'last_boot', 'unexpected_restarts', 'rtsp_clients'):
            self.assertIn(k, d)

    def test_rtsp_probe_accepts_digest_challenge(self):
        reply = self.base / 'rtsp-reply'
        reply.write_bytes(b'RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm="LIVE555"\r\n\r\n')
        code = function('www/cgi-bin/state.cgi', 'rtsp_describe_local_ok')
        code += '\nRTSP_REPLY=' + shlex.quote(str(reply)) + '; export RTSP_REPLY; nc() { cat "$RTSP_REPLY"; }; rtsp_describe_local_ok video0_unicast 554 root pass 2'
        self.assertEqual(run(code).returncode, 0)

    def test_audio_write_targets_audio_not_video(self):
        source = action_cgi_text()
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
        self.assertEqual(writes, [(' ', 'volume', '7')])


    def test_motion_form_fields_are_read(self):
        # Settings → Motion & Sound posts these names; conf_motiondetect read
        # motionBlink (a name the form never sends) and ignored the sound fields.
        html = (ROOT / 'www/settings.html').read_text()
        form = html[html.index('id="formDetect"'):html.index('</form>', html.index('id="formDetect"'))]
        names = set(re.findall(r'name="([^"]+)"', form))
        cgi = action_cgi_text()
        handler = cgi[cgi.index('    conf_motiondetect)'):cgi.index('    ;;', cgi.index('    conf_motiondetect)'))]
        for n in names:
            self.assertIn('F_' + n, handler, n)


    def test_removed_features_stay_removed(self):
        # Removed in 2.1.9 (unused with Frigate, or needing internet): the old
        # ffmpeg recorder, timelapse, motion mail and snapshots, ONVIF event
        # push. (audio_stream.cgi came back for 3.0: the microphone through ALSA.)
        # (controlscripts/recording came back for 3.0: it switches the recorder inside tc100_rtsp, no ffmpeg.)
        for rel in ('controlscripts/timelapse', 'controlscripts/motion-mail',
                    'controlscripts/motion-snapshot', 'scripts/timelapse.sh', 'scripts/sendPictureMail.sh',
                    'scripts/onvif-notify.sh', 'bin/ffmpeg-min-recorder'):
            self.assertFalse((ROOT / rel).exists(), rel)
        self.assertNotIn('onvif-notify', (ROOT / 'scripts/motion-event.sh').read_text())
        self.assertNotIn('sendPictureMail', (ROOT / 'scripts/detectionOn.sh').read_text())


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

    def test_config_transaction_rejects_all_files_before_commit(self):
        stage, target, backup = (self.base / name for name in ('stage', 'target', 'backup'))
        stage.mkdir(); target.mkdir()
        (stage / 'boot.conf').write_text((ROOT / 'config/boot.conf.dist').read_text().replace('REBOOT_SCHEDULE_HOUR=4', 'REBOOT_SCHEDULE_HOUR=99'))
        (stage / 'mqtt.conf').write_text((ROOT / 'config/mqtt.conf.dist').read_text().replace('MQTT_QOS=0', 'MQTT_QOS=9'))
        original_boot = 'REBOOT_SCHEDULE_HOUR=4\n'
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
        code += '; tc_set_flat ' + shlex.quote(str(stage / 'boot.conf')) + ' REBOOT_SCHEDULE_HOUR 5'
        code += '; tc_set_ini ' + shlex.quote(str(rtsp)) + ' 0 fps 12'
        code += '; tc_set_ini ' + shlex.quote(str(rtsp)) + ' root imageflip 1'
        code += '; tc_validate_candidate rtspserver.conf ' + shlex.quote(str(rtsp))
        code += '; tc_commit_config_files ' + ' '.join(map(shlex.quote, [str(stage), str(target), str(backup), 'boot.conf mqtt.conf']))
        code += '; printf "%s" "$TC_COMMIT_COUNT"'
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'1')
        self.assertIn('REBOOT_SCHEDULE_HOUR=5', (target / 'boot.conf').read_text())
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
            '"imageflip"', '"RTSPLOGENABLED"', '"REC_LOCAL"', '"REC_WHEN"', '"REC_SEGMENT_SEC"',
            '"REC_RESERVE_MB"', '"REC_POSTROLL_SEC"', '"REC_OFFLINE_SEC"', '"REC_CLIENT"', '"REC_RING_KB"',
            '"LUMA_NIGHT"', '"DAYNIGHT_SOURCE"', '"NTFY_AUTH"', '"VOX_MODE"', '"TAMPER_HOLD_SEC"',
            '"WIFI_RESCUE_PSK"', '"MQTT_PASSWORD"', '"BRIGHTNESS"', '"BOOT_GUARD"']:
            self.assertIn(expected, source)
        # dead or removed settings must not come back
        for obsolete in ['"0_codec"', '"audioCodec0"', '"postrec";"record_post"', '"rec_postrecord_sec"',
                         '"rec_file_duration_sec"', '"rec_reserverd_disk_mb"', '"daynightlum"', '"nightdaylum"',
                         '"daynightawb"', '"nightdayawb"', 'PRIVACY_MODE']:
            self.assertNotIn(obsolete, source)
        self.assertIn('res && res.ok === true', (ROOT / 'www/backup.html').read_text())

    def config_exchange_code(self, entry='_ce_import'):
        names = ['_ce_cleanup', '_ce_fail', '_ce_truthy', '_ce_add_file',
                 '_ce_prepare_file', '_ce_row_table', '_ce_build_rows', '_ce_build_wpa', '_ce_export', '_ce_import']
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh')) + '\n'
        code += function('www/cgi-bin/func.cgi', 'urldecode') + '\n'
        code += 'json_body_err() { printf \'{"ok":false,"error":"%s","message":"%s"}\\n\' "$1" "$2"; }\n'
        code += '\n'.join(function('www/cgi-bin/config_exchange.cgi', name) for name in names)
        return code + '\n' + entry

    def exchange_env(self, cfg, **extra):
        env = dict(os.environ, CONFIG_ROOT=str(cfg), TC_CONFIG_ROOT=str(cfg), JSONFLAT=str(ROOT / 'scripts/jsonflat.awk'),
                   F_exclude_network='0', F_exclude_credentials='0', F_include_secrets='0')
        env.update(extra)
        return env

    def seed_config(self, names=None):
        cfg = self.base / 'config'; cfg.mkdir(exist_ok=True)
        for f in sorted((ROOT / 'config').glob('*.dist')):
            if names is None or f.name[:-5] in names:
                (cfg / f.name[:-5]).write_text(f.read_text())
        return cfg

    def import_json(self, cfg, doc, **extra):
        body = json.dumps(doc).encode()
        env = self.exchange_env(cfg, CONTENT_LENGTH=str(len(body)), **extra)
        r = run(self.config_exchange_code(), body, env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_json_import_applies_sections_and_rejects_whole_invalid_batch(self):
        cfg = self.seed_config()
        good = {'video': {'main': {'fps': 12, 'bitrate': 1000}},
                'recording': {'segment_sec': 600, 'when': 'always'},
                'secrets': {'telegram_token': '123:abc$def'}}
        res = self.import_json(cfg, good)
        self.assertTrue(res['transactional'], res)
        rtsp = (cfg / 'rtspserver.conf').read_text()
        self.assertRegex(rtsp, r'(?s)\[0\].*?\nbps=1000\n.*?\nfps=12\n')
        boot = (cfg / 'boot.conf').read_text()
        self.assertIn('\nREC_SEGMENT_SEC=600\n', boot)
        self.assertIn('\nREC_WHEN=always\n', boot)
        self.assertIn("apiToken='123:abc$def'", (cfg / 'telegram.conf').read_text())

        before_rtsp = rtsp
        bad = {'video': {'main': {'fps': 10}}, 'recording': {'segment_sec': 2}}
        self.assertEqual(self.import_json(cfg, bad)['error'], 'VALIDATION_FAILED')
        self.assertEqual((cfg / 'rtspserver.conf').read_text(), before_rtsp)

    def test_json_import_ignores_the_removed_web_mode_keys(self):
        # a backup made by an older version still carries boot.web_mode / boot.ultralite_port: it imports fine
        cfg = self.seed_config()
        res = self.import_json(cfg, {'boot': {'web_mode': 'full', 'ultralite_port': 8080, 'topology': 'dual'},
                                     'recording': {'segment_sec': 600}})
        self.assertTrue(res.get('ok'), res)
        boot = (cfg / 'boot.conf').read_text()
        self.assertIn('\nREC_SEGMENT_SEC=600\n', boot)
        self.assertNotIn('WEB_MODE', boot)
        self.assertNotIn('ULTRALITE_HTTP_PORT', boot)

    def test_camera_never_serves_or_builds_https_for_itself(self):
        # 3.0 serves plain HTTP on port 80 only; HTTPS is a reverse proxy on the owner's network.
        # Outgoing https:// to third parties (ntfy, GitHub, Telegram, webhooks) is client TLS and allowed.
        files = [ROOT / 'v3/autorun-linux66.sh']
        for d in ('scripts', 'controlscripts', 'www/cgi-bin', 'src/webui/index'):
            files += [p for p in sorted((ROOT / d).rglob('*')) if p.is_file() and p.suffix not in ('.png', '.bin', '.gz')]
        own = re.compile(r'https://(\$|127\.|localhost|10\.42\.|192\.168\.|"\s*\+\s*(location|window)|\$\{?(AP_IP|primary_ip|web_host))', re.I)
        port443 = re.compile(r'(?<![0-9A-Za-z.])443(?![0-9])')
        bad = []
        for p in files:
            for n, line in enumerate(p.read_text(errors='replace').splitlines(), 1):
                if own.search(line) or port443.search(line) or re.search(r'WEB_MODE|ULTRALITE_HTTP_PORT|lighttpd\.pem', line):
                    bad.append('%s:%d: %s' % (p.relative_to(ROOT), n, line.strip()[:120]))
        self.assertEqual(bad, [])
        # the one place that used to build the base URL
        self.assertIn('web_base_url="http://${web_host}"', (ROOT / 'www/cgi-bin/state.cgi').read_text())

    def test_json_import_validates_every_new_setting_strictly(self):
        cfg = self.seed_config()
        good = {
            'recording': {'local': 1, 'when': 'offline', 'stream': 'sub', 'segment_sec': 300, 'reserve_mb': 256,
                          'postroll_sec': 30, 'offline_sec': 5, 'client': '192.168.1.10', 'ring_kb': 1024, 'audio': 1},
            'daynight': {'luma_night': 30, 'luma_day': 90, 'source': 'ae', 'ae_night_above': 7000, 'ae_day_below': 2000,
                         'night_hold': 10, 'day_hold': 60, 'vendor_night_lum': 3584, 'vendor_day_lum': 1536,
                         'ir_led_max_on': 50400, 'night_style': 1, 'lowlight_fps': 0, 'ir_led_mode': 'auto'},
            'notify': {'ntfy_enabled': 1, 'ntfy_url': 'https://ntfy.sh', 'ntfy_priority': 'high', 'cooldown_sec': 30,
                       'events': 'motion tamper', 'webhook_method': 'PUT', 'attach_snapshot': 0},
            'tamper': {'enabled': 1, 'hold_sec': 8, 'jpeg_drop_pct': 40, 'luma_min': 12},
            'services': {'sound_det_threshold': -30, 'sound_det_interval': 3, 'sound_det_min_loud': 2, 'vox_mode': 1,
                         'vox_hold': 9, 'alarm_detect': 1, 'alarm_hold': 20},
            'isp': {'brightness': -5, 'contrast': 10, 'power_hz': 50, 'exposure_max_pct': 80, 'mask_color': 'gray',
                    'mask1': '0,0,25,30'},
            'wifi_rescue': {'enabled': 1, 'after_min': 10, 'manual_min': 15, 'ssid': 'Rescue cam'},
            'boot': {'boot_guard': 1, 'log_persist': 0, 'log_persist_min': 20, 'wifi_quality': 1, 'wifi_country': 'FR'}}
        res = self.import_json(cfg, good)
        self.assertTrue(res.get('ok'), res)
        for name, lines in {
            'daynight.conf': ['LUMA_NIGHT=30', 'DAYNIGHT_SOURCE=ae', 'AE_NIGHT_ABOVE=7000', 'IR_LED_MODE=auto'],
            'notify.conf': ['NTFY_PRIORITY="high"', 'NOTIFY_EVENTS="motion tamper"', 'NOTIFY_COOLDOWN_SECONDS=30',
                            'WEBHOOK_METHOD="PUT"'],
            'tamper.conf': ['ENABLE=1', 'TAMPER_HOLD_SEC=8'],
            'sound_detection.conf': ['THRESHOLD_DB=-30', 'VOX_MODE=1', 'ALARM_HOLD_SECONDS=20', 'MIN_LOUD_SECONDS=2'],
            'isp_tune.conf': ['BRIGHTNESS=-5', 'POWER_HZ=50', 'MASK1=0,0,25,30', 'MASK_COLOR=gray'],
            'boot.conf': ['REC_CLIENT=192.168.1.10', 'REC_STREAM=sub', 'WIFI_RESCUE_SSID="Rescue cam"', 'LOG_PERSIST=0',
                          'BOOT_GUARD=1', 'WIFI_COUNTRY=FR']}.items():
            text = (cfg / name).read_text()
            for line in lines:
                self.assertIn('\n' + line + '\n', '\n' + text, (name, line))
            self.assertEqual(subprocess.run(['/bin/sh', '-n', str(cfg / name)]).returncode, 0, name)

        # every one of these must be refused, and the files must not move
        snapshot = {f.name: f.read_bytes() for f in cfg.iterdir()}
        for bad in [
            {'recording': {'when': 'never'}}, {'recording': {'client': '999.1.1.1'}},
            {'recording': {'client': '1.2.3.4;reboot'}}, {'recording': {'ring_kb': 64}},
            {'daynight': {'source': 'x; id'}}, {'daynight': {'luma_day': 20, 'luma_night': 30}},
            {'notify': {'ntfy_url': 'https://x/$(id)'}}, {'notify': {'ntfy_url': 'ftp://host/'}},
            {'notify': {'events': 'motion; id'}}, {'notify': {'events': 'fire'}},
            {'secrets': {'telegram_token': "a'b"}},
            {'notify': {'ntfy_topic': 'a b'}}, {'notify': {'webhook_url': 'http://h/`id`'}},
            {'services': {'sound_det_threshold': 5}}, {'services': {'vox_hold': 0}},
            {'isp': {'brightness': 60}}, {'isp': {'mask1': '10,10,5,5'}}, {'isp': {'mask_color': 'red'}},
            {'wifi_rescue': {'ssid': 'a$(id)'}}, {'secrets': {'wifi_rescue_psk': 'pa"ss1234'}},
            {'wifi_rescue': {'after_min': 1}}, {'boot': {'log_persist': 'maybe'}},
            {'boot': {'wifi_country': 'fr'}}, {'boot': {'wifi_country': 'FRA'}}, {'boot': {'wifi_country': '$(id)'}}]:
            res = self.import_json(cfg, bad, F_include_secrets='1')
            self.assertIn(res.get('error'), ('VALIDATION_FAILED', 'TRANSACTION_FAILED'), bad)
            self.assertEqual({f.name: f.read_bytes() for f in cfg.iterdir()}, snapshot, bad)

    def test_json_import_secrets_and_exclude_credentials(self):
        cfg = self.seed_config()
        doc = {'secrets': {'mqtt_user': 'user1', 'mqtt_password': 'pw:with$chars', 'telegram_chat_id': '-1001',
                           'wifi_rescue_psk': 'rescue-psk-1',
                           'wifi': [{'ssid': 'Home net', 'psk': 'secret-psk-1'}, {'ssid': 'Open', 'psk': ''}]},
               'notify': {'ntfy_auth': 'Bearer tk_abc'}}
        doc['secrets']['camera_password'] = 'longpass1'
        # excluded: nothing credential-like is written (and the import has nothing left to apply)
        res = self.import_json(cfg, dict(doc, mqtt={'enabled': 1}), F_exclude_credentials='1')
        self.assertTrue(res['ok'], res)
        self.assertEqual(res['skipped'], 10, res)
        self.assertNotIn('pw:with', (cfg / 'mqtt.conf').read_text())
        self.assertFalse((cfg / 'wpa_supplicant.conf').exists())
        res = self.import_json(cfg, doc)
        self.assertTrue(res['ok'], res)
        self.assertIn("MQTT_PASSWORD='pw:with$chars'", (cfg / 'mqtt.conf').read_text())
        self.assertIn('WIFI_RESCUE_PSK="rescue-psk-1"', (cfg / 'boot.conf').read_text())
        wpa = (cfg / 'wpa_supplicant.conf').read_text()
        self.assertIn('ssid="Home net"', wpa)
        self.assertIn('psk="secret-psk-1"', wpa)
        self.assertRegex(wpa, r'ssid="Open"\n\tscan_ssid=1\n\tkey_mgmt=NONE')
        self.assertLess(wpa.index('Home net'), wpa.index('"Open"'))
        for bad in [{'secrets': {'wifi': [{'ssid': 'a"b', 'psk': 'secret-psk-1'}]}},
                    {'secrets': {'wifi': [{'ssid': 'ok', 'psk': 'short'}]}},
                    {'secrets': {'wifi': [{'psk': 'secret-psk-1'}]}},
                    {'secrets': {'camera_password': 'a b c d'}}, {'secrets': {'camera_password': 'abc'}},
                    {'secrets': {'camera_password': 'p"wd1'}}]:
            before = (cfg / 'wpa_supplicant.conf').read_bytes()
            res = self.import_json(cfg, bad)
            self.assertFalse(res.get('ok'), bad)
            self.assertEqual((cfg / 'wpa_supplicant.conf').read_bytes(), before, bad)

    def export_json(self, cfg, secrets):
        env = self.exchange_env(cfg, F_include_secrets='1' if secrets else '0')
        r = run(self.config_exchange_code('_ce_export'), None, env, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        def no_dupes(pairs):
            keys = [k for k, _ in pairs]
            self.assertEqual(len(keys), len(set(keys)), keys)
            return dict(pairs)
        return json.loads(r.stdout, object_pairs_hook=no_dupes), r.stdout.decode()

    def test_json_export_has_no_secrets_unless_asked_and_round_trips(self):
        cfg = self.seed_config()
        (cfg / 'mqtt.conf').write_text((cfg / 'mqtt.conf').read_text().replace('MQTT_USER=\n', "MQTT_USER='cam1'\n")
                                       .replace('MQTT_PASSWORD=\n', "MQTT_PASSWORD='mqttpw1'\n"))
        (cfg / 'telegram.conf').write_text('apiToken="777:TOKEN$X"\nuserChatId="4242"\nTELEGRAM_ENABLE=1\n')
        (cfg / 'user.pwd').write_text('camerapw1\n')
        (cfg / 'wpa_supplicant.conf').write_text(
            'ctrl_interface=/var/run/wpa_supplicant\nnetwork={\n\tssid="Home"\n\tscan_ssid=1\n\tkey_mgmt=WPA-PSK\n'
            '\tpsk="homepass123"\n\tpriority=2\n}\nnetwork={\n\tssid="Old"\n\tkey_mgmt=NONE\n\tpriority=1\n}\n')
        (cfg / 'notify.conf').write_text((cfg / 'notify.conf').read_text().replace('NTFY_AUTH=""', 'NTFY_AUTH="Bearer tk_9"')
                                         .replace('NTFY_TOPIC=""', 'NTFY_TOPIC="mytopic"'))
        plain, text = self.export_json(cfg, False)
        for secret in ['mqttpw1', 'cam1', 'TOKEN', '4242', 'camerapw1', 'homepass123', 'Home', 'tk_9', 'mytopic', 'tc100rescue']:
            self.assertNotIn(secret, text)
        self.assertNotIn('secrets', plain)
        self.assertFalse(plain['includes_secrets'])
        self.assertEqual(plain['telegram'], {'enabled': 1})
        self.assertEqual(plain['recording']['when'], 'offline')
        self.assertIn('segment_sec', plain['recording'])
        self.assertNotIn('privacy', plain.get('peripherals', {}))
        full, text = self.export_json(cfg, True)
        self.assertTrue(full['includes_secrets'])
        sec = full['secrets']
        self.assertEqual((sec['mqtt_user'], sec['mqtt_password'], sec['telegram_token'], sec['telegram_chat_id']),
                         ('cam1', 'mqttpw1', '777:TOKEN$X', '4242'))
        self.assertEqual(sec['camera_password'], 'camerapw1')
        self.assertEqual(sec['wifi'], [{'ssid': 'Home', 'psk': 'homepass123'}, {'ssid': 'Old', 'psk': ''}])
        self.assertEqual(sec['wifi_rescue_psk'], 'tc100rescue')
        self.assertEqual(full['notify']['ntfy_auth'], 'Bearer tk_9')
        self.assertEqual(full['notify']['ntfy_topic'], 'mytopic')

        # what one camera exports another camera imports, secrets included, and exports again unchanged
        cfg2 = self.base / 'config2'; cfg2.mkdir()
        for f in cfg.iterdir():
            (cfg2 / f.name).write_bytes(f.read_bytes())
        for name in ('mqtt.conf', 'telegram.conf', 'wpa_supplicant.conf', 'notify.conf'):
            (cfg2 / name).unlink()
        for f in (ROOT / 'config').glob('*.dist'):
            if f.name[:-5] in ('mqtt.conf', 'telegram.conf', 'notify.conf'):
                (cfg2 / f.name[:-5]).write_text(f.read_text())
        res = self.import_json(cfg2, full)
        self.assertTrue(res.get('ok'), res)
        again, _ = self.export_json(cfg2, True)
        self.assertEqual(again, full)

    def test_json_push_reads_its_form_and_sends_token_and_credentials(self):
        source = (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text()
        push = source[source.index('  push)'):]
        self.assertIn('_ce_form_get target', push)
        self.assertIn('_ce_form_get user', push)
        self.assertIn('_ce_form_get password', push)
        self.assertIn('F_include_secrets=0', push)
        self.assertIn('exclude_network=1&exclude_credentials=1', push)
        self.assertIn('-H "X-CSRF-Token: $_tok"', push)
        self.assertIn('-u "${_push_user}:${_push_password}"', push)
        html = (ROOT / 'www/backup.html').read_text()
        self.assertIn('X-CSRF-Token', html[html.index('syncBtn.addEventListener'):])
        # the CGIs of the old tar backup are gone; the full backup of 2026-11-05 is config_exchange.cgi cmd=archive/restore
        for gone in ('configbackup', 'upload_backup', 'conf-export', 'conf-import'):
            self.assertNotIn(gone, html)
            self.assertNotIn(gone, (ROOT / 'www/settings.html').read_text())
        self.assertIn('config_exchange.cgi?cmd=archive', html)

    def test_ptt_plays_through_alsa_and_leaves_rtsp_running(self):
        # The speaker is an ALSA playback substream: the microphone of the RTSP stream keeps going.
        source = (ROOT / 'www/cgi-bin/upload_audio.cgi').read_text()
        self.assertNotIn('rtsp-h26x', source)
        play = source.index('sh "$SPEAKER_PLAY" "$pcm_file" "$ptt_volume"')
        unlock = source.index('rmdir "$PTT_LOCK_DIR"', play)
        transfer = source.index('lock_acquired=0', unlock)
        self.assertLess(unlock, transfer)


    def test_stream_profile_health_uses_raw_rtsp_describe(self):
        source = action_cgi_text()
        start = source.index('rtsp_strict_describe_check() {')
        end = source.index('AUTO_STREAM_SELFTEST_BLOCKING_FAIL=', start)
        probe = source[start:end]
        self.assertIn("printf 'DESCRIBE %s RTSP/1.0", probe)
        self.assertIn('| nc -w "$rtsp_timeout"', probe)
        self.assertIn("*'RTSP/1.0 401 Unauthorized'*", probe)
        self.assertNotIn('/mnt/bin/curl', probe)

    def test_frigate_light_profile_matches_ak3918_budget(self):
        code = function('www/cgi-bin/action.cgi', 'select_compat_profile_values')
        code += '\nselect_compat_profile_values frigate-light-ak3918'
        code += '\nprintf "%s|%s|%s|%s|%s|%s|%s|%s|%s" "$codec0" "$width0" "$height0" "$fps0" "$bps0" "$codec1" "$fps1" "$bps1" "$rtsp_audio"'
        r = run(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b'2|1280|720|12|1000|2|8|320|0')


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


class WebUiLanguage(unittest.TestCase):
    """FR/EN switch: www/scripts/i18n.js + www/i18n/fr.js."""

    def test_every_ui_string_has_a_translation(self):
        r = subprocess.run([sys.executable, str(ROOT / 'src/webui/i18n-strings.py'), '--missing'],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '', 'add these to www/i18n/fr.js:\n' + r.stdout)

    def test_dictionary_is_valid(self):
        text = (ROOT / 'www/i18n/fr.js').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('window.tc100I18nFr = {'))
        data = json.loads(text[text.index('{'):text.rindex('}') + 1])
        for k, v in data['strings'].items():
            self.assertTrue(v.strip() or k.strip() == 'file.', k)
        for pattern, _ in data['rules']:
            re.compile(pattern)

    def test_pages_load_the_switch(self):
        index = (ROOT / 'www/index.html').read_text()
        self.assertIn('scripts/i18n.js?v=', index)
        self.assertIn('id="lang_toggle"', index)
        self.assertIn('/scripts/i18n.js?v=', (ROOT / 'www/cgi-bin/wizard.cgi').read_text(encoding='utf-8'))
        # the stamps are the files' md5 (src/webui/stamp-assets.sh): i18n.js by its own, fr.js inside i18n.js
        js = (ROOT / 'www/scripts/i18n.js').read_bytes()
        self.assertIn('i18n.js?v=' + hashlib.md5(js).hexdigest()[:8], index)
        version = re.search(r'VERSION = "([^"]+)"', js.decode()).group(1)
        self.assertEqual(version, hashlib.md5((ROOT / 'www/i18n/fr.js').read_bytes()).hexdigest()[:8])



class AutostartModes(unittest.TestCase):
    def test_autostart_entries_are_executable_in_git(self):
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-s', 'config/autostart'],
                             capture_output=True, text=True, check=True).stdout.split('\n')
        modes = {l.split()[3]: l.split()[0] for l in out if l.strip()}
        self.assertTrue(modes)
        for f, m in modes.items():
            self.assertEqual(m, '100755', f)


class JsonFlat(unittest.TestCase):
    """scripts/jsonflat.awk replaces jq on the flash firmware."""
    AWK = ROOT / 'scripts/jsonflat.awk'
    # the camera runs busybox awk; the others must agree (audit D1: a gawk-only pass proved nothing)
    AWKS = [a for a in (['busybox', 'awk'], ['mawk'], ['gawk'], ['original-awk'], ['awk'])
            if shutil.which(a[0]) and (a[0] != 'busybox' or subprocess.run(a + ['BEGIN{}'], capture_output=True).returncode == 0)]

    def flat(self, text, *args, awk=('awk',)):
        return subprocess.run([*awk, *args, '-f', str(self.AWK)], input=text.encode(), capture_output=True,
                              env=dict(os.environ, LC_ALL='C'))

    def test_paths_types_and_escapes(self):
        doc = '{"a":{"b":"x\\"y\\\\ \\u00e9\\ud83d\\ude00\\tz","n":-1.5e3,"t":true,"z":null},"l":[1,[2,{"k":"v"}],[]],"e":{}}'
        self.assertTrue(self.AWKS)
        for awk in self.AWKS:
            r = self.flat(doc, awk=awk)
            self.assertEqual(r.returncode, 0, (awk, r.stderr))
            lines = r.stdout.decode('utf-8').splitlines()
            self.assertEqual(lines, ['.a.b\ts\tx"y\\\\ \u00e9\U0001F600\\tz', '.a.n\tn\t-1.5e3', '.a.t\tb\ttrue',
                                     '.a.z\tz\t', '.l[0]\tn\t1', '.l[1][0]\tn\t2', '.l[1][1].k\ts\tv'], awk)

    def test_rejects_malformed_and_wrong_top_level(self):
        for awk in self.AWKS:
            for bad in ('{"a":1,}', '{"a" 1}', '[1', '{"a":"x}', '{} x', 'nul'):
                self.assertEqual(self.flat(bad, awk=awk).returncode, 2, (awk, bad))
            self.assertEqual(self.flat('[1]', '-v', 'require=object', awk=awk).returncode, 2, awk)
            self.assertEqual(self.flat('{"a":1}', '-v', 'require=object', awk=awk).returncode, 0, awk)


class EventLogQueries(unittest.TestCase):
    def test_last_matches_as_json(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'ev.jsonl'
            log.write_text('{"timestamp":100,"level":"info","msg":"a"}\n{"timestamp":200,"level":"error","msg":"b"}\n\n'
                           '{"timestamp":300,"level":"critical","msg":"c"}\n{"timestamp":400,"level":"info","msg":"d"}\n')
            def q(call):
                r = subprocess.run(['sh', '-c', '. %s >/dev/null 2>&1; %s' % (ROOT / 'scripts/event-logger.sh', call)],
                                   capture_output=True, text=True, env=dict(os.environ, EVENT_LOG_FILE=str(log)))
                return [e['msg'] for e in json.loads(r.stdout)]
            self.assertEqual(q('get_events_since 150 2'), ['c', 'd'])
            self.assertEqual(q('get_recent_events 10'), ['a', 'b', 'c', 'd'])
            self.assertEqual(q('get_error_events 0 5'), ['b', 'c'])
            self.assertEqual(q('get_error_events 250 5'), ['c'])



class SetupWizard(unittest.TestCase):
    """www/cgi-bin/wizard.cgi: the first-boot wizard's backend."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        (d / 'config').mkdir()
        (d / 'config/boot.conf').write_text('REC_LOCAL=0\nREC_WHEN=offline\n')
        (d / 'config/mqtt.conf.dist').write_text('MQTT_ENABLE=0\nMQTT_HOST=\n')
        (d / 'first').write_text('')
        (d / 'wpa.conf').write_text('network={\n\tssid="OldNet"\n\tpsk="oldpassword"\n\tpriority=2\n}\n')
        sc = d / 'scripts'; sc.mkdir()
        shutil.copy(ROOT / 'scripts/wifi-txt.sh', sc / 'wifi-txt.sh')
        (d / 'v3/install').mkdir(parents=True)
        (d / 'v3/install/install66.sh').write_text('#!/bin/sh\ncase "$1" in check) echo ok ;; run) touch "%s/installed" ;; esac\n' % d)
        (d / 'csrf').write_text('0123456789abcdef0123456789abcdef')   # the per-boot token (W4)
        self.env = dict(os.environ, WZ_CSRF_FILE=str(d / 'csrf'), WZ_FIRST_BOOT_FLAG=str(d / 'first'), WZ_CONFIG=str(d / 'config'), WZ_CARD=str(d),
                        WZ_SCRIPTS=str(sc), WZ_WIFI_CONF=str(d / 'wpa.conf'), TC100_STORAGE_FILE=str(d / 'storage'),
                        WZ_FLASHMODE=str(d / 'flashmode'))

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, body, token='0123456789abcdef0123456789abcdef'):
        env = dict(self.env, REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(body)), QUERY_STRING='')
        if token is not None:
            env['HTTP_X_CSRF_TOKEN'] = token
        r = subprocess.run(['sh', str(ROOT / 'www/cgi-bin/wizard.cgi')], input=body.encode(), capture_output=True, env=env)
        return json.loads(r.stdout.decode().split('\n\n', 1)[1])

    def test_full_answers_are_applied(self):
        from urllib.parse import urlencode
        r = self.post(urlencode(dict(profile='frigate_ha', rec='offline', wifi_ssid='New Net',
                                     wifi_pass='p@ss w0rd!', mqtt_host='192.0.2.5', mqtt_port='1883',
                                     frigate_url='192.0.2.9:5000/', flash_install='1')))
        self.assertEqual(r, {'ok': True, 'wifi': 'applied', 'flash': 'installing', 'password': 'unchanged'})
        boot = (self.d / 'config/boot.conf').read_text()
        self.assertIn('REC_LOCAL=1', boot); self.assertIn('REC_WHEN=offline', boot)
        self.assertNotIn('MQTT_ENABLE', boot)                             # mqtt.conf is its one place
        self.assertNotIn('WEB_MODE', boot)                                # no 2.x web mode key any more
        self.assertIn('MQTT_HOST=192.0.2.5', (self.d / 'config/mqtt.conf').read_text())
        self.assertIn('MQTT_ENABLE=1', (self.d / 'config/mqtt.conf').read_text())
        self.assertEqual((self.d / 'config/frigate_live.conf').read_text(), 'FRIGATE_URL=http://192.0.2.9:5000\nFRIGATE_CAMERA=\n')
        wpa = (self.d / 'wpa.conf').read_text()
        self.assertIn('ssid="New Net"', wpa); self.assertIn('psk="p@ss w0rd!"', wpa)
        self.assertIn('ssid="OldNet"', wpa)                               # fallback kept
        self.assertTrue((self.d / 'config/.wizard3_done').exists()); self.assertFalse((self.d / 'first').exists())
        for _ in range(120):
            if (self.d / 'installed').exists():
                break
            time.sleep(0.1)
        self.assertTrue((self.d / 'installed').exists())   # install66.sh run, 8 s after the answer
        self.assertFalse(self.post('profile=standalone')['ok'])   # once only

    def test_invalid_answers_write_nothing(self):
        before = (self.d / 'config/boot.conf').read_text()
        for body in ('profile=standalone&wifi_ssid=Net&wifi_pass=short',
                     'profile=standalone&wifi_ssid=a%22b&wifi_pass=12345678',
                     'profile=standalone&frigate_url=http://x%24y',
                     'profile=standalone&rec=sometimes'):
            self.assertFalse(self.post(body)['ok'], body)
        self.assertEqual((self.d / 'config/boot.conf').read_text(), before)
        self.assertIn('OldNet', (self.d / 'wpa.conf').read_text()); self.assertNotIn('Net"\n\tscan', (self.d / 'wpa.conf').read_text())
        self.assertTrue((self.d / 'first').exists())

    def test_minimal_answers_keep_wifi_and_recording(self):
        r = self.post('profile=nvr&rec=keep')
        self.assertEqual(r['wifi'], 'unchanged'); self.assertEqual(r['flash'], 'no')
        self.assertIn('REC_LOCAL=0', (self.d / 'config/boot.conf').read_text())
        self.assertNotIn('New', (self.d / 'wpa.conf').read_text())

    def test_info_and_flash_mode(self):
        env = dict(self.env, REQUEST_METHOD='GET', QUERY_STRING='info', PATH='/nonexistent:/usr/bin:/bin')
        out = subprocess.run(['sh', str(ROOT / 'www/cgi-bin/wizard.cgi')], capture_output=True, text=True, env=env).stdout
        info = json.loads(out.split('\n\n', 1)[1])
        self.assertEqual((info['first_boot'], info['storage'], info['flash'], info['card']), (True, 'sd', 'ready66', 1))
        (self.d / 'flashmode').write_text('')
        r = self.post('profile=standalone&flash_install=1')
        self.assertEqual(r['flash'], 'no')


class PasswordsStayOffTheBrowser(unittest.TestCase):
    def test_form_drafts_skip_password_fields(self):
        js = (ROOT / 'www/scripts/index.bundle.min.js').read_text()
        cache = js[js.index('function cacheFormState'):js.index('function restoreFormState')]
        self.assertIn("field.type !== 'password'", cache)
        restore = js[js.index('function restoreFormState'):js.index('function restoreFormState') + 1500]
        self.assertIn("field.type !== 'password'", restore)

    def test_password_command_refuses_unsafe_characters(self):
        src = action_cgi_text()
        block = src[src.index('    set_all_password)'):src.index('all_password "$password"')]
        pattern = re.search(r'\n        (\*\[.*?\]\*)\|', block).group(1)
        for pw, ok in (('Good-pass1', True), ('a b', False), ('a"b', False), ("a'b", False), ('a$b', False),
                       ('a`b', False), ('a\\b', False), ('a%b', False)):
            r = subprocess.run(['sh', '-c', 'case "$1" in %s) echo bad ;; *) echo ok ;; esac' % pattern, 'x', pw],
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), 'ok' if ok else 'bad', pw)


class LogForwarder(unittest.TestCase):
    """src/logfwd/tc100-logfwd.c built for the host: filter, repeats, rate limit, rotation."""

    @unittest.skipUnless(shutil.which('gcc'), 'gcc')
    def setUp(self):
        import socket
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        self.bin = d / 'logfwd'
        subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-o', str(self.bin),
                        str(ROOT / 'src/logfwd/tc100-logfwd.c')], check=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0)); self.sock.settimeout(0.3)
        self.log = d / 'messages'; self.log.write_text('')
        self.proc = None

    def tearDown(self):
        if self.proc:
            self.proc.terminate(); self.proc.wait(5)
        self.sock.close(); self.tmp.cleanup()

    def start(self, *extra):
        port = self.sock.getsockname()[1]
        self.proc = subprocess.Popen([str(self.bin), '-r', '127.0.0.1:%d' % port, '-f', str(self.log), '-b', *extra])
        time.sleep(0.3)

    def write(self, *lines):
        with open(self.log, 'a') as f:
            for l in lines:
                f.write('Oct 18 09:10:%02d CAM %s\n' % (len(l) % 60, l))

    def received(self, wait=1.0):
        out, end = [], time.time() + wait
        while time.time() < end:
            try:
                out.append(self.sock.recv(2048).decode())
            except OSError:
                pass
        return out

    def test_filter_repeats_and_pri(self):
        self.start('-w', '2')
        self.write('kern.info usb 1-1: new device', 'user.err tag: get frame failed',
                   'authpriv.info login[123]: root login on pts/0')
        for i in range(5):
            self.write('kern.err >50, sjf:46191%02d, ul:10' % i)
        got = self.received()
        self.assertFalse(any('usb 1-1' in g for g in got))                 # info: not forwarded
        self.assertIn('<11>', ''.join(got))                                 # user.err = 1*8+3
        self.assertTrue(any(g.startswith('<86>') and 'root login' in g for g in got))   # authpriv.info kept
        self.assertEqual(sum('sjf:' in g for g in got), 1)                 # digits ignored: one line
        self.assertTrue(got[0].startswith('<') and ' CAM ' in got[0])
        later = self.received(3.0)
        self.assertTrue(any('repeated 4 times' in g and 'sjf:' in g for g in later), later)

    def test_rate_limit(self):
        self.start('-m', '3')
        self.write(*['user.err tag: distinct message %s' % chr(65 + i) for i in range(6)])
        self.assertEqual(len(self.received()), 3)

    def test_follows_rotation_and_starts_at_the_end_without_b(self):
        self.write('user.err tag: before start')
        port = self.sock.getsockname()[1]
        self.proc = subprocess.Popen([str(self.bin), '-r', '127.0.0.1:%d' % port, '-f', str(self.log)])
        time.sleep(0.3)
        self.write('user.err tag: first')
        os.rename(self.log, str(self.log) + '.0')
        with open(str(self.log) + '.0', 'a') as f:
            f.write('Oct 18 09:10:59 CAM user.err tag: tail of the old file\n')
        time.sleep(0.2)
        self.log.write_text('Oct 18 09:11:00 CAM user.crit tag: after rotation\n')
        got = ''.join(self.received(3.5))
        self.assertNotIn('before start', got)
        for m in ('first', 'tail of the old file', 'after rotation'):
            self.assertIn(m, got)



class RtspServerChoice(unittest.TestCase):
    """Settings → Video → RTSP server: action.cgi set_rtsp_server / rtsp_server_info."""

    def test_form_fields_are_read_and_info_parses(self):
        import json
        html = (ROOT / 'www/settings.html').read_text()
        form = html[html.index('id="formRtspServer"'):html.index('</form>', html.index('id="formRtspServer"'))]
        cgi = action_cgi_text()
        h = cgi[cgi.index('    set_rtsp_server)'):cgi.index('    ;;', cgi.index('    set_rtsp_server)'))]
        for n in set(re.findall(r'name="([^"]+)"', form)):
            self.assertIn('F_' + n, h, n)
        for k in ('RTSP_SUBSTREAM', 'RTSP_LITE_TALK'):
            self.assertIn('rewrite_config /mnt/config/boot.conf %s' % k, h)
        info = cgi[cgi.index('    rtsp_server_info)') + len('    rtsp_server_info)'):cgi.index('    ;;', cgi.index('    rtsp_server_info)'))]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'boot.conf').write_text('RTSP_SUBSTREAM=0\nRTSP_LITE_TALK="1"\n')
            (d / 'rwconf').write_text('#!/bin/sh\necho 8554\n'); (d / 'rwconf').chmod(0o755)
            # two established connections to port 8554 (0x216A), one listening socket, one other port
            (d / 'tcp').write_text('  sl local rem st\n0: 0100007F:216A 0A000002:C000 01\n1: 0100007F:216A 0A000003:C001 01\n'
                                   '2: 00000000:216A 00000000:0000 0A\n3: 0100007F:0050 0A000002:C002 01\n')
            code = info.replace('/mnt/config/boot.conf', str(d / 'boot.conf')).replace('/mnt/bin/rwconf', str(d / 'rwconf')) \
                .replace('/proc/net/tcp', str(d / 'tcp'))
            r = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=10)
            j = json.loads(r.stdout)
        self.assertEqual(j, {'ok': True, 'server': 'tc100_rtsp', 'substream': 0, 'talk': 1, 'port': 8554, 'clients': 2,
                                 'idle_fps': 0, 'idle_after': 10, 'idle_when': 'still', 'motion_detection': 0})



class MotionZones(unittest.TestCase):
    """src/tc100fix/md.c (zones the vendor motion detection ignores) and its CGI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


    def run_cgi_block(self, fields, running=True):
        cgi = action_cgi_text()
        h = cgi[cgi.index('    conf_motiondetect)'):cgi.index('    ;;', cgi.index('    conf_motiondetect)'))]
        block = h[h.index('      if [ -n "${F_md_zone_form:-}" ]; then'):]
        info = cgi[cgi.index('    md_zones_info)') + len('    md_zones_info)'):cgi.index('    ;;', cgi.index('    md_zones_info)'))]
        d = self.d
        (d / 'md').write_text('#!/bin/sh\necho "$1" >> %s/md.calls\n[ "$1" = status ] && %s\nexit 0\n' % (d, 'echo "PID: 1"' if running else ':'))
        (d / 'md').chmod(0o755)
        (d / 'rtspserver.conf').write_text('mdenabled=1\n')
        (d / 'md_zones').write_text('starts=2 grid=32x24 sensitivity=60 ignored=96 result=area\n')
        code = ''.join('%s=%s\n' % (k, shlex.quote(v)) for k, v in fields.items())
        code += 'json_escape() { printf "%s" "$1"; }\n'
        code += (block + '\nwait\n' + info).replace('/mnt/config', str(d)).replace('/mnt/controlscripts/motion-detection', str(d / 'md')) \
                                     .replace('/var/run/md_zones', str(d / 'md_zones'))
        return subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=20)

    def test_cgi_saves_valid_zones_without_restarting_the_detector(self):
        import json
        r = self.run_cgi_block({'F_md_zone_form': '1', 'F_md_zone1': '0,0,50,25', 'F_md_zone2': 'x;rm -rf /',
                                'F_md_zone3': '', 'F_md_zone4': '10,10,20,20'})
        self.assertEqual((self.d / 'motion_zones.conf').read_text(), 'MDZ1="0,0,50,25"\nMDZ2="10,10,20,20"\n')
        self.assertIn('Motion zones: 2', r.stdout)
        # tc100_rtsp reads motion_zones.conf while it runs: the detector is not touched
        self.assertFalse((self.d / 'md.calls').exists())
        info = json.loads(r.stdout.splitlines()[-1])
        self.assertEqual(info['zones'], ['0,0,50,25', '10,10,20,20'])
        self.assertEqual(info['enabled'], 1)
        self.assertEqual(info['detector'], {'grid': '32x24', 'ignored': 96, 'result': 'area'})
        # same zones again: nothing rewritten, detector left alone
        self.run_cgi_block({'F_md_zone_form': '1', 'F_md_zone1': '0,0,50,25', 'F_md_zone2': '10,10,20,20'})
        self.assertFalse((self.d / 'md.calls').exists())
        # all removed: the file goes
        self.run_cgi_block({'F_md_zone_form': '1'}, running=False)
        self.assertFalse((self.d / 'motion_zones.conf').exists())



class NetGuard(unittest.TestCase):
    """scripts/net-guard.sh: reboot after a long network loss, with backoff."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        (d / 'boot.conf').write_text('NET_GUARD=1\nNET_GUARD_MIN=15\n')
        (d / 'route').write_text('Kernel IP routing table\n0.0.0.0 192.0.2.1 0.0.0.0 UG 0 0 0 wlan0\n')
        (d / 'ping').write_text('#!/bin/sh\necho "$@" >> %s/pings\n[ -f %s/net_ok ]\n' % (d, d)); (d / 'ping').chmod(0o755)
        for n in ('reboot', 'killwd'):
            (d / n).write_text('#!/bin/sh\necho %s >> %s/actions\n' % (n, d)); (d / n).chmod(0o755)
        (d / 'tracker.sh').write_text('echo "$@" >> %s/intents\n' % d)
        self.env = dict(os.environ, NG_BOOT_CONF=str(d / 'boot.conf'), NG_STATE=str(d / 'st'),
                        NG_PERSIST=str(d / 'persist'), NG_WR_RUN=str(d / 'wr'), NG_ROUTE_FILE=str(d / 'route'),
                        NG_PING=str(d / 'ping'), NG_REBOOT=str(d / 'reboot'), NG_KILLWD=str(d / 'killwd'),
                        NG_TRACKER=str(d / 'tracker.sh'), NG_FORCE_S='0', NG_RETRY_S='0')

    def tearDown(self):
        self.tmp.cleanup()

    def once(self, up):
        subprocess.run(['sh', str(ROOT / 'scripts/net-guard.sh'), 'once'], env=dict(self.env, NG_UPTIME=str(up)),
                       capture_output=True, timeout=10)
        time.sleep(0.1)

    def actions(self):
        p = self.d / 'actions'
        return p.read_text().split() if p.exists() else []

    def test_reboot_only_after_the_limit_then_backoff_then_reset(self):
        self.once(100)                        # first failure: start counting
        self.once(100 + 14 * 60)
        self.assertEqual(self.actions(), [])
        self.once(100 + 15 * 60)
        self.assertEqual(sorted(self.actions()), ['killwd', 'reboot'])
        self.assertEqual((self.d / 'persist').read_text().strip(), '1')
        self.assertIn('no network for 900 s', (self.d / 'intents').read_text())
        self.assertIn('192.0.2.1', (self.d / 'pings').read_text())
        # Next boot: the limit is now 30 min.
        shutil.rmtree(self.d / 'st'); (self.d / 'actions').unlink()
        self.once(60); self.once(60 + 29 * 60)
        self.assertEqual(self.actions(), [])
        self.once(60 + 30 * 60)
        self.assertIn('reboot', self.actions())
        self.assertEqual((self.d / 'persist').read_text().strip(), '2')
        # Network back for 10 min: count cleared.
        shutil.rmtree(self.d / 'st'); (self.d / 'net_ok').write_text('')
        self.once(60); self.assertTrue((self.d / 'persist').exists())
        self.once(60 + 600); self.assertFalse((self.d / 'persist').exists())

    def test_soft_repairs_before_the_reboot(self):
        """Item 17: NET_GUARD_SOFT=1, wlan0 present: reassociation at 2 min, wifi-apply at 5, USB probe at 8, once each"""
        d = self.d
        (d / 'sys/class/net/wlan0').mkdir(parents=True)
        (d / 'boot.conf').write_text('NET_GUARD=1\nNET_GUARD_MIN=15\nNET_GUARD_SOFT=1\n')
        (d / 'wpa_cli').write_text('#!/bin/sh\necho "wpa_cli $*" >> %s/soft\n' % d); (d / 'wpa_cli').chmod(0o755)
        (d / 'apply').write_text('echo apply >> %s/soft\n' % d)
        (d / 'recover').write_text('echo "recover $1" >> %s/soft\n' % d)
        self.env.update(NG_SYS=str(d / 'sys'), NG_WPA_CLI=str(d / 'wpa_cli'), NG_WIFI_APPLY=str(d / 'apply'),
                        NG_WIFI_RECOVER=str(d / 'recover'))
        soft = lambda: (d / 'soft').read_text().splitlines() if (d / 'soft').exists() else []
        self.once(100); self.once(100 + 60)
        self.assertEqual(soft(), [])
        self.once(100 + 120); self.once(100 + 180)
        self.assertEqual(soft(), ['wpa_cli -i wlan0 reassociate'])
        self.once(100 + 300); self.once(100 + 360)
        self.assertEqual(soft()[1:], ['apply'])
        self.once(100 + 480); self.once(100 + 600)
        self.assertEqual(soft()[2:], ['recover reprobe'])
        self.assertEqual(self.actions(), [])
        self.once(100 + 900)
        self.assertIn('reboot', self.actions())                       # still the last resort
        # network back: the steps start again at the next outage; off by default
        (d / 'net_ok').write_text(''); self.once(2000); (d / 'net_ok').unlink(); (d / 'soft').unlink()
        self.once(3000); self.once(3000 + 130)
        self.assertEqual(soft(), ['wpa_cli -i wlan0 reassociate'])
        (d / 'boot.conf').write_text('NET_GUARD=1\nNET_GUARD_MIN=15\n'); (d / 'soft').unlink()
        self.once(3000 + 400)
        self.assertEqual(soft(), [])

    def test_limit_capped_at_two_hours(self):
        (self.d / 'persist').write_text('9\n')
        r = subprocess.run(['sh', str(ROOT / 'scripts/net-guard.sh'), 'status'], env=dict(self.env, NG_UPTIME='10'),
                           capture_output=True, text=True)
        self.assertIn('limit_s=7200', r.stdout)

    def test_short_outage_no_default_route_and_off_switch(self):
        self.once(100); (self.d / 'net_ok').write_text('')
        self.once(100 + 10 * 60); (self.d / 'net_ok').unlink()
        self.once(100 + 20 * 60); self.once(100 + 30 * 60)
        self.assertEqual(self.actions(), [])              # counting restarted at 20 min
        (self.d / 'route').write_text('')                 # no default route = failure
        self.once(100 + 36 * 60)
        self.assertIn('reboot', self.actions())
        (self.d / 'actions').unlink(); shutil.rmtree(self.d / 'st')
        (self.d / 'boot.conf').write_text('NET_GUARD=0\n')
        self.once(10); self.once(10 + 3 * 3600)
        self.assertEqual(self.actions(), [])

    def test_never_while_rescue_access_point_is_up(self):
        (self.d / 'wr').mkdir()
        sleeper = subprocess.Popen(['sleep', '30'])
        try:
            (self.d / 'wr/hostapd.pid').write_text(str(sleeper.pid))
            self.once(100); self.once(100 + 3600)
            self.assertEqual(self.actions(), [])
        finally:
            sleeper.kill(); sleeper.wait()

    def test_web_guard_loop_calls_net_guard(self):
        wg = (ROOT / 'scripts/web-guard.sh').read_text()
        self.assertIn('net-guard.sh}" once', wg)
        self.assertIn('scripts/web-guard.sh', (ROOT / 'v3/autorun-linux66.sh').read_text())
        self.assertIn('NET_GUARD=1', (ROOT / 'config/boot.conf.dist').read_text())


class WebGuardAndSdHealth(unittest.TestCase):
    """scripts/web-guard.sh (rescue telnet) and scripts/sd-health.sh."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        (d / 'ports').write_text('')
        (d / 'common.sh').write_text(
            'port_listening() { grep -qx "$1" "%s/ports"; }\n'
            'http_server() { echo restart >> "%s/restarts"; }\n' % (d, d))
        (d / 'telnetd').write_text('#!/bin/sh\nexec sleep 300\n'); (d / 'telnetd').chmod(0o755)
        self.env = dict(os.environ, WG_COMMON=str(d / 'common.sh'), WG_STATE=str(d / 'st'),
                        WG_PIDFILE=str(d / 'rescue.pid'), WG_TELNETD=str(d / 'telnetd'),
                        WG_RESTART='http_server', TC100_STORAGE_FILE=str(d / 'storage'))

    def tearDown(self):
        pid = self.d / 'rescue.pid'
        if pid.exists():
            subprocess.run(['kill', pid.read_text().strip()], capture_output=True)
        self.tmp.cleanup()

    def guard(self):
        subprocess.run(['sh', str(ROOT / 'scripts/web-guard.sh'), 'once'], env=self.env, capture_output=True, timeout=10)

    def rescue_alive(self):
        p = self.d / 'rescue.pid'
        return p.exists() and subprocess.run(['kill', '-0', p.read_text().strip()], capture_output=True).returncode == 0

    def test_restart_then_rescue_telnet_then_closed_when_web_is_back(self):
        self.guard()
        self.assertEqual((self.d / 'restarts').read_text(), 'restart\n')
        self.assertFalse(self.rescue_alive())
        self.guard()
        self.assertTrue(self.rescue_alive())
        (self.d / 'ports').write_text('80\n')
        self.guard(); self.assertTrue(self.rescue_alive())          # one good check is not enough
        self.guard(); time.sleep(0.2); self.assertFalse(self.rescue_alive())
        self.assertEqual((self.d / 'restarts').read_text(), 'restart\n')

    def test_user_telnet_on_23_is_left_alone(self):
        (self.d / 'ports').write_text('23\n')
        self.guard(); self.guard()
        self.assertFalse((self.d / 'rescue.pid').exists())


class WebUiSources(unittest.TestCase):
    def test_index_bundle_is_built_from_src_webui_index(self):
        r = subprocess.run(['sh', str(ROOT / 'src/webui/build-index.sh'), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dash_endpoint_reads_proc_without_processes(self):
        # Polled every 5 s while the dashboard is open: shell built-ins only.
        body = (ROOT / 'www/cgi-bin/dash.cgi').read_text()
        self.assertNotIn('. /mnt/www/cgi-bin/func.cgi', body)
        self.assertEqual(body.count('$(') - body.count('$(('), 0)   # no command substitution (a fork)
        self.assertNotIn(' | ', body)                    # no pipeline
        for f in ('/proc/stat', '/proc/meminfo', '/proc/net/dev', '/mnt/scripts/wifi-signal.sh', '/proc/net/tcp'):
            self.assertIn(f, body)
        code = body
        tmp = tempfile.mkdtemp()
        try:
            script = Path(tmp) / 'dash.sh'; script.write_text(code)
            r = subprocess.run(['busybox', 'ash', str(script)] if shutil.which('busybox') else ['sh', str(script)],
                               capture_output=True, text=True)
            d = json.loads(r.stdout[r.stdout.index('{'):])   # after the CGI header
            self.assertEqual(len(d['cpu']), 7); self.assertEqual(len(d['mem']), 2); self.assertEqual(len(d['net']), 2)
        finally:
            shutil.rmtree(tmp)

    def test_statusline_and_func_cgi_avoid_subshells(self):
        s = (ROOT / 'www/cgi-bin/statelib.cgi').read_text()
        body = s[s.index('statusline_json() {\n'):]
        subshells = [l.strip() for l in body.splitlines() if '$(' in l.replace('$((', '')]
        # only the one-time CSRF token creation and the rare non-hex token clean-up
        self.assertEqual(len(subshells), 3, subshells)
        f = (ROOT / 'www/cgi-bin/func.cgi').read_text()
        self.assertIn('*%*|*+*) value="$(urldecode "${raw_value}")" ;;', f)
        self.assertIn('/tmp/.tc100-timeout-ok', f)
        # plain and encoded values still decode to the same thing
        sh = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']   # ${x//a/b}: ash, not dash
        r = subprocess.run(sh + ['-c', '. ' + str(ROOT / 'www/cgi-bin/func.cgi') + '; printf "%s|%s|%s" "$F_cmd" "$F_a" "$F_b"'],
                           env={'PATH': os.environ['PATH'], 'REQUEST_METHOD': 'GET',
                                'QUERY_STRING': 'cmd=statusline&a=x%20y%26z&b=1+2'}, capture_output=True, text=True)
        self.assertEqual(r.stdout.split('\n')[-1], 'statusline|x y&z|1 2')

    def test_home_views_and_settings_deep_links(self):
        js = (ROOT / 'www/scripts/index.bundle.min.js').read_text()
        self.assertIn('function showHome(view)', js)
        self.assertIn('leaveHome();\n        content.innerHTML = html;', js)   # home kept aside, not rebuilt
        self.assertIn('window.tc100SettingsTab', js)
        html = (ROOT / 'www/index.html').read_text()
        self.assertIn('id="view_dashboard"', html); self.assertIn('id="view_live"', html)
        self.assertIn("if (mode !== 'dark' && mode !== 'light') mode = 'dark';", html)
        self.assertIn('css/ui.pico.min.css?v=', html)   # the three sheets in one file (src/webui/build-css.sh)
        for old in ('css/ui.css', 'css/pico-shim.css', 'css/pico-2.0.6.min.css'):
            self.assertNotIn('href="' + old, html)



class CameraLogFindings(unittest.TestCase):
    """2026-10-16: what two cameras' logs showed (docs/known-issues.md)."""

    def tz(self, text):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'timezone.conf'; f.write_text(text)
            sh = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
            r = subprocess.run(sh + ['-c', '. %s; printf %%s "$TZ"' % (ROOT / 'scripts/update_timezone.sh')],
                               env=dict(os.environ, TIME_ZONE_CONFIG_FILE=str(f)), capture_output=True, text=True)
            return r.stdout


    @unittest.skipUnless(shutil.which('node'), 'node')
    def test_logs_page_tells_vendor_chatter_from_faults(self):
        src = (ROOT / 'www/logs.html').read_text()
        js = ("const src=require('fs').readFileSync(process.argv[1],'utf8');"
              "const a=src.indexOf('  var severityMeta'),b=src.indexOf('  var state = {');"
              "const c=src.indexOf('  function detectSeverity'),d=src.indexOf('  function extractTimeInfo');"
              "eval(src.slice(a,b)+src.slice(c,d));"
              "for (const l of JSON.parse(process.argv[2])) console.log(detectSeverity(l));")
        lines = ['Oct 16 18:35:10 anyka kern.err kernel: reg0x40, read:0x89',
                 'Oct 16 18:35:12 anyka user.emerg syslog:  group_type=1, index=589, ts=37040, enc_ts=36812',
                 'Oct 16 18:35:10 anyka user.err syslog:  [ak_cmd_register_module:741] no server was register, can not register module',
                 'Oct 16 18:45:25 IPCAMERA1 user.emerg syslog:  [wait_move_stable:193] not stable',
                 'Jan  1 00:00:15 anyka kern.warn kernel: RTW: module init start',
                 'Oct 16 11:56:44 cam kern.err kernel: mmcblk0: timed out sending r/w cmd command, card status 0x400e00',
                 'Oct 16 11:56:44 cam kern.warn kernel: mmc0: data(write) req failed (CMD25): -110, retrying(1)...',
                 'Oct 16 12:00:00 cam user.notice tc100: started']
        r = subprocess.run(['node', '-e', js, str(ROOT / 'www/logs.html'), json.dumps(lines)], capture_output=True, text=True)
        self.assertEqual(r.stdout.split(), ['known'] * 5 + ['error', 'warning', 'notice'], r.stderr)


class ForkLightLoops(unittest.TestCase):
    """The loops that run all day start (almost) no process: 525 -> 85 forks/min measured on a test camera."""

    def body(self, rel, name):
        src = (ROOT / rel).read_text()
        i = src.index(name + '()\n{'); j = src.index('\n}\n', i)
        return src[i:j]

    def test_sound_detection_loop(self):
        loop = self.body('controlscripts/sound-detection', 'run_daemon')
        tail = loop[loop.index('while :; do'):]
        self.assertNotRegex(tail.split('publish_sound_event')[0], r'\$\((?!\()')   # no command substitution
        self.assertIn('sd_wait "$interval"', loop)
        self.assertNotIn('sleep', tail)
        self.assertIn('-nt "$SD_STAMP"', self.body('controlscripts/sound-detection', 'load_config'))

    def test_waits_fall_back_to_sleep(self):
        for rel, name, var in (('controlscripts/sound-detection', 'sd_wait', 'SD_FIFO'),
                               ('scripts/mqtt-bridge.sh', 'mqtt_wait', 'MQTT_WAIT_FIFO')):
            with tempfile.TemporaryDirectory() as d:
                code = '%s=%s/fifo\n%s\n}\n%s 1\n' % (var, d, self.body(rel, name), name)
                t0 = time.time()
                subprocess.run(['sh', '-c', code], check=True, timeout=10)
                self.assertGreaterEqual(time.time() - t0, 0.9, rel)   # dash has no read -t: sleep

    def test_mqtt_spool_skipped_when_unchanged(self):
        drain = self.body('scripts/mqtt-bridge.sh', 'drain_command_spool')
        self.assertIn('[ "$_dc_mark" -nt "$_dc_file" ] && return 0', drain)
        self.assertLess(drain.index('-nt "$_dc_file"'), drain.index('wc -c'))


class ResetButton(unittest.TestCase):
    """scripts/button-watch.sh fed with struct input_event records through a FIFO."""

    def run_events(self, holds, storage='flash', cmd=None):
        import struct
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            data = b''
            t = 100
            for h in holds:
                data += struct.pack('<IIHHi', t, 0, 1, 11, 1) + struct.pack('<IIHHi', t, 0, 0, 0, 0)
                data += struct.pack('<IIHHi', t + h, 0, 1, 11, 0)
                t += h + 50
            os.mkfifo(d / 'ev')
            (d / 'storage').write_text(storage + '\n')
            for name, line in (('fc.sh', 'echo "fc $*"'), ('reboot', 'echo reboot')):
                (d / name).write_text('#!/bin/sh\n%s >> "%s/calls"\n' % (line, d)); (d / name).chmod(0o755)
            env = dict(os.environ, BUTTON_DEV=str(d / 'ev'), BUTTON_FLASH_CODE=str(d / 'fc.sh'),
                       BUTTON_REBOOT_CMD=str(d / 'reboot'), TC100_STORAGE_FILE=str(d / 'storage'))
            p = subprocess.Popen(cmd or ['sh', str(ROOT / 'scripts/button-watch.sh')], env=env)
            with open(d / 'ev', 'wb') as w:
                w.write(data); w.flush(); time.sleep(1.5)
            p.wait(timeout=10)
            return (d / 'calls').read_text().split('\n')[:-1] if (d / 'calls').exists() else []

    def test_hold_durations(self):
        self.assertEqual(self.run_events([3]), [])
        self.assertEqual(self.run_events([9]), ['reboot'])
        self.assertEqual(self.run_events([21]), ['fc clear', 'reboot'])
        self.assertEqual(self.run_events([21], storage='sd'), ['reboot'])


# (audit D7: LocalRecording tested src/tc100fix/rec.c, the 2.x recorder now on branch 2.x, and was always skipped;
# the 3.0 recorder src/tc100rtsp/rec.c is tested in tests/test_tc100rtsp.py)


class WifiTxt(unittest.TestCase):
    """scripts/wifi-txt.sh: Wi-Fi settings from wifi.txt on the SD card."""

    def apply(self, d, text, anyka=None):
        (d / 'sd').mkdir(exist_ok=True)
        (d / 'sd' / 'wifi.txt').write_bytes(text.encode())
        args = ['sh', str(ROOT / 'scripts/wifi-txt.sh'), 'apply', str(d / 'sd' / 'wifi.txt'), str(d / 'wpa.conf')]
        if anyka:
            (d / 'anyka.ini').write_text(anyka); args.append(str(d / 'anyka.ini'))
        return subprocess.run(args, capture_output=True, text=True).returncode

    def test_applies_keeps_fallbacks_and_removes_the_password(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rc = self.apply(d, 'SSID=Phone Hotspot\r\nPASSWORD="new secret 1"\r\n',
                            '[wireless]\nssid = Home\npassword = homepass99\n[ethernet]\nssid = x\n')
            self.assertEqual(rc, 0)
            conf = (d / 'wpa.conf').read_text()
            self.assertIn('ssid="Phone Hotspot"\n\tscan_ssid=1\n\tkey_mgmt=WPA-PSK\n\tpsk="new secret 1"\n\tpriority=2', conf)
            self.assertIn('ssid="Home"\n\tscan_ssid=1\n\tkey_mgmt=WPA-PSK\n\tpsk="homepass99"\n\tpriority=1', conf)
            self.assertNotIn('ssid="x"', conf)
            self.assertEqual(oct((d / 'wpa.conf').stat().st_mode & 0o777), '0o600')
            self.assertFalse((d / 'sd' / 'wifi.txt').exists())
            self.assertNotIn('new secret', (d / 'sd' / 'wifi-applied.txt').read_text())
            # a second file keeps the earlier networks as fallbacks, once each
            self.assertEqual(self.apply(d, 'SSID=Home\nPASSWORD=changed99\n'), 0)
            conf = (d / 'wpa.conf').read_text()
            self.assertEqual(conf.count('ssid="Home"'), 1)
            self.assertIn('psk="changed99"\n\tpriority=2', conf)
            self.assertIn('ssid="Phone Hotspot"', conf)

    def test_invalid_file_is_set_aside_and_conf_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'wpa.conf').write_text('old\n')
            self.assertEqual(self.apply(d, 'SSID=x\nPASSWORD=short\n'), 2)
            self.assertEqual((d / 'wpa.conf').read_text(), 'old\n')
            self.assertIn('8-63', (d / 'sd' / 'wifi-invalid.txt').read_text())
            self.assertFalse((d / 'sd' / 'wifi.txt').exists())
            self.assertEqual(self.apply(d, 'SSID=Open net\n'), 0)
            self.assertIn('key_mgmt=NONE', (d / 'wpa.conf').read_text())


class CameraPanel(unittest.TestCase):
    """camcontrols.cgi panel/set/mode (camera controls under the picture) and
    the regrouped Services page."""

    def run_cgi(self, d, method, query, body=b''):
        func = (ROOT / 'www/cgi-bin/func.cgi').read_text().replace('/tmp/csrf_token', str(d / 'csrf'))
        (d / 'func.cgi').write_text(func)
        src = (ROOT / 'www/cgi-bin/camcontrols.cgi').read_text().replace('/mnt/www/cgi-bin/func.cgi', str(d / 'func.cgi'))
        env = dict(os.environ, REQUEST_METHOD=method, QUERY_STRING=query, CONTENT_LENGTH=str(len(body)),
                   CONTENT_TYPE='application/x-www-form-urlencoded', HTTP_X_CSRF_TOKEN='ab12',
                   SCRIPT_HOME=str(d / 'cs'), PANEL_RUN=str(d / 'run'), PANEL_SYS=str(d / 'sys'),
                   PANEL_SETCONF=str(d / 'setconf'))
        r = subprocess.run(['bash', '-c', src], input=body, capture_output=True, env=env, timeout=20)
        out = r.stdout.split(b'\r\n\r\n', 1)
        return json.loads(out[1]) if len(out) == 2 else r.stdout

    def setup_fake(self, d):
        (d / 'csrf').write_text('ab12\n')
        for p in ('run', 'sys/user-gpio', 'sys/class/leds/blue_led', 'sys/class/leds/red_led', 'cs'):
            (d / p).mkdir(parents=True, exist_ok=True)
        def put(path, v): (d / path).write_text(v + '\n')
        # A fake camera: the controlscripts write the files the panel reads.
        put('n', '3')
        (d / 'setconf').write_text('#!/bin/sh\ncat "%s/n"\n' % d); (d / 'setconf').chmod(0o755)
        put('sys/user-gpio/ir-led', '0'); put('run/ircut', '1'); put('run/vday', '1')
        put('sys/class/leds/blue_led/brightness', '0'); put('sys/class/leds/red_led/brightness', '0')
        scripts = {
            'night-mode': ('echo 3 > %(d)s/n; echo 1 > %(d)s/sys/user-gpio/ir-led; echo 0 > %(d)s/run/ircut; echo 0 > %(d)s/run/vday',
                           'echo 3 > %(d)s/n; echo 0 > %(d)s/sys/user-gpio/ir-led; echo 1 > %(d)s/run/ircut; echo 1 > %(d)s/run/vday'),
            'auto-night-detection': ('echo 2 > %(d)s/n', 'echo 3 > %(d)s/n'),
            'front-led': ('echo 1 > %(d)s/sys/class/leds/blue_led/brightness', 'echo 0 > %(d)s/sys/class/leds/blue_led/brightness'),
        }
        for name, (on, off) in scripts.items():
            (d / 'cs' / name).write_text('case "$1" in start) %s ;; stop) %s ;; esac\necho "$0 $1" >> %s/calls\n'
                                         % (on % {'d': d}, off % {'d': d}, d))

    def test_panel_state_and_commands(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); self.setup_fake(d)
            st = self.run_cgi(d, 'GET', 'cmd=panel')
            self.assertEqual((st['mode'], st['ir-led'], st['ir-cut'], st['black-white'], st['front-led']), ('day', 0, 1, 0, 0))
            st = self.run_cgi(d, 'POST', '', b'cmd=mode&value=night')
            self.assertEqual((st['mode'], st['ir-led'], st['ir-cut'], st['black-white']), ('night', 1, 0, 1))
            st = self.run_cgi(d, 'POST', '', b'cmd=mode&value=auto')
            self.assertEqual(st['mode'], 'auto')
            st = self.run_cgi(d, 'POST', '', b'cmd=set&control=front-led&on=1')
            self.assertEqual(st['front-led'], 1)
            # only the five switches, and never without the CSRF token
            self.assertFalse(self.run_cgi(d, 'POST', '', b'cmd=set&control=rtsp-h26x&on=0')['ok'])
            calls = (d / 'calls').read_text()
            (d / 'csrf').write_text('ffff\n')
            r = self.run_cgi(d, 'POST', '', b'cmd=mode&value=day')
            self.assertEqual((d / 'calls').read_text(), calls)
            self.assertNotIn(b'"ok":true', r if isinstance(r, bytes) else json.dumps(r).encode())

    def test_services_page_grouped_without_camera_controls(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            src = (ROOT / 'www/cgi-bin/scripts.cgi').read_text().replace('/mnt/www/cgi-bin/func.cgi', str(ROOT / 'www/cgi-bin/func.cgi'))
            env = dict(os.environ, REQUEST_METHOD='GET', QUERY_STRING='', SCRIPT_HOME=str(ROOT / 'controlscripts'),
                       AUTOSTART_DIR=str(d))
            html = subprocess.run(['sh', '-c', src], capture_output=True, env=env, timeout=30).stdout.decode()
            rows = re.findall(r"<div class='svc-card' data-script-name='([^']+)'", html)
            self.assertIn('rtsp-h26x', rows)
            for hidden in ('night-mode', 'ir-led', 'ir-cut', 'black-white', 'front-led', 'red-led', 'auto-night-detection'):
                self.assertNotIn(hidden, rows)
            # item 46: three themed cards (core, network and access, integrations)
            group = lambda g: html.split("data-group='%s'" % g)[1].split('</section>')[0]
            self.assertIn("data-script-name='rtsp-h26x'", group('core'))
            self.assertIn("data-script-name='web-server'", group('core'))
            self.assertIn("data-script-name='ssh-server'", group('access'))
            self.assertIn("data-script-name='mqtt-bridge'", group('integrations'))
            # ONVIF and the rescue access point have no other switch: they stay in Services
            self.assertIn("data-script-name='onvif'", group('integrations'))
            self.assertIn("data-script-name='wifi-rescue'", group('access'))
            self.assertEqual(html.count('<section'), html.count('</section>'))
            for feature in ('motion-detection', 'sound-detection', 'telegram-bot'):
                self.assertNotIn(feature, rows)   # switched in their Settings tab
            self.assertNotIn('Camera Controls', html)

    def test_navigation(self):
        html = (ROOT / 'www/index.html').read_text()
        nav = html.split('id="common_nav"')[1].split('navbar-end')[0]
        self.assertLess(nav.index('id="dashboard_nav"'), nav.index('id="home_nav"'))
        # menus by use (2026-11-03): Image (live picture), Settings, Tools
        image = nav.split('<span>Image</span>')[1].split('<span>Settings</span>')[0]
        for tab in ('tab-image', 'tab-overlay', 'tab-daynight'):
            self.assertIn('data-tab="%s"' % tab, image)
        settings_menu = nav.split('<span>Settings</span>')[1].split('<span>Tools</span>')[0]
        for tab in ('tab-video', 'tab-detect', 'tab-record', 'tab-notify', 'tab-network', 'tab-integrations', 'tab-system'):
            self.assertIn('data-tab="%s"' % tab, settings_menu)
        tools = nav.split('<span>Tools</span>')[1]
        for page in ('data-tab="tab-backup"', 'id="services"', 'id="diagnostics"', 'id="logs"', 'id="configeditor"', 'cmd=reboot'):
            self.assertIn(page, tools)
        self.assertLess(nav.index('id="home_nav"'), nav.index('<span>Image</span>'))
        # every settings deep link names a section that exists
        settings = (ROOT / 'www/settings.html').read_text()
        for tab in re.findall(r'data-tab="([^"]+)"', nav):
            self.assertIn('id="%s"' % tab, settings)
        self.assertEqual(html.count('data-cam-control='), 5)
        self.assertIn('initCamPanel();', (ROOT / 'www/scripts/index.bundle.min.js').read_text())


class SettingsByUse(unittest.TestCase):
    """isp_pro split between Image and Day/night; local recording commands."""

    def test_isp_pro_writes_only_what_was_posted(self):
        text = action_cgi_text()
        block = action_arm('isp_pro')
        self.assertIn('if [ -n "${F_daynightlum}${F_nightdaylum}${F_dn_source}" ]; then', block)
        self.assertIn('if [ -n "${F_osd_form}" ]; then', block)
        self.assertLess(block.index('if [ -n "${F_daynightlum}'), block.index('/mnt/config/daynight.conf'))
        self.assertLess(block.index('/mnt/config/daynight.conf'), block.index('if [ -n "${F_osd_form}" ]'))
        self.assertLess(block.index('if [ -n "${F_osd_form}" ]'), block.index('setconf -k o'))
        self.assertIn('name="osd_form"', (ROOT / 'www/settings.html').read_text())
        # orientation alone (Settings -> Picture) is handled outside the osd_form block
        self.assertGreater(block.index('if [ -n "${F_imageflip+x}" ]'), block.index('setconf -k y'))

    def test_isp_tune_mask_only_form_keeps_the_tuning_switch(self):
        block = action_arm('isp_tune')
        self.assertNotIn('_it_masks', block)
        self.assertIn('_it_want="$(isp_tune_enabled)"', block)
        self.assertIn('if [ -n "${F_isp_enable+x}" ] || [ -n "${F_isp_brightness+x}" ]; then', block)
        html = (ROOT / 'www/settings.html').read_text()
        mask_form = html[html.index('id="formMasks"'):html.index('id="formISP"')]
        self.assertIn('name="isp_mask_form"', mask_form)
        for field in ('isp_enable', 'isp_brightness', 'isp_contrast'):
            self.assertNotIn('name="%s"' % field, mask_form)
        tune_form = html[html.index('id="formIspTune"'):html.index('id="formOrientation"')]
        self.assertNotIn('isp_mask_form', tune_form)

    def test_local_recording_commands(self):
        text = action_cgi_text()
        self.assertRegex(text, r'wifi_get_ssid\|wifi_rescue_info(\|wifi_country_info)?\|local_rec_status\|sd_card_info\|md_zones_info(\|motion_heatmap)?\|rtsp_server_info(\|events_info)?(\|hw_state)?(\|mem_budget)?\) ;;')     # read-only: no CSRF needed
        block = text[text.index('    set_local_recording)'):text.index('    local_rec_status)')]
        for key in ('REC_LOCAL', 'REC_WHEN', 'REC_STREAM', 'REC_SEGMENT_SEC', 'REC_RESERVE_MB'):
            self.assertIn('rewrite_config /mnt/config/boot.conf %s ' % key, block)
        self.assertNotIn('schedule_service_restart', block)        # tc100_rtsp reads them while it runs
        html = (ROOT / 'www/settings.html').read_text()
        for name in ('rec_local', 'rec_when', 'rec_stream', 'rec_segment_min', 'rec_reserve_mb'):
            self.assertIn('name="%s"' % name, html)
        self.assertIn('initServiceToggles: initServiceToggles,', (ROOT / 'www/scripts/index.bundle.min.js').read_text())



class SettingsLayout(unittest.TestCase):
    """Settings by use (2026-10-16): Image, Video, Day/night, Audio, Detection, Recording, Integrations,
    Network, System, Update & backup; Tools = Diagnostics / Logs / Services / Config editor."""

    def test_tabs_by_use_and_unique_ids(self):
        html = (ROOT / 'www/settings.html').read_text()
        tabs = re.findall(r'data-tab="([^"]+)"', html)
        # sidebar order (2.1.0): Image, Video & audio, Events, Network & integrations, System
        self.assertEqual(tabs, ['tab-image', 'tab-overlay', 'tab-daynight', 'tab-video', 'tab-detect', 'tab-record',
                                'tab-notify', 'tab-network', 'tab-integrations', 'tab-system', 'tab-backup'])
        self.assertIn('id="settings_search"', html)
        self.assertIn('window.tc100SettingsTab = ', html)
        def tab(t):
            a = html.index('id="%s"' % t)
            nxt = [html.index('id="%s"' % o, a + 1) for o in tabs if html.find('id="%s"' % o, a + 1) > 0]
            return html[a:min(nxt) if nxt else len(html)]
        self.assertIn('id="formIspTune"', tab('tab-image')); self.assertIn('id="formOrientation"', tab('tab-image'))
        self.assertNotIn('daynightlum', tab('tab-image')); self.assertNotIn('isp_mask1', tab('tab-image'))
        self.assertIn('id="formMasks"', tab('tab-overlay')); self.assertIn('id="formISP"', tab('tab-overlay'))
        self.assertNotIn('id="imageflip"', tab('tab-overlay'))
        self.assertNotIn('switches live tuning on', html)
        self.assertIn('id="formDayNight"', tab('tab-daynight')); self.assertIn('data-cam-panel', tab('tab-daynight'))
        self.assertIn('id="formAudioAdvanced"', tab('tab-video')); self.assertIn('id="dash_rtsp_link_0"', tab('tab-video'))
        self.assertNotIn('id="dash_rtsp_link_0"', tab('tab-integrations'))
        self.assertIn("'tab-audio': 'tab-video'", html)                      # old section id still lands somewhere
        self.assertIn('id="btnRecEject"', tab('tab-record')); self.assertIn('id="sd_card_box"', tab('tab-record'))
        self.assertIn('id="ha_discovery_badge"', tab('tab-integrations'))
        self.assertIn('id="wifiRescueInfo"', tab('tab-network'))
        self.assertLess(html.index('id="formPassword"'), html.index('id="formLeds"'))
        self.assertLess(html.index('id="formLeds"'), html.index('id="formRebootSchedule"'))
        self.assertLess(html.index('id="formRebootSchedule"'), html.index('id="formTuning"'))
        self.assertLess(html.index('id="formTuning"'), html.index('id="btnWizardReset"'))
        self.assertIn('data-service="motion-detection"', tab('tab-detect'))
        self.assertIn('id="formLocalRec"', tab('tab-record'))
        self.assertIn('id="fwuFile"', tab('tab-backup')); self.assertNotIn('id="fwuFile"', tab('tab-system'))
        for t in tabs:
            self.assertEqual(html.count('id="%s"' % t), 1, t)
        ids = re.findall(r'\bid=["\']([^"\']+)["\']', html.split('<script>')[0])
        dup = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dup, [])
        # every form that existed before the move is still there
        for form in ('formVideoAdvanced', 'formVideoSub', 'formAudioAdvanced', 'formISP', 'formIspTune', 'formMasks', 'formOrientation', 'formMQTT',
                     'formFrigateLive', 'formDetect', 'formTelegram', 'formSyslog', 'formNetwork',
                     'formTime', 'formTuning', 'formLeds', 'formRebootSchedule', 'preset_dropdown', 'fwuFile'):
            self.assertIn('id="%s"' % form, html)
        self.assertIn('network.cgi?part=settings', html)
        self.assertIn('data-src="backup.html"', html)

    def test_tools_menu_and_network_parts(self):
        index = (ROOT / 'www/index.html').read_text()
        for gone in ('cgi-bin/sysusageinfo.cgi', 'cgi-bin/devinfo.cgi', 'data-target="cgi-bin/network.cgi"',
                     'cgi-bin/disk.cgi', 'data-target="backup.html"'):
            self.assertNotIn(gone, index)
        self.assertIn('data-target="diagnostics.html"', index)
        diag = (ROOT / 'www/diagnostics.html').read_text()
        for src in ('sysusageinfo.cgi', 'devinfo.cgi', 'disk.cgi', 'network.cgi?part=diag'):
            self.assertIn(src, diag)
        net = (ROOT / 'www/cgi-bin/network.cgi').read_text()
        self.assertLess(net.index('if [ "$NET_PART" = settings ]'), net.index('connections_text="$(capture_limited_output'))  # settings part skips the probes
        js = (ROOT / 'www/scripts/index.bundle.min.js').read_text()
        self.assertIn('loadInto: loadInto,', js)
        self.assertNotIn('loadSubPage(', js)

class FrigateLiveAndSyslog(unittest.TestCase):
    """Settings: Frigate live link and remote syslog host, both written to sourced/parsed config."""

    def test_syslog_host_is_validated(self):
        text = action_cgi_text()
        block = action_arm('set_syslog_config')
        self.assertIn('*[!A-Za-z0-9.:-]*)', block)
        self.assertLess(block.index('syslog_err'), block.index('rewrite_config'))

    def test_frigate_live_link_in_statusline(self):
        state = state_text('www/cgi-bin/state.cgi')
        self.assertIn('\\"frigate_live\\":\\"$frigate_live\\"', state)
        action = action_cgi_text()
        self.assertIn('/mnt/config/frigate_live.conf', action)
        self.assertIn('id="live_frigate"', (ROOT / 'www/index.html').read_text())


class WebUiCss(unittest.TestCase):
    """The pages use one sheet, css/ui.pico.min.css (tests/test_css_bundle.py); the wizard keeps its own styles."""

    def test_wizard_has_its_own_styles(self):
        w = (ROOT / 'www/cgi-bin/wizard.cgi').read_text(encoding='utf-8')
        self.assertNotIn('ui.pico.min.css', w)
        self.assertNotIn('href="css/', w)                             # no sheet of the pages

class ServicesAndStatus(unittest.TestCase):
    def test_allstates_is_answered_without_a_script_name(self):
        # The Services page polls scripts.cgi?cmd=allstates with no script; the
        # handler used to sit inside the per-script branch, so it got the HTML
        # listing and every row stayed on "Loading...".
        s = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        self.assertLess(s.index('if [ "$F_cmd" = "allstates" ]'), s.index('if [ -n "$F_script" ]'))
        self.assertEqual(s.count('  emit_allstates_response\n'), 1)   # a single call site
        js = (ROOT / 'www/scripts/scripts.bundle.min.js').read_text()
        self.assertIn("fetch('cgi-bin/scripts.cgi?cmd=allstates'", js)

    def test_service_status_conventions(self):
        # status: output + rc 0 = running, no output + rc 0 or rc 1 = stopped.
        cgi = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        self.assertEqual(cgi.count('elif [ "$status_rc" -eq 1 ]; then'), 2)
        for name in ('telegram-bot',):
            s = (ROOT / 'controlscripts' / name).read_text()
            self.assertIn('[ "$1" = "status" ] || echo "You have to configure', s)
        r = run('PIDFILE=/nonexistent\n' + function('controlscripts/syslog-forward', 'status') + '\nstatus')
        self.assertEqual((r.returncode, r.stdout), (1, b''))
        ws = (ROOT / 'controlscripts/web-server').read_text()
        self.assertIn('pidof httpfront', ws)

    def test_dashboard_gateway_is_the_live_default_route(self):
        fn = function('www/cgi-bin/state.cgi', 'get_live_gateway')
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'route'
            hdr = 'Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n'
            for body, want in [('wlan0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n'
                                'wlan0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n', '192.168.1.1'),
                               ('wlan0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n', 'n/a')]:
                f.write_text(hdr + body)
                r = run(fn + '\nROUTE_PROC_FILE=%s; get_live_gateway' % shlex.quote(str(f)))
                self.assertEqual(r.stdout.decode().strip(), want)
        self.assertNotIn('get_cfg DEFAULT_GATEWAY', (ROOT / 'www/cgi-bin/state.cgi').read_text())

    def test_config_disabled_services_report_disabled(self):
        # memory-guard starts at boot but stays off until enabled in boot.conf:
        # status exits 3, shown as "Disabled", not as a problem.
        for name, var in (('memory-guard', 'MEM_GUARD_ENABLE'),):
            fn = function('controlscripts/' + name, 'status')
            for enable, want in (('0', 3), ('1', 0)):
                code = ('PIDFILE=/nonexistent\nis_truthy() { [ "$1" = 1 ]; }\n'
                        'load_config() { %s=%s; }\n' % (var, enable)) + fn + '\nstatus'
                self.assertEqual(run(code).returncode, want, (name, enable))
        cgi = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        self.assertEqual(cgi.count('state="disabled"'), 3)   # probe (x2) + fast path
        js = (ROOT / 'www/scripts/scripts.bundle.min.js').read_text()
        self.assertIn("case 'disabled':", js)
        self.assertIn('state === "disabled") return false;', js)

    def test_page_audit_regressions(self):
        logs = (ROOT / 'www/logs.html').read_text()
        self.assertIn('headers["X-CSRF-Token"] = token', logs)          # showlog POST was 403
        idx = (ROOT / 'www/scripts/index.bundle.min.js').read_text()
        self.assertIn("cmd=list_presets&format=json", idx)               # empty text -> JSON error
        self.assertIn("cmd=load_preset&format=json", idx)
        self.assertIn('xhr.open("GET", "cgi-bin/state.cgi?cmd=hostname', idx)  # logout did nothing
        svc = (ROOT / 'www/scripts/scripts.bundle.min.js').read_text()
        self.assertIn("cmd=source&script=", svc)                          # View opens a dialog
        self.assertNotIn("window.open(href, '_blank'", svc)
        cgi = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        self.assertIn('      source)\n', cgi)
        self.assertIn("-e 's/</\\&lt;/g'", cgi)                           # view page escapes markup
        health = (ROOT / 'www/cgi-bin/health.cgi').read_text()
        self.assertIn('[ -x "/mnt/controlscripts/$_as_name" ] || continue', health)
        # Gateway parsing of the /proc/net/route fallback format.
        net = (ROOT / 'www/cgi-bin/network.cgi').read_text()
        awk = re.search(r"default_gateway=\"\$\(printf '%s\\n' \"\$routes_text\" \| awk '(.*?)'\)\"", net).group(1)
        for text, want in (('Iface Destination Gateway\nwlan0 0.0.0.0 192.168.1.1 0003\n', '192.168.1.1'),
                           ('Destination Gateway Genmask\n0.0.0.0 192.168.1.1 0.0.0.0 UG\n', '192.168.1.1'),
                           ('default via 10.0.0.1 dev wlan0\n', '10.0.0.1')):
            r = subprocess.run(['awk', awk], input=text.encode(), capture_output=True)
            self.assertEqual(r.stdout.decode().strip(), want, text)
        # timeout shim resolves bare command names (busybox applet could not).
        for p in ('www/cgi-bin/func.cgi', 'scripts/common_functions.sh'):
            self.assertIn('_to_cmd="$(command -v "$1" 2>/dev/null)"', (ROOT / p).read_text())

    def test_allstates_fast_path(self):
        # Fast-path services must have a pidfile-only status(); the fast path
        # must agree with it (running iff the pidfile PID is alive).
        cgi = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        fast = re.search(r'FAST_PIDFILE_SERVICES=" ([^"]+) "', cgi).group(1).split()
        for name in fast:
            body = function('controlscripts/' + name, 'status')
            self.assertRegex(body, r'\$\{?(PIDFILE|PID_FILE)', name)
            self.assertNotRegex(body, r'(setconf|_status\b|_led |ir_cut|ir_led|motion_detection)', name)
        code = '\n'.join(function('www/cgi-bin/scripts.cgi', f) for f in
                         ('parse_script_capabilities', 'boot_conf_flag', 'fast_pidfile_state'))
        code = ('cd %s\n' % shlex.quote(str(ROOT))) + re.search(r'^FAST_PIDFILE_SERVICES=.*$', cgi, re.M).group(0) + '\n' + code
        code += '\n_svc_pid_uptime() { _svc_uptime_s=7; }\n'
        with tempfile.TemporaryDirectory() as d:
            live, dead = Path(d) / 'live.pid', Path(d) / 'dead.pid'
            live.write_text('%d\n' % os.getpid()); dead.write_text('999999\n')
            for pidfile, want in ((live, 'running 1 7'), (dead, 'stopped 0 -1'), (Path(d) / 'none', 'stopped 0 -1')):
                r = run(code + '\nparse_script_capabilities controlscripts/ftp-server; script_pidfile=%s; state=unknown; running=0; uptime_s=-1;'
                        ' fast_pidfile_state ftp-server; echo "$state $running $uptime_s"' % shlex.quote(str(pidfile)))
                self.assertEqual(r.stdout.decode().strip(), want, (pidfile, r.stderr))
            r = run(code + '\nparse_script_capabilities controlscripts/auto-night-detection; fast_pidfile_state auto-night-detection; echo "rc=$?"')
            self.assertEqual(r.stdout.decode().strip(), 'rc=1')

    def test_allstates_payload_and_caps_cache(self):
        cgi = (ROOT / 'www/cgi-bin/scripts.cgi').read_text()
        names = ['is_valid_script_name', '_svc_read_uptime_s', '_svc_pid_uptime', 'parse_script_capabilities',
                 'read_first', 'kv_value', 'fast_toggle_state', 'boot_conf_flag', 'fast_pidfile_state',
                 'ensure_caps_cache', 'generate_allstates_payload']
        code = re.search(r'^FAST_PIDFILE_SERVICES=.*$', cgi, re.M).group(0) + '\n'
        code += '\n'.join(function('www/cgi-bin/scripts.cgi', n) for n in names)
        code += '\nrun_status_probe() { echo "PROBED $1" >&2; return 1; }\n'
        with tempfile.TemporaryDirectory() as d:
            env = 'SCRIPT_HOME=%s; AUTOSTART_DIR=%s; CAPS_CACHE_FILE=%s/caps\n' % (
                shlex.quote(str(ROOT / 'controlscripts')), shlex.quote(d), shlex.quote(d))
            r = run(env + code + '\ngenerate_allstates_payload')
            data = json.loads(r.stdout)
            self.assertEqual(len(data['services']), len(list((ROOT / 'controlscripts').iterdir())))
            self.assertNotIn(b'PROBED', r.stderr)          # every script is on a fast path
            caps = (Path(d) / 'caps').read_text()
            self.assertIn('rtsp-h26x 1 1 1 /var/run/v4l2rtspserver.pid', caps)
            r2 = run(env + code + '\nparse_script_capabilities() { echo REPARSED >&2; }\ngenerate_allstates_payload')
            self.assertEqual(json.loads(r2.stdout), data)
            self.assertNotIn(b'REPARSED', r2.stderr)      # cache reused
        # The fast toggle paths read the same files as common_functions.sh.
        cf = (ROOT / 'scripts/common_functions.sh').read_text()
        for f in ('/sys/user-gpio/ir-led', '/var/run/ircut', '/var/run/vday', '/sys/class/leds/$2/brightness',
                  '/mnt/bin/setconf -g p'):
            self.assertIn(f, cf)

    def test_statusline_reports_wifi_quality(self):
        fn = function('www/cgi-bin/state.cgi', 'get_wifi_quality')
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'wireless'
            hdr = ('Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n'
                   ' face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n')
            cases = [(' wlan0: 0000   86.   78.    0.       0      0      0      0      0        0\n'
                      ' wlan1: 0000    0.    0.    0.       0      0      0      0      0        0\n', '86 wlan0'),
                     (' wlan1: 0000    0.    0.    0.       0      0      0      0      0        0\n', 'null '),
                     (' wlan1: 0000   40.   30.    0.       0      0      0      0      0        0\n', '40 wlan1'),
                     (' wlan0: 0000  120.   78.    0.       0      0      0      0      0        0\n', '100 wlan0'),
                     ('', 'null ')]
            for body, want in cases:
                f.write_text(hdr + body)
                r = run('. %s\n' % (ROOT / 'scripts/wifi-signal.sh') + fn + '\nWIFI_PROC_FILE=%s; get_wifi_quality; echo "$wifi_qual_json $wifi_iface_json"' % shlex.quote(str(f)))
                self.assertEqual(r.stdout.decode().strip('\n'), want, body)
        s = state_text('www/cgi-bin/state.cgi')
        self.assertIn('\\"wifi_qual\\":$wifi_qual_json', s)

class ActionCommandFiles(unittest.TestCase):
    """action.cgi only reads the file of the requested command (scripts/action.d)."""

    ARM = re.compile(r'^ {4,5}([^ #()\n][^()\n]*)\)[ \t]*$', re.M)

    def routes(self):
        cgi = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        block = cgi[cgi.index('Each command lives in scripts/action.d'):]
        block = block[:block.index('  fi\n')]
        out = {}
        for pats, group in re.findall(r'^    ([^ *][^)]*)\)\n      _action_group=([a-z]+) ;;$', block, re.M):
            for p in pats.split('|'):
                self.assertNotIn(p, out, p)
                out[p] = group
        return out

    def test_every_command_is_routed_to_the_file_that_has_it(self):
        routes = self.routes()
        found = {}
        for f in sorted((ROOT / 'scripts/action.d').glob('*.sh')):
            for pats in self.ARM.findall(f.read_text()):
                for p in pats.split('|'):
                    self.assertNotIn(p, found, p)
                    found[p] = f.stem
        self.assertEqual(found, routes)
        self.assertGreater(len(routes), 80)

    def test_no_command_left_in_action_cgi(self):
        cgi = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        main = cgi[cgi.index('if [ -n "$F_cmd" ]; then'):]
        # only the routing patterns are left: each one is followed by its group
        self.assertEqual(len(self.ARM.findall(main)), main.count('      _action_group='))
        self.assertNotIn('    showlog)\n      if', main)
        self.assertIn('. "/mnt/scripts/action.d/$_action_group.sh"', main)
        # the checks run before any command file is read
        self.assertLess(main.index('csrf_check'), main.index('_action_group='))

    def test_files_parse_with_the_camera_shell(self):
        for f in sorted((ROOT / 'scripts/action.d').glob('*.sh')):
            r = subprocess.run(['sh', '-n', str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (f.name, r.stderr))

    @unittest.skipUnless(shutil.which('busybox'), 'busybox')
    def test_read_commands_answer_through_their_file(self):
        with tempfile.TemporaryDirectory() as d:
            mnt = Path(d) / 'mnt'
            shutil.copytree(ROOT / 'www', mnt / 'www')
            shutil.copytree(ROOT / 'scripts', mnt / 'scripts')
            (mnt / 'config').mkdir()
            (mnt / 'config/pttvolume.conf').write_text('55\n')
            cgi = mnt / 'www/cgi-bin/action.cgi'
            cgi.write_text(cgi.read_text().replace('/mnt/', str(mnt) + '/'))
            def get(q):
                env = dict(os.environ, REQUEST_METHOD='GET', QUERY_STRING=q, REMOTE_ADDR='127.0.0.%d' % (len(q) % 200 + 2))
                return subprocess.run(['busybox', 'sh', str(cgi)], cwd=d, env=env, capture_output=True,
                                      text=True, timeout=20).stdout
            self.assertIn('"message":"55"', get('cmd=get_ptt_vol&format=json'))
            self.assertIn('"zones":[]', get('cmd=md_zones_info&format=json'))
            self.assertIn('"ssid"', get('cmd=wifi_get_ssid&format=json'))


class NetworkAccessFilter(unittest.TestCase):
    """LAN-only access: src/netacl (accept/bind filter) and its shell side."""

    def test_filter_only_preloaded_into_uclibc_programs(self):
        # libnetacl.so is a uClibc library: in a musl program (the 3.0 base system) it would load a second libc.
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d) / 'libnetacl.so'; lib.write_text('')
            for name, head, want in (('uc', '\x7fELF /lib/ld-uClibc.so.0', lib.as_posix()), ('mu', '\x7fELF /lib/ld-musl-arm.so.1', '')):
                prog = Path(d) / name
                prog.write_text('#!/bin/sh\n# %s\necho "preload=$LD_PRELOAD"\n' % head); prog.chmod(0o755)
                code = (function('scripts/common_functions.sh', 'netacl_exec') +
                        '\nnetacl_lib() { printf %%s %s; }\nnetacl_allow_list() { printf 10.0.0.0/8; }\nnetacl_exec t %s'
                        % (shlex.quote(str(lib)), shlex.quote(str(prog))))
                self.assertEqual(run(code).stdout.decode().strip(), 'preload=' + want, name)

    @unittest.skipUnless(shutil.which('gcc'), 'gcc')
    def test_filter_refuses_outside_the_list_and_never_locks_out(self):
        import socket
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d) / 'netacl.so'
            subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', '-o', str(lib),
                            str(ROOT / 'src/netacl/netacl.c'), '-ldl'], check=True)
            srv = Path(d) / 'srv.py'
            srv.write_text(
                'import socket, sys, os\n'
                's = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n'
                's.bind(("0.0.0.0", 0)); s.listen(4); print(s.getsockname()[1], int("LD_PRELOAD" in os.environ), flush=True)\n'
                'b = socket.socket(); b.bind(("0.0.0.0", int(sys.argv[1]))); print(b.getsockname()[0], flush=True)\n'
                'while True:\n'
                '    try: c, a = s.accept(); break\n'
                '    except ConnectionAbortedError: pass\n'
                'print("accepted", a[0], flush=True)\n')
            try:
                me = socket.gethostbyname(socket.gethostname())
            except OSError:
                me = ''
            if not me or me.startswith('127.'):
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.connect(('192.0.2.1', 9)); me = probe.getsockname()[0]
                except OSError:
                    self.skipTest('no non-loopback address')
                finally:
                    probe.close()
            def run(allow, local_ports=''):
                free = socket.socket(); free.bind(('127.0.0.1', 0)); lp = free.getsockname()[1]; free.close()
                env = dict(os.environ, LD_PRELOAD=str(lib), TC100_NET_ALLOW=allow,
                           TC100_NET_LOCAL_PORTS=local_ports.replace('PORT', str(lp)), TC100_NET_STATUS=str(Path(d) / 'st'))
                pr = subprocess.Popen([sys.executable, str(srv), str(lp)], env=env, stdout=subprocess.PIPE, text=True)
                port, preload = pr.stdout.readline().split()
                bound = pr.stdout.readline().strip()
                for host in (me, '127.0.0.1'):
                    try:
                        socket.create_connection((host, int(port)), timeout=2).close()
                    except OSError:
                        pass
                out = pr.stdout.readline().strip()
                pr.kill(); pr.wait(); pr.stdout.close()
                return out, preload, bound
            self.assertEqual(run('')[0], 'accepted ' + me)                  # no list: no filter
            self.assertEqual(run('not-a-network')[0], 'accepted ' + me)     # unreadable list: no filter
            self.assertEqual(run(me + '/32')[0], 'accepted ' + me)
            out, preload, _ = run('203.0.113.0/24')                         # outside: refused, loopback still in
            self.assertEqual(out, 'accepted 127.0.0.1')
            self.assertEqual(preload, '0')                                  # not passed on to children
            self.assertIn('refused=1 last=' + me, (Path(d) / 'st').read_text())
            self.assertEqual(run('', 'PORT')[2], '127.0.0.1')               # local-only port
            self.assertEqual(run('', '1')[2], '0.0.0.0')

    def test_allow_list_from_boot_conf(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / 'boot.conf'
            code = function('scripts/common_functions.sh', 'read_kv_config_value') + '\n'
            code += function('scripts/common_functions.sh', 'netacl_allow_list').replace('/mnt/config/boot.conf', str(conf)) + '\n'
            code += 'NETACL_PRIVATE="10.0.0.0/8 192.168.0.0/16"\nnetacl_allow_list'
            conf.write_text('X=1\n')
            self.assertEqual(run(code).stdout, b'10.0.0.0/8 192.168.0.0/16')    # on by default
            conf.write_text('NET_LAN_ONLY=0\n')
            self.assertEqual(run(code).stdout, b'')
            conf.write_text('NET_LAN_ONLY=1\nNET_ALLOW_EXTRA="203.0.113.7/32 198.51.100.0/24"\n')
            self.assertEqual(run(code).stdout, b'10.0.0.0/8 192.168.0.0/16 203.0.113.7/32 198.51.100.0/24')


    def test_autoclose_stops_the_service(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / 'boot.conf'; conf.write_text('REMOTE_SHELL_TIMEOUT_MIN=0\n')
            code = function('scripts/common_functions.sh', 'read_kv_config_value') + '\n'
            code += function('scripts/common_functions.sh', 'service_autoclose').replace('/mnt/config/boot.conf', str(conf)).replace('/var/run/', d + '/') + '\n'
            code += 'service_autoclose x; ls ' + d
            self.assertNotIn(b'x.autoclose', run(code).stdout)                 # 0 = never
            conf.write_text('REMOTE_SHELL_TIMEOUT_MIN=15\n')
            code2 = code.replace('ls ' + d, 'cat ' + d + '/x.autoclose; kill $(cat ' + d + '/x.autoclose)')
            self.assertRegex(run(code2).stdout, rb'^\d+')


if __name__ == '__main__':
    unittest.main()


class SdWear(unittest.TestCase):
    """Routine logs stay in RAM; the SD card only gets rare, useful writes."""

    def tracker(self, d, *args):
        env = dict(os.environ, REBOOT_TRACKER_DIR=str(Path(d) / 'sd'),
                   REBOOT_TRACKER_MARK=str(Path(d) / 'ram' / 'important.last'),
                   REBOOT_TRACKER_SYSLOG='%s %s' % (Path(d) / 'messages.0', Path(d) / 'messages'))
        return subprocess.run(['/bin/sh', str(ROOT / 'scripts/reboot-tracker.sh')] + list(args),
                              capture_output=True, timeout=8, env=env)

    def test_only_new_critical_lines_reach_the_card(self):
        with tempfile.TemporaryDirectory() as d:
            msgs = Path(d) / 'messages'
            noise = 'Oct 13 18:00:0%d anyka kern.info kernel: akotg_usbhc_hub_status_data\n'
            msgs.write_text(noise % 1 +
                            'Jan  1 00:00:04 anyka kern.info kernel:  mmcblk0: p1\n' +
                            'Oct 13 18:00:02 anyka kern.err kernel: FAT-fs (mmcblk0p1): error\n' +
                            noise % 3)
            self.tracker(d, 'flush')
            imp = Path(d) / 'sd' / 'important.log'
            self.assertEqual(imp.read_text().count('\n'), 1)
            self.assertIn('FAT-fs', imp.read_text())
            before = imp.stat().st_mtime_ns
            self.tracker(d, 'flush')                      # nothing new: no write
            self.assertEqual(imp.stat().st_mtime_ns, before)
            with msgs.open('a') as f:
                f.write('Oct 13 18:05:00 anyka user.err tc100-event: rtsp: GOP stall\n')
            self.tracker(d, 'flush')
            self.assertEqual(imp.read_text().count('\n'), 2)
            self.assertNotIn('usbhc', imp.read_text())
            # Marker rotated out of the RAM log (or a new boot): all matches are new.
            msgs.write_text('Oct 13 19:00:00 anyka kern.err kernel: Out of memory: Killed process 808\n')
            self.tracker(d, 'flush')
            self.assertEqual(imp.read_text().count('\n'), 3)

    def test_heartbeat_is_rewritten_in_place_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            self.tracker(d, 'heartbeat')
            hb = Path(d) / 'sd' / '.heartbeat'
            self.assertEqual(hb.stat().st_size, 64)
            ino = hb.stat().st_ino
            self.tracker(d, 'heartbeat')
            self.assertEqual((hb.stat().st_size, hb.stat().st_ino), (64, ino))
            env = dict(os.environ, REBOOT_TRACKER_DIR=str(Path(d) / 'sd'),
                       REBOOT_TRACKER_LAST=str(Path(d) / 'last'))
            subprocess.run(['/bin/sh', str(ROOT / 'scripts/reboot-tracker.sh'), 'boot'], env=env, timeout=8)
            line = (Path(d) / 'last').read_text()
            self.assertRegex(line, r'MemAvailable [0-9]+ kB\n$')       # padding trimmed

    def test_boot_line_names_a_failing_sd_card(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'sdh').write_text('state=errors\nerrors=42\n')
            env = dict(os.environ, REBOOT_TRACKER_DIR=str(Path(d) / 'sd'), SDH_OUT=str(Path(d) / 'sdh'),
                       REBOOT_TRACKER_LAST=str(Path(d) / 'last'))
            subprocess.run(['/bin/sh', str(ROOT / 'scripts/reboot-tracker.sh'), 'heartbeat'], env=env, timeout=8)
            subprocess.run(['/bin/sh', str(ROOT / 'scripts/reboot-tracker.sh'), 'boot'], env=env, timeout=8)
            self.assertIn('SD card errors (42 kernel errors): likely cause', (Path(d) / 'last').read_text())


    def test_stability_samples_are_batched(self):
        with tempfile.TemporaryDirectory() as d:
            sd, ram = Path(d) / 'stability.csv', Path(d) / 'pending'
            code = ('STABILITY_FILE=%s; STABILITY_PENDING=%s; STABILITY_MAX_SAMPLES=576\n'
                    % (shlex.quote(str(sd)), shlex.quote(str(ram))) +
                    function('scripts/health-snapshot.sh', 'stability_flush') +
                    '\nfor i in 1 2 3; do echo "$i,0,0,0,0" >> "$STABILITY_PENDING"; done\n'
                    'stability_flush')
            self.assertEqual(run(code).returncode, 0)
            self.assertEqual(sd.read_text().count('\n'), 4)        # header + 3
            self.assertEqual(ram.read_text(), '')


class MqttFastPath(unittest.TestCase):
    """Publishes reuse the persistent listener connection when it is up."""

    def run_pub(self, d, topic, payload, retain='0', session=True, connack=b'\x20\x02\x00\x00'):
        raw = Path(d) / 'stream.bin'
        fifo = Path(str(raw) + '.input')
        if session:
            os.mkfifo(fifo)
            (Path(str(raw) + '.session')).write_text('3\n')
            (Path(str(raw) + '.ready')).write_text('3\n')
            (Path(str(raw) + '.3')).write_bytes(connack + b'\x90\x03\x00\x01\x00')
        code = '\n'.join(function(MQTT, n) for n in
                         ('_mqtt_str', '_mqtt_varint', '_mqtt_publish_packet', '_mqtt_publish_session'))
        code += ('\nMQTT_STREAM_RAW=%s; MQTT_FASTPATH_MAX_BYTES=4000\n' % shlex.quote(str(raw)) +
                 ('exec 3<>%s\n' % shlex.quote(str(fifo)) if session else '') +
                 '_mqtt_publish_session %s %s %s; echo "rc=$?" >&2\n'
                 % (shlex.quote(topic), shlex.quote(payload), retain) +
                 ('timeout 1 cat <&3\n' if session else ''))
        return run(code, timeout=10)

    def test_publish_goes_through_the_session_fifo(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_pub(d, 'tc100/cam/event', '{"type":"sound","level_db":-27}', '1')
            self.assertIn(b'rc=0', r.stderr)
            pk = packets(r.stdout)
            self.assertEqual(len(pk), 1)
            hdr, body = pk[0]
            self.assertEqual(hdr, 0x31)                       # PUBLISH, retained
            tl = int.from_bytes(body[:2], 'big')
            self.assertEqual(body[2:2 + tl], b'tc100/cam/event')
            self.assertEqual(body[2 + tl:], b'{"type":"sound","level_db":-27}')
            self.assertEqual((Path(d) / 'stream.bin.connack').read_text(), '3\n')

    def test_falls_back_without_a_live_accepted_session(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn(b'rc=1', self.run_pub(d, 't', 'p', session=False).stderr)
        with tempfile.TemporaryDirectory() as d:                 # broker refused
            r = self.run_pub(d, 't', 'p', connack=b'\x20\x02\x00\x05')
            self.assertIn(b'rc=1', r.stderr)
            self.assertEqual(r.stdout, b'')
        with tempfile.TemporaryDirectory() as d:                 # too big for one atomic write
            r = self.run_pub(d, 't', 'x' * 5000)
            self.assertIn(b'rc=1', r.stderr)
            self.assertEqual(r.stdout, b'')

    def test_no_publish_before_the_handshake_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / 'stream.bin'
            os.mkfifo(str(raw) + '.input')
            Path(str(raw) + '.session').write_text('4\n')
            Path(str(raw) + '.ready').write_text('3\n')            # previous session
            Path(str(raw) + '.4').write_bytes(b'\x20\x02\x00\x00')
            code = '\n'.join(function(MQTT, n) for n in
                             ('_mqtt_str', '_mqtt_varint', '_mqtt_publish_packet', '_mqtt_publish_session'))
            code += '\nMQTT_STREAM_RAW=%s; MQTT_FASTPATH_MAX_BYTES=4000\n_mqtt_publish_session t p 0; echo rc=$?' % shlex.quote(str(raw))
            self.assertIn(b'rc=1', run(code).stdout)
        w = function(MQTT, 'mqtt_listener_packets')
        self.assertLess(w.index('.ready"'), w.index('_ml_pings=0'))
        self.assertLess(w.rindex('rm -f "${MQTT_STREAM_RAW}.ready"'), w.rindex("printf '\\xe0\\x00'"))

    def test_publish_raw_tries_the_session_first(self):
        fn = function(MQTT, 'mqtt_publish_raw')
        self.assertLess(fn.index('_mqtt_publish_session'), fn.index('nc -w 4'))
