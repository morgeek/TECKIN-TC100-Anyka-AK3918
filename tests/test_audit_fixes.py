"""Regression tests for the fixes of the 2026-11-03 audit (docs/linux-port/audit-2026-11-03.md).

- values typed in the UI and written unquoted into shell-sourced files (mqtt.conf, telegram.conf) are checked;
- the JSON import applies its values in one pass per file (tc_apply_edits) with the result of the sequential calls;
- the flat / ini key cache of the validation answers like the awk lookups;
- every state.cgi branch that reports the stream settings loads rtspserver.conf first (it reported 15 fps).
"""
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']


def function(path, name):
    match = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', (ROOT / path).read_text(), re.M | re.S)
    if not match:
        raise AssertionError((path, name))
    return match.group(0)


def sh(code, timeout=60):
    return subprocess.run(ASH + ['-c', code], capture_output=True, text=True, timeout=timeout)


def q(value):
    return "'" + value.replace("'", "'\\''") + "'"


class SourcedValues(unittest.TestCase):
    def test_sourced_value_ok_refuses_what_breaks_a_sourced_file(self):
        code = function('www/cgi-bin/action.cgi', 'sourced_value_ok') + '\n'
        good = ['morgeekha', 'P@ss!#%^*=+-.:_~,/?', '123456:ABC-def_ghi', '']
        bad = ['a b', "a'b", 'a"b', 'a$b', '$(reboot)', 'a`b', 'a\\b', 'a;b', 'a&b', 'a|b', 'a<b', 'a>b', 'a(b',
               'a)b', 'a\tb']
        for v in good + bad:
            code += f'sourced_value_ok {q(v)} && echo ok || echo no\n'
        r = sh(code)
        self.assertEqual(r.stdout.split(), ['ok'] * len(good) + ['no'] * len(bad), r.stderr)

    def test_ui_writers_of_sourced_files_check_typed_values(self):
        integ = (ROOT / 'scripts/action.d/integrations.sh').read_text()
        system = (ROOT / 'scripts/action.d/system.sh').read_text()
        self.assertIn('refuse_unsafe_value "MQTT user" "$mqtt_user"', integ)
        self.assertIn('refuse_unsafe_value "MQTT password" "$F_mqtt_password"', integ)
        self.assertIn('refuse_unsafe_value "MQTT password" "$ha_password"', integ)
        self.assertIn('refuse_unsafe_value "Telegram token" "$telegram_token"', system)
        # the check comes before the value is written
        self.assertLess(integ.index('refuse_unsafe_value "MQTT user" "$mqtt_user"'),
                        integ.index('rewrite_config /mnt/config/mqtt.conf MQTT_USER "$mqtt_user"'))
        wizard = (ROOT / 'www/cgi-bin/wizard.cgi').read_text()
        self.assertNotIn('[^a-zA-Z0-9._@!#%^*()=+-]', wizard)


