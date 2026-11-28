"""The acceptance bench (tests/camera/): syntax for BusyBox ash, the guards of the safety rules, --list and --dry-run
without side effects, and the rule that no build takes tests/camera. The bench itself runs on the camera: these tests
do not run a check (see tests/camera/README.md)."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAM = ROOT / 'tests' / 'camera'
BENCH = CAM / 'recette.sh'
HOST = CAM / 'recette-host.sh'
SCRIPTS = [BENCH, HOST]
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']

# the safety rules of the bench: a word here is a failure wherever it appears (comments included)
FORBIDDEN = ['flashw', '/dev/mtd', 'fw_setenv', 'envtool', 'reboot', 'cfg-persist save', 'saveenv', 'setenv',
             'poweroff', 'shutdown', 'halt', 'bootargs']

# the readiness items the bench must cover (readiness-3.0.2.md section 1, scriptable parts)
REQUIRED_IDS = ['AUDIT-1116-KERNEL', 'AUDIT-1116-VENCIRQ', 'AUDIT-1116-USB', 'AUDIT-1116-RTSP', 'AUDIT-1116-NET',
                'CLEANUP-1124', 'SMALL-B-1124', 'SMALL-A-1124', 'WIFIQ-FORKS', 'HARDEN', 'R2-BUTTON', 'W1-PRIVFILL',
                'W3-ZERO', 'B4-HUE', 'T1B5-PARITY', 'W5-AUDIT', 'MEMWATCH', 'FAILCOUNT', 'R3-MQTT']
MODES = {'safe', 'dist', 'wifi', 'manual'}
HOST_NEEDS = ['password', 'mqtt', '']


def text(path):
    return path.read_text(encoding='utf-8')


def run(args, env=None, cwd=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=cwd,
                          env=dict(os.environ, **(env or {})))


def code_lines(path):
    return [line for line in text(path).splitlines() if line.strip() and not line.lstrip().startswith('#')]


class BenchStatic(unittest.TestCase):
    def test_files_present_and_lf(self):
        for p in SCRIPTS + [CAM / 'README.md']:
            self.assertTrue(p.is_file(), p)
            self.assertNotIn(b'\r', p.read_bytes(), f'CRLF in {p}')

    def test_syntax_for_sh_and_busybox(self):
        for p in SCRIPTS:
            r = run(['sh', '-n', str(p)])
            self.assertEqual(r.returncode, 0, r.stderr)
            if shutil.which('busybox'):
                r = run(['busybox', 'ash', '-n', str(p)])
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_bashisms(self):
        pats = [r'\[\[', r'<<<', r'\$\'', r'\bfunction\s+\w+', r'\blocal\s', r'\bdeclare\s', r'\bpushd\b',
                r'\bsource\s', r'\bselect\s+\w+\s+in\b', r'==']
        for p in SCRIPTS:
            for line in code_lines(p):
                for pat in pats:
                    if pat == '==':
                        # only inside [ ... ] is it a bashism (busybox test takes =)
                        self.assertFalse(re.search(r'\[\s[^\]]*==', line), f'{p.name}: {line}')
                    else:
                        self.assertIsNone(re.search(pat, line), f'{p.name}: {pat} in {line}')

    def test_forbidden_words_absent(self):
        for p in SCRIPTS:
            low = text(p).lower()
            for word in FORBIDDEN:
                self.assertNotIn(word, low, f'{p.name} contains {word!r}')

    def test_no_password_printed_or_logged(self):
        for p in SCRIPTS:
            for line in text(p).splitlines():
                if 'RECETTE_PASS' in line and not line.lstrip().startswith('#'):
                    self.assertFalse(re.search(r'\becho\b|\bRESULT\b|\bprintf\b.*>>?\s*\$', line),
                                     f'{p.name}: password near an output: {line}')

    def test_bench_traps_exit_int_term(self):
        self.assertIn('trap cleanup EXIT INT TERM', text(BENCH))

    def test_bench_cannot_run_a_flash_or_env_write(self):
        # the bench writes only under its run folder, /tmp and the camera's RAM logs; no write to /mnt/config
        for line in code_lines(BENCH):
            if re.search(r'>\s*/mnt/config|>>\s*/mnt/config|tee\s+/mnt/config', line):
                self.fail(f'bench writes under /mnt/config: {line}')

    def test_only_camera_scripts_do_not_restart_the_wifi_by_gpio(self):
        self.assertNotIn('WIFI_POWER_GPIO', text(BENCH))
        self.assertNotIn('wifi-recover', text(BENCH))


class BenchLists(unittest.TestCase):
    def setUp(self):
        self.lines = run(['sh', str(BENCH), '--list']).stdout.splitlines()

    def test_list_one_line_per_check(self):
        self.assertGreaterEqual(len(self.lines), 50)
        seen = set()
        for line in self.lines:
            parts = line.split(' ')
            self.assertEqual(len(parts), 3, line)
            self.assertIn(parts[2], MODES, line)
            self.assertNotIn(tuple(parts[:2]), seen, f'duplicate check {line}')
            seen.add(tuple(parts[:2]))

    def test_list_covers_the_readiness_items(self):
        ids = {line.split(' ')[0] for line in self.lines}
        host = run(['sh', str(HOST), '--list']).stdout.splitlines()
        ids |= {line.split(' ')[0] for line in host}
        for want in REQUIRED_IDS:
            self.assertIn(want, ids)

    def test_dry_run_one_line_per_check_and_no_folder(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, 'run')
            r = run(['sh', str(BENCH), '--dry-run', '--out', out])
            self.assertEqual(r.returncode, 0, r.stderr)
            dry = r.stdout.splitlines()
            self.assertEqual(len(dry), len(self.lines))
            self.assertTrue(all(line.startswith('DRY ') for line in dry))
            self.assertFalse(os.path.exists(out), 'dry run created the run folder')
            only = run(['sh', str(BENCH), '--dry-run', '--only', 'HARDEN,FAILCOUNT'])
            self.assertEqual(len(only.stdout.splitlines()), 6)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_manual_checks_say_why(self):
        src = code_lines(BENCH)
        manual = [l for l in src if '|manual|' in l]
        self.assertTrue(manual)
        for l in manual:
            self.assertTrue(l.split('|')[4].strip(), f'manual check without a reason: {l}')


class HostScript(unittest.TestCase):
    def test_host_list_and_dry_run_touch_nothing(self):
        # a fake ssh, scp, curl, nc and mosquitto that leave a marker: the dry run must not call them
        tmp = tempfile.mkdtemp()
        try:
            bindir = os.path.join(tmp, 'bin')
            os.mkdir(bindir)
            marker = os.path.join(tmp, 'called')
            for name in ['ssh', 'scp', 'curl', 'nc', 'mosquitto_pub', 'mosquitto_sub', 'ffprobe']:
                p = os.path.join(bindir, name)
                with open(p, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('#!/bin/sh\necho "$0 $*" >> "%s"\nexit 1\n' % marker)
                os.chmod(p, 0o755)
            env = {'PATH': bindir + os.pathsep + os.environ.get('PATH', ''), 'RECETTE_PASS': 'not-used-here'}
            lst = run(['sh', str(HOST), '--list'], env=env).stdout.splitlines()
            self.assertGreaterEqual(len(lst), 10)
            for line in lst:
                self.assertEqual(len(line.split(' ')), 3, line)
                self.assertTrue(line.endswith(' host'), line)
            dry = run(['sh', str(HOST), '--dry-run', '--camera', '192.0.2.10'], env=env)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse(os.path.exists(marker), 'a dry run or --list called ssh/curl/nc')
            self.assertGreaterEqual(len(dry.stdout.splitlines()), len(lst) + 50)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_host_requires_camera_for_a_run(self):
        r = run(['sh', str(HOST)], env={'RECETTE_CAMERA': ''})
        self.assertNotEqual(r.returncode, 0)

    def test_host_never_echoes_secrets(self):
        for line in text(HOST).splitlines():
            if ('RECETTE_PASS' in line or 'RECETTE_MQTT_PASS' in line) and not line.lstrip().startswith('#'):
                self.assertIsNone(re.search(r'\becho\b.*\$RECETTE_(MQTT_)?PASS', line), line)


class BuildIsolation(unittest.TestCase):
    """No build, package or test pack takes tests/camera: a glob or a copy of tests/ in a build file would."""
    SKIP_DIRS = {'.git', 'tests', 'docs', 'node_modules', 'scratchpad', '.pytest_cache', '__pycache__'}
    SKIP_NAMES = {'.git'}

    def test_no_build_file_names_the_bench(self):
        bad = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            rel = Path(dirpath).relative_to(ROOT)
            if rel.parts and rel.parts[0] in ('docs',):
                continue
            for name in filenames:
                if name in self.SKIP_NAMES:
                    continue
                p = Path(dirpath) / name
                if p.suffix not in ('.sh', '.mk', '.yml', '.yaml', '.in', '') and name != 'Makefile':
                    continue
                try:
                    body = p.read_text(encoding='utf-8')
                except (UnicodeDecodeError, OSError):
                    continue
                if 'tests/camera' in body or 'recette' in body.lower():
                    bad.append(str(p.relative_to(ROOT)))
        self.assertEqual(bad, [], 'a build file names the bench')

    def test_no_build_copies_the_tests_folder(self):
        pat = re.compile(r'(cp|tar|find|rsync|zip)\b[^\n]*\btests\b')
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in self.SKIP_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix not in ('.sh', '.mk', '.yml', '.yaml') and name != 'Makefile':
                    continue
                try:
                    body = p.read_text(encoding='utf-8')
                except (UnicodeDecodeError, OSError):
                    continue
                for line in body.splitlines():
                    if pat.search(line) and not line.lstrip().startswith('#') and 'tests/docker' not in line \
                            and 'tests/ci-vendor' not in line:
                        self.fail(f'{p.relative_to(ROOT)} copies tests/: {line.strip()}')

    def test_docs_point_at_the_entry(self):
        queue = (ROOT / 'docs' / 'linux-port' / 'test-queue.md').read_text(encoding='utf-8')
        self.assertIn('### RECETTE-BENCH', queue)
        ready = (ROOT / 'docs' / 'linux-port' / 'readiness-3.0.2.md').read_text(encoding='utf-8')
        self.assertIn('recette-host.sh', ready)

class SafetyGuards(unittest.TestCase):
    """Review fixes of the 3.0.2 bench: night mode, config snapshot, Wi-Fi address and route, SIGSTOP cleanup,
    credentials, MQTT retained check, PATH."""

    def bench(self):
        return text(BENCH)

    def host(self):
        return text(HOST)

    def test_nightmode_only_with_keep_auto(self):
        for line in self.bench().splitlines():
            if '/mnt/scripts/nightmode.sh' in line and not line.lstrip().startswith('#'):
                self.assertIn('NIGHT_KEEP_AUTO=1', line, f'nightmode.sh without the keep-auto variable: {line}')

    def test_no_auto_night_detection_restart(self):
        self.assertNotIn('auto-night-detection restart', self.bench())
        self.assertNotIn('auto-night-detection stop', self.bench())

    def test_no_sigstop_in_the_bench(self):
        # SIGSTOP does not simulate a capture stall (tc100_rtsp.c discounts a stopped process): the check is manual
        self.assertNotIn('kill -STOP', self.bench())
        self.assertIn('AUDIT-1116-RTSP|stall-exit|manual|skip_manual|SIGSTOP', self.bench())

    def test_stopped_server_is_not_running(self):
        self.assertIn('[ "$_st" = T ]', self.bench())

    def test_config_check_is_detect_only(self):
        b = self.bench()
        self.assertIn('config-before.md5', b)
        self.assertIn('config-unchanged', b)
        self.assertIn('INFO GLOBAL', b)
        self.assertNotIn('config-before/', b)
        self.assertNotIn('cp -R', b)
        self.assertNotIn('cp -f', b)

    def test_no_write_to_mnt_config(self):
        # the bench never creates, copies, moves, removes or redirects into /mnt/config (the camera's own daemons write
        # there; the bench only reads it, see tests/camera/README.md)
        write = re.compile(r'\b(cp|mv|rm|tee|touch|chmod|chown|install)\b|sed -i|>>?\s*"?\S*/mnt/config')
        for line in code_lines(BENCH):
            if '/mnt/config' in line:
                self.assertIsNone(write.search(line), f'write near /mnt/config: {line.strip()}')

    def test_path_has_ext_bin(self):
        self.assertTrue(any(line.startswith('PATH=/mnt/ext/bin:') for line in self.bench().splitlines()))

    def test_daemon_night_flag_nonce(self):
        b = self.bench()
        self.assertIn('/var/run/tc100-sv.night', b)
        self.assertIn('auto_on', b)

    def test_wifi_keeps_address_and_route(self):
        b = self.bench()
        self.assertIn('pidof udhcpc', b)
        self.assertIn('ip route add default via', b)
        self.assertIn('ip addr add', b)
        self.assertIn('kill -USR1', b)
        self.assertIn('command -v wpa_cli', b)

    def test_no_nul_bytes(self):
        for p in SCRIPTS + [Path(__file__)]:
            self.assertNotIn(bytes([0]), p.read_bytes(), p.name)

    def test_mosquitto_options_file_format(self):
        h = self.host()
        self.assertIn('"-h $RECETTE_MQTT_HOST"', h)
        self.assertIn('"-P $RECETTE_MQTT_PASS"', h)
        self.assertNotIn('echo "host ', h)

    def test_host_credentials_stay_out_of_argv(self):
        h = self.host()
        for line in h.splitlines():
            if line.lstrip().startswith('mosquitto_'):
                self.assertNotIn(' -P ', line, line)
        self.assertIn('XDG_CONFIG_HOME', h)
        self.assertIn('chmod 700', h)
        self.assertNotIn('sed "s|$RECETTE_PASS', h)
        self.assertIn('index(s, p)', h)

    def test_mqtt_retained_check_order_and_trap(self):
        h = self.host()
        body = h.split('h_mqtt_retained() {', 1)[1].split('h_mqtt_two() {', 1)[0]
        self.assertLess(body.index('mosquitto_sub -t "$RES_TOPIC"'), body.index('mqtt-bridge restart'))
        self.assertIn('delta=', body)
        self.assertIn('RETAINED_SET=1', body)
        self.assertIn('RETAINED_SET:-0', h)

    def test_hold_restart_is_manual(self):
        self.assertIn('SMALL-A-1124|hold-restart|manual|', self.bench())
        self.assertNotIn('c_hold_restart', self.bench())


def function_text(src, name):
    """The text of one shell function of a script (its one-line form, or from its header to the closing brace)."""
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(name + '() {'):
            if line.rstrip().endswith('}'):
                return line
            body = [line]
            for later in lines[i + 1:]:
                body.append(later)
                if later == '}':
                    return '\n'.join(body)
    raise AssertionError(f'no function {name} in the bench')


class BenchLoops(unittest.TestCase):
    """The loops of the bench run for real under stubs (sleep, kill, pidof, ssh-less sh, venc_irq): busybox ash when it is
    installed, else sh. kill_cycles must run exactly N cycles, also when a helper it calls clobbers a counter."""

    STUBS = r'''
sleep() { :; }
pidof() { cat "$PIDF"; }
ctr() { echo 7; }
sh() { echo "sh $*" >> "$SHLOG"; case "$*" in *start*) _pp=$(cat "$PIDF"); echo $((_pp + 1)) > "$PIDF" ;; esac; return 0; }
kill() { case "$1" in -0) return 1 ;; *) echo "$*" >> "$KLOG"; return 0 ;; esac; }
venc_irq() { _vn=$(cat "$VF"); echo $((_vn + 10)) > "$VF"; echo $((_vn + 10)); }
'''

    def harness(self, names, body, stat_line=True, extra_env=None, tmp=None):
        tmp = tmp or tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        paths = {k: os.path.join(tmp, v) for k, v in {
            'LOG': 'tc100_rtsp.log', 'RESFILE': 'results.txt', 'LOGF': 'recette.log', 'SHLOG': 'sh.log',
            'KLOG': 'kill.log', 'VF': 'vf', 'PIDF': 'pid'}.items()}
        env = dict(paths, T=tmp)
        with open(paths['VF'], 'w', encoding='utf-8', newline='\n') as f:
            f.write('100\n')
        with open(paths['PIDF'], 'w', encoding='utf-8', newline='\n') as f:
            f.write('4242\n')   # each start of the fake server gives it a new pid (the stub sh)
        for k in ('RESFILE', 'LOGF', 'SHLOG', 'KLOG'):
            open(paths[k], 'w', encoding='utf-8').close()
        with open(paths['LOG'], 'w', encoding='utf-8', newline='\n') as f:
            f.write('STAT cap 1 enc 1 pp_ms 1\n' if stat_line else '')
        src = text(BENCH)
        bounds = 'MAX_LOOP=1000\nMAX_WAIT_S=3600\n'   # the bench's own constants (recette.sh, top)
        script = '#!/bin/sh\n' + bounds + '\n'.join(function_text(src, n) for n in names) + '\n' + self.STUBS + body + '\n'
        path = os.path.join(tmp, 'harness.sh')
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(script)
        env.update(extra_env or {})
        return run(SHELL + [path], env=env), env

    def lines(self, path):
        return [l for l in Path(path).read_text(encoding='utf-8').splitlines() if l]

    KILL_NAMES = ['ev', 'res', 'rtsp_pid', 'log_count', 'ensure_rtsp', 'wait_stat', 'wait_gone', 'kill_cycles']
    KILL_BODY = 'CUR_ID=AUDIT-1116-KERNEL; CUR_CHECK=kill-loop; CUR=x; RESN=0\n' \
                'kill_cycles 3 "$T/kill.stats"\necho "K_OK=$K_OK K_BAD=$K_BAD"\n'

    def test_kill_cycles_runs_exactly_n(self):
        r, env = self.harness(self.KILL_NAMES, self.KILL_BODY)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('K_OK=3 K_BAD=0', r.stdout)
        self.assertEqual(sum(1 for l in self.lines(env['KLOG']) if l.startswith('-TERM')), 3)
        self.assertEqual(len(self.lines(os.path.join(env['T'], 'kill.stats'))), 3)

    def test_kill_cycles_counts_a_missing_stat_as_bad_and_stops(self):
        r, env = self.harness(self.KILL_NAMES, self.KILL_BODY, stat_line=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('K_OK=0 K_BAD=3', r.stdout)
        self.assertEqual(sum(1 for l in self.lines(env['KLOG']) if l.startswith('-TERM')), 3)

    def test_kill_cycles_still_exact_when_a_helper_clobbers_the_counters(self):
        # ensure_rtsp runs inside the loop: it resets every counter a helper could own, the loop counter included
        clobber = 'ensure_rtsp() { _i=0; _kc_n=0; _ws_n=0; _wg_n=0; _wa_n=0; _nb_n=0; }\n'
        r, env = self.harness(self.KILL_NAMES, clobber + self.KILL_BODY)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('K_OK=3 K_BAD=0', r.stdout)
        self.assertEqual(sum(1 for l in self.lines(env['KLOG']) if l.startswith('-TERM')), 3)

    def test_stream_cycles_run_their_count(self):
        body = 'CUR_ID=CLEANUP-1124; CUR_CHECK=stream-cycles; CUR=x; RESN=0\nc_stream_cycles\n'
        r, env = self.harness(['ev', 'res', 'rtsp_pid', 'wait_stat', 'c_stream_cycles'], body,
                              extra_env={'RECETTE_STREAM_CYCLES': '4'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sum(1 for l in self.lines(env['SHLOG']) if 'stop' in l), 4)
        self.assertEqual(sum(1 for l in self.lines(env['SHLOG']) if 'start' in l), 4)
        self.assertIn('4/4 stop + start cycles', Path(env['RESFILE']).read_text(encoding='utf-8'))

    def test_reassociate_runs_five_and_passes_without_a_drop(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        bindir = os.path.join(tmp, 'bin')
        os.mkdir(bindir)
        for name, body in (('wpa_cli', 'echo "$*" >> "$WPALOG"\nexit 0\n'), ('iw', 'exit 0\n')):
            with open(os.path.join(bindir, name), 'w', encoding='utf-8', newline='\n') as f:
                f.write('#!/bin/sh\n' + body)
            os.chmod(os.path.join(bindir, name), 0o755)
        body = ('wlan_assoc() { return 0; }\nwlan_addr_now() { echo 10.0.0.2; }\ngateway() { echo 10.0.0.1; }\n'
                'net_save() { :; }\nwlan_restore() { :; }\n'
                'CUR_ID=AUDIT-1116-USB; CUR_CHECK=wpa-reassociate; CUR=x; RESN=0\nc_reassoc\n')
        r, env = self.harness(['ev', 'res', 'c_reassoc', 'wait_assoc', 'net_back'], body, tmp=tmp,
                              extra_env={'WPALOG': os.path.join(tmp, 'wpa.log'),
                                         'PATH': bindir + os.pathsep + os.environ.get('PATH', '')})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.lines(env['WPALOG'])), 5)
        self.assertIn('5/5 reassociate commands ok, 5/5 back with address and route',
                      Path(env['RESFILE']).read_text(encoding='utf-8'))


    SETTLED_NAMES = ['stat_count', 'stat_window_vals', 'stat_settled']

    def settled(self, caps):
        body = 'printf "STAT cap %s enc 1\\n" ' + ' '.join(str(c) for c in caps) + ' > "$LOG"\n' \
               'stat_settled cap && echo SETTLED || echo MOVING\n'
        r, _ = self.harness(self.SETTLED_NAMES, body)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_privacy_baseline_waits_for_the_catch_up(self):
        # IPCAM1, 2026-11-27: the windows after the kill loop were 71 113 104 55 50 51 (10 fps camera)
        self.assertEqual(self.settled([71, 113, 104]), 'MOVING')
        self.assertEqual(self.settled([113, 104, 55]), 'MOVING')
        self.assertEqual(self.settled([104, 55, 50]), 'MOVING')
        self.assertEqual(self.settled([71, 113, 104, 55, 50, 51]), 'SETTLED')
        self.assertEqual(self.settled([0, 0, 0]), 'SETTLED')
        self.assertEqual(self.settled([50, 51]), 'MOVING')

    def test_privacy_waits_for_a_steady_rate_before_its_baseline(self):
        body = function_text(text(BENCH), 'c_privacy')
        self.assertLess(body.index('stat_settled cap'), body.index('_pv_a0=$(stat_count)'))


class BenchStaticLoops(unittest.TestCase):
    def test_every_while_counter_belongs_to_one_function(self):
        src = text(BENCH)
        owner = {}
        cur = None
        for line in src.splitlines():
            m = re.match(r'^(\w+)\(\) \{', line)
            if m:
                cur = m.group(1)
            for name in re.findall(r'\b(_\w+)=', line):
                owner.setdefault(name, set()).add(cur)
            if line == '}' or (m and line.rstrip().endswith('}')):
                cur = None
        counters = set(re.findall(r'while \[ "?\$(\w+)"? -(?:lt|le) ', src))
        counters |= set(re.findall(r'while \[ "?\$(_\w+)"? -(?:lt|le) ', src))
        self.assertTrue(counters)
        for name in counters:
            self.assertIsInstance(owner.get(name), set, name)
            self.assertEqual(len(owner[name]), 1, f'loop counter {name} is set in {owner[name]}')

    def test_every_counted_loop_has_an_upper_bound(self):
        for p in SCRIPTS:
            for line in code_lines(p):
                if re.match(r'\s*while \[', line) and '$#' not in line:
                    self.assertTrue(re.search(r' -(lt|le) ', line), f'{p.name}: loop without a bound: {line}')


class BenchTransport(unittest.TestCase):
    def test_no_scp_anywhere(self):
        for p in SCRIPTS:
            for line in code_lines(p):
                self.assertIsNone(re.search(r'\bscp\b', line), f'{p.name}: {line}')

    def test_every_ssh_command_takes_the_options(self):
        for line in code_lines(HOST):
            if re.search(r'(^|[;&|({])\s*ssh\s', line):
                self.assertIn('SSHO', line, f'ssh without the options: {line}')

    def test_ssh_options_variable_documented(self):
        self.assertIn('RECETTE_SSH_OPTS', text(HOST))
        self.assertIn('RECETTE_SSH_OPTS', (CAM / 'README.md').read_text(encoding='utf-8'))

    def test_summary_counts_are_result_lines_by_status(self):
        for p in SCRIPTS:
            self.assertIsNone(re.search(r"grep -c ' (PASS|FAIL|SKIP) ", text(p)), p.name)
        self.assertIn('$1 == "RESULT"', text(BENCH))
        self.assertIn('$1 == "RESULT"', text(HOST))


class BenchRc5Checks(unittest.TestCase):
    """3.2 checks in tests/camera/recette.sh: Dropbear 2026.93 listener netacl check and flash-mode PRIVDROP pwd check."""

    def test_c_ssh_maps_skips_reexec_session_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / 'proc'
            for pid, cmd, maps in (
                ('101', b'dropbear\x00-R\x00-P\x00/var/run/dropbear.pid\x00', '76f00000 libnetacl-musl.so\n'),
                ('202', b'dropbear\x00-2\x008\x00', '76f00000 libc.so\n'),
            ):
                pdir = proc / pid
                pdir.mkdir(parents=True)
                (pdir / 'cmdline').write_bytes(cmd)
                (pdir / 'maps').write_text(maps, encoding='utf-8')
            fn = function_text(text(BENCH), 'c_ssh_maps').replace('"/proc/$_p', f'"{proc}/$_p')
            resfile = Path(tmp) / 'res'
            script = (
                '#!/bin/sh\n'
                f'res() {{ echo "$1|$2" > "{resfile}"; }}\n'
                'pidof() { echo "101 202"; }\n'
                + fn + '\nc_ssh_maps\n'
            )
            subprocess.run(['sh', '-c', script], check=True)
            self.assertEqual(resfile.read_text(encoding='utf-8').strip(),
                             'PASS|1 of 1 dropbear listener(s) map libnetacl-musl.so (1 session child(ren) skipped)')
            # Missing preload on the listener itself must still fail
            (proc / '101' / 'maps').write_text('76f00000 libc.so\n', encoding='utf-8')
            subprocess.run(['sh', '-c', script], check=True)
            self.assertTrue(resfile.read_text(encoding='utf-8').startswith('FAIL|0 of 1 '))

    def test_c_pwd_file_modes_and_sd_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            cfg = t / 'config'
            cfg.mkdir()
            (cfg / 'user.pwd').write_text('hash\n', encoding='utf-8')
            flashflag = t / 'flashmode'
            resfile = t / 'res'
            fn = (function_text(text(BENCH), 'c_pwd_file')
                  .replace('/mnt/config', str(cfg))
                  .replace('/tmp/flashmode', str(flashflag)))

            def run_case(boot_conf, mode_str, gid_str, flash=True):
                (cfg / 'boot.conf').write_text(boot_conf, encoding='utf-8')
                if flash:
                    flashflag.write_text('1', encoding='utf-8')
                elif flashflag.exists():
                    flashflag.unlink()
                script = (
                    '#!/bin/sh\n'
                    f'res() {{ echo "$1|$2" > "{resfile}"; }}\n'
                    f'ls() {{ if [ "$1" = "-ln" ]; then echo "{mode_str} 1 0 {gid_str} 5 Nov 28 12:00 $2"; else echo "user.pwd"; fi; }}\n'
                    + fn + '\nc_pwd_file\n'
                )
                subprocess.run(['sh', '-c', script], check=True)
                return resfile.read_text(encoding='utf-8').strip()

            self.assertTrue(run_case('', '-rwxr-xr-x', '0', flash=False).startswith('SKIP|SD trial'))
            self.assertTrue(run_case('PRIVDROP=1\n', '-rw-r-----', '1001', flash=True).startswith('PASS|user.pwd mode -rw-r----- group 1001'))
            self.assertTrue(run_case('PRIVDROP=1\n', '-rw-------', '0', flash=True).startswith('FAIL|'))
            self.assertTrue(run_case('PRIVDROP=0\n', '-rw-------', '0', flash=True).startswith('PASS|user.pwd mode -rw-------'))


if __name__ == '__main__':
    unittest.main()
