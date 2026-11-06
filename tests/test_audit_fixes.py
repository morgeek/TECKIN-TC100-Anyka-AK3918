"""Regression tests for the fixes of the 2026-11-03 audit (docs/linux-port/audit-2026-11-03.md).

- values typed in the UI and written unquoted into shell-sourced files (mqtt.conf, telegram.conf) are checked;
- the JSON import applies its values in one pass per file (tc_apply_edits) with the result of the sequential calls;
- the flat / ini key cache of the validation answers like the awk lookups;
- every state.cgi branch that reports the stream settings loads rtspserver.conf first (it reported 15 fps).
"""
from pathlib import Path
import json
import os
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


class WhepAcceptsBrowserOffers(unittest.TestCase):
    """Chrome 157 sends a 7607-byte offer (video + audio recvonly); whep.cgi and tc100-whep refused anything over 6000
    with 413, so the page never tried WebRTC on IPCAM2 (rc28): 'WebRTC off (HTTP 413): MP4 live view'."""

    def test_same_limit_large_enough_in_cgi_and_daemon(self):
        cgi = (ROOT / 'www/cgi-bin/whep.cgi').read_text()
        src = (ROOT / 'src/whep/tc100_whep.c').read_text()
        lim_cgi = int(re.search(r'\[ "\$_cl" -le (\d+) \]', cgi).group(1))
        lim_d = int(re.search(r'#define WH_MAX_OFFER (\d+)', src).group(1))
        buf = int(re.search(r'char rq\[(\d+)\]', src).group(1))
        self.assertEqual(lim_cgi, lim_d)
        self.assertGreaterEqual(lim_d, 7607 + 2000)
        self.assertGreater(buf, lim_d + 2048, 'room for the request headers')


class UpdateKeepsAutoDayNight(unittest.TestCase):
    """rc29 on both cameras (2026-11-06): the update stopped auto-night-detection, whose stop writes daynight=3 (the
    manual Day / Night choice, kept for good) now that the rc28 ships rwconf; both cameras came back with
    'auto day/night not started: manual mode'. Update and install use halt, which keeps the setting."""

    def run_cs(self, verb):
        with tempfile.TemporaryDirectory() as t:
            log = Path(t, 'rwconf.log')
            src = (ROOT / 'controlscripts/auto-night-detection').read_text()
            src = src.replace('/tmp/linux66', f'{t}/linux66').replace('/mnt/bin/rwconf', f'{t}/rwconf') \
                     .replace('/var/run/', f'{t}/').replace('/mnt/scripts/supervisor.sh', f'{t}/none.sh')
            Path(t, 'linux66').write_text('')
            Path(t, 'rwconf').write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
            os.chmod(Path(t, 'rwconf'), 0o755)
            cs = Path(t, 'cs'); cs.write_text(src)
            subprocess.run(['sh', str(cs), verb], check=True, timeout=10)
            return log.read_text() if log.exists() else ''

    def test_halt_keeps_the_mode_stop_writes_manual(self):
        self.assertIn('daynight 3', self.run_cs('stop'))
        self.assertNotIn('daynight', self.run_cs('halt'))

    def test_update_and_install_halt(self):
        # recording stop writes REC_LOCAL=0 and motion-detection stop mdenabled=0, for good, as auto-night-detection
        # stop writes daynight=3: the update must halt them (rc29: the .24 came back without its recording)
        for rel in ('v3/install/update66.sh', 'v3/install/install66.sh', 'www/cgi-bin/update.cgi'):
            src = (ROOT / rel).read_text()
            self.assertRegex(src, r'for (s|sv) in recording motion-detection auto-night-detection; do', rel)
            for line in src.splitlines():
                if 'for ' in line and ' in ' in line and 'halt' not in line and ('stop' in line or 'rtsp-h26x' in line):
                    for svc in ('auto-night-detection', 'recording', 'motion-detection'):
                        self.assertNotIn(svc, line, (rel, line))
        for cs in ('recording', 'motion-detection', 'auto-night-detection'):
            src = (ROOT / 'controlscripts' / cs).read_text()
            self.assertRegex(src, r'(?m)^halt\(\)', cs)
            self.assertRegex(src, r'\|halt\)', cs)

    def test_recording_halt_leaves_rec_local(self):
        with tempfile.TemporaryDirectory() as t:
            boot = Path(t, 'boot.conf'); boot.write_text('REC_LOCAL=1\n')
            src = (ROOT / 'controlscripts/recording').read_text().replace('/mnt/config/boot.conf', str(boot)) \
                .replace('. /mnt/scripts/common_functions.sh', ':')
            cs = Path(t, 'cs'); cs.write_text(src)
            subprocess.run(['sh', str(cs), 'halt'], check=True, timeout=10, capture_output=True)
            self.assertIn('REC_LOCAL=1', boot.read_text())


