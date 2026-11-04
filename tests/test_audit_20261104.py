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


class RtspInterleavedFrame(unittest.TestCase):

    def test_buffer_ended_after_a_consumed_frame(self):
        src = text('src/tc100rtsp/tc100_rtsp.c')
        body = src[src.index('static void cli_read(struct cli *c)'):src.index('/* ---- motion detection')]
        frame = body[body.index("== '$'"):body.index('continue;')]
        self.assertIn('c->buf[c->blen] = 0;', frame)
        self.assertIn('if (used > c->blen) { cli_close(c); return; }', body)


if __name__ == '__main__':
    unittest.main()
