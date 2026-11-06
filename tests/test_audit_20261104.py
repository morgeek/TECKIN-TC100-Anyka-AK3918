"""Fixes of the 2026-11-04 audit (docs/linux-port/audit-2026-11-04.md): no request value printed back into an HTML
page, the audit log keeps only a command name, showlog escapes the logs, a password exists before the web server."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class NoReflectedValues(unittest.TestCase):

    def test_error_pages_do_not_print_the_request_back(self):
        for f in ('www/cgi-bin/viewrecords.cgi', 'www/cgi-bin/camcontrols.cgi', 'www/cgi-bin/scripts.cgi'):
            t = text(f)
            for line in t.splitlines():
                if line.lstrip().startswith('#') or 'echo' not in line:
                    continue
                self.assertNotRegex(line, r'echo[^#]*\$\{?F_(cmd|script)\b', (f, line))

    def test_audit_log_keeps_a_command_name_only(self):
        src = text('www/cgi-bin/action.cgi')
        fn = src[src.index('audit_log() {'):src.index('\n}\n', src.index('audit_log() {')) + 3]
        with tempfile.TemporaryDirectory() as d:
            code = fn.replace('/tmp/log', d) + '\naudit_log "$1"\ncat %s/audit.log\n' % d
            r = subprocess.run(SHELL + ['-c', code, 'sh', 'set_x<script>alert(1)</script>\nforged cmd=reboot'],
                               capture_output=True, text=True, env=dict(os.environ, REMOTE_ADDR='192.168.1.5'))
            out = r.stdout
            self.assertEqual(len(out.splitlines()), 1, out)
            self.assertNotIn('<', out)
            self.assertIn('cmd=set_xscriptalert1scriptforgedcmdreb', out)

    def test_showlog_escapes_the_logs(self):
        src = text('www/cgi-bin/action.cgi')
        body = src[src.index('emit_log_tail_dir() {'):src.index('\n}\n', src.index('emit_log_tail_dir() {'))]
        self.assertIn("sed 's/&/\\&amp;/g; s/</\\&lt;/g; s/>/\\&gt;/g'", body)
        r = subprocess.run(SHELL + ['-c', "printf '%s\\n' '<b>&' | sed 's/&/\\&amp;/g; s/</\\&lt;/g; s/>/\\&gt;/g'"],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '&lt;b&gt;&amp;')


class PasswordBeforeTheWebServer(unittest.TestCase):

    def test_user_pwd_seeded_before_web_auth_on_every_path(self):
        a = text('v3/autorun-linux66.sh')
        seed = a.index('[ -s /mnt/config/user.pwd ] || { [ -s /mnt/config/user.pwd.dist ]')
        self.assertLess(seed, a.index('sh /mnt/v3/linux66-sd/web-auth'))
        self.assertGreater(seed, a.index('# 6. Start Web Server'))     # outside the video branch (safe mode too)


class NoControlCharacters(unittest.TestCase):

    def test_web_sources_hold_no_control_characters(self):
        """A backspace (0x08) where `\\b` was meant made the reboot regex of 90-startup.js never match (the dashboard
        said "Command sent" and showed a red error while the camera restarted)."""
        bad = []
        files = [f for base in ('www', 'src/webui', 'scripts', 'controlscripts', 'v3', 'docs') for f in (ROOT / base).rglob('*')]
        files += [ROOT / n for n in ('CHANGELOG.md', 'README.md', 'AGENTS.md', 'CREDITS.md')]
        for f in files:
            if not f.is_file() or f.suffix in ('.png', '.jpg', '.gz', '.ico', '.woff', '.woff2', '.pcm', '.bin'):
                continue
            if 'openipc' in f.relative_to(ROOT).parts:              # raw logs captured from the stock firmware
                continue
            data = f.read_bytes()
            if b'\0' in data[:4096]:
                continue                                           # binary
            if re.search(rb'[\x01-\x08\x0b\x0e-\x1f]', data):
                bad.append(str(f.relative_to(ROOT)))
        self.assertEqual(bad, [])


class RtspInterleavedFrame(unittest.TestCase):

    def test_buffer_ended_after_a_consumed_frame(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        body = src[src.index('static void cli_read(struct cli *c)'):src.index('/* ---- motion detection')]
        frame = body[body.index("== '$'"):body.index('continue;')]
        self.assertIn('c->buf[c->blen] = 0;', frame)
        self.assertIn('if (used > c->blen) { cli_close(c); return; }', body)


class SavesOneAtATime(unittest.TestCase):
    """B5: cfg-persist save takes a lock (a held one is waited for, one left by a dead save is taken over)"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / 'config').mkdir()
        (self.tmp / 'defaults').mkdir()
        self.lock = self.tmp / 'lock'
        self.env = dict(os.environ, CFG=str(self.tmp / 'config'), DEFAULTS=str(self.tmp / 'defaults'),
                        CFG_STATUS=str(self.tmp / 'status'), CFGP_LOCK=str(self.lock))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def save(self):
        return subprocess.Popen(SHELL + [str(ROOT / 'v3/linux66-sd/cfg-persist'), 'save'], env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_waits_for_a_held_lock_then_releases_its_own(self):
        self.lock.mkdir()
        (self.lock / 'pid').write_text('%d\n' % os.getpid())                 # a live holder
        p = self.save()
        try:
            self.assertRaises(subprocess.TimeoutExpired, p.wait, 1.5)
            shutil.rmtree(self.lock)
            self.assertEqual(p.wait(10), 0)                                     # nothing to save: exit 0
        finally:
            if p.poll() is None:
                p.kill()
        self.assertFalse(self.lock.exists())

    def test_lock_of_a_dead_save_is_taken_over(self):
        self.lock.mkdir()
        dead = subprocess.Popen(['true'])
        dead.wait()
        (self.lock / 'pid').write_text('%d\n' % dead.pid)
        p = self.save()
        self.assertEqual(p.wait(10), 0)
        self.assertFalse(self.lock.exists())


class UpdateStopsWhatRestarts(unittest.TestCase):
    """B4, B6: the web update stops the housekeeper (it restarted tc100_rtsp from the stack being erased) and the same
    services as install66.sh, saves the settings and clears the boot counter first, keeps two backups"""

    def test_order_and_lists(self):
        s = text('v3/install/update66.sh')
        body = s[s.index('stopping the services'):s.rindex('for p in stack:stack.sqfs')]
        order = ['housekeeper.sh stop', 'web-guard\\.sh run',
                 'for s in recording motion-detection auto-night-detection; do sh /mnt/controlscripts/$s halt',
                 'for s in rtsp-h26x mqtt-bridge onvif;',
                 'cfg-persist flush', 'boot-guard clear', 'mkdir /tmp/cfg-persist.lock', 'cfg-persist daemon',
                 "sort -r | sed 1d"]
        pos = [body.index(o) for o in order]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('no SD card: the firmware now in the flash is not saved before writing', body)
        r = subprocess.run(SHELL + ['-n', str(ROOT / 'v3/install/update66.sh')])
        self.assertEqual(r.returncode, 0)


class LanOnlyEverywhere(unittest.TestCase):
    """W2: NET_LAN_ONLY reaches httpfront (both launch points) and tc100_rtsp through TC100_NET_ALLOW"""

    def test_launchers_pass_the_list(self):
        a = text('v3/autorun-linux66.sh')
        self.assertIn('TC100_NET_ALLOW="$(sh -c \'. /mnt/scripts/common_functions.sh; netacl_allow_list\' 2>/dev/null)" ', a)
        self.assertIn('TC100_WEB_LOCKOUT="$BC_WEB_LOCKOUT"', a)                   # item 30
        self.assertIn('/mnt/tc100test/httpfront -p 80', a)
        self.assertIn('( TC100_NET_ALLOW="$(netacl_allow_list)"; export TC100_NET_ALLOW', text('scripts/common_functions.sh'))
        launch = text('v3/linux66-sd/rtsp-launch.sh')
        self.assertLess(launch.index('export TC100_NET_ALLOW'), launch.index('exec /tmp/tc100_rtsp'))
        hf = text('src/httpfront/httpfront.c')
        self.assertIn('parse_allow(getenv_(envp, "TC100_NET_ALLOW"));', hf)
        self.assertIn('if (!allowed(ip)) { sc(SYS_close, c, 0, 0, 0, 0); continue; }', hf)


if __name__ == '__main__':
    unittest.main()
