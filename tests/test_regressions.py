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
import subprocess
import sys
import time
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

    def test_tc100fix_preload_is_opt_in_and_scoped_to_rtsp_server(self):
        s = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        for default in (': "${RTSP_FPS_LOCK:=0}"', ': "${RTSP_MIC_OFF_WHEN_NO_AUDIO:=1}"', ': "${VENDOR_PRINT_LEVEL:=}"'):
            self.assertIn(default, s)
        # The preload is set on the v4l2rtspserver command only, never exported.
        self.assertNotIn('export LD_PRELOAD', s)
        self.assertIn('env LD_PRELOAD=/mnt/lib/libtc100fix.so $TC100FIX_ENV /mnt/bin/v4l2rtspserver', s)
        conf = (ROOT / 'config/boot.conf.dist').read_text()
        for line in ('RTSP_FPS_LOCK=0', 'RTSP_MIC_OFF_WHEN_NO_AUDIO=1', 'VENDOR_PRINT_LEVEL='):
            self.assertRegex(conf, r'(?m)^' + re.escape(line) + r'$')
        lib = (ROOT / 'lib/libtc100fix.so').read_bytes()
        self.assertEqual(lib[:4], b'\x7fELF')
        self.assertEqual(lib[18], 40)  # e_machine = EM_ARM
        for sym in (b'ak_vi_set_fps', b'ak_vi_set_switch_fps_enable', b'ak_ai_start_capture',
                    b'ak_ai_set_aec', b'ak_ai_set_nr_agc', b'ak_print_set_level', b'libc.so.0'):
            self.assertIn(sym, lib)

    def test_rtsp_start_waits_for_port_to_drain(self):
        # Restarting while old client sockets on :554 are still closing made the
        # server exit at once ("Address family not supported"), seen on hardware.
        code = function('controlscripts/rtsp-h26x', 'rtsp_wait_port_free')
        state = self.base / 'netstat-calls'
        # netstat runs in a pipeline subshell, so the call counter lives in a file.
        st = shlex.quote(str(state))
        code += ('\necho 0 > ' + st + '\nnetstat() { n=$(($(cat ' + st + ') + 1)); echo $n > ' + st +
                 '; [ $n -lt 3 ] && echo "tcp 0 0 192.168.1.51:554 192.168.1.2:40000 TIME_WAIT"; return 0; }'
                 '\nsleep() { :; }\nrtsp_wait_port_free 554 10; echo "rc=$?"')
        self.assertEqual(run(code).stdout.strip(), b'rc=0')
        self.assertEqual(state.read_text().strip(), '3')
        busy = function('controlscripts/rtsp-h26x', 'rtsp_wait_port_free')
        busy += '\nnetstat() { echo "tcp 0 0 0.0.0.0:554 0.0.0.0:* LISTEN"; }\nsleep() { :; }\nrtsp_wait_port_free 554 5; echo "rc=$?"'
        self.assertEqual(run(busy).stdout.strip(), b'rc=1')
        s = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        loop = s[s.index('    while [ $_rtsp_try -lt 3 ]; do'):s.index('    done', s.index('    while [ $_rtsp_try -lt 3 ]; do'))]
        self.assertIn('rtsp_wait_port_free "$RTSP_PORT_NUM"', loop)
        self.assertIn('kill -0 "$_rtsp_pid"', loop)

    def test_tc100fix_env_assembly(self):
        # Extract the env-building block of rtsp-h26x and run it with each option.
        s = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        block = s[s.index('    TC100FIX_ENV=""'):s.index('    if [ -n "$TC100FIX_ENV" ] && [ ! -f')]
        cases = [
            ({}, ''),
            ({'RTSP_FPS_LOCK': '1'}, 'TC100FIX_FPS_LOCK=1'),
            ({'RTSP_MIC_OFF_WHEN_NO_AUDIO': '1', 'RTSP_AUDIO': '1'}, ''),
            ({'RTSP_MIC_OFF_WHEN_NO_AUDIO': '1', 'RTSP_AUDIO': '0'}, 'TC100FIX_MIC_OFF=1'),
            ({'VENDOR_PRINT_LEVEL': '1'}, 'TC100FIX_PRINT_LEVEL=1'),
            ({'VENDOR_PRINT_LEVEL': '12'}, ''),
            ({'RTSP_DAYNIGHT_POLL_MS': '500'}, 'TC100FIX_DAYNIGHT_POLL_MS=500'),
            ({'RTSP_DAYNIGHT_POLL_MS': 'x'}, ''),
        ]
        for env, expected in cases:
            vals = {'RTSP_FPS_LOCK': '0', 'RTSP_MIC_OFF_WHEN_NO_AUDIO': '0', 'VENDOR_PRINT_LEVEL': '', 'RTSP_AUDIO': '1',
                    'RTSP_DAYNIGHT_POLL_MS': '0'}
            vals.update(env)
            code = ''.join('%s=%s\n' % (k, shlex.quote(v)) for k, v in vals.items()) + block + 'printf "%s" "$TC100FIX_ENV"'
            self.assertEqual(run(code).stdout.decode().strip(), expected, env)

    def test_tc100fix_behaviour_under_arm_emulation(self):
        # Runs only where qemu-arm and a camera sysroot (uClibc /lib) are available:
        # TC100_SYSROOT=/path/to/extracted/rootfs. Fixtures: tests/tc100fix/build.sh.
        import shutil
        sysroot = os.environ.get('TC100_SYSROOT')
        fx = ROOT / 'tests/tc100fix'
        if not (sysroot and shutil.which('qemu-arm') and (fx / 'driver').exists()):
            self.skipTest('qemu-arm, TC100_SYSROOT or ARM fixtures not available')
        def emu(*envs):
            args = ['qemu-arm', '-L', sysroot, '-E', 'LD_LIBRARY_PATH=%s' % fx]
            for e in envs:
                args += ['-E', e]
            return subprocess.run(args + [str(fx / 'driver')], capture_output=True, timeout=30)
        plain = emu().stdout.decode()
        inert = emu('LD_PRELOAD=%s' % (ROOT / 'lib/libtc100fix.so')).stdout.decode()
        self.assertEqual(inert, plain)
        out = emu('LD_PRELOAD=%s' % (ROOT / 'lib/libtc100fix.so'), 'TC100FIX_FPS_LOCK=1',
                  'TC100FIX_MIC_OFF=1', 'TC100FIX_PRINT_LEVEL=1').stdout.decode()
        self.assertIn('vendor print_level 1', out)
        self.assertLess(out.index('vendor switch_fps_enable 0'), out.index('vendor set_fps 25'))
        self.assertIn('vendor set_aec 0', out)
        self.assertIn('vendor set_nr_agc 0', out)
        self.assertNotIn('vendor start_capture', out)
        self.assertIn('rc start_capture 0', out)
        self.assertNotIn('vendor stop_capture', out)

    def test_tc100fix_isp_tuning_under_arm_emulation(self):
        # Same requirements as the emulated shim test; ~20 s (thread sleeps).
        import shutil
        sysroot = os.environ.get('TC100_SYSROOT')
        fx = ROOT / 'tests/tc100fix'
        if not (sysroot and shutil.which('qemu-arm') and (fx / 'ispdriver').exists()):
            self.skipTest('qemu-arm, TC100_SYSROOT or ARM fixtures not available')
        conf, status = self.base / 'isp_tune.conf', self.base / 'isp.status'
        out = subprocess.run(['qemu-arm', '-L', sysroot, '-E', 'LD_LIBRARY_PATH=%s' % fx,
                              '-E', 'LD_PRELOAD=%s' % (ROOT / 'lib/libtc100fix.so'),
                              '-E', 'TC100FIX_ISP_TUNE=%s' % conf, '-E', 'TC100FIX_ISP_STATUS=%s' % status,
                              str(fx / 'ispdriver')], capture_output=True, timeout=60).stdout.decode()
        start = out.split('--- after start')[1].split('--- after change')[0]
        self.assertIn('status: BRIGHTNESS=20', start)
        self.assertIn('status: SHARPNESS=50', start)          # 99 clamped to 50
        self.assertIn('status: EXPOSURE_NOW=500', start)      # 50% of 1000
        change = out.split('--- after change')[0].split('--- after start')[1]
        self.assertIn('vpss effect_set 3 0', change)          # contrast back to ISP value
        self.assertIn('vpss effect_set 6 50', change)         # mains frequency
        reload = out.split('--- after reload')[0].split('vpss reload')[1]
        self.assertIn('vpss ae exp_time_max=500', reload)     # cap survives an ISP reload
        reset = out.split('--- after reset')[1]
        self.assertIn('status: EXPOSURE_MAX_PCT=0', reset)
        self.assertIn('status: EXPOSURE_NOW=1000', reset)     # original restored

    def test_isp_tune_helpers_validate_and_report(self):
        conf, boot, status = self.base / 'isp_tune.conf', self.base / 'boot.conf', self.base / 'status'
        conf.write_text((ROOT / 'config/isp_tune.conf.dist').read_text())
        boot.write_text('ISP_TUNE=1\n')
        status.write_text('BRIGHTNESS=20\nPOWER_HZ=50\nEXPOSURE_NOW=450\nEXPOSURE_ORIG=1125\n')
        env = 'ISP_TUNE_CONF=%s ISP_TUNE_BOOT=%s ISP_TUNE_STATUS=%s\n' % tuple(shlex.quote(str(x)) for x in (conf, boot, status))
        lib = env + function('scripts/common_functions.sh', 'rewrite_config') + '\nsync() { :; }\n' + (ROOT / 'scripts/isp-tune.sh').read_text()
        for key, val, ok in [('BRIGHTNESS', '20', '20'), ('BRIGHTNESS', '-50', '-50'), ('BRIGHTNESS', '51', None),
                             ('BRIGHTNESS', '1x', None), ('HUE', '', '0'), ('POWER_HZ', '60', '60'), ('POWER_HZ', '55', None),
                             ('EXPOSURE_MAX_PCT', '0', ''), ('EXPOSURE_MAX_PCT', '9', None), ('EXPOSURE_MAX_PCT', '40', '40')]:
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
        self.assertEqual(len(lines), 8)   # 6 numbers + select + switch
        for line in lines:
            topic, payload = line.split('\t', 1)
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
        self.assertEqual(len(lines), 8)   # 6 sensors + 2 binary sensors
        for line in lines:
            topic, payload = line.split('\t', 1)
            d = json.loads(payload)
            self.assertEqual(d['stat_t'], 'cam/x/health', topic)
            self.assertIn('value_json.diag.', d['val_tpl'])
            self.assertEqual(d['dev']['ids'], ['cam_x'])
        sd = json.loads([l for l in lines if 'sd_problem' in l][0].split('\t', 1)[1])
        self.assertEqual(sd['val_tpl'], '{{ "ON" if value_json.diag.sd_problem == 1 else "OFF" }}')

    def test_diag_payload_is_valid_json(self):
        fn = function('scripts/mqtt-bridge.sh', 'build_diag_payload')
        r = run(fn + '\nnow_ts=$(date +%s); build_diag_payload; printf "%s" "$diag_payload"')
        d = json.loads(r.stdout)
        for k in ('wifi_rssi_dbm', 'mem_available_kb', 'sound_db', 'light_level', 'sd_problem'):
            self.assertIn(k, d)
        self.assertIsInstance(d['mem_available_kb'], int)

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

    def test_sound_detection_never_fakes_a_level(self):
        # 1.8.3 read /dev/voice or /dev/dsp (absent on the AK3918) and then
        # reported threshold+100: enabling it produced a fake event per poll.
        script = (ROOT / 'controlscripts/sound-detection').read_text()
        live = '\n'.join(l for l in script.splitlines() if not l.lstrip().startswith('#'))
        for bad in ('/dev/voice', '/dev/dsp', 'threshold + 100'):
            self.assertNotIn(bad, live)
        self.assertIn('/var/run/sound_level', live)
        rtsp = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        self.assertIn('TC100FIX_SOUND_LEVEL=/var/run/sound_level', rtsp)
        # The meter needs the microphone: MIC_OFF must not be set when enabled.
        block = rtsp[rtsp.index('_sound_enable='):rtsp.index('VENDOR_PRINT_LEVEL', rtsp.index('_sound_enable='))]
        self.assertRegex(block, r'if \[ "\$_sound_enable" = "1" \]; then\n\s*TC100FIX_ENV="\$TC100FIX_ENV TC100FIX_SOUND_LEVEL=[^"]*"\n\s*else')

    def test_motion_form_fields_are_read(self):
        # Settings → Motion & Sound posts these names; conf_motiondetect read
        # motionBlink (a name the form never sends) and ignored the sound fields.
        html = (ROOT / 'www/settings.html').read_text()
        form = html[html.index('id="formDetect"'):html.index('</form>', html.index('id="formDetect"'))]
        names = set(re.findall(r'name="([^"]+)"', form))
        cgi = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        handler = cgi[cgi.index('    conf_motiondetect)'):cgi.index('    ;;', cgi.index('    conf_motiondetect)'))]
        for n in names:
            self.assertIn('F_' + n, handler, n)

    def test_tcp_tw_recycle_stays_off(self):
        # tcp_tw_recycle=1 silently drops SYNs from NATed clients (Frigate's
        # go2rtc): new RTSP connections timed out while ping worked.
        files = [ROOT / 'autorun.sh'] + [p for d in ('scripts', 'controlscripts', 'config/autostart', 'www/cgi-bin')
                                          for p in (ROOT / d).iterdir() if p.is_file()]
        for p in files:
            for line in p.read_text(errors='ignore').splitlines():
                if 'tcp_tw_recycle' in line and not line.lstrip().startswith('#'):
                    self.assertRegex(line, r'echo 0 > /proc/sys/net/ipv4/tcp_tw_recycle', str(p))

    def test_bundled_binaries_unchanged(self):
        count = 0
        for line in (ROOT / 'config/packages.lock.dist').read_text().splitlines():
            if not line.startswith('#') and '|' in line:
                name, digest = line.split('|')
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)
                count += 1
        self.assertEqual(count, 27)

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
                 '_ce_prepare_file', '_ce_row_table', '_ce_build_rows', '_ce_import']
        code = '. ' + shlex.quote(str(ROOT / 'scripts/config-transaction.sh')) + '\n'
        code += function('www/cgi-bin/func.cgi', 'urldecode') + '\n'
        code += 'json_body_err() { printf \'{"ok":false,"error":"%s","message":"%s"}\\n\' "$1" "$2"; }\n'
        code += '\n'.join(function('www/cgi-bin/config_exchange.cgi', name) for name in names)
        return code + '\n_ce_import'

    def test_json_import_applies_sections_and_rejects_whole_invalid_batch(self):
        cfg = self.base / 'config'; cfg.mkdir()
        for name in ('boot.conf', 'rtspserver.conf', 'recording.conf', 'telegram.conf'):
            (cfg / name).write_text((ROOT / ('config/' + name + '.dist')).read_text())
        env = dict(os.environ, CONFIG_ROOT=str(cfg), TC_CONFIG_ROOT=str(cfg), JSONFLAT=str(ROOT / 'scripts/jsonflat.awk'),
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

    def test_ptt_coordinates_exclusive_audio_with_rtsp(self):
        source = (ROOT / 'www/cgi-bin/upload_audio.cgi').read_text()
        stop = source.index('"$RTSP_SERVICE" stop')
        play = source.index('"$AUDIOPLAY_BIN" 8000 1')
        restart = source.index('"$RTSP_SERVICE" start', play)
        unlock = source.index('rmdir "$PTT_LOCK_DIR"', restart)
        transfer = source.index('lock_acquired=0', unlock)
        self.assertLess(stop, play)
        self.assertLess(play, restart)
        self.assertLess(restart, unlock)
        self.assertLess(unlock, transfer)

    def test_ptt_player_patcher_rejects_unknown_firmware_binary(self):
        source = self.base / 'ak_ao_demo'
        destination = self.base / 'ak_ao_ptt'
        source.write_bytes(b'unknown firmware binary')
        env = dict(os.environ, PTT_SOURCE_BIN=str(source), PTT_DEST_BIN=str(destination))
        r = subprocess.run(
            ['/bin/sh', str(ROOT / 'scripts/prepare-ptt-player.sh')],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(destination.exists())
        patcher = (ROOT / 'scripts/prepare-ptt-player.sh').read_text()
        self.assertIn('seek=3584', patcher)
        self.assertIn('seek=4208', patcher)
        self.assertIn('04b300db2de09f5fbbbef316b978a42e', patcher)
        self.assertIn('50afb76d22a1341366306dccffd2d671', patcher)

    def test_stream_profile_health_uses_raw_rtsp_describe(self):
        source = (ROOT / 'www/cgi-bin/action.cgi').read_text()
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

class ConfigMigrate(unittest.TestCase):
    """scripts/config-migrate.sh: configs from older releases gain new .dist
    settings without losing the user's values."""
    SCRIPT = ROOT / 'scripts/config-migrate.sh'
    # ${KEY:-x} used only to print a log line, not as a behavioural default.
    DISPLAY_ONLY = {'dns.conf:DNS_SECONDARY'}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name)
        for d in (ROOT / 'config').glob('*.dist'):
            (self.cfg / d.name).write_bytes(d.read_bytes())
        httpd = (ROOT / 'tests/fixtures/lighttpd.conf.v1.8.3').read_text()
        (self.cfg / 'lighttpd.conf').write_text(re.sub(r'^server\.max-keep-alive.*\n', '', httpd, flags=re.M))
        boot = [l for l in (ROOT / 'config/boot.conf.dist').read_text().splitlines()
                if not l.startswith(('MEM_WATCHDOG', 'FRONT_LED', 'SYSLOG_', 'RED_LED'))]
        (self.cfg / 'boot.conf').write_text('\n'.join(boot) + '\nRED_LED=1')   # no final newline
        (self.cfg / 'mqtt.conf').write_text('MQTT_ENABLE=1\n#MQTT_PORT=1884\nMQTT_HOST=10.0.0.5\n')
        (self.cfg / 'rtspserver.conf').write_text('[0]\nPORT=554\n')

    def tearDown(self):
        self.tmp.cleanup()

    def migrate(self, *args, shell=None):
        env = dict(os.environ, CONFIGPATH=str(self.cfg), MIGRATE_LOG=str(self.cfg / 'log'),
                   LIGHTTPD_BIN='/nonexistent')
        cmd = (shell or ['/bin/bash']) + [str(self.SCRIPT)] + list(args)
        return subprocess.run(cmd, capture_output=True, env=env, timeout=30)

    def kv(self, name):
        out = {}
        for l in (self.cfg / name).read_text().splitlines():
            m = re.match(r'^([A-Za-z_]\w*)=(.*)$', l)
            if m:
                self.assertNotIn(m.group(1), out, (name, 'duplicate key', m.group(1)))
                out[m.group(1)] = m.group(2)
        return out

    def check_result(self):
        boot = self.kv('boot.conf')
        self.assertEqual(boot['RED_LED'], '1')                  # user value kept
        self.assertEqual(boot['FRONT_LED'], '0')                # new key added
        self.assertEqual(boot['MEM_WATCHDOG_ENABLE'], '0')      # code default, not the .dist one
        mqtt = self.kv('mqtt.conf')
        self.assertEqual(mqtt['MQTT_HOST'], '10.0.0.5')
        self.assertNotIn('MQTT_PORT', mqtt)                     # commented out by the user: left alone
        self.assertIn('MQTT_STREAM_ENABLE', mqtt)
        self.assertEqual((self.cfg / 'rtspserver.conf').read_text(), '[0]\nPORT=554\n')
        httpd = (self.cfg / 'lighttpd.conf').read_text()
        httpd = '\n'.join(l for l in httpd.splitlines() if not l.lstrip().startswith('#'))
        self.assertEqual(httpd.count('server.max-keep-alive-idle = 45'), 1)
        # webperf block (lighttpd -tt cannot run here, so it is accepted)
        self.assertEqual(httpd.count('server.modules += ("mod_setenv", "mod_expire", "mod_deflate")'), 1)
        self.assertEqual(httpd.count('deflate.max-loadavg'), 1)
        for name in ('boot.conf', 'mqtt.conf'):
            r = subprocess.run(['sh', '-n', str(self.cfg / name)], capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.cfg / 'lighttpd.conf.pre-migrate').exists())

    def test_appends_missing_settings_only(self):
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.check_result()
        snapshot = {p.name: p.read_bytes() for p in self.cfg.iterdir()}
        self.assertEqual(self.migrate('--force').returncode, 0)      # idempotent
        for name in ('boot.conf', 'mqtt.conf', 'lighttpd.conf'):
            self.assertEqual((self.cfg / name).read_bytes(), snapshot[name], name)
        stamp = (self.cfg / '.migrate-stamp').read_text()
        (self.cfg / 'boot.conf').write_text('X=1\n')
        self.migrate()                                                 # stamp matches: no-op
        self.assertEqual((self.cfg / 'boot.conf').read_text(), 'X=1\n')
        self.assertEqual((self.cfg / '.migrate-stamp').read_text(), stamp)

    # Plugins compiled into bin/lighttpd: src/lighttpd/plugin-static.h. A
    # static lighttpd refuses a config that loads anything else.
    @staticmethod
    def built_in_modules():
        return set(re.findall(r'^PLUGIN_INIT\((mod_\w+)\)', (ROOT / 'src/lighttpd/plugin-static.h').read_text(), re.M))

    def test_httpd_dist_modules_are_built_in(self):
        built_in = self.built_in_modules()
        for name in ('lighttpd.conf.dist', 'lighttpd.http.conf.dist'):
            text = (ROOT / 'config' / name).read_text()
            live = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))
            mods = set()
            for m in re.finditer(r'^server\.modules \+?= \((.*?)\)', live, re.M | re.S):
                mods |= set(re.findall(r'"(mod_\w+)"', m.group(1)))
            self.assertIn('mod_deflate', mods, name)
            self.assertLessEqual(mods, built_in, name)

    def test_bundled_lighttpd_matches_plugin_list(self):
        # The 1.8.3 binary had neither zlib nor mod_setenv/expire/deflate
        # registered ("plugin not found"); the rebuilt one has both.
        binary = (ROOT / 'bin/lighttpd').read_bytes()
        self.assertIn(b'\t+ zlib support', binary)
        self.assertNotIn(b'/home/a/PROJECTS', binary)          # not the old build
        for mod in self.built_in_modules():
            self.assertIn(mod.encode() + b'\0', binary, mod)
        self.assertEqual(self.built_in_modules() & {'mod_setenv', 'mod_expire', 'mod_deflate'},
                         {'mod_setenv', 'mod_expire', 'mod_deflate'})

    def test_repairs_config_naming_mod_setenv(self):
        # A camera installed from the 1.8.3-rc20 .dist names mod_setenv, which
        # the bundled lighttpd lacks: the web server does not start.
        stub = self.cfg / 'lighttpd-stub'
        stub.write_text('#!/bin/sh\n[ "$1" = -tt ] && [ "$2" = -f ] || exit 2\n'
                        'grep -q "mod_setenv" "$3" && exit 255\nexit 0\n')
        stub.chmod(0o755)
        old = (ROOT / 'tests/fixtures/lighttpd.conf.v1.8.3').read_text().replace(
            '"mod_openssl",\n', '"mod_openssl",\n                  "mod_setenv",\n')
        old += ('\nsetenv.add-response-header = (\n  "X-Frame-Options" => "SAMEORIGIN"\n)\n'
                '$HTTP["url"] =~ "\\.css$" {\n  setenv.add-response-header = (\n    "Cache-Control" => "x"\n  )\n}\n')
        (self.cfg / 'lighttpd.conf').write_text(old)
        env = dict(os.environ, CONFIGPATH=str(self.cfg), MIGRATE_LOG=str(self.cfg / 'log'), LIGHTTPD_BIN=str(stub))
        r = subprocess.run(['/bin/bash', str(self.SCRIPT)], capture_output=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        httpd = (self.cfg / 'lighttpd.conf').read_text()
        live = [l for l in httpd.splitlines() if not l.lstrip().startswith('#')]
        self.assertFalse([l for l in live if 'setenv' in l], httpd)
        self.assertIn('$HTTP["url"] =~ "\\.css$" {', live)          # block kept, now empty
        log = (self.cfg / 'log').read_text()
        self.assertIn('removed mod_setenv', log)
        # The stub is the 1.8.3 binary: the webperf block (mod_setenv) is
        # refused, the config stays as repaired, and the next boot retries.
        self.assertIn('lighttpd rejected the migrated config', log)
        self.assertNotIn('deflate.max-loadavg', httpd)
        self.assertFalse((self.cfg / '.migrate-stamp').exists())

    def test_vendor_busybox(self):
        # The camera runs this with its own BusyBox 1.24 ash (rootfs /bin/busybox).
        sysroot = os.environ.get('TC100_SYSROOT')
        if not (sysroot and shutil.which('qemu-arm') and Path(sysroot, 'bin/busybox').exists()):
            self.skipTest('qemu-arm or TC100_SYSROOT not available')
        cmd = ['qemu-arm', '-L', sysroot]
        for k in ('CONFIGPATH', 'MIGRATE_LOG', 'LIGHTTPD_BIN'):
            cmd += ['-E', '%s=%s' % (k, {'CONFIGPATH': self.cfg, 'MIGRATE_LOG': self.cfg / 'log',
                                         'LIGHTTPD_BIN': '/nonexistent'}[k])]
        r = subprocess.run(cmd + [str(Path(sysroot, 'bin/busybox')), 'sh', str(self.SCRIPT)],
                           capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.check_result()

    def test_dist_divergences_are_declared(self):
        # A key whose .dist default differs from the code's fallback must be in
        # MIGRATE_KEEP_BEHAVIOUR, or migrating would change a camera's behaviour.
        script = self.SCRIPT.read_text()
        kv_files = re.search(r'^MIGRATE_KV_CONFIGS="([^"]*)"', script, re.M).group(1).split()
        keep = re.search(r"^MIGRATE_KEEP_BEHAVIOUR='(.*?)'", script, re.M | re.S).group(1).splitlines()
        keep = {l.split('=', 1)[0]: l.split('=', 1)[1].strip('"') for l in keep}
        sources = [ROOT / 'autorun.sh'] + list((ROOT / 'scripts').glob('*.sh')) + \
            list((ROOT / 'controlscripts').iterdir()) + list((ROOT / 'config/autostart').iterdir()) + \
            list((ROOT / 'www/cgi-bin').iterdir())
        text = '\n'.join(p.read_text(errors='ignore') for p in sources if p.is_file())
        for name in kv_files:
            dist = (ROOT / 'config' / (name + '.dist')).read_text()
            for m in re.finditer(r'^([A-Za-z_]\w*)=(.*)$', dist, re.M):
                key, val = m.group(1), m.group(2).strip().strip('"\'')
                code = {d.strip('"\'') for d in re.findall(r'\$\{' + key + r':?[-=]([^}]*)\}', text)}
                code.discard('$motion_save_dir')
                if '%s:%s' % (name, key) in self.DISPLAY_ONLY:
                    continue
                if code and val not in code:
                    self.assertIn('%s:%s' % (name, key), keep, 'undeclared default divergence')
                    self.assertIn(keep['%s:%s' % (name, key)], code)

    def test_httpd_dist_blocks_are_well_formed(self):
        for name in ('lighttpd.conf.dist', 'lighttpd.http.conf.dist'):
            text = (ROOT / 'config' / name).read_text()
            blocks = re.findall(r'^# @migrate (\S+) ([^\n]+)\n(.*?)^# @end$', text, re.M | re.S)
            self.assertEqual([b[0] for b in blocks], ['webperf', 'updatestream', 'keepalive'], name)
            for _, probe, body in blocks:
                self.assertIn(probe, body, (name, probe))


class FwUpdate(unittest.TestCase):
    """scripts/fw-update.sh: verify / install / rollback of an update package."""
    SCRIPT = ROOT / 'scripts/fw-update.sh'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.root = self.d / 'root'
        for rel, text in {'VERSION': '1.0\n', 'www/index.html': 'old page\n', 'bin/tool': 'old bin\n',
                          'wpa_supplicant.conf.dist': 'my wifi\n', 'config/lighttpd.conf': 'x\n',
                          'config/autostart/rtsp-h26x': 'old toggle\n',
                          'config/autostart/00_system-config': '#!/bin/sh\necho old\n'}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        self.pkg_files = {'VERSION': '2.0\n', 'www/index.html': 'new page\n', 'bin/tool': 'old bin\n',
                          'scripts/new.sh': '#!/bin/sh\necho hi\n', 'wpa_supplicant.conf.dist': 'template\n',
                          'config/autostart/ftp-server': '/mnt/controlscripts/ftp-server\n',
                          'config/autostart/rtsp-h26x': 'new toggle\n',
                          'config/autostart/00_system-config': '#!/bin/sh\necho new\n'}
        self.ok = self.d / 'ok.sh'; self.ok.write_text('#!/bin/sh\nexit 0\n'); self.ok.chmod(0o755)
        self.bad = self.d / 'bad.sh'; self.bad.write_text('#!/bin/sh\nexit 1\n'); self.bad.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, files=None, extra=None, manifest=None):
        import tarfile, io
        files = dict(self.pkg_files if files is None else files)
        lines = manifest if manifest is not None else \
            ''.join('%s  %s\n' % (hashlib.md5(v.encode()).hexdigest(), k) for k, v in files.items())
        out = self.d / 'pkg.tar'
        with tarfile.open(out, 'w') as t:
            for name, data in list({'MANIFEST': lines}.items()) + list(files.items()) + list((extra or {}).items()):
                b = data.encode(); ti = tarfile.TarInfo(name); ti.size = len(b)
                t.addfile(ti, io.BytesIO(b))
        return out

    def run_fwu(self, *args, lighttpd=None, shell=None):
        env = dict(os.environ, FWU_ROOT=str(self.root), FWU_BACKUPS=str(self.d / 'bk'), FWU_LOCK=str(self.d / 'lock'),
                   FWU_MIGRATE='/dev/null', FWU_TRACKER='/dev/null', FWU_LIGHTTPD=str(lighttpd or self.ok))
        return subprocess.run((shell or ['sh']) + [str(self.SCRIPT)] + list(args), capture_output=True, env=env, timeout=60)

    def read(self, rel):
        return (self.root / rel).read_text()

    def test_install_and_rollback(self):
        r = self.run_fwu('verify', str(self.package()))
        info = json.loads(r.stdout)
        self.assertTrue(info['ok'], r.stdout)
        # VERSION, index.html, new.sh, 00_system-config; not the toggles, not wpa, not the unchanged bin
        self.assertEqual(info['changed'], 4)
        r = self.run_fwu('install', '--no-reboot')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read('VERSION'), '2.0\n')
        self.assertEqual(self.read('www/index.html'), 'new page\n')
        self.assertEqual(self.read('config/autostart/00_system-config'), '#!/bin/sh\necho new\n')
        self.assertEqual(self.read('wpa_supplicant.conf.dist'), 'my wifi\n')          # credentials kept
        self.assertEqual(self.read('config/autostart/rtsp-h26x'), 'old toggle\n')    # boot choice kept
        self.assertFalse((self.root / 'config/autostart/ftp-server').exists())       # not re-enabled
        self.assertEqual(json.loads(self.run_fwu('status').stdout)['rollback_to'], '1.0')
        r = self.run_fwu('rollback', '--no-reboot')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read('VERSION'), '1.0\n')
        self.assertEqual(self.read('www/index.html'), 'old page\n')
        self.assertFalse((self.root / 'scripts/new.sh').exists())

    def test_only_changed_files_are_extracted(self):
        # The SD card only receives what will actually be installed.
        r = self.run_fwu('verify', str(self.package()))
        self.assertTrue(json.loads(r.stdout)['ok'], r.stdout)
        stage = self.root / 'update/stage'
        got = sorted(str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file())
        self.assertEqual(got, ['MANIFEST', 'VERSION', 'config/autostart/00_system-config',
                               'scripts/new.sh', 'www/index.html'])
        # A changed script with a syntax error is still refused.
        files = dict(self.pkg_files, **{'scripts/new.sh': 'if then fi(\n'})
        r = self.run_fwu('verify', str(self.package(files)))
        self.assertIn('scripts/new.sh', json.loads(r.stdout).get('syntax_errors', ''))

    def test_failed_web_server_check_rolls_back(self):
        self.run_fwu('verify', str(self.package()))
        r = self.run_fwu('install', '--no-reboot', lighttpd=self.bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read('VERSION'), '1.0\n')
        self.assertEqual(self.read('www/index.html'), 'old page\n')
        self.assertFalse((self.root / 'scripts/new.sh').exists())

    def test_damaged_copy_is_detected_and_rolled_back(self):
        # A write that comes out wrong (seen on the SD card under memory
        # pressure) must never be renamed into place.
        self.run_fwu('verify', str(self.package()))
        (self.root / 'update/stage/scripts/new.sh').write_text('#!/bin/sh\necho damaged\n')
        r = self.run_fwu('install', '--no-reboot')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.read('VERSION'), '1.0\n')
        self.assertFalse((self.root / 'scripts/new.sh').exists())
        self.assertFalse(list(self.root.rglob('*.fwu')))
        self.assertIn('damaged on write', (self.root / 'update/update.log').read_text())

    def test_rejects_bad_packages(self):
        bad_md5 = self.package(manifest='%s  VERSION\n' % ('0' * 32))
        self.assertEqual(json.loads(self.run_fwu('verify', str(bad_md5)).stdout)['error'], 'verify_failed')
        bad_sh = dict(self.pkg_files, **{'scripts/new.sh': 'if then fi(\n'})
        self.assertEqual(json.loads(self.run_fwu('verify', str(self.package(bad_sh))).stdout)['error'], 'verify_failed')
        evil = self.package(extra={'../escape': 'x'})
        self.assertEqual(json.loads(self.run_fwu('verify', str(evil)).stdout)['error'], 'unsafe_path')
        self.assertFalse((self.d / 'escape').exists())
        self.assertNotEqual(self.run_fwu('install', '--no-reboot').returncode, 0)   # nothing staged

    def test_vendor_busybox(self):
        sysroot = os.environ.get('TC100_SYSROOT')
        if not (sysroot and shutil.which('qemu-arm') and Path(sysroot, 'bin/busybox').exists()):
            self.skipTest('qemu-arm or TC100_SYSROOT not available')
        sh = ['qemu-arm', '-L', sysroot, str(Path(sysroot, 'bin/busybox')), 'sh']
        r = self.run_fwu('verify', str(self.package()), shell=sh)
        self.assertTrue(json.loads(r.stdout)['ok'], r.stdout + r.stderr)
        r = self.run_fwu('install', '--no-reboot', shell=sh)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read('VERSION'), '2.0\n')
        r = self.run_fwu('rollback', '--no-reboot', shell=sh)
        self.assertEqual(self.read('VERSION'), '1.0\n')

    def test_status_survives_garbage_in_the_log(self):
        # The log of the 2026-10-13 FAT incident held file names made of
        # random bytes; update.cgi status then returned invalid JSON.
        (self.root / 'update').mkdir(parents=True, exist_ok=True)
        (self.root / 'update/update.log').write_bytes(b'ok\nrm: bad \x01\x1b name\x7f\n')
        info = json.loads(self.run_fwu('status').stdout)
        self.assertIn('bad ?? name?', info['log'])

    def test_firmware_image_goes_to_new_and_rolls_back_by_rename(self):
        # The image in use is loop-mounted: never replaced under it, swapped at
        # the next boot (scripts/rofs.sh); no 7 MB backup copy.
        (self.root / 'firmware.sqfs').write_text('image v1\n')
        files = dict(self.pkg_files, **{'firmware.sqfs': 'image v2\n'})
        self.assertTrue(json.loads(self.run_fwu('verify', str(self.package(files))).stdout)['ok'])
        r = self.run_fwu('install', '--no-reboot')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read('firmware.sqfs'), 'image v1\n')
        self.assertEqual(self.read('firmware.sqfs.new'), 'image v2\n')
        self.assertFalse(list((self.d / 'bk').rglob('firmware.sqfs')))
        # Rolled back before the reboot: the pending image is dropped.
        self.assertEqual(self.run_fwu('rollback', '--no-reboot').returncode, 0)
        self.assertFalse((self.root / 'firmware.sqfs.new').exists())
        self.assertEqual(self.read('firmware.sqfs'), 'image v1\n')
        # Installed and booted (rofs.sh swapped it): rollback brings .old back as .new.
        self.run_fwu('verify', str(self.package(files)))
        self.run_fwu('install', '--no-reboot')
        os.rename(self.root / 'firmware.sqfs', self.root / 'firmware.sqfs.old')
        os.rename(self.root / 'firmware.sqfs.new', self.root / 'firmware.sqfs')
        self.assertEqual(self.run_fwu('rollback', '--no-reboot').returncode, 0)
        self.assertEqual(self.read('firmware.sqfs.new'), 'image v1\n')


