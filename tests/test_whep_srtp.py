"""Item 35: the SRTP code of the WHEP gateway (src/whep/srtp.h): the published vectors (FIPS-197, RFC 3174,
RFC 2202, RFC 3711 B.2 / B.3) through srtp-bench -t, and one protected packet decrypted back with the same keystream."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src/whep'

ROUNDTRIP = r'''
#include <stdio.h>
#include "srtp.h"
int main(void)
{
	uint8_t mk[16], ms[14], p[200 + 10], q[200];
	struct srtp_ctx s;
	int i;
	for (i = 0; i < 16; i++) mk[i] = (uint8_t)i;
	for (i = 0; i < 14; i++) ms[i] = (uint8_t)(100 + i);
	srtp_init(&s, mk, ms);
	for (i = 0; i < 200; i++) p[i] = (uint8_t)(i * 3);
	p[0] = 0x80; p[2] = 0xff; p[3] = 0xfe;				/* sequence 65534 */
	memcpy(q, p, 200);
	if (srtp_protect(&s, p, 200) != 210) return 1;
	if (!memcmp(p + 12, q + 12, 188) || memcmp(p, q, 12)) return 2;	/* payload changed, header kept */
	srtp_aes_cm(&s.enc, s.salt, aes_be32(q + 8), 0xfffe, p + 12, 188);	/* the same keystream decrypts */
	if (memcmp(p + 12, q + 12, 188)) return 3;
	{	/* the tag is HMAC-SHA1(header + payload + ROC), first 10 bytes */
		uint8_t tag[20], roc[4] = { 0, 0, 0, 0 }, r[200];
		memcpy(r, q, 200);
		srtp_aes_cm(&s.enc, s.salt, aes_be32(q + 8), 0xfffe, r + 12, 188);
		hmac_sha1(&s.auth, r, 200, roc, 4, tag);
		if (memcmp(tag, p + 200, 10)) return 4;
	}
	/* sequence wraps 65535 -> 0: the rollover counter goes to 1 */
	p[2] = 0xff; p[3] = 0xff; srtp_protect(&s, p, 200);
	p[2] = 0; p[3] = 0; srtp_protect(&s, p, 200);
	if (s.roc != 1) return 5;
	puts("ok");
	return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'needs gcc')
class Srtp(unittest.TestCase):
    def test_vectors(self):
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t, 'b')
            subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-o', str(exe), str(SRC / 'srtp_bench.c')], check=True)
            r = subprocess.run([str(exe), '-t'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn('self-test: all ok', r.stdout)
            vectors = [l for l in r.stdout.splitlines() if l.endswith(' ok') and not l.startswith('self-test')]
            self.assertEqual(len(vectors), 10)
            r = subprocess.run([str(exe), '0.5', '1200'], capture_output=True, text=True)
            self.assertIn('stream of 1200 kbit/s', r.stdout)

    def test_protect_roundtrip_and_rollover(self):
        with tempfile.TemporaryDirectory() as t:
            c = Path(t, 'rt.c'); c.write_text(ROUNDTRIP)
            exe = Path(t, 'rt')
            subprocess.run(['gcc', '-O2', '-Wall', '-Werror', '-I', str(SRC), '-o', str(exe), str(c)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, 'ok'))


if __name__ == '__main__':
    unittest.main()
