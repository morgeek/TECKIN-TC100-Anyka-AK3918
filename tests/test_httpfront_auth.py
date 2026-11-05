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


if __name__ == '__main__':
    unittest.main()
