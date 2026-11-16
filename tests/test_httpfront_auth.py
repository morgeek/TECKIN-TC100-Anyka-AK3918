"""Item 30: the MD5 crypt and Base64 of src/httpfront/md5crypt.h (freestanding, used by httpfront to count wrong web
logins) give the same results as the C library's crypt() / Python's base64: a mistake here would lock the owner out."""
import base64
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    try:
        import crypt
    except ImportError:
        crypt = None

PROG = r'''
#include <stdio.h>
#include "md5crypt.h"
int main(int argc, char **argv)
{
	char out[96], dec[300];
	if (argv[1][0] == 'c') { if (md5crypt(argv[2], argv[3], out)) return 3; puts(out); }
	else { if (b64dec(argv[2], dec, sizeof dec) < 0) return 4; puts(dec); }
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class Md5Crypt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        Path(cls.tmp, 't.c').write_text(PROG)
        subprocess.run(['gcc', '-O1', '-Wall', '-I', str(ROOT / 'src/httpfront'), '-o', str(Path(cls.tmp, 't')),
                        str(Path(cls.tmp, 't.c'))], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_t(self, *a):
        return subprocess.run([str(Path(self.tmp, 't'))] + list(a), capture_output=True, text=True)

    def test_known_vectors(self):
        # reference value from openssl passwd -1 -salt saltsalt password (and glibc crypt)
        self.assertEqual(self.run_t('c', 'password', '$1$saltsalt$').stdout.strip(), '$1$saltsalt$qjXMvbEw8oaL.CzflDtaK/')
        self.assertEqual(self.run_t('c', 'x', 'nope').returncode, 3)

    @unittest.skipUnless(crypt is not None, 'needs the crypt module')
    def test_matches_the_c_library(self):
        for pw, salt in (('pass', 'abcdefgh'), ('', 'xy'), ('a' * 40, 'Zz9./'), ('é mot de passe', 'q1w2e3r4'),
                         ('p:with:colons', '12345678'), ('x' * 17, 'short')):
            want = crypt.crypt(pw, '$1$' + salt + '$')
            self.assertEqual(self.run_t('c', pw, want).stdout.strip(), want, (pw, salt))

    def test_base64(self):
        for raw in (b'root:pass', b'root:', b'a', b'ab', b'abc', b'user:p@ss:w0rd'):
            self.assertEqual(self.run_t('b', base64.b64encode(raw).decode()).stdout.rstrip('\n'), raw.decode())


class LoginCounting(unittest.TestCase):
    """2026-11-12 review of httpfront (WEB_LOCKOUT=1 and HTTPFRONT_NATIVE=1 are the boot.conf defaults)"""

    def setUp(self):
        src = (ROOT / 'src/httpfront/httpfront.c').read_text()
        self.lo = src[src.index('static int login_ok('):src.index('static void lock_note(')]

    def test_only_the_headers_are_searched(self):
        # a form body line "Authorization: Basic x" must not count as a wrong login (owner lockout by a hostile page)
        self.assertIn("if (*h == '\\n' || (*h == '\\r' && h[1] == '\\n')) return -1;", self.lo)

    def test_header_name_and_scheme_in_any_case(self):
        self.assertIn('ipfx(h, "authorization:")', self.lo)
        self.assertIn('ipfx(v, "basic")', self.lo)
        # any run of blanks (TAB too) after "Basic", as busybox httpd accepts
        self.assertNotIn(r"(v[5] != ' ' && v[5] != '\t')", self.lo)      # "BasicYWRt..." (no blank) is read as httpd does
        self.assertIn('if (!ipfx(v, "basic")) return 0;', self.lo)

    def test_present_authorization_is_never_minus_one_for_a_token(self):
        # the token is read like busybox httpd does (alphabet only, no blank needed); a padded guess is counted
        self.assertIn("if (i >= (int)sizeof tok - 1) return 0;", self.lo)
        self.assertNotIn("return -1;	/* cut", self.lo)

    def test_audit_1116_headers_must_end_inside_the_peek(self):
        src = (ROOT / 'src/httpfront/httpfront.c').read_text()
        sv = src[src.index('static void serve('):src.index('int run(')]
        self.assertIn('lockout && (!has_end(b, (int)n) || auth_count(b) > 1)', sv)
        self.assertIn('431', sv)
        self.assertIn('char b[4096]', sv)
        self.assertIn('lockout && has_end(b, (int)n) && hdr_bad(b, (int)n)', sv)
        self.assertIn('#define NLOCK 64', src)

    def test_audit_1116_locked_entry_never_evicted_and_fail_file_renamed(self):
        src = (ROOT / 'src/httpfront/httpfront.c').read_text()
        ln = src[src.index('static void lock_note('):src.index('#include "status.h"')]
        self.assertIn('lk[i].until <= t && (old < 0', ln)
        self.assertIn('full_until = t + LOCK_S', ln)      # a full table fails closed
        self.assertIn('SYS_rename', ln)
        self.assertNotIn('O_TRUNC', ln)

    def test_remembered_login_depends_on_the_password_file(self):
        # a new password (web-auth rewrites httpd.conf) must forget the remembered login
        self.assertIn('md5_update(&m, conf, (unsigned int)n);', self.lo)
        self.assertLess(self.lo.index('read_file(httpd_conf'), self.lo.index('read_file(ok_file'))


if __name__ == '__main__':
    unittest.main()