class ImportInOnePass(unittest.TestCase):
    LIB = (ROOT / 'scripts/config-transaction.sh').read_text()

    def test_apply_edits_matches_the_sequential_set_calls(self):
        rng = random.Random(7)
        values = ['1', '0', 'abc', 'a b', "'q'", '"d"', 'x=y', '#h', '*/?']
        for dist in sorted((ROOT / 'config').glob('*.dist')):
            text = dist.read_text(errors='ignore')
            keys = re.findall(r'^\s*([A-Za-z0-9_]+)=', text, re.M) or ['X']
            sections = sorted(set(re.findall(r'^\[([0-9]+)\]\s*$', text, re.M)))
            for trial in range(4):
                mode = 'ini' if sections or trial % 2 else 'flat'
                edits = []
                for _ in range(rng.randint(1, 10)):
                    k = rng.choice(keys + ['NEWKEY%d' % rng.randint(0, 3)])
                    s = rng.choice(sections + ['root', '9']) if mode == 'ini' else ''
                    edits.append((mode, s, k, rng.choice(values)))
                with tempfile.TemporaryDirectory() as d:
                    a, b, e = Path(d, 'a'), Path(d, 'b'), Path(d, 'e')
                    a.write_text(text); b.write_text(text)
                    e.write_text(''.join(f'{m}\t{s}\t{k}\t{v}\n' for m, s, k, v in edits))
                    calls = [f'tc_set_flat {a} {k} {q(v)}' if m == 'flat' else f'tc_set_ini {a} {s} {k} {q(v)}'
                             for m, s, k, v in edits]
                    r = sh(self.LIB + '\n' + '\n'.join(calls) + f'\ntc_apply_edits {b} {e}\n')
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(a.read_text(), b.read_text(), (dist.name, edits))

    def test_import_queues_flat_and_ini_values(self):
        cgi = (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text()
        loop = cgi[cgi.index('_ce_import() {'):]
        self.assertNotIn('tc_set_flat "$_ce_stage', loop)
        self.assertNotIn('tc_set_ini "$_ce_stage', loop)
        self.assertIn('tc_apply_edits "$_ce_stage/$_ce_f" "$_ce_edits"', loop)


class ValidationCache(unittest.TestCase):
    LIB = (ROOT / 'scripts/config-transaction.sh').read_text()
    FLAT = "A=1\n#B=2\nDUP=1\nDUP=2\nNOEQ\n  SP=3\nW=a=b\nQ='x y'\nG=*?\nE=\n"
    INI = "imageflip=1\n[0]\nfps=25\n#maxqp=9\nmaxqp=40\nmaxqp=41\n[1]\nfps=10\n"

    def lookups(self, path, cached):
        code = self.LIB + '\n' + (f'tc_flat_cache_load {path}\n' if cached else '')
        for k in ['A', 'B', 'DUP', 'NOEQ', 'SP', 'W', 'Q', 'G', 'E', 'NOPE', '*']:
            code += (f'tc_has_flat {path} {q(k)} && echo "Y $(tc_read_flat {path} {q(k)})" || echo N; '
                     f'tc_flat_value {path} {q(k)}; echo "V $TC_FLAT_VALUE"\n')
        for s, k in [('root', 'imageflip'), ('0', 'fps'), ('0', 'maxqp'), ('1', 'fps'), ('1', 'maxqp'), ('root', 'fps')]:
            code += f'tc_ini_value {path} {s} {k} && echo "I $TC_INI_VALUE" || echo IN\n'
        r = sh(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_cached_lookups_answer_like_the_awk_ones(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'c.conf'); p.write_text(self.FLAT + self.INI)
            self.assertEqual(self.lookups(p, True), self.lookups(p, False))

    def test_cache_only_lives_during_one_validation(self):
        body = function('scripts/config-transaction.sh', 'tc_validate_candidate')
        self.assertIn('tc_flat_cache_load "$2"', body)
        self.assertIn('tc_flat_cache_clear', body)


class StreamSummaryLoadsItsConfig(unittest.TestCase):
    def test_every_caller_loads_rtspserver_conf_first(self):
        lines = (ROOT / 'www/cgi-bin/state.cgi').read_text().split('\n')
        calls = [i for i, l in enumerate(lines) if l.strip() == 'read_rtsp_stream_summary']
        self.assertGreaterEqual(len(calls), 6)
        for i in calls:
            j = i - 1
            while j >= 0 and not re.match(r'^  [a-z_|]+\)$', lines[j]) and not re.match(r'^[a-z_]+\(\) \{', lines[j]):
                j -= 1
            branch = '\n'.join(lines[j:i])
            self.assertIn('load_conf_file /mnt/config/rtspserver.conf', branch, f'state.cgi:{i + 1} ({lines[j]})')


if __name__ == '__main__':
    unittest.main()


class MqttBridgeControlStopsTheDaemon(unittest.TestCase):
    """controlscripts/mqtt-bridge with MQTT_BRIDGE_IMPL=c: run_busybox is a shell function, so `$!` after
    `run_busybox nohup BIN &` is the subshell, not tc100-mqttd. stop then left the daemon running and the next start
    brought a second one with the same client id (the broker dropped them in turn every 2 s, IPCAM2 2026-11-04)."""
    TEXT = (ROOT / 'controlscripts/mqtt-bridge').read_text()

    def test_start_records_the_daemon_pid(self):
        start = function('controlscripts/mqtt-bridge', 'start')
        self.assertIn('_mb_pid="$(cat "$MQTTD_PIDFILE" 2>/dev/null)"', start)
        self.assertIn('echo "$_mb_pid" > "$PIDFILE"', start)
        self.assertLess(start.index('rm -f "$MQTTD_PIDFILE"'), start.index('nohup "$BIN"'))

    def test_start_leaves_no_shell_parent(self):
        """The background subshell execs busybox nohup, which execs the daemon: $! is the daemon (P0 #2 of the
        implementer list, a `sh mqtt-bridge start` of ~200 KB PSS stayed alive as the daemon's parent)."""
        start = function('controlscripts/mqtt-bridge', 'start')
        self.assertNotIn('run_busybox nohup', start)
        d = Path(tempfile.mkdtemp())
        try:
            (d / 'bb').write_text('#!/bin/sh\n[ "$1" = nohup ] && shift\nexec "$@"\n')
            (d / 'daemon').write_text('#!/bin/sh\necho $$ > "$OUT"\nexec sleep 30\n')
            for f in ('bb', 'daemon'):
                (d / f).chmod(0o755)
            code = ('status() { return 1; }\nbridge_impl() { echo c; }\nbridge_enabled_in_config() { return 1; }\n'
                    f'get_busybox_bin() {{ echo {d}/bb; }}\n' + start +
                    f'\nexport OUT={d}/out; PIDFILE={d}/pid; MQTTD_PIDFILE={d}/mqttd.pid; BIN={d}/daemon\n'
                    'start >/dev/null\n')
            r = sh(code)
            self.assertEqual(r.returncode, 0, r.stderr)
            pid = (d / 'pid').read_text().strip()
            self.assertEqual(pid, (d / 'out').read_text().strip())      # the pid file holds the daemon, no subshell
            subprocess.run(['kill', pid])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_stop_kills_every_daemon(self):
        stop = function('controlscripts/mqtt-bridge', 'stop')
        self.assertIn('killpid_graceful "$MQTTD_PIDFILE" 5', stop)
        self.assertIn('pidof tc100-mqttd', stop)
        self.assertLess(stop.index('pidof tc100-mqttd'), stop.index('rm -f "$MQTTD_PIDFILE"'))


class NoLibcDataImports(unittest.TestCase):
    """Programs linked against the stand-in libc of their Makefile (glibc cross compiler, uClibc loader on the camera:
    src/tc100rtsp, src/mqttd, src/onvifd, src/supervisord, src/logfwd, src/netacl) declare every import as a function. A libc *variable*
    (stderr, stdout, optarg, environ, timezone...) then reads the PLT instead of the FILE pointer: tc100-onvifd crashed
    on its first fprintf(stderr, ...) on IPCAM2 (rc27, 2026-11-05), tc100-supervisord would on an error path."""
    DATA = r'\b(stdin|stdout|stderr|optarg|optind|opterr|optopt|environ|__environ|timezone|daylight|tzname|errno_value)\b'

    def test_stand_in_programs_use_no_libc_variable(self):
        bad = []
        for mk in sorted(ROOT.glob('src/*/Makefile')):
            text = mk.read_text()
            if 'stubs.c' not in text or ('ld-uClibc' not in text and 'libc.so.0' not in text):
                continue
            for c in sorted(mk.parent.glob('*.c')):
                if c.name == 'stubs.c' or c.name.startswith('test_'):	# test_*.c: host test programs, not on the camera
                    continue
                for n, line in enumerate(c.read_text().splitlines(), 1):
                    code = re.sub(r'/\*.*?\*/|//.*$|"(?:\\.|[^"\\])*"', '', line)
                    if code.lstrip().startswith('*'):
                        continue
                    if re.search(self.DATA, code):
                        bad.append(f'{c.relative_to(ROOT)}:{n}: {line.strip()[:80]}')
        self.assertEqual(bad, [])


class WhepForwardsFullRtpPackets(unittest.TestCase):
    """tc100-whep dropped every RTP packet over 1400 bytes; tc100_rtsp sends 12 + RTP_PAYLOAD (1400) = 1412 for a full
    FU-A fragment, so no IDR reached the viewer (IPCAM2, rc27: audio fine, 0 video picture)."""

    def test_limit_fits_tc100_rtsp_packets(self):
        payload = int(re.search(r'#define RTP_PAYLOAD (\d+)', (ROOT / 'src/tc100rtsp/tc100_rtsp.c').read_text()).group(1))
        src = (ROOT / 'src/whep/tc100_whep.c').read_text()
        self.assertNotIn('n > 1400', src)
        tag = int(re.search(r'#define WH_SRTP_TAG (\d+)', src).group(1))
        for fn in ('on_video', 'on_audio'):
            body = src[src.index('static void ' + fn):]
            body = body[:body.index('\n}\n')]
            buf = int(re.search(r'uint8_t b\[(\d+)\]', body).group(1))
            self.assertIn('sizeof b - WH_SRTP_TAG', body)
            self.assertGreaterEqual(buf - tag, 12 + payload, fn)