class SyslogdOptionsExist(unittest.TestCase):
    """rc29 (2026-11-06): BusyBox syslogd of the base image had no -D and no -f; syslogd_start used both, syslogd exited
    at once, and with SYSLOG_ENABLE=1 both cameras kept no log and forwarded nothing."""

    def test_fragment_enables_what_the_script_uses(self):
        frag = (ROOT / 'v3/buildroot/board/tc100/busybox.fragment').read_text()
        self.assertIn('CONFIG_FEATURE_SYSLOGD_DUP=y', frag)
        self.assertIn('CONFIG_FEATURE_SYSLOGD_CFG=y', frag)

    def test_script_falls_back_without_the_options(self):
        cf = (ROOT / 'scripts/common_functions.sh').read_text()
        body = cf[cf.index('syslogd_start() {'):cf.index('tc100_log_event()')]
        self.assertIn('unrecognized option: [Df]', body)
        self.assertNotRegex(body, r'exec \$_sl_bin -n -D')
        probe = re.search(r'\$_sl_bin -D -f /dev/null --help 2>&1 \| grep -Eq "([^"]+)"', body).group(1)
        self.assertRegex('syslogd: unrecognized option: D', probe)      # the camera's BusyBox without the features
        self.assertNotRegex("syslogd: unrecognized option '--help'", probe)  # a full BusyBox: keep the options