class FirmwareImage(unittest.TestCase):
    """scripts/rofs.sh: boot-time decision to run from firmware.sqfs, with stubbed mount."""
    SCRIPT = ROOT / 'scripts/rofs.sh'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.sd = self.d / 'sd'
        for sub in ('bin', 'lib', 'scripts', 'controlscripts', 'www', 'config'):
            (self.sd / sub).mkdir(parents=True)
        (self.sd / 'VERSION').write_text('2.0\n')
        self.stub = self.d / 'stub'; self.stub.mkdir()
        self.calls = self.d / 'calls'
        # mount stub: a squashfs mount "fills" the mount point with the image's
        # VERSION and directories; binds and umount just get logged.
        (self.stub / 'mount').write_text(
            '#!/bin/sh\necho "mount $*" >> "%s"\n'
            'case "$*" in *squashfs*) [ -n "$STUB_MOUNT_FAIL" ] && exit 1\n'
            '  for a; do t="$a"; done; for x in bin lib scripts controlscripts www; do mkdir -p "$t/$x"; done\n'
            '  echo "$STUB_IMAGE_VERSION" > "$t/VERSION" ;; esac\nexit 0\n' % self.calls)
        (self.stub / 'umount').write_text('#!/bin/sh\necho "umount $*" >> "%s"\n' % self.calls)
        for f in self.stub.iterdir():
            f.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_rofs(self, *args, image_version='2.0', fail=False):
        env = dict(os.environ, ROFS_SD=str(self.sd), ROFS_RUN=str(self.d / 'run'), ROFS_LOG=str(self.d / 'log/rofs.log'),
                   PATH='%s:%s' % (self.stub, os.environ['PATH']), STUB_IMAGE_VERSION=image_version)
        if fail:
            env['STUB_MOUNT_FAIL'] = '1'
        r = subprocess.run(['sh', str(self.SCRIPT)] + list(args), capture_output=True, env=env, timeout=30)
        return (self.d / 'run/status').read_text().strip() if (self.d / 'run/status').exists() else '', r

    def test_no_image_keeps_fat(self):
        self.assertEqual(self.run_rofs('mount')[0], 'inactive no_image')

    def test_disabled_and_recovery(self):
        (self.sd / 'firmware.sqfs').write_text('img')
        (self.sd / 'config/boot.conf').write_text('FIRMWARE_IMAGE=0\n')
        self.assertEqual(self.run_rofs('mount')[0], 'inactive disabled')
        (self.sd / 'RECOVERY').write_text('')
        self.assertEqual(self.run_rofs('mount')[0], 'inactive recovery_mode')

    def test_stale_image_is_not_used(self):
        (self.sd / 'firmware.sqfs').write_text('img')
        status, _ = self.run_rofs('mount', image_version='1.0')
        self.assertEqual(status, 'inactive version_mismatch image=1.0 sd=2.0')
        self.assertNotIn('bind', self.calls.read_text())

    def test_mount_failure_falls_back(self):
        (self.sd / 'firmware.sqfs').write_text('img')
        self.assertEqual(self.run_rofs('mount', fail=True)[0], 'inactive mount_failed')

    def test_pending_image_is_swapped_in_before_mounting(self):
        (self.sd / 'firmware.sqfs').write_text('old')
        (self.sd / 'firmware.sqfs.new').write_text('new')
        status, r = self.run_rofs('mount')
        self.assertEqual((self.sd / 'firmware.sqfs').read_text(), 'new')
        self.assertEqual((self.sd / 'firmware.sqfs.old').read_text(), 'old')
        self.assertFalse((self.sd / 'firmware.sqfs.new').exists())
        # The FAT view is bound before the overlays, then each code directory.
        binds = [l.split()[-1] for l in self.calls.read_text().splitlines() if 'bind' in l]
        self.assertEqual(binds[0], str(self.d / 'run/fat'))
        self.assertEqual(binds[1:], [str(self.sd / x) for x in ('bin', 'lib', 'scripts', 'controlscripts', 'www')])
        # The stub cannot provide a runnable busybox, so the smoke test refuses
        # the overlay and everything is unmounted again.
        self.assertEqual(status, 'inactive smoke_test_failed')
        self.assertIn('umount %s' % (self.d / 'run/img'), self.calls.read_text())

    def test_verify_renames_a_corrupt_image(self):
        (self.d / 'run').mkdir()
        (self.d / 'run/status').write_text('active 2.0\n')
        (self.sd / 'firmware.sqfs').write_text('img')
        (self.sd / 'firmware.sqfs.md5').write_text('%s  firmware.sqfs\n' % hashlib.md5(b'img').hexdigest())
        _, r = self.run_rofs('verify')
        self.assertEqual(r.returncode, 0)
        self.assertEqual((self.d / 'run/verified').read_text().strip(), 'verified')
        (self.sd / 'firmware.sqfs').write_text('imG')
        _, r = self.run_rofs('verify')
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.sd / 'firmware.sqfs.bad').exists())
        self.assertFalse((self.sd / 'firmware.sqfs').exists())

    def test_image_build_is_executable_and_reproducible(self):
        if not shutil.which('mksquashfs') or not shutil.which('unsquashfs'):
            self.skipTest('squashfs-tools not installed')
        outs = []
        for n in ('a', 'b'):
            out = self.d / n
            subprocess.run(['sh', str(ROOT / 'src/release/build-image.sh'), str(out)], check=True,
                           capture_output=True, timeout=300)
            outs.append((out / 'firmware.sqfs').read_bytes())
        self.assertEqual(outs[0], outs[1])
        listing = subprocess.run(['unsquashfs', '-lls', str(self.d / 'a/firmware.sqfs')],
                                 capture_output=True, text=True).stdout
        modes = {}
        for l in listing.splitlines():
            path = [w for w in l.split() if w.startswith('squashfs-root/')]
            if path:
                modes[path[0][len('squashfs-root/'):]] = l.split()[0]
        self.assertEqual(modes['bin/busybox'], '-rwxr-xr-x')        # FAT gives every file x
        self.assertEqual(modes['www/cgi-bin/state.cgi'], '-rwxr-xr-x')
        self.assertTrue(modes['bin/ak_ao_ptt'].startswith('l'))
        self.assertTrue(modes['lib/libcurl.so.4'].startswith('l'))
        self.assertIn('VERSION', modes)

    def test_prepare_ptt_player_uses_ram_with_image(self):
        text = (ROOT / 'scripts/prepare-ptt-player.sh').read_text()
        self.assertIn("' /mnt/bin squashfs ' /proc/mounts", text)
        self.assertIn('DEST_BIN=/tmp/bin/ak_ao_ptt', text)

    def test_boot_wiring(self):
        auto = (ROOT / 'autorun.sh').read_text()
        self.assertLess(auto.index('rofs.sh mount'), auto.index('. /mnt/scripts/common_functions.sh'))
        self.assertIn("grep -q '^/dev/loop0 /tmp/rofs/'", auto)      # vendor ramdisk cleanup keeps the image
        self.assertIn('rofs.sh verify', auto)
        fwu = (ROOT / 'scripts/fw-update.sh').read_text()
        self.assertIn('ROOT=/tmp/rofs/fat', fwu)

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
        self.assertIn('/scripts/i18n.js?v=', (ROOT / 'www/cgi-bin/wizard.cgi').read_text())
        js = (ROOT / 'www/scripts/i18n.js').read_text()
        version = re.search(r'VERSION = "([^"]+)"', js).group(1)
        self.assertIn('i18n.js?v=' + version, index)     # bump both together (30-day cache)


