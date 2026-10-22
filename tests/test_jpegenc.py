"""Offline checks of the hardware JPEG tables and of `jpegenc --dry` (src/jpegenc)."""
import os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src', 'jpegenc')
sys.path.insert(0, SRC)
import jpeg_hw_tables as t  # noqa: E402


class Tables(unittest.TestCase):
    def test_quality_35_matches_the_vendor_jpeg(self):
        # first DQT values of a 1920x1080 JPEG made by the vendor encoder at this quality
        self.assertEqual(t.quant_zigzag(35, t.LUMA)[:8], [23, 16, 17, 20, 17, 14, 23, 20])
        self.assertEqual(t.quant_zigzag(35, t.CHROMA)[:8], [24, 26, 26, 34, 30, 34, 67, 37])

    def test_huffman_word_format(self):
        # first words of the hardware tables (checked against the vendor library)
        ac = t.huffman_words(*t.AC_LUMA, True)
        self.assertEqual(ac[:4], [0x01000002, 0x03000c05, 0x04001c31, 0x05003a41])
        self.assertNotEqual(ac[161], 0)  # EOB entry exists
        self.assertNotEqual(ac[160], 0)  # ZRL entry exists
        dc = t.huffman_words(*t.DC_LUMA, False)
        self.assertEqual(dc[:3], [0x01000001, 0x02000202, 0x02000303])

    def test_generated_header_is_current(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(SRC, 'gen_tables_h.py'), d)
            shutil.copy(os.path.join(SRC, 'jpeg_hw_tables.py'), d)
            subprocess.run([sys.executable, os.path.join(d, 'gen_tables_h.py')], check=True)
            self.assertEqual(open(os.path.join(d, 'jpeg_std_tables.h')).read(),
                             open(os.path.join(SRC, 'jpeg_std_tables.h')).read())


@unittest.skipUnless(shutil.which('gcc'), 'gcc needed')
class DryRun(unittest.TestCase):
    def test_dry_run_table_block_and_control_words(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, 'jpegenc')
            subprocess.run(['gcc', '-O2', '-DJPEGENC_NO_DEVICE', os.path.join(SRC, 'jpegenc.c'), '-o', exe], check=True)
            w, h = 1920, 1080
            open(os.path.join(d, 'in.nv12'), 'wb').write(bytes(w * h * 3 // 2))
            out = subprocess.run([exe, '--dry', '-q', '35', os.path.join(d, 'in.nv12'), str(w), str(h),
                                  os.path.join(d, 'o.jpg')], check=True, capture_output=True, text=True).stdout
            words = out.split('):')[1].split('\n')[0].split()
            # same first words as the recorded vendor frame
            self.assertEqual(words[:4], ['00000130', '077f0437', '00100009', '00000780'])
            self.assertEqual(words[8:], ['0007e700', '00000800', '0007df00'])
            subprocess.run([sys.executable, os.path.join(SRC, 'check_tables_block.py'),
                            os.path.join(d, 'o.jpg.tables'), '35'], check=True, capture_output=True)
            hdr = open(os.path.join(d, 'o.jpg.header'), 'rb').read()
            self.assertEqual(hdr[:2], b'\xff\xd8')
            self.assertEqual(hdr[-14:-12], b'\xff\xda')


if __name__ == '__main__':
    unittest.main()