class TechnicalStopsUseHalt(unittest.TestCase):
    """R19 (rc29 -> rc30): a technical stop (update, install, low memory) must not write a setting for good. memory-guard
    called stop on its MEM_GUARD_CRITICAL_SERVICES (motion-detection by default, recording on older configs), whose stop
    writes mdenabled=0 / REC_LOCAL=0: it calls halt on a service that has one."""

    HALT_SERVICES = ('recording', 'motion-detection', 'auto-night-detection')

    def run_guard(self, services):
        with tempfile.TemporaryDirectory() as t:
            log = Path(t, 'calls.log')
            cs_dir = Path(t, 'cs'); cs_dir.mkdir()
            run_dir = Path(t, 'run'); run_dir.mkdir()
            for name, has_halt in services.items():
                verbs = 'start|stop|halt' if has_halt else 'start|stop'
                body = f'#!/bin/sh\ncase "$1" in {verbs}) echo "{name} $1" >> {log} ;; esac\n'
                if has_halt:
                    body = 'halt() { :; }\n' + body
                p = cs_dir / name; p.write_text(body); os.chmod(p, 0o755)
                Path(run_dir, f'{name}.pid').write_text('1\n')
            fn = function('controlscripts/memory-guard', 'stop_service_if_running') \
                .replace('/mnt/controlscripts/', f'{cs_dir}/').replace('/var/run/', f'{run_dir}/')
            code = f'get_now_ts() {{ echo 0; }}\nLOGPATH={t}/mg.log\n{fn}\n' + \
                ''.join(f'stop_service_if_running {n}\n' for n in services)
            r = sh(code, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            return log.read_text().split('\n') if log.exists() else []

    def test_memory_guard_halts_what_has_halt(self):
        calls = self.run_guard({'motion-detection': True, 'recording': True, 'ftp-server': False})
        self.assertIn('motion-detection halt', calls)
        self.assertIn('recording halt', calls)
        self.assertIn('ftp-server stop', calls)
        self.assertNotIn('motion-detection stop', calls)
        self.assertNotIn('recording stop', calls)

    def test_real_controlscripts_are_recognised(self):
        # the memory-guard test of the verb must see the halt of the real scripts
        for cs in self.HALT_SERVICES:
            src = (ROOT / 'controlscripts' / cs).read_text()
            self.assertTrue(re.search(r'(?m)^halt\(\)', src) or '|halt)' in src, cs)

    def test_no_technical_loop_stops_a_halt_service(self):
        for rel in ('v3/install/update66.sh', 'v3/install/install66.sh', 'www/cgi-bin/update.cgi',
                    'controlscripts/memory-guard'):
            for line in (ROOT / rel).read_text().splitlines():
                code = line.split('#', 1)[0]
                if re.search(r'\bstop\b', code) and 'halt' not in code:
                    for svc in self.HALT_SERVICES:
                        self.assertNotIn(svc, code, (rel, line))


class SdRepairGuards(unittest.TestCase):
    """R14 (rc28/rc29 on the .24): with SD_AUTO_REPAIR=1 the old SD boot card (wifitest, bin, v3...) got fsck.fat -a -w
    at every boot, and fsck.fat was OOM-killed (~24 MB for 64 GB). repair() now leaves a boot card alone, does not start
    fsck.fat without the memory it needs (the card is mounted as it is), and mounts the card again after a failed fsck."""

    def boot_sector(self, path, total_sectors, sectors_per_cluster=64):
        b = bytearray(512)
        b[3:11] = b'MSDOS5.0'
        b[11:13] = (512).to_bytes(2, 'little')
        b[13] = sectors_per_cluster
        b[32:36] = total_sectors.to_bytes(4, 'little')
        b[510:512] = b'\x55\xaa'
        Path(path).write_bytes(bytes(b))

    def run_repair(self, t, mounted=False, boot_file=None, mem_kb=200000, fsck_rc=0, total=125000000):
        t = Path(t)
        log = t / 'calls.log'
        bin_dir = t / 'bin'; bin_dir.mkdir()
        mnt = t / 'sd'; mnt.mkdir()
        ro = t / 'ro'; ro.mkdir()
        dev = t / 'dev.img'
        self.boot_sector(dev, total)
        for name, rc in (('fsck.fat', fsck_rc), ('mount', 0), ('umount', 0)):
            f = bin_dir / name
            f.write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\nexit {rc}\n')
            os.chmod(f, 0o755)
        rec = t / 'rec-storage.sh'
        rec.write_text(f'#!/bin/sh\necho "rec-storage $1" >> {log}\n')
        os.chmod(rec, 0o755)
        if boot_file:
            (mnt if mounted else ro).joinpath(boot_file).mkdir()
        (t / 'mounts').write_text(f'/dev/mmcblk0p1 {mnt} vfat rw 0 0\n' if mounted else 'rootfs / rootfs rw 0 0\n')
        (t / 'health').write_text('state=ok\nerrors=0\nreadonly=0\n')
        (t / 'flash').write_text('')
        env = dict(os.environ, PATH=f'{bin_dir}:' + os.environ.get('PATH', ''),
                   SDD_PROC_MOUNTS=str(t / 'mounts'), SDD_HEALTH=str(t / 'health'), SDD_FLASHMODE=str(t / 'flash'),
                   SDD_SDINFO=str(t / 'nosdinfo'), SDD_MNT=str(mnt), SDD_RO_MNT=str(ro), SDD_DEV=str(dev),
                   SDD_STATUS_FILE=str(t / 'status'), SDD_REC_STORAGE=str(rec), SDD_MEMAVAIL_KB=str(mem_kb),
                   # busybox ash runs its own mount applet before the PATH
                   SDD_MOUNT=str(bin_dir / 'mount'), SDD_UMOUNT=str(bin_dir / 'umount'))
        r = subprocess.run(ASH + [str(ROOT / 'scripts/sd-diag.sh'), 'repair'], capture_output=True, text=True,
                           timeout=30, env=env, cwd=str(t))
        calls = log.read_text().splitlines() if log.exists() else []
        return r, calls

    def test_same_boot_files_as_the_recorder(self):
        diag = (ROOT / 'scripts/sd-diag.sh').read_text()
        rec = (ROOT / 'scripts/rec-storage.sh').read_text()
        want = re.search(r'^SD_BOOT_FILES="([^"]+)"', rec, re.M).group(1).split()   # the recorder's list (R25)
        self.assertIn('for _bad in $SD_BOOT_FILES; do', rec)
        have = re.search(r'^SD_BOOT_FILES="([^"]+)"', diag, re.M).group(1).split()
        self.assertEqual(have, want)

    def test_boot_card_is_never_checked(self):
        for mounted in (False, True):
            with tempfile.TemporaryDirectory() as t:
                r, calls = self.run_repair(t, mounted=mounted, boot_file='wifitest')
                self.assertEqual(json.loads(r.stdout)['state'], 'refused', r.stdout + r.stderr)
                self.assertFalse([c for c in calls if c.startswith('fsck.fat')], calls)
                self.assertNotIn('rec-storage eject', calls)
                self.assertNotIn('rec-storage resume', calls)
                if not mounted:
                    self.assertTrue(any(c.startswith('mount') and ' ro ' in c + ' ' for c in calls), calls)

    def test_not_enough_memory_mounts_without_fsck(self):
        with tempfile.TemporaryDirectory() as t:
            # 64 GB, 32 KB clusters: about 24 MB for fsck.fat; 20 MB available
            r, calls = self.run_repair(t, mem_kb=20000)
            j = json.loads(r.stdout)
            self.assertEqual(j['state'], 'dirty-not-checked', r.stdout + r.stderr)
            self.assertFalse([c for c in calls if c.startswith('fsck.fat')], calls)
            self.assertIn('rec-storage resume', calls)
            self.assertIn('dirty-not-checked', Path(t, 'status').read_text())

    def test_enough_memory_runs_fsck_then_resumes(self):
        with tempfile.TemporaryDirectory() as t:
            r, calls = self.run_repair(t, mem_kb=200000)
            self.assertTrue(any(c.startswith('fsck.fat -a -w') for c in calls), calls)
            self.assertLess(calls.index('rec-storage eject'), calls.index('rec-storage resume'))

    def test_failed_fsck_still_resumes(self):
        with tempfile.TemporaryDirectory() as t:
            r, calls = self.run_repair(t, mem_kb=200000, fsck_rc=137)
            self.assertTrue(any(c.startswith('fsck.fat') for c in calls), calls)
            self.assertIn('rec-storage resume', calls)

    def test_fsck_is_the_oom_victim(self):
        diag = (ROOT / 'scripts/sd-diag.sh').read_text()
        self.assertRegex(diag, r'echo 1000 > /proc/self/oom_score_adj; exec fsck\.fat -a -w')

    def test_recording_page_shows_dirty_not_checked(self):
        self.assertIn('/tmp/sd-diag.status', (ROOT / 'scripts/action.d/storage.sh').read_text())
        html = (ROOT / 'www/settings.html').read_text()
        self.assertIn("d.diag === 'dirty-not-checked'", html)
        self.assertIn('id="sd_dirty_word"', html)


class RebootAfterUpdateHasAnIntent(unittest.TestCase):
    """R18 (rc29, both cameras): the reboot of the web update had no reboot-tracker intent, the next boot was classified
    'unknown (no heartbeat recorded yet)'. The intent is written before the flush that saves /mnt/config to the flash."""

    def test_update66_intent_before_the_flush(self):
        src = (ROOT / 'v3/install/update66.sh').read_text()
        body = src[src.index('stopping the services'):]
        i = body.index('reboot-tracker.sh intent "web update to $(cat "$D/VERSION")"')
        self.assertLess(i, body.index('sh /mnt/v3/linux66-sd/cfg-persist flush'))
        # the backups still go to the card after the intent: the card is not remounted read-only by it
        line = next(l for l in body.splitlines() if 'reboot-tracker.sh intent' in l)
        self.assertIn('REBOOT_TRACKER_KEEP_CARD=1', line)

    def test_install66_and_update_cgi_reboots_have_an_intent(self):
        inst = (ROOT / 'v3/install/install66.sh').read_text()
        self.assertLess(inst.index('reboot-tracker.sh intent'), inst.index('cfg-persist save'))
        cgi = (ROOT / 'www/cgi-bin/update.cgi').read_text()
        for line in cgi.splitlines():
            if re.search(r'\breboot \)', line):
                self.assertIn('reboot-tracker.sh intent', line, line)

    def test_keep_card_skips_the_read_only_remount(self):
        fn = function('scripts/reboot-tracker.sh', 'rt_card_clean')
        with tempfile.TemporaryDirectory() as t:
            Path(t, 'flash').write_text('')
            Path(t, 'mounts').write_text('/dev/mmcblk0p1 /mnt/sd vfat rw 0 0\n')
            Path(t, 'st').write_text('state=paused\n')
            env = (f'REBOOT_TRACKER_FLASHMODE={t}/flash REBOOT_TRACKER_MOUNTS={t}/mounts TC100FIX_REC_STATUS={t}/st '
                   f'REBOOT_TRACKER_REMOUNT="touch {t}/remounted"')
            r = sh(f'{fn}\n{env} REBOOT_TRACKER_KEEP_CARD=1 rt_card_clean')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse(Path(t, 'remounted').exists())
            self.assertFalse(Path(t, 'st.pause').exists())
            r = sh(f'{fn}\nexport {env}; rt_card_clean')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(t, 'remounted').exists())


