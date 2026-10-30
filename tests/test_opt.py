"""Host tests of the CPU / RAM / fork optimisations of the shell side ([opt] commits): the dashboard answer cache,
the CSRF guard on GET, the fast camera panel, the health prober, the network and web guards, the day/night daemon,
the boot script's single boot.conf parse and the RTSP launcher. Camera-side scripts run in busybox ash when it is
installed (the CI image has it).
Run: python3 -m unittest tests/test_opt.py
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']


def sh(code, env=None, timeout=20):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(SH + ['-c', code], capture_output=True, text=True, timeout=timeout, env=e)


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', (ROOT / path).read_text(), re.M | re.S)
    if not m:
        raise AssertionError((path, name))
    return m.group(0)


def read(path):
    return (ROOT / path).read_text()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class DashinfoCache(Tmp):
    def call(self, uptime, host='cam', compute='x'):
        (self.d / 'uptime').write_text('%d.00 0.00\n' % uptime)
        (self.d / 'host').write_text(host + '\n')
        code = function('www/cgi-bin/state.cgi', 'dashinfo_cached')
        code = code.replace('/proc/uptime', str(self.d / 'uptime')).replace('/proc/sys/kernel/hostname', str(self.d / 'host'))
        for f in ('/mnt/config/rtspserver.conf', '/mnt/config/hostname.conf', '/mnt/config/boot.conf', '/etc/wpa_supplicant.conf',
                  '/mnt/VERSION', '/tmp/flashmode', '/tmp/tc100-storage', '/tmp/camera_ip.txt'):
            code = code.replace(f, str(self.d / ('f' + f.replace('/', '_'))))
        code = ('DASHINFO_CACHE_FILE=%s; DASHINFO_CACHE_TTL_SECONDS=300\n' % (self.d / 'cache') +
                'dashinfo_compute() { echo x >> %s; printf \'{"hostname":"%%s","n":"%s"}\' "$(read h < %s; echo $h)"; }\n'
                % (self.d / 'calls', compute, self.d / 'host') + code + '\ndashinfo_cached\n')
        r = sh(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def calls(self):
        p = self.d / 'calls'
        return len(p.read_text().split()) if p.exists() else 0

    def test_cached_until_ttl_host_change_or_newer_config(self):
        a = self.call(1000)
        self.assertEqual(a, '{"hostname":"cam","n":"x"}')
        self.assertEqual(self.call(1100, compute='y'), a)       # inside the TTL: the cached answer, no recompute
        self.assertEqual(self.calls(), 1)
        self.assertIn('"n":"y"', self.call(1301, compute='y'))   # TTL over
        self.assertEqual(self.calls(), 2)
        self.call(1310, host='other')                            # host name changed
        self.assertEqual(self.calls(), 3)
        self.call(1320, host='other')
        self.assertEqual(self.calls(), 3)
        conf = self.d / 'f_mnt_config_rtspserver.conf'           # a file the card is made of is newer than the cache
        conf.write_text('x')
        t = (self.d / 'cache').stat().st_mtime + 5
        os.utime(conf, (t, t))
        self.call(1330, host='other')
        self.assertEqual(self.calls(), 4)

    def test_failed_compute_is_not_cached(self):
        code = function('www/cgi-bin/state.cgi', 'dashinfo_cached').replace('/proc/uptime', str(self.d / 'up'))
        (self.d / 'up').write_text('5.0 1\n')
        r = sh('DASHINFO_CACHE_FILE=%s; DASHINFO_CACHE_TTL_SECONDS=300\ndashinfo_compute() { echo oops; }\n%s\ndashinfo_cached'
               % (self.d / 'cache', code))
        self.assertEqual(r.stdout.strip(), 'oops')
        self.assertFalse((self.d / 'cache').exists())

    def test_dashinfo_uses_the_cache_and_no_nested_subshells_for_the_stream_summary(self):
        s = read('www/cgi-bin/state.cgi')
        self.assertIn('  dashinfo)', s)
        arm = s[s.index('  dashinfo)'):s.index('  fullconfig)')]
        self.assertIn('dashinfo_cached', arm)
        summary = function('www/cgi-bin/state.cgi', 'read_rtsp_stream_summary')
        self.assertNotIn('$(', summary)


class CsrfGuardOnGet(Tmp):
    def run_guard(self, method, token_file_text, header=''):
        tok = self.d / 'token'
        if token_file_text is not None:
            tok.write_text(token_file_text)
        code = function('www/cgi-bin/func.cgi', 'csrf_guard').replace('/tmp/csrf_token', str(tok))
        stubs = ('tr() { echo tr >> %s; /usr/bin/tr "$@" 2>/dev/null || busybox tr "$@"; }\n'
                 'head() { echo 0123456789abcdef; }\nhexdump() { cat; }\nlogger() { :; }\n' % (self.d / 'trlog'))
        r = sh(stubs + code + '\ncsrf_guard\necho rc=$?', env={'REQUEST_METHOD': method, 'HTTP_X_CSRF_TOKEN': header})
        trlog = self.d / 'trlog'
        return r.stdout, (trlog.read_text().split() if trlog.exists() else [])

    def test_get_with_a_clean_token_forks_nothing(self):
        out, tr = self.run_guard('GET', 'ab12\n')
        self.assertEqual(out.strip(), 'rc=0')
        self.assertEqual(tr, [])

    def test_get_still_creates_a_missing_token(self):
        out, _ = self.run_guard('GET', None)
        self.assertIn('rc=0', out)
        self.assertEqual((self.d / 'token').read_text().strip(), '0123456789abcdef')

    def test_get_with_a_dirty_token_cleans_it(self):
        out, tr = self.run_guard('HEAD', 'zz\n')
        self.assertIn('rc=0', out)
        self.assertEqual((self.d / 'token').read_text().strip(), '0123456789abcdef')   # nothing hex left: new token

    def test_post_still_needs_the_token(self):
        out, tr = self.run_guard('POST', 'ab12\n', header='ab12')
        self.assertEqual(out.strip(), 'rc=0')
        out, _ = self.run_guard('POST', 'ab12\n', header='ffff')
        self.assertIn('403 Forbidden', out)
        out, _ = self.run_guard('POST', 'ab12\n', header='')
        self.assertIn('403 Forbidden', out)


class CameraPanelFastPath(Tmp):
    def panel(self, query, method='GET'):
        for p in ('run', 'sys/user-gpio'):
            (self.d / p).mkdir(parents=True, exist_ok=True)
        (self.d / 'run/ircut').write_text('1\n')
        (self.d / 'run/vday').write_text('1\n')
        (self.d / 'sys/user-gpio/ir-led').write_text('0\n')
        (self.d / 'setconf').write_text('#!/bin/sh\necho 3\n')
        (self.d / 'setconf').chmod(0o755)
        src = read('www/cgi-bin/camcontrols.cgi').replace('/mnt/www/cgi-bin/func.cgi', str(self.d / 'no-such-func.cgi'))
        env = dict(os.environ, REQUEST_METHOD=method, QUERY_STRING=query, PANEL_RUN=str(self.d / 'run'),
                   PANEL_SYS=str(self.d / 'sys'), PANEL_SETCONF=str(self.d / 'setconf'), SCRIPT_HOME=str(self.d / 'cs'))
        return subprocess.run(SH + ['-c', src], capture_output=True, text=True, env=env, timeout=20)

    def test_get_panel_does_not_source_func_cgi(self):
        for q in ('cmd=panel', 'cmd=panel&_=123', 'x=1&cmd=panel', 'x=1&cmd=panel&y=2'):
            r = self.panel(q)
            self.assertIn('"mode":"day"', r.stdout, (q, r.stdout, r.stderr))
            self.assertIn('"ir-cut":1', r.stdout)
            self.assertNotIn('no-such-func', r.stderr)

    def test_other_requests_still_take_the_normal_path(self):
        r = self.panel('cmd=panelx')           # not the panel command: func.cgi is sourced (and is missing here)
        self.assertIn('no-such-func', r.stderr)
        r = self.panel('cmd=panel', method='POST')
        self.assertIn('no-such-func', r.stderr)


class HealthProbe(Tmp):
    def probe(self, svc, env=None, extra=''):
        code = function('scripts/health-probe.sh', 'probe_service_fast')
        code = code.replace('/mnt/controlscripts', str(self.d)).replace('/tmp/tc100_md', str(self.d / 'md')) \
                   .replace('/var/run/v4l2rtspserver.pid', str(self.d / 'gate'))
        r = sh(extra + code + '\nprobe_service_fast ' + svc, env=dict(env or {}, HP_DEEP_FILE=str(self.d / 'deep')))
        return r.stdout.strip()

    def script(self, name, body):
        p = self.d / name
        p.write_text('#!/bin/sh\necho "$1" >> %s/%s.log\n%s\n' % (self.d, name, body))
        p.chmod(0o755)

    def count(self, name):
        p = self.d / (name + '.log')
        return len(p.read_text().split()) if p.exists() else 0

    def test_motion_detection_off_is_stopped_without_running_the_script(self):
        self.script('motion-detection', 'echo "ok: running"')
        self.assertEqual(self.probe('motion-detection'), 'stopped')
        self.assertEqual(self.count('motion-detection'), 0)

    def test_motion_detection_on_still_checks_the_monitor_pid(self):
        self.script('motion-detection', 'echo "ok: running"')
        (self.d / 'md').write_text('')
        # the monitor pid file is /var/run/detection-monitor.pid: absent here = stopped, and still no exec
        self.assertEqual(self.probe('motion-detection'), 'stopped')
        self.assertEqual(self.count('motion-detection'), 0)

    def test_rtsp_deep_check_every_nth_probe_while_healthy(self):
        self.script('rtsp-h26x', 'case "$1" in health) echo "ok: up" ;; esac')
        (self.d / 'gate').write_text(str(os.getpid()))
        res = [self.probe('rtsp-h26x', env={'HP_DEEP_EVERY': '3'}) for _ in range(7)]
        self.assertEqual(res, ['running'] * 7)
        self.assertEqual(self.count('rtsp-h26x'), 3)             # probes 1, 4 and 7

    def test_rtsp_failure_is_rechecked_every_time_and_dead_pid_is_stopped(self):
        self.script('rtsp-h26x', 'case "$1" in health) exit 1 ;; esac')
        (self.d / 'gate').write_text(str(os.getpid()))
        self.assertEqual([self.probe('rtsp-h26x') for _ in range(3)], ['unhealthy'] * 3)
        self.assertEqual(self.count('rtsp-h26x'), 3)
        (self.d / 'gate').write_text('999999')
        self.assertEqual(self.probe('rtsp-h26x'), 'stopped')
        self.assertEqual(self.count('rtsp-h26x'), 3)


class NetGuardNoForks(Tmp):
    def test_gateway_from_proc_net_route(self):
        route = self.d / 'route'
        route.write_text('Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n'
                         'wlan0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n'
                         'wlan0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n')
        code = function('scripts/net-guard.sh', '_ng_gateway').replace('/proc/net/route', str(route))
        r = sh(code + '\n_ng_gateway; echo "[$_gw]"')
        self.assertEqual(r.stdout.strip(), '[192.168.1.1]', r.stderr)
        route.write_text('Iface\tDestination\tGateway\n')
        r = sh(code + '\n_ng_gateway; echo "[$_gw]"')
        self.assertEqual(r.stdout.strip(), '[]')

    def test_boot_conf_value_matches_the_former_sed(self):
        conf = self.d / 'boot.conf'
        conf.write_text('NET_GUARD="0"\nNET_GUARD_MIN=20\nNET_GUARD_MIN="30"\nX="a"b"\nY=\n')
        code = function('scripts/net-guard.sh', '_ng_kv')
        for key in ('NET_GUARD', 'NET_GUARD_MIN', 'X', 'Y', 'NOPE'):
            want = sh('sed -n "s/^%s=\\"\\{0,1\\}\\([^\\"]*\\)\\"\\{0,1\\}\\$/\\1/p" %s | tail -n 1' % (key, conf)).stdout.strip()
            got = sh('CONF=%s\n%s\n_ng_kv %s; echo "$_kv"' % (conf, code, key)).stdout.strip()
            self.assertEqual(got, want, key)

    def test_web_guard_runs_net_guard_every_minute_only_while_down(self):
        wg = read('scripts/web-guard.sh')
        self.assertIn('net-guard.sh}" once', wg)
        self.assertIn('down_since', wg)
        self.assertIn('_i % 3', wg)
        self.assertNotIn('cat "$PIDF"', wg)
        # common_functions.sh is sourced lazily, not at the top of the script
        self.assertNotRegex(wg, r'(?m)^\. "\$\{WG_COMMON')

    def test_web_guard_card_signature(self):
        code = function('scripts/web-guard.sh', '_wg_sdsig')
        r = sh(code + '\n_wg_sdsig; echo "$_wg_sig"')
        self.assertEqual(r.returncode, 0, r.stderr)


class AutoNightDaemon(Tmp):
    def test_does_not_source_common_functions_and_waits_without_sleep(self):
        s = read('scripts/auto-night-daemon.sh')
        self.assertNotIn('\n  . /mnt/scripts/common_functions.sh', s)
        self.assertIn('read -t "$1" _x <> "$DN_FIFO"', s)

    def test_config_is_read_again_only_when_a_file_changed(self):
        rt, dn, stamp = self.d / 'rtspserver.conf', self.d / 'daynight.conf', self.d / 'stamp'
        rt.write_text('daynight=2\n'); dn.write_text('LUMA_NIGHT=30\n')
        code = function('scripts/auto-night-daemon.sh', 'dn_conf_changed')
        env = dict(DN_RTSPCONF=str(rt), DN_CONF=str(dn), DN_STAMP=str(stamp))
        def changed():
            return sh(code + '\ndn_conf_changed && echo yes || echo no', env).stdout.strip()
        self.assertEqual(changed(), 'yes')                       # no stamp yet
        stamp.write_text('')
        t = rt.stat().st_mtime + 10
        os.utime(stamp, (t, t))
        self.assertEqual(changed(), 'no')
        os.utime(dn, (t + 5, t + 5))                             # written after the last read
        self.assertEqual(changed(), 'yes')
        os.utime(dn, (t - 5, t - 5))
        self.assertEqual(changed(), 'no')
        dn.unlink()                                              # a missing file is read (and ignored) every time
        self.assertEqual(changed(), 'yes')


class BootScript(Tmp):
    def test_boot_conf_parse_matches_the_former_bootv(self):
        text = read('v3/autorun-linux66.sh')
        a = text.index('if [ -r /mnt/config/boot.conf ]; then')
        b = text.index('\non() {', a)
        parse = text[a:b]
        conf = self.d / 'boot.conf'
        conf.write_text('ENABLE_NTP="0"\nENABLE_CROND=1\nENABLE_CROND="0"\nBAD="a"b"\nEMPTY=\nLOG_PERSIST=0\n'
                        '# comment=1\n  INDENT=1\nspace key=1\nUPDATE_CHECK=yes\nLAST=v')
        code = parse.replace('/mnt/config/boot.conf', str(conf))
        keys = ('ENABLE_NTP', 'ENABLE_CROND', 'BAD', 'EMPTY', 'LOG_PERSIST', 'INDENT', 'UPDATE_CHECK', 'LAST', 'MISSING')
        for key in keys:
            want = sh('sed -n "s/^%s=\\"\\{0,1\\}\\([^\\"]*\\)\\"\\{0,1\\}\\$/\\1/p" %s | tail -n 1' % (key, conf)).stdout.strip()
            got = sh(code + '\necho "$BC_%s"' % key).stdout.strip()
            self.assertEqual(got, want, key)

    def test_no_bootv_left_and_crond_needs_an_entry(self):
        t = read('v3/autorun-linux66.sh')
        self.assertNotIn('bootv', t)
        a = t.index('_cron=0')
        block = t[a:t.index('\nfi\n', t.index('crond -c', a))]
        for content, want in (('', '0'), ('# only a comment\n\n', '0'), ('   \n', '0'), ('0 4 * * * reboot\n', '1'),
                              ('# c\n30 3 * * 1 reboot', '1')):
            f = self.d / 'root'
            f.write_text(content)
            code = block.replace('/mnt/config/cron/crontabs/root', str(f)).replace(
                'crond -c /mnt/config/cron/crontabs </dev/null >/dev/null 2>&1', 'echo started')
            r = sh(code)
            self.assertEqual(r.stdout.strip(), 'started' if want == '1' else '', (content, r.stderr))

    def test_links_are_made_in_one_call(self):
        t = read('v3/autorun-linux66.sh')
        self.assertIn('ln -sf $LIBLINKS /lib/', t)
        self.assertIn('ln -sfn "$@" /tmp/www/', t)
        self.assertNotIn('$(basename "$f")', t)
        # busybox ln: several targets into a directory, names kept, -f replaces
        src, dst = self.d / 'src', self.d / 'dst'
        src.mkdir(); dst.mkdir()
        (src / 'a.so').write_text('1'); (src / 'b.so').write_text('2'); (dst / 'a.so').write_text('old')
        ln = 'busybox ln' if shutil.which('busybox') else 'ln'
        r = sh('set -- %s/*; %s -sfn "$@" %s/; ls -l %s | grep -c -- "->"' % (src, ln, dst, dst))
        self.assertEqual(r.stdout.strip(), '2', r.stderr)


class RtspLaunch(unittest.TestCase):
    def test_log_is_capped_by_the_server_and_pid_comes_from_the_subshell(self):
        t = read('v3/linux66-sd/rtsp-launch.sh')
        self.assertIn('export RTSP_LOGFILE="$RTSP_LOG"', t)
        self.assertIn(': > "$RTSP_LOG"', t)
        self.assertIn('>>"$RTSP_LOG" 2>&1 ) &', t)
        self.assertNotIn('sleep 2\n', t)
        self.assertIn('RPID=$!', t)
        self.assertIn('echo "$RPID" > /var/run/v4l2rtspserver.pid', t)
        self.assertIn('pidof tc100_rtsp', t)           # the fallback
        # the console log (rtsp.debug) is not a file the server can truncate
        self.assertRegex(t, r'\[ "\$RTSP_LOG" != /dev/console \]')

    def test_launcher_parses(self):
        r = subprocess.run(SH + ['-n', str(ROOT / 'v3/linux66-sd/rtsp-launch.sh')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class WebUiRequests(unittest.TestCase):
    def test_page_load_makes_fewer_cgi_requests(self):
        js = read('www/scripts/index.bundle.min.js')
        self.assertNotIn('fetch("cgi-bin/state.cgi?cmd=hostname", { cache: "no-store" })', js)
        self.assertIn('function applyHostName(title)', js)
        self.assertIn('if (st.hostname) applyHostName(st.hostname);', js)
        a = js.index('function loadPttVolume()')
        self.assertIn('get_ptt_vol', js[a:a + 400])
        self.assertEqual(js.count('cmd=get_ptt_vol'), 1)
        # the logout trick still asks for the host name with bad credentials
        self.assertIn('xhr.open("GET", "cgi-bin/state.cgi?cmd=hostname', js)

    def test_day_night_tab_polls_every_5_seconds(self):
        js = read('src/webui/index/80-camera-controls.js')
        a = js.index('function initDayNight()')
        self.assertIn('}, 5000);', js[a:a + 1200])


if __name__ == '__main__':
    unittest.main()