class SdCardKit(unittest.TestCase):
    """src/release/build-sd.sh: content of a new SD card."""

    def test_boot_hook_starts_autorun(self):
        hook = ROOT / 'wifitest/wifi_test.sh'
        self.assertIn('/mnt/autorun.sh &', hook.read_text())
        self.assertTrue(os.access(hook, os.X_OK))

    def test_kit_is_complete_and_safe(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'kit'
            env = dict(os.environ, PATH='/nonexistent:' + os.environ['PATH'])
            subprocess.run(['sh', str(ROOT / 'src/release/build-sd.sh'), str(out)], check=True,
                           capture_output=True, env=env)
            for p in ('autorun.sh', 'VERSION', 'wifitest/wifi_test.sh', 'SD-CARD.txt',
                      'scripts/rofs.sh', 'config/boot.conf.dist', 'log'):
                self.assertTrue((out / p).exists(), p)
            names = {p.name for p in out.iterdir()}
            for bad in ('uimage', 'uImage', 'root.sqsh4', 'usr.sqsh4', 'usr.jffs2', 'update',
                        'wpa_supplicant.conf'):
                self.assertNotIn(bad, names)
            for live in ('mqtt.conf', 'user.pwd', 'lighttpd.pem'):
                self.assertFalse((out / 'config' / live).exists(), live)


class FlashUsrImage(unittest.TestCase):
    """src/flash/build-usr.sh on a synthetic vendor /usr: cloud removed, SD keeps priority."""

    SERVICE = ('#! /bin/sh\nstart_service ()\n{\n\tif [ $WIFI_TEST = 1 ]; then\n'
               '\t    /mnt/wifitest/wifi_test.sh \n\telse\n'
               '\t\tdaemon\n\t\techo 1 > /sys/class/leds/red_led/brightness\n'
               '\t\t/usr/sbin/anyka_ipc.sh start \n\t\techo "start net service......"\n\tfi\n'
               '\tif [ -z "$boot_from" ] && [ $FACTORY_TEST = 0 ] && [ $WIFI_TEST = 0 ] && [ $AGING_TEST = 0 ];then\n'
               '\t\techo "start net service......"\n\t\t/usr/sbin/net_manage.sh &\n\tfi\n}\n')

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs-tools')
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v = d / 'usr'
            for sub in ('bin', 'lib', 'sbin', 'modules', 'share'):
                (v / sub).mkdir(parents=True)
            (v / 'sbin/service.sh').write_text(self.SERVICE); (v / 'sbin/service.sh').chmod(0o755)
            for f in ('modules/8188fu.ko', 'bin/anyka_ipc', 'bin/ak_vi_demo', 'bin/ak_ao_demo',
                      'bin/wpa_supplicant', 'lib/libapp_net.so', 'lib/libakv_encode.so', 'share/x.mp3'):
                (v / f).write_text(f)
            tc = d / 'tc'; (tc / 'bin').mkdir(parents=True); (tc / 'lib').mkdir()
            (tc / 'bin/curl').write_text('x')
            out = d / 'u.img'
            subprocess.run(['sh', str(ROOT / 'src/flash/build-usr.sh'), str(v), str(tc), str(out)],
                           check=True, capture_output=True)
            x = d / 'x'
            subprocess.run(['unsquashfs', '-q', '-d', str(x), str(out)], check=True, capture_output=True)
            for gone in ('bin/anyka_ipc', 'bin/ak_vi_demo', 'lib/libapp_net.so', 'share/x.mp3'):
                self.assertFalse((x / gone).exists(), gone)
            for kept in ('bin/ak_ao_demo', 'bin/wpa_supplicant', 'lib/libakv_encode.so',
                         'modules/8188fu.ko', 'tc100/bin/curl'):
                self.assertTrue((x / kept).exists(), kept)
            svc = (x / 'sbin/service.sh').read_text()
            self.assertIn('/mnt/wifitest/wifi_test.sh', svc)   # SD path untouched
            self.assertNotIn('anyka_ipc.sh start', svc)
            self.assertIn('/etc/jffs2/tc100/boot.sh', svc)
            self.assertIn('telnetd -p 23', svc)
            self.assertIn('/usr/tc100/scripts/flashboot.sh', svc)
            self.assertIn('[ "${TC100_FLASH:-0}" = 0 ];then', svc)

    def test_flash_script_checks_partition_and_reads_back(self):
        t = (ROOT / 'src/flash/flash-usr.sh').read_text()
        self.assertIn('"C"$', t)
        self.assertIn('if=/dev/mtd6', t)       # verify from the raw flash, not the block cache
        self.assertIn('3891200', t)


class FlashBoot(unittest.TestCase):
    """scripts/flashboot.sh with stubbed mount: SD layout rebuilt from /usr/tc100 + jffs2 config."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        self.code = d / 'usr_tc100'
        for sub in ('bin', 'lib', 'scripts', 'controlscripts', 'www', 'sounds', 'config/autostart'):
            (self.code / sub).mkdir(parents=True)
        (self.code / 'autorun.sh').write_text('#!/bin/sh\necho ran > "%s/autorun.ran"\n' % d)
        (self.code / 'autorun.sh').chmod(0o755)
        (self.code / 'VERSION').write_text('9.9\n')
        (self.code / 'config/boot.conf.dist').write_text('WEB_MODE=full\nWIFI_CLIENT=vendor\nX=1\n')
        (self.code / 'config/mqtt.conf.dist').write_text('MQTT_ENABLE=0\n')
        (self.code / 'config/autostart/rtsp-h26x').write_text('x')
        (self.code / 'config/autostart/02_system-webserver').write_text('new')
        self.stub = d / 'stub'; self.stub.mkdir()
        self.calls = d / 'calls'
        for name in ('mount', 'umount', 'telnetd'):
            (self.stub / name).write_text('#!/bin/sh\necho "%s $*" >> "%s"\n' % (name, self.calls))
            (self.stub / name).chmod(0o755)
        self.persist = d / 'jffs2'; self.mnt = d / 'mnt'; self.mnt.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_fb(self):
        env = dict(os.environ, PATH='%s:%s' % (self.stub, os.environ['PATH']),
                   FLASHBOOT_CODE=str(self.code), FLASHBOOT_PERSIST=str(self.persist),
                   FLASHBOOT_MNT=str(self.mnt), FLASHBOOT_LOG=str(self.d / 'fb.log'),
                   FLASHBOOT_STATE=str(self.d / 'storage'), FLASHBOOT_CODEROOT=str(self.code),
                   FLASHBOOT_ZONE='0')
        r = subprocess.run(['sh', str(ROOT / 'scripts/flashboot.sh')], env=env, capture_output=True, text=True)
        time.sleep(0.3)
        return r

    def test_layout_and_config(self):
        self.run_fb()
        calls = self.calls.read_text()
        self.assertIn('mount -t tmpfs -o size=4m', calls)
        for d in ('bin', 'scripts', 'www', 'controlscripts'):
            self.assertIn('mount -o bind %s/%s %s/%s' % (self.code, d, self.mnt, d), calls)
        self.assertIn('mount -o bind %s/config %s/config' % (self.persist, self.mnt), calls)
        cfg = self.persist / 'config'
        self.assertTrue((cfg / 'mqtt.conf.dist').is_symlink())
        self.assertTrue((cfg / 'autostart/rtsp-h26x').exists())
        boot = (cfg / 'boot.conf').read_text()
        self.assertIn('WEB_MODE=full', boot); self.assertIn('WIFI_CLIENT=new', boot); self.assertIn('X=1', boot)
        self.assertTrue((self.d / 'autorun.ran').exists())
        self.assertEqual((self.d / 'storage').read_text().strip(), 'flash')

    def test_system_boot_scripts_come_from_the_image(self):
        cfg = self.persist / 'config/autostart'
        cfg.mkdir(parents=True)
        (cfg / '02_system-webserver').write_text('old copy from an SD card')
        (cfg / 'ftp-server').write_text('switch')
        self.run_fb()
        self.assertTrue((cfg / '02_system-webserver').is_symlink())
        self.assertEqual((cfg / '02_system-webserver').read_text(), 'new')
        self.assertEqual((cfg / 'ftp-server').read_text(), 'switch')

    def test_second_boot_does_not_rewrite_config(self):
        self.run_fb()
        boot = self.persist / 'config/boot.conf'
        before = boot.stat().st_mtime_ns
        time.sleep(0.05)
        self.run_fb()
        self.assertEqual(boot.stat().st_mtime_ns, before)

    def pending_env(self, net_ok=True):
        fc = self.code / 'scripts/flash-code.sh'
        fc.write_text('#!/bin/sh\necho "fc $*" >> "%s"\ncase "$1" in mount) exit 1 ;; status) echo none ;; esac\n' % self.calls)
        fc.chmod(0o755)
        for name, body in (('netstat', 'echo "tcp 0 0 0.0.0.0:443 0.0.0.0:* LISTEN"' if net_ok else 'true'),
                           ('route', 'echo "0.0.0.0 192.168.1.1 0.0.0.0 UG 0 0 0 wlan0"'), ('ping', 'exit 0'),
                           ('reboot', 'echo reboot >> "%s"' % self.calls), ('logger', 'true')):
            (self.stub / name).write_text('#!/bin/sh\n%s\n' % body); (self.stub / name).chmod(0o755)
        self.persist.mkdir(exist_ok=True)

    def run_fb_zone(self, tries='3'):
        env = dict(os.environ, PATH='%s:%s' % (self.stub, os.environ['PATH']),
                   FLASHBOOT_CODE=str(self.code), FLASHBOOT_PERSIST=str(self.persist),
                   FLASHBOOT_MNT=str(self.mnt), FLASHBOOT_LOG=str(self.d / 'fb.log'),
                   FLASHBOOT_STATE=str(self.d / 'storage'), FLASHBOOT_CODEROOT=str(self.code),
                   FLASHBOOT_CONFIRM_STEP='0', FLASHBOOT_CONFIRM_TRIES=tries, FLASHBOOT_REBOOT=str(self.stub / 'reboot'))
        subprocess.run(['sh', str(ROOT / 'scripts/flashboot.sh')], env=env, capture_output=True)
        time.sleep(1.0)

    def test_pending_update_confirmed(self):
        self.pending_env()
        (self.persist / 'code-pending').write_text('2.0 0\n')
        self.run_fb_zone()
        self.assertFalse((self.persist / 'code-pending').exists())
        self.assertIn('confirmed 2.0', (self.persist / 'log/code-updates.log').read_text())
        self.assertNotIn('reboot', self.calls.read_text())

    def test_pending_update_not_confirmed_reboots_then_rolls_back(self):
        self.pending_env(net_ok=False)
        (self.persist / 'code-pending').write_text('2.0 0\n')
        self.run_fb_zone(tries='2')
        self.assertEqual((self.persist / 'code-pending').read_text().split(), ['2.0', '1'])
        self.assertIn('reboot', self.calls.read_text())
        self.run_fb_zone()                    # next boot: never confirmed -> clear
        self.assertIn('fc clear', self.calls.read_text())
        self.assertFalse((self.persist / 'code-pending').exists())

    def test_no_code_gives_rescue_telnet(self):
        shutil.rmtree(self.code / 'scripts')
        self.run_fb()
        self.assertIn('telnetd -p 23', self.calls.read_text())


class FlashWebServer(unittest.TestCase):
    def test_flash_conf_uses_mbedtls_without_h2(self):
        t = (ROOT / 'config/lighttpd.flash.conf.dist').read_text()
        self.assertIn('"mod_mbedtls"', t); self.assertNotIn('"mod_openssl"', t)
        self.assertIn('"server.h2proto" => "disable"', t)
        self.assertIn('ssl.pemfile = "/mnt/config/lighttpd.pem"', t)

    def test_flash_conf_needs_no_pcre(self):
        t = (ROOT / 'config/lighttpd.flash.conf.dist').read_text()
        code = '\n'.join(l for l in t.splitlines() if not l.lstrip().startswith('#'))
        self.assertNotRegex(code, r'=~|!~|url\.redirect|url\.rewrite|"mod_redirect"')
        self.assertIn('$HTTP["querystring"] =^ "v="', code)
        self.assertIn('$HTTP["url"] =^ "/cgi-bin/" {\n  deflate.mimetypes = ()', code)
        self.assertIn('server.document-root = "/mnt/www/http-redirect"', code)
        self.assertIn('location.replace("https://"', (ROOT / 'www/http-redirect/index.html').read_text())

    def test_selection_in_flash_mode(self):
        cf = (ROOT / 'scripts/common_functions.sh').read_text()
        self.assertIn('_hs_conf=/mnt/config/lighttpd.flash.conf.dist', cf)
        ws = (ROOT / 'config/autostart/02_system-webserver').read_text()
        flash = ws.index('/tmp/tc100-storage'); full = ws.index('case "$WEB_MODE" in')
        self.assertLess(flash, full)   # decided before the OpenSSL path
        self.assertIn('lighttpd.flash.conf', ws[flash:full])


class AutostartModes(unittest.TestCase):
    def test_autostart_entries_are_executable_in_git(self):
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-s', 'config/autostart'],
                             capture_output=True, text=True, check=True).stdout.split('\n')
        modes = {l.split()[3]: l.split()[0] for l in out if l.strip()}
        self.assertTrue(modes)
        for f, m in modes.items():
            self.assertEqual(m, '100755', f)

    def test_autorun_runs_non_executable_entries_with_sh(self):
        self.assertIn('if [ -x "$i" ]; then "$i"; else sh "$i"; fi', (ROOT / 'autorun.sh').read_text())


class JsonFlat(unittest.TestCase):
    """scripts/jsonflat.awk replaces jq on the flash firmware."""
    AWK = ROOT / 'scripts/jsonflat.awk'

    def flat(self, text, *args):
        return subprocess.run(['awk', *args, '-f', str(self.AWK)], input=text.encode(), capture_output=True,
                              env=dict(os.environ, LC_ALL='C'))

    def test_paths_types_and_escapes(self):
        doc = '{"a":{"b":"x\\"y\\\\ \\u00e9\\ud83d\\ude00\\tz","n":-1.5e3,"t":true,"z":null},"l":[1,[2,{"k":"v"}],[]],"e":{}}'
        r = self.flat(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.decode('utf-8').splitlines()
        self.assertEqual(lines, ['.a.b\ts\tx"y\\\\ \u00e9\U0001F600\\tz', '.a.n\tn\t-1.5e3', '.a.t\tb\ttrue',
                                 '.a.z\tz\t', '.l[0]\tn\t1', '.l[1][0]\tn\t2', '.l[1][1].k\ts\tv'])

    def test_rejects_malformed_and_wrong_top_level(self):
        for bad in ('{"a":1,}', '{"a" 1}', '[1', '{"a":"x}', '{} x', 'nul'):
            self.assertEqual(self.flat(bad).returncode, 2, bad)
        self.assertEqual(self.flat('[1]', '-v', 'require=object').returncode, 2)
        self.assertEqual(self.flat('{"a":1}', '-v', 'require=object').returncode, 0)

    def test_no_jq_left_in_flash_paths(self):
        for rel in ('www/cgi-bin/config_exchange.cgi', 'www/cgi-bin/action.cgi', 'scripts/event-logger.sh', 'scripts/mqtt-bridge.sh'):
            text = (ROOT / rel).read_text()
            self.assertNotRegex(text, r'(/mnt/bin/jq|JQ_BIN|command -v jq)', rel)
        self.assertIn('jq|', (ROOT / 'src/flash/stage-tc100.sh').read_text())


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


class FlashCodeZone(unittest.TestCase):
    """scripts/flash-code.sh + update.cgi in flash mode, on a fake 2 MB KERNEL partition."""

    @unittest.skipUnless(shutil.which('mksquashfs'), 'squashfs-tools')
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.d = Path(self.tmp.name)
        self.mtd = d / 'mtd1'
        self.kernel = os.urandom(0x15aca0)
        self.mtd.write_bytes(self.kernel + b'\xff' * (0x200000 - 0x15aca0))
        (d / 'proc').write_text('mtd1: 00200000 00001000 "KERNEL"\n')
        stage = d / 'stage'
        for sub in ('scripts', 'www', 'config'):
            (stage / sub).mkdir(parents=True)
        (stage / 'autorun.sh').write_text('#!/bin/sh\n'); (stage / 'autorun.sh').chmod(0o755)
        (stage / 'VERSION').write_text('9.9-test\n')
        (stage / 'scripts/x.sh').write_text('echo x\n')
        self.pkg = d / 'code.bin'
        subprocess.run(['sh', str(ROOT / 'src/flash/build-code.sh'), str(stage), str(self.pkg)], check=True, capture_output=True)
        self.stub = d / 'stub'; self.stub.mkdir()
        (self.stub / 'reboot').write_text('#!/bin/sh\necho rebooted > "%s/rebooted"\n' % d); (self.stub / 'reboot').chmod(0o755)
        self.env = dict(os.environ, FC_MTD_CHAR=str(self.mtd), FC_MTD_BLOCK=str(self.mtd), FC_PROC_MTD=str(d / 'proc'),
                        FC_LOG=str(d / 'fc.log'), PATH='%s:%s' % (self.stub, os.environ['PATH']),
                        FC_PENDING=str(d / 'pending'), FC_HISTORY=str(d / 'hist'))

    def tearDown(self):
        self.tmp.cleanup()

    def fc(self, *args):
        return subprocess.run(['sh', str(ROOT / 'scripts/flash-code.sh'), *args], capture_output=True, text=True, env=self.env)

    def test_write_status_clear_and_kernel_untouched(self):
        self.assertEqual(self.fc('status').stdout.strip(), 'none')
        self.assertEqual(self.fc('check', str(self.pkg)).stdout.split()[:2], ['ok', '9.9-test'])
        self.assertEqual(self.fc('write', str(self.pkg)).stdout.strip(), 'ok 9.9-test')
        self.assertEqual((self.d / 'pending').read_text().split(), ['9.9-test', '0'])
        self.assertEqual(self.fc('status').stdout.strip(), 'valid 9.9-test')
        data = self.mtd.read_bytes()
        self.assertEqual(len(data), 0x200000)
        self.assertEqual(data[:0x15aca0], self.kernel)
        self.assertEqual(data[0x160000:0x160000 + 11], b'TC100CODE 1')
        self.assertEqual(self.fc('clear').stdout.strip(), 'ok')
        self.assertFalse((self.d / 'pending').exists())
        self.assertIn('installed 9.9-test', (self.d / 'hist').read_text())
        self.assertEqual(self.fc('status').stdout.strip(), 'none')
        self.assertEqual(self.mtd.read_bytes()[:0x15aca0], self.kernel)

    def test_refusals_and_damage(self):
        bad = self.d / 'bad.bin'; bad.write_bytes(b'TC100CODE 1\nsize 10\nmd5 ' + b'0' * 32 + b'\n' + b'\0' * 5000)
        self.assertIn('refused', self.fc('write', str(bad)).stdout)
        (self.d / 'proc').write_text('mtd1: 00200000 00010000 "KERNEL"\n')
        self.assertIn('refused', self.fc('write', str(self.pkg)).stdout)
        (self.d / 'proc').write_text('mtd1: 00200000 00001000 "KERNEL"\n')
        self.fc('write', str(self.pkg))
        with open(self.mtd, 'r+b') as f:
            f.seek(0x161010); f.write(b'\0' * 64)
        self.assertEqual(self.fc('status').stdout.strip(), 'bad md5')

    def cgi(self, method, cmd, body=b''):
        (self.d / 'csrf').write_text('ab12\n')
        src = (ROOT / 'www/cgi-bin/update.cgi').read_text().replace('/tmp/csrf_token', str(self.d / 'csrf'))
        env = dict(self.env, REQUEST_METHOD=method, QUERY_STRING='cmd=' + cmd, CONTENT_LENGTH=str(len(body)),
                   HTTP_X_CSRF_TOKEN='ab12', TC100_STORAGE_FILE=str(self.d / 'storage'),
                   FC_SCRIPT=str(ROOT / 'scripts/flash-code.sh'), FC_WORK=str(self.d / 'work'))
        (self.d / 'storage').write_text('flash\n')
        r = subprocess.run(['sh', '-c', src], input=body, capture_output=True, env=env)
        return json.loads(r.stdout.split(b'\r\n\r\n', 1)[1])

    def test_update_cgi_flash_flow(self):
        self.assertEqual(self.cgi('GET', 'status')['state'], 'idle')
        self.assertFalse(self.cgi('POST', 'upload', b'x' * 5000)['ok'])
        up = self.cgi('POST', 'upload', self.pkg.read_bytes())
        self.assertTrue(up['ok']); self.assertEqual(up['kind'], 'code'); self.assertEqual(up['version'], '9.9-test')
        st = self.cgi('GET', 'status'); self.assertEqual((st['state'], st['staged']), ('staged', '9.9-test'))
        self.assertTrue(self.cgi('POST', 'install')['ok'])
        for _ in range(50):
            if (self.d / 'rebooted').exists():
                break
            time.sleep(0.1)
        self.assertTrue((self.d / 'rebooted').exists())
        self.assertEqual(self.fc('status').stdout.strip(), 'valid 9.9-test')


class ForkLightLoops(unittest.TestCase):
    """The loops that run all day start (almost) no process: 525 -> 85 forks/min measured on camera 2."""

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

    def run_events(self, holds, storage='flash'):
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
            p = subprocess.Popen(['sh', str(ROOT / 'scripts/button-watch.sh')], env=env)
            with open(d / 'ev', 'wb') as w:
                w.write(data); w.flush(); time.sleep(1.5)
            p.wait(timeout=10)
            return (d / 'calls').read_text().split('\n')[:-1] if (d / 'calls').exists() else []

    def test_hold_durations(self):
        self.assertEqual(self.run_events([3]), [])
        self.assertEqual(self.run_events([9]), ['reboot'])
        self.assertEqual(self.run_events([21]), ['fc clear', 'reboot'])
        self.assertEqual(self.run_events([21], storage='sd'), ['reboot'])


class LocalRecording(unittest.TestCase):
    """src/tc100fix/rec.c built for the host, fed Annex-B streams; scripts/rec-storage.sh."""

    @unittest.skipUnless(shutil.which('gcc') and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'gcc + ffmpeg')
    def test_fragmented_mp4_h264_h265(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            exe = d / 'rec-test'
            subprocess.run(['gcc', '-DREC_HOST_TEST', '-Wall', '-Wextra', '-Werror', '-O2', '-o', str(exe),
                            str(ROOT / 'src/tc100fix/rec.c'), '-lpthread'], check=True)
            for enc, fmt, extra in (('libx264', 'h264', ['-x264-params', 'aud=1']),
                                    ('libx265', 'hevc', ['-x265-params', 'aud=1:log-level=error'])):
                src = d / ('in.' + fmt)
                r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=12',
                                    '-t', '70', '-c:v', enc, '-g', '24', '-bf', '0', '-sc_threshold', '0'] + extra +
                                   ['-f', fmt, str(src)], capture_output=True)
                if r.returncode:
                    self.skipTest('ffmpeg without ' + enc)
                for drop in (None, '50'):
                    out = d / ('out-%s-%s' % (fmt, drop)); out.mkdir()
                    env = dict(os.environ, TC100FIX_REC_DIR=str(out), TC100FIX_REC_STATUS=str(d / 'st'),
                               TC100FIX_REC_SEGMENT_SEC='30', TC100FIX_REC_RESERVE_MB='16', REC_TEST_ANY_FS='1')
                    if drop:
                        env['REC_TEST_DROP'] = drop
                    subprocess.run([str(exe), str(src), '12'], env=env, check=True, capture_output=True, timeout=60)
                    files = sorted(out.glob('*/*.mp4'))
                    self.assertTrue(all(re.fullmatch(r'\d{6}\.mp4', f.name) for f in files), files)
                    total = 0
                    for f in files:
                        p = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
                                            'stream=codec_name,width,height,nb_read_frames', '-of', 'json', str(f)],
                                           capture_output=True, text=True, check=True)
                        st = json.loads(p.stdout)['streams'][0]
                        self.assertEqual((st['codec_name'], st['width'], st['height']), (fmt, 640, 360))
                        total += int(st['nb_read_frames'])
                        e = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(f), '-f', 'null', '-'], capture_output=True, text=True)
                        self.assertEqual(e.stderr, '', f)
                    # 840 frames, 30 s files cut at keyframes (every 2 s);
                    # a dropped frame skips to the next keyframe (frame 72).
                    self.assertEqual(len(files), 3)
                    self.assertEqual(total, 840 if not drop else 840 - 22)
                    status = (d / 'st').read_text()
                    self.assertIn('codec=%s' % ('h264' if fmt == 'h264' else 'h265'), status)
                # a file cut short (power loss) stays readable up to the cut
                f = sorted((d / ('out-%s-None' % fmt)).glob('*/*.mp4'))[0]
                cut = d / 'cut.mp4'; cut.write_bytes(f.read_bytes()[:f.stat().st_size // 2])
                p = subprocess.run(['ffprobe', '-v', 'quiet', '-count_frames', '-show_entries', 'stream=nb_read_frames',
                                    '-of', 'csv=p=0', str(cut)], capture_output=True, text=True)
                self.assertGreater(int(p.stdout.strip() or 0), 100)

    def test_refuses_ram_and_flash_filesystems(self):
        src = (ROOT / 'src/tc100fix/rec.c').read_text()
        for magic in ('0x01021994', '0x858458f6', '0x72b6', '0x73717368'):
            self.assertIn(magic, src)
        self.assertIn('O_CREAT | O_EXCL', src)

    def test_storage_dir_and_wiring(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'storage').write_text('sd\n')
            env = dict(os.environ, TC100_STORAGE_FILE=str(d / 'storage'), REC_SD_DIR=str(d / 'records'),
                       REC_PROC_MOUNTS=str(d / 'mounts'), REC_SD_DEVS=str(d / 'nodev'), REC_SD_MOUNT=str(d / 'sd'))
            r = subprocess.run(['sh', str(ROOT / 'scripts/rec-storage.sh'), 'dir'], env=env, capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), str(d / 'records'))
            self.assertTrue((d / 'records').is_dir())
            (d / 'storage').write_text('flash\n')
            (d / 'mounts').write_text('')
            r = subprocess.run(['sh', str(ROOT / 'scripts/rec-storage.sh'), 'dir'], env=env, capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout), (1, ''))
        rtsp = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        self.assertIn('TC100FIX_REC_DIR=$_rec_dir', rtsp)
        boot = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertIn('\nREC_LOCAL=0\n', boot)
        self.assertIn('rec.c', (ROOT / 'src/tc100fix/build.sh').read_text())


class CodePackageRelease(unittest.TestCase):
    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs-tools')
    def test_package_from_git_is_valid_and_executable(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'c.bin'
            subprocess.run(['sh', str(ROOT / 'src/release/build-code-package.sh'), str(out)], check=True, capture_output=True)
            r = subprocess.run(['sh', str(ROOT / 'scripts/flash-code.sh'), 'check', str(out)], capture_output=True, text=True)
            self.assertTrue(r.stdout.startswith('ok '), r.stdout)
            sq = Path(d) / 'c.sqsh'; sq.write_bytes(out.read_bytes()[4096:])
            ls = subprocess.run(['unsquashfs', '-lls', str(sq)], capture_output=True, text=True).stdout
            self.assertRegex(ls, r'-rwxr-xr-x .* squashfs-root/config/autostart/02_system-webserver')
            self.assertIn('squashfs-root/scripts/flashboot.sh', ls)
            self.assertNotIn('config/ssl', ls)
        self.assertIn('build-code-package.sh', (ROOT / '.github/workflows/ci.yml').read_text())


class VendorWpaWrapper(unittest.TestCase):
    def test_filters_conf_and_keeps_args(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake = d / 'wpa'; fake.write_text('#!/bin/sh\nfor a; do echo "[$a]"; done\n'); fake.chmod(0o755)
            conf = d / 'v.conf'; conf.write_text('ctrl_interface=/var/run/wpa_supplicant\ndevice_name=X\nwps_cred_processing=1\nnetwork={\n}\n')
            tmpc = d / 'out.conf'
            env = dict(os.environ, WPA_NEW=str(fake), WPA_TMPCONF=str(tmpc))
            r = subprocess.run(['sh', str(ROOT / 'src/flash/wpa_supplicant-wrapper.sh'), '-B', '-iwlan0', '-Dwext',
                                '-c', str(conf)], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(r.stdout.split(), ['[-B]', '[-iwlan0]', '[-Dwext]', '[-c]', '[%s]' % tmpc])
            out = tmpc.read_text()
            self.assertIn('ctrl_interface', out); self.assertNotIn('device_name', out); self.assertNotIn('wps_', out)


class SettingsLayout(unittest.TestCase):
    """Settings regrouped (2026-10-14): 6 tabs, Tools reduced to Diagnostics / Logs / Config editor."""

    def test_six_tabs_and_unique_ids(self):
        html = (ROOT / 'www/settings.html').read_text()
        tabs = re.findall(r'data-tab="([^"]+)"', html)
        self.assertEqual(tabs, ['tab-video', 'tab-detect', 'tab-integrations', 'tab-network', 'tab-system', 'tab-backup'])
        for t in tabs:
            self.assertEqual(html.count('id="%s"' % t), 1, t)
        ids = re.findall(r'\bid=["\']([^"\']+)["\']', html.split('<script>')[0])
        dup = sorted({i for i in ids if ids.count(i) > 1})
        self.assertEqual(dup, [])
        # every form that existed before the move is still there
        for form in ('formVideoAdvanced', 'formVideoSub', 'formAudioAdvanced', 'formISP', 'formIspTune', 'formMQTT',
                     'formFrigateLive', 'formDetect', 'formTimelapse', 'formTelegram', 'formSyslog', 'formNetwork',
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
        text = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        block = text[text.index('    set_syslog_config)'):text.index('    set_frigate_live)')]
        self.assertIn('*[!A-Za-z0-9.:-]*)', block)
        self.assertLess(block.index('syslog_err'), block.index('rewrite_config'))

    def test_frigate_live_link_in_statusline(self):
        state = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        self.assertIn('\\"frigate_live\\":\\"$frigate_live\\"', state)
        action = (ROOT / 'www/cgi-bin/action.cgi').read_text()
        self.assertIn('/mnt/config/frigate_live.conf', action)
        self.assertIn('id="live_frigate"', (ROOT / 'www/index.html').read_text())

class WifiClient(unittest.TestCase):
    """scripts/wifi-client.sh: opt-in wpa_supplicant 2.11 with fallback to the vendor client."""
    SCRIPT = ROOT / 'scripts/wifi-client.sh'

    def run_wc(self, conf_text, state, bin_ok=True):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); stub = d / 'stub'; stub.mkdir()
            calls = d / 'calls'
            (stub / 'newwpa').write_text('#!/bin/sh\necho "new $*" >> %s\n[ "$1" = -v ] && exit %d\nexit 0\n'
                                         % (calls, 0 if bin_ok else 1))
            (stub / 'wpa_cli').write_text('#!/bin/sh\necho "wpa_state=%s"\n' % state)
            (stub / 'logger').write_text('#!/bin/sh\necho "logger $*" >> %s\n' % calls)
            for f in stub.iterdir():
                f.chmod(0o755)
            conf = d / 'wpa.conf'; conf.write_text(conf_text)
            env = dict(os.environ, PATH='%s:%s' % (stub, os.environ['PATH']), WIFI_NEW_BIN=str(stub / 'newwpa'),
                       WIFI_NEW_TIMEOUT='2', WIFI_CLIENT_LOG=str(d / 'log'))
            r = subprocess.run(['sh', str(self.SCRIPT), 'start', str(conf)], capture_output=True, env=env, timeout=60)
            return r.returncode, calls.read_text() if calls.exists() else '', \
                Path('/tmp/wpa_supplicant-new.conf').read_text() if Path('/tmp/wpa_supplicant-new.conf').exists() else ''

    def test_associates_with_plain_config(self):
        rc, calls, _ = self.run_wc('ctrl_interface=/var/run/wpa_supplicant\nnetwork={\n ssid="x"\n}\n', 'COMPLETED')
        self.assertEqual(rc, 0)
        self.assertRegex(calls, r'new -B -i wlan0 -Dwext -c \S+/wpa.conf ')       # the UI's file itself

    def test_wps_keys_are_filtered_and_fallback_on_timeout(self):
        rc, calls, filtered = self.run_wc('ctrl_interface=/var/run/wpa_supplicant\nconfig_methods=keypad\n'
                                          'device_type=1-0050F204-1\n', 'SCANNING')
        self.assertEqual(rc, 1)
        self.assertIn('-c /tmp/wpa_supplicant-new.conf', calls)
        self.assertNotIn('config_methods', filtered)
        self.assertIn('logger -t tc100-event', calls)

    def test_unusable_binary_is_not_started(self):
        rc, calls, _ = self.run_wc('ctrl_interface=/x\n', 'COMPLETED', bin_ok=False)
        self.assertEqual(rc, 1)
        self.assertNotIn('-B', calls)

    def test_release_check_is_opt_in(self):
        auto = (ROOT / 'autorun.sh').read_text()
        self.assertIn('is_truthy "${UPDATE_CHECK:-0}" && [ -x /mnt/scripts/update-check.sh ]', auto)
        self.assertIn('UPDATE_CHECK=0', (ROOT / 'config/boot.conf.dist').read_text())

    def test_boot_wiring_defaults_to_vendor(self):
        auto = (ROOT / 'autorun.sh').read_text()
        self.assertEqual(auto.count('wifi-client.sh start'), 2)
        self.assertIn('WIFI_CLIENT=vendor', (ROOT / 'config/boot.conf.dist').read_text())

class WebUiCss(unittest.TestCase):
    """www/css/bulma.1.0.2.purged.min.css is generated by src/webui/purge-bulma.mjs."""

    @staticmethod
    def classes(css):
        return set(re.findall(r'\.(-?[A-Za-z_][\w-]*)', re.sub(r'url\([^)]*\)|"[^"]*"', '', css)))

    def test_purged_bulma_keeps_every_class_the_ui_uses(self):
        full = self.classes((ROOT / 'src/webui/bulma.1.0.2.min.css').read_text())
        purged = self.classes((ROOT / 'www/css/bulma.1.0.2.purged.min.css').read_text())
        files = list((ROOT / 'www').glob('*.html')) + list((ROOT / 'www/scripts').glob('*.js')) + \
            [p for p in (ROOT / 'www/cgi-bin').iterdir() if p.is_file()]
        tokens = set()
        for f in files:
            tokens |= set(re.findall(r'[A-Za-z0-9_-]+', f.read_text(errors='ignore')))
        missing = sorted((full & tokens) - purged)
        self.assertEqual(missing, [], 'run: cd src/webui && npm install && npm run purge')

    def test_ui_links_the_purged_bulma(self):
        self.assertFalse((ROOT / 'www/css/bulma.1.0.2.min.css').exists())
        for f in [ROOT / 'www/index.html', ROOT / 'www/cgi-bin/wizard.cgi']:
            self.assertIn('css/bulma.1.0.2.purged.min.css', f.read_text())
        self.assertLess((ROOT / 'www/css/bulma.1.0.2.purged.min.css').stat().st_size, 160_000)

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
        for name in ('telegram-bot', 'network-monitor'):
            s = (ROOT / 'controlscripts' / name).read_text()
            self.assertIn('[ "$1" = "status" ] || echo "You have to configure', s)
        r = run('PIDFILE=/nonexistent\n' + function('controlscripts/syslog-forward', 'status') + '\nstatus')
        self.assertEqual((r.returncode, r.stdout), (1, b''))
        ws = (ROOT / 'controlscripts/web-server').read_text()
        self.assertIn('pidof "$_name"', ws)

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
        # memory-guard / cpu-scaler start at boot but stay off until enabled in
        # boot.conf: status exits 3, shown as "Disabled", not as a problem.
        for name, var in (('memory-guard', 'MEM_GUARD_ENABLE'), ('cpu-scaler', 'CPU_SCALER_ENABLE')):
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
                r = run(fn + '\nWIFI_PROC_FILE=%s; get_wifi_quality; echo "$wifi_qual_json $wifi_iface_json"' % shlex.quote(str(f)))
                self.assertEqual(r.stdout.decode().strip('\n'), want, body)
        s = (ROOT / 'www/cgi-bin/state.cgi').read_text()
        self.assertIn('\\"wifi_qual\\":$wifi_qual_json', s)

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
            self.assertRegex(line, r'MemFree [0-9]+ kB\n$')       # padding trimmed

    def test_routine_logs_live_in_ram(self):
        self.assertIn('LOG_FILE="/tmp/log/sound-detection.log"',
                      (ROOT / 'controlscripts/sound-detection').read_text())
        rtsp = (ROOT / 'controlscripts/rtsp-h26x').read_text()
        self.assertIn('LOGDIR="/tmp/log"', rtsp)
        self.assertIn('cap_log', function('controlscripts/rtsp-h26x', 'health'))
        autorun = (ROOT / 'autorun.sh').read_text()
        self.assertIn('*/5 * * * * /bin/sh /mnt/scripts/reboot-tracker.sh tick', autorun)
        self.assertNotIn('* * * * * /bin/sh /mnt/scripts/reboot-tracker.sh', autorun)
        self.assertIn('remount,noatime /mnt', (ROOT / 'config/autostart/00_system-config').read_text())
        conf = function('scripts/common_functions.sh', 'syslogd_start')
        self.assertIn('*.notice;auth.*;authpriv.*', conf)
        self.assertEqual(conf.count('-l 6'), 2)
        self.assertNotIn('/mnt', conf)

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