class WebUiRc30Cleanup(unittest.TestCase):
    """R20 for the rc30: U1 no Shutdown entry in the menu (the camera stays off until unplugged; the command stays on
    the server for ssh), U3 no lightweight_mode left in the page script nor in set_advanced_tuning (nothing reads it
    on 3.0; config_exchange keeps the key for older exports)."""

    def test_no_shutdown_in_the_menu(self):
        html = (ROOT / 'www/index.html').read_text()
        self.assertNotIn('cmd=shutdown', html)
        self.assertIn('cmd=reboot', html)
        self.assertRegex((ROOT / 'scripts/action.d/system.sh').read_text(), r'(?m)^\s*shutdown\)')

    def test_no_lightweight_mode_writer(self):
        self.assertNotIn('lightweight_mode', (ROOT / 'src/webui/index/95-settings-page.js').read_text())
        self.assertNotIn('LIGHTWEIGHT_MODE', (ROOT / 'scripts/action.d/video.sh').read_text())
        self.assertIn('LIGHTWEIGHT_MODE', (ROOT / 'www/cgi-bin/config_exchange.cgi').read_text())


class StandInLibcNoGlibcOnlyCalls(unittest.TestCase):
    """rc31 on IPCAM2 (2026-11-06): tc100-logfwd died at its first log line ("can't resolve symbol '__isoc99_sscanf'"),
    so the remote syslog never worked with the CI build (rc28-rc31); libnetacl.so imported __isoc23_strtol. The glibc
    headers turn sscanf / strtol / isdigit... into names the camera's uClibc 0.9.33 does not export (the CI check is
    tests/check-libc-data-imports.sh on the built objects). In the programs linked against the stand-in libc, parse
    by hand."""

    DIRS = ('logfwd', 'netacl', 'tc100rtsp', 'mqttd', 'onvifd', 'supervisord', 'rwconf')
    CALL = re.compile(r'\b(sscanf|fscanf|scanf|vsscanf|strtol|strtoul|strtoll|strtoull|strtod|isdigit|isspace|isalpha|'
                      r'isalnum|isupper|islower|isxdigit|isprint|tolower|toupper)\s*\(')

    def test_no_redirected_calls(self):
        bad = []
        for d in self.DIRS:
            for p in sorted((ROOT / 'src' / d).glob('*.c')):
                if p.name == 'stubs.c' or p.name.startswith('test_') or p.name.endswith('_test.c'):
                    continue
                code = re.sub(r'/\*.*?\*/', '', p.read_text(errors='replace'), flags=re.S)
                code = re.sub(r'//[^\n]*', '', code)
                bad += [f'{p.relative_to(ROOT)}: {m.group(1)}' for m in self.CALL.finditer(code)]
        self.assertEqual(bad, [])

    def test_ci_check_knows_the_glibc_only_names(self):
        s = (ROOT / 'tests/check-libc-data-imports.sh').read_text()
        for n in ('__isoc99_', '__isoc23_', '__ctype_(b|tolower|toupper)_loc'):
            self.assertIn(n, s)


