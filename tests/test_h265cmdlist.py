"""Command list of the H.265 encoder core (src/h265enc): field table, builder, register sequence.

Recorded and RecordedTrace are opt-in (audit D7): they replay data captured on a camera (TC100_H265_LISTS = the
command lists as JSON, TC100_H265_TRACE = a register trace), which the repository does not hold; the CI skips them."""
import json, os, random, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'h265enc'))
import cmdlist as c  # noqa: E402
import hwseq  # noqa: E402

SRC = dict(src_y=0x80b45100, src_uv=0x80d3f500, tables=0x815b95a0, work=0x80f331a0, small=0x815bd5e0, stream=0x80eae100)


class Fields(unittest.TestCase):
    def test_no_overlapping_fields(self):
        self.assertEqual(c.overlaps(), [])

    def test_roundtrip(self):
        rnd = random.Random(1)
        vals = {name: rnd.getrandbits(n) for (w, lo, n, name) in c.FIELDS}
        # fields that share their name with nothing else: encode then decode
        words = c.encode(vals)
        self.assertEqual(c.decode(words), vals)


class Builder(unittest.TestCase):
    def test_idr_first_words_match_the_recorded_picture(self):
        w = c.build_list(True, 35, 0, rec=0x80f395a0, ref=0, **SRC)
        self.assertEqual(len(w), 112)
        self.assertEqual(w[0x01], 0x880860ef)            # 1920x1080 in 8-pixel units
        self.assertEqual(w[0x03] >> 16 & 0xff, 35)       # QP
        self.assertEqual(w[0x28], 0)                     # no reference for an IDR
        self.assertEqual((w[0x0c], w[0x10]), (0, 0xffffffff))

    def test_p_picture_references_the_previous_frame_buffer(self):
        a, b = 0x80f395a0, 0x812795a0
        w = c.build_list(False, 37, 2, rec=b, ref=a, **SRC)
        self.assertEqual((w[0x24], w[0x28]), (b, a))
        self.assertEqual(w[0x29], a + 0x1fe000)
        self.assertEqual(w[0x0c], 2)
        self.assertEqual(c.decode(w)['sp_40'], 1)


class Hwseq(unittest.TestCase):
    def test_cycle_shape(self):
        ops = hwseq.cycle(0x80f32e20)
        self.assertEqual(ops[-1], ('WR', 0x8084, 2))
        self.assertEqual(ops[-2], ('WR', 0x8080, 0x80f32e20))


@unittest.skipUnless(os.environ.get('TC100_H265_LISTS'), 'recorded lists not available')
class Recorded(unittest.TestCase):
    def test_replay_lists(self):
        with open(os.environ['TC100_H265_LISTS']) as fh:
            frames = json.load(fh)
        self.assertEqual(c.replay(frames), [])


@unittest.skipUnless(os.environ.get('TC100_H265_TRACE'), 'recorded trace not available')
class RecordedTrace(unittest.TestCase):
    def test_register_sequence(self):
        ok, bad, skipped, notes = hwseq.check_trace(os.environ['TC100_H265_TRACE'])
        self.assertGreater(ok, 20)
        self.assertLessEqual(bad, 1)


if __name__ == '__main__':
    unittest.main()


# ---- step 2 (2026-11-07): h265enc.c and capture.py, offline
import shutil  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import capture  # noqa: E402

BASE = 0x81800000


