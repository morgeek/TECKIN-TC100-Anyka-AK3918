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
                 '; [ $n -lt 3 ] && echo "tcp 0 0 192.168.1.11:554 192.168.1.2:40000 TIME_WAIT"; return 0; }'
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
        ]
        for env, expected in cases:
            vals = {'RTSP_FPS_LOCK': '0', 'RTSP_MIC_OFF_WHEN_NO_AUDIO': '0', 'VENDOR_PRINT_LEVEL': '', 'RTSP_AUDIO': '1'}
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
        self.assertEqual(count, 26)

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