class FlashModeRefusesBootCard(unittest.TestCase):
    """rc32 on IPCAM1 (2026-11-06): the initramfs mounts the card read-write for the SD mode and flashmode-prep.sh kept
    it at /mnt/sd "for video storage" even when it is a boot / install card (wifitest/): ADRESSE.txt and the logs were
    written to it, the recorder and the update used it. rec-storage.sh refused it, but only after."""

    def test_same_list_everywhere_and_checked_before_the_card_is_kept(self):
        lists = {}
        for rel in ('scripts/rec-storage.sh', 'scripts/sd-diag.sh', 'v3/linux66-sd/flashmode-prep.sh'):
            lists[rel] = re.search(r'^SD_BOOT_FILES="([^"]+)"', (ROOT / rel).read_text(), re.M).group(1).split()
        self.assertEqual(len({tuple(v) for v in lists.values()}), 1, lists)
        fp = (ROOT / 'v3/linux66-sd/flashmode-prep.sh').read_text()
        self.assertLess(fp.index('[ -e /tmp/cardmnt/$b ]'), fp.index('mount --move /tmp/cardmnt /mnt/sd'))
        self.assertIn('umount /tmp/cardmnt', fp)
        self.assertIn('mount -o remount,ro /tmp/cardmnt', fp)