@unittest.skipUnless(shutil.which('gcc') and shutil.which('make'), 'gcc')
class H265encDry(unittest.TestCase):
    """h265enc --dry puts its buffers in an IDR template exactly where cmdlist.build_list does"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(ROOT, 'src/h265enc/h265enc.c'), cls.tmp)
        os.makedirs(os.path.join(cls.tmp, '..', 'libakuio'), exist_ok=True)
        cls.bin = os.path.join(cls.tmp, 'h265enc-host')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-DH265ENC_NO_DEVICE', '-o', cls.bin,
                        os.path.join(cls.tmp, 'h265enc.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_dry(self, template, qp):
        d = tempfile.mkdtemp(dir=self.tmp)
        open(os.path.join(d, 'list.bin'), 'wb').write(struct.pack('<64I', *template[:64]))
        open(os.path.join(d, 'tables.bin'), 'wb').write(b'\x11' * 0x4040)
        nv12 = os.path.join(d, 'in.nv12')
        open(nv12, 'wb').write(b'\x80' * (1920 * 1080 * 3 // 2))
        r = subprocess.run([self.bin, '--dry', '-q', str(qp), d, nv12, os.path.join(d, 'o.h265')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        hexw = r.stdout.split('list (input words):')[1].split('dry run')[0].split()
        return [int(x, 16) for x in hexw]

    def test_same_list_as_the_model(self):
        # a recorded-like IDR list with the vendor's addresses, then what h265enc must make of it with its own buffers
        vendor = c.build_list(True, 35, 0, 0x80100000, 0x802fa400, 0x80f395a0, 0, 0x815b95a0, 0x80f331a0, 0x815bd5e0, 0x80eae100)
        for qp in (22, 30, 41):
            got = self.run_dry(vendor, qp)
            want = c.build_list(True, qp, 0, BASE + 0x100000, BASE + 0x100000 + 1920 * 1080, BASE + 0x400000, 0,
                                BASE + 0x80000, BASE + 0x88000, BASE + 0x8f000, BASE + 0x0)
            self.assertEqual(['%08x' % x for x in got], ['%08x' % x for x in want[:0x40]], qp)

    def test_refuses_a_p_list(self):
        p = c.build_list(False, 30, 2, 1, 2, 3, 4, 5, 6, 7, 8)
        d = tempfile.mkdtemp(dir=self.tmp)
        open(os.path.join(d, 'list.bin'), 'wb').write(struct.pack('<64I', *p[:64]))
        r = subprocess.run([self.bin, '--dry', d, '/nonexistent', '/dev/null'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('not an IDR list', r.stderr)


class CaptureFiles(unittest.TestCase):
    """capture.py on a synthetic capture: records, the picture found in the stream buffer, its length found in a status
    word, the h265enc inputs"""

    def test_report_and_inputs(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        pool_p, pool_v = 0x81800000, 0x40000000
        stream_p = pool_p + 0x10000
        lst = c.build_list(True, 33, 0, pool_p + 0x200000, pool_p + 0x3fa400, pool_p + 0x500000, 0, pool_p + 0x1000,
                           pool_p + 0x6000, pool_p + 0xd000, stream_p)
        pic = b'\x00\x00\x00\x01\x40\x01VPS' + b'\x00\x00\x00\x01\x42\x01SPS' + b'\x00\x00\x00\x01\x44\x01PPS' + \
              b'\x00\x00\x00\x01\x26\x01' + bytes(range(256)) * 4
        lst[0x45] = len(pic) * 8                                     # pretend the core gives the length in bits there
        stream = b'\x00' * 0x820 + pic + b'\xa5' * 64

        def rec(tag, paddr, data):
            return tag.encode() + struct.pack('<II', paddr, len(data)) + data + b'\x00' * (-len(data) & 3)
        body = (rec('REGS', 0x20028000, struct.pack('<256I', *([0] * 0x20 + [pool_p + 0x100] + [0] * 223)))
                + rec('LIST', pool_p + 0x100, struct.pack('<112I', *lst)) + rec('TABL', pool_p + 0x1000, b'T' * 0x4040)
                + rec('WORK', pool_p + 0x6000, b'W' * 0x6400) + rec('SMAL', pool_p + 0xd000, b'S' * 0x100)
                + rec('STRM', stream_p, stream))
        open(os.path.join(d, 'c.0.cap'), 'wb').write(b'TC100CAP' + struct.pack('<5I', 1, pool_p, pool_v, 0x960000, 0) + body)
        open(os.path.join(d, 'f.0.h26x'), 'wb').write(pic)
        open(os.path.join(d, 'f.log'), 'w').write('0 %x %d\n' % (pool_v + 0x10000 + 0x820, len(pic)))
        caps, frames = capture.load(d)
        import io
        out = io.StringIO()
        capture.report(caps, frames, out)
        txt = out.getvalue()
        self.assertIn('IDR qp 33 poc   0  model same', txt)
        self.assertIn('NAL types [32, 33, 34, 19]', txt)
        self.assertIn('at +0x820, bytes identical', txt)
        self.assertIn('list word 0x45 = %d (bits)' % (len(pic) * 8), txt)
        files = capture.write_inputs(caps, frames, os.path.join(d, 'in'))
        self.assertEqual(files, ['list.bin', 'params.bin', 'plist.bin', 'small.bin', 'tables.bin', 'work.bin'])
        self.assertEqual(open(os.path.join(d, 'in/params.bin'), 'rb').read(), pic[:pic.index(b'\x00\x00\x00\x01\x26')])


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class H265liveDry(unittest.TestCase):
    """h265live --dry: the lists of an IDR and two P pictures are cmdlist.build_list's, and our slice headers are the
    vendor's (bytes seen in the IPCAM2 captures of 2026-11-07: IDR QP 36, P POC 2 QP 42, P POC 4 QP 38)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'h265live-host')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-DH265LIVE_NO_DEVICE', '-I', os.path.join(ROOT, 'src/h265enc'),
                        '-o', cls.bin, os.path.join(ROOT, 'src/h265enc/h265live.c')], check=True)
        idr = c.build_list(True, 36, 0, 0x80100000, 0x802fa400, 0x80f395a0, 0, 0x815b95a0, 0x80f331a0, 0x815bd5e0, 0x80eae100)
        p = c.build_list(False, 36, 2, 0x80100000, 0x802fa400, 0x80f395a0, 0x812795a0, 0x815b95a0, 0x80f331a0, 0x815bd5e0, 0x80eae100)
        open(os.path.join(cls.tmp, 'list.bin'), 'wb').write(struct.pack('<64I', *idr[:64]))
        open(os.path.join(cls.tmp, 'plist.bin'), 'wb').write(struct.pack('<64I', *p[:64]))
        open(os.path.join(cls.tmp, 'params.bin'), 'wb').write(b'\x00\x00\x00\x01\x40\x01')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def dry(self, qp):
        r = subprocess.run([self.bin, '--dry', '-q', str(qp), self.tmp, '/dev/null'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lists = [[int(x, 16) for x in l.split(':')[1].split()] for l in r.stdout.splitlines() if ' list:' in l]
        heads = [l.split(':')[1].replace(' ', '') for l in r.stdout.splitlines() if ' head:' in l]
        return lists, heads

    def test_lists_are_the_model(self):
        b = 0x81800000
        lists, _ = self.dry(30)
        for k, got in enumerate(lists):
            cur = k & 1
            want = c.build_list(k == 0, 30, 2 * k, 0x82d00000, 0x82d00000 + 1920 * 1080, b + 0x100000 + cur * 0x340000,
                                b + 0x100000 + (cur ^ 1) * 0x340000, b + 0x80000, b + 0x88000, b + 0x8f000, b)
            self.assertEqual(['%08x' % x for x in got], ['%08x' % x for x in want[:64]], k)

    def test_slice_headers_are_the_vendors(self):
        self.assertEqual(self.dry(36)[1][0], '000000012601ac2980')          # IDR, QP 36
        self.assertEqual(self.dry(42)[1][1], '000000010201d0042af820c0')    # P, POC 2, QP 42
        self.assertTrue('000000010201d0082af863bc'.startswith(self.dry(38)[1][2]))   # P, POC 4, QP 38 (+ data)


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class RateControl(unittest.TestCase):
    """rc.h on a simulated encoder (src/h265enc/rctest.c: size halves every 6 QP, an IDR 4 P pictures, a busier scene
    halfway): the mean bit rate is the target, the QP moves at most 3 per picture. On IPCAM2 (2026-11-07) 150 live
    pictures at -b 1600 gave 1612 kbit/s."""

    def test_targets(self):
        with tempfile.TemporaryDirectory() as d:
            b = os.path.join(d, 'rctest')
            subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', b,
                            os.path.join(ROOT, 'src/h265enc/rctest.c'), '-lm'], check=True)
            for kbps, cplx in ((1600, 20000), (1600, 5000), (250, 1500), (3000, 20000)):   # within the QP range (qmax 50)
                out = subprocess.run([b, str(kbps), '500', str(cplx)], capture_output=True, text=True, check=True).stdout
                mean = float(out.split()[1]); step = int(out.split('max step ')[1].split(',')[0])
                self.assertLess(abs(mean / kbps - 1), 0.05, out)
                self.assertLessEqual(step, 3, out)


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class ParamSets(unittest.TestCase):
    """paramsets.h writes the VPS/SPS/PPS of the vendor encoder byte for byte (1920x1080, 25 fps: the 112 bytes of the
    IPCAM2 capture of 2026-11-07), and other sizes stay valid H.265 (ffprobe)"""
    VENDOR = '0000000140010c01ffff014000000300900000030000030078bc0900000001420101014000000300900000030000030078a003c08010e59efb91280ecaa520a694929a4954929248953aa9d493a9a7511780a5050505e1000003000100000300192f840208000000014401c073c0c6d9'

    def build(self, d):
        b = os.path.join(d, 'pstest')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', b,
                        os.path.join(ROOT, 'src/h265enc/pstest.c')], check=True)
        return b

    def test_vendor_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run([self.build(d), '1920', '1080', '25'], capture_output=True, check=True).stdout
            self.assertEqual(out.hex(), self.VENDOR)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg')
    def test_other_sizes_parse(self):
        with tempfile.TemporaryDirectory() as d:
            b = self.build(d)
            for w, h, fps in ((640, 360, 25), (1280, 720, 15)):
                f = os.path.join(d, 'p.h265')
                open(f, 'wb').write(subprocess.run([b, str(w), str(h), str(fps)], capture_output=True, check=True).stdout)
                # no picture: the bitstream filter that prints every syntax element reads the parameter sets alone
                r = subprocess.run(['ffmpeg', '-hide_banner', '-i', f, '-c', 'copy', '-bsf:v', 'trace_headers', '-f', 'null', '-'],
                                   capture_output=True, text=True)
                self.assertRegex(r.stderr, r'pic_width_in_luma_samples\s+\d+ = %d\b' % w)
                self.assertRegex(r.stderr, r'pic_height_in_luma_samples\s+\d+ = %d\b' % h)
                self.assertRegex(r.stderr, r'vui_time_scale\s+\d+ = %d\b' % fps)
                self.assertRegex(r.stderr, r'rbsp_stop_one_bit')
