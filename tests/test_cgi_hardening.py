"""Web input hardening from the review of the cgi brief (docs/linux-port/frontier/cgi-2026-11-11.md).

Run in busybox ash, the camera's shell: the form parser must not expand file names nor execute a value, the CSRF
guard must not accept an empty token, action.cgi must refuse a GET that changes something, sanitize_int_range must
not let a huge number or a leading zero through, and the import must not write shell code into a sourced file.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASH = shutil.which("busybox")


def ash(code, env=None, cwd=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([ASH, "ash", "-c", code], capture_output=True, text=True, env=e, cwd=cwd, timeout=20)


def block(path, start, end):
    s = (ROOT / path).read_text(encoding="utf-8")
    i = s.index(start)
    return s[i:s.index(end, i) + len(end)]


def shfunc(path, name):
    s = (ROOT / path).read_text(encoding="utf-8")
    return re.search(r"^" + re.escape(name) + r"\(\)\s*\{.*?^}", s, re.M | re.S).group(0)


@unittest.skipUnless(ASH, "needs busybox")
class CgiHardening(unittest.TestCase):
    def parse(self, qs, cwd=None):
        code = (shfunc("www/cgi-bin/func.cgi", "urldecode") + "\n"
                + block("www/cgi-bin/func.cgi", "_IFS=${IFS}; IFS='&'; set -f", "unset _IFS _VAR name raw_value value")
                + '\nset | grep "^F_" ; echo "glob=$(echo /proc/se*)"')
        return ash(code, {"QUERY_STRING": qs}, cwd)

    def test_parser_does_not_expand_file_names(self):
        with tempfile.TemporaryDirectory() as t:
            Path(t, "abc").write_text("")
            r = self.parse("a*&x=1&y=/proc/*", cwd=t)
        self.assertNotIn("F_abc", r.stdout)
        self.assertIn("F_x='1'", r.stdout)
        self.assertIn("F_y='/proc/*'", r.stdout)
        self.assertNotIn("glob=/proc/se*", r.stdout)     # set +f again after the loop

    def test_parser_never_executes_a_value(self):
        with tempfile.TemporaryDirectory() as t:
            mark = Path(t, "pwned")
            qs = "a=%24(touch%20" + str(mark).replace("/", "%2F") + ")&b=%60touch%20x%60&c=%22%3Becho%20hi%3B%22&d=%5C"
            r = self.parse(qs, cwd=t)
            self.assertFalse(mark.exists())
            self.assertFalse(Path(t, "x").exists())
        self.assertIn("F_a='$(touch", r.stdout)
        self.assertIn("F_c='\";echo hi;\"'", r.stdout)
        self.assertIn("F_d='\\'", r.stdout)

    def csrf(self, stored, header, method="POST"):
        with tempfile.TemporaryDirectory() as t:
            tok = Path(t, "tok")
            if stored is not None:
                tok.write_text(stored)
            f = shfunc("www/cgi-bin/func.cgi", "csrf_guard").replace("/tmp/csrf_token", str(tok))
            f = f.replace("< /proc/sys/kernel/random/uuid", "< /nonexistent")
            code = "logger() { :; }; hexdump() { cat >/dev/null; }; md5sum() { cat >/dev/null; }\n" + f + "\ncsrf_guard; echo PASSED"
            return ash(code, {"REQUEST_METHOD": method, "HTTP_X_CSRF_TOKEN": header, "PATH": os.environ["PATH"]})

    def test_csrf_refuses_an_empty_token(self):
        # the token cannot be made (no hexdump, no md5sum): an empty header must not match it
        r = self.csrf(None, "")
        self.assertNotIn("PASSED", r.stdout)
        self.assertIn("403", r.stdout)

    def test_csrf_accepts_the_right_token_only(self):
        t = "0123456789abcdef0123456789abcdef"
        self.assertIn("PASSED", self.csrf(t, t).stdout)
        self.assertNotIn("PASSED", self.csrf(t, t[:-1] + "0").stdout)
        self.assertIn("PASSED", self.csrf(t, "", "GET").stdout)

    def gate(self, method, cmd):
        code = block("www/cgi-bin/action.cgi", 'ACTION_GET_READS="', "    esac ;;\nesac\n") + "\necho PASSED"
        env = {"F_cmd": cmd}
        if method:
            env["REQUEST_METHOD"] = method
        return ash(code, env)

    def test_get_cannot_change_anything(self):
        for cmd in ("reboot", "shutdown", "set_all_password", "isp_tune", "sd_card_format", "", "x"):
            r = self.gate("GET", cmd)
            self.assertNotIn("PASSED", r.stdout, cmd)
            self.assertIn("405", r.stdout, cmd)
        self.assertNotIn("PASSED", self.gate("HEAD", "reboot").stdout)
        for cmd in ("sd_card_info", "rtsp_server_info", "md_zones_info", "wifi_get_ssid", "showlog"):
            self.assertIn("PASSED", self.gate("GET", cmd).stdout, cmd)
        self.assertIn("PASSED", self.gate("POST", "reboot").stdout)
        self.assertIn("PASSED", self.gate(None, "reboot").stdout)    # not a web request: scripts, tests

    def test_every_get_read_of_the_pages_is_allowed(self):
        reads = re.search(r'ACTION_GET_READS="([a-z_ ]+)"', (ROOT / "www/cgi-bin/action.cgi").read_text()).group(1).split()
        used = set()
        for p in list((ROOT / "www").glob("*.html")) + list((ROOT / "src/webui").rglob("*.js")):
            for m in re.finditer(r"(?<![A-Za-z])fetch\(\s*['\"]cgi-bin/action\.cgi\?cmd=([a-z_0-9]+)", p.read_text(encoding="utf-8")):
                used.add(m.group(1))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(reads)), [])

    def test_sanitize_int_range(self):
        f = shfunc("www/cgi-bin/action.cgi", "sanitize_int_range")
        for v, want in (("99999999999999999999", "50"), ("08", "8"), ("0012", "12"), ("0", "0"), ("100", "100"),
                        ("150", "100"), ("abc", "50"), ("", "50")):
            r = ash(f + f'\nsanitize_int_range "{v}" 0 100 50')
            self.assertEqual(r.stdout.strip(), want, v)

    def test_import_cannot_write_shell_code_into_a_sourced_file(self):
        exch = (ROOT / "www/cgi-bin/config_exchange.cgi").read_text()
        tx = (ROOT / "scripts/config-transaction.sh").read_text()
        # notify.conf is sourced by notify.sh: a value between double quotes must not hold $ ` " \
        self.assertIn('. "$NOTIFY_CONF"', (ROOT / "scripts/notify.sh").read_text())
        for key, typ in re.findall(r'row\("notify\.conf";"flatd";"root";"([A-Z_]+)";"([a-z_]+)"', exch):
            self.assertNotIn(typ, ("credential", "credential_optional", "safe_text", "safe_text_optional"), key)
        self.assertIn('tc_check_flat "$_tc_file" NOTIFY_UPLOAD_AUTH ntfy_auth "$_tc_rel" || return 1', tx)


if __name__ == "__main__":
    unittest.main()
