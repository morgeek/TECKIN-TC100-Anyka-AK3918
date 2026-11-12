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
                        '-o', cls.bin, os.path.join(ROOT, 'src/h265enc/h265live.c'), '-lm'], check=True)
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

    def build(self, d):
        b = os.path.join(d, 'rctest')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', b,
                        os.path.join(ROOT, 'src/h265enc/rctest.c'), '-lm'], check=True)
        return b

    def run_rc(self, b, *args):
        out = subprocess.run([b] + [str(a) for a in args], capture_output=True, text=True, check=True).stdout.splitlines()
        first = out[0]
        mean = float(first.split()[1])
        qp = [int(x) for x in out[1].split('qp ')[1].replace(' then ', '..').split('..')] if len(out) > 1 else None
        return mean, qp, out

    # the output of rctest built from rc.h / rctest.c of 1abd9c4 (before VBR), same arguments: CBR is bit for bit unchanged
    CBR_GOLDEN = {
        (1600, 500, 20000): 'mean 1639 kbit/s, qp 40..50, max step 3, worst 1 s window off by 14 %',
        (1600, 500, 5000): 'mean 1608 kbit/s, qp 28..42, max step 3, worst 1 s window off by 14 %',
        (250, 500, 1500): 'mean 253 kbit/s, qp 34..46, max step 3, worst 1 s window off by 10 %',
        (3000, 500, 20000): 'mean 3049 kbit/s, qp 35..47, max step 3, worst 1 s window off by 8 %',
        (1600, 500, 1500): 'mean 1602 kbit/s, qp 22..27, max step 1, worst 1 s window off by 65 %',
        (400, 3000, 8000): 'mean 473 kbit/s, qp 44..50, max step 3, worst 1 s window off by 47 %',
    }

    def test_cbr_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            b = self.build(d)
            for args, want in self.CBR_GOLDEN.items():
                self.assertEqual(self.run_rc(b, *args)[2][0], want, args)
                self.assertEqual(self.run_rc(b, *args, 0)[2][0], want, args)    # vbr 0 given: the same
            # a still scene sits at qmin (22) in CBR, whatever the floor machinery does
            self.assertEqual(self.run_rc(b, 1600, 500, 1500, 0)[1][:2], [22, 22])

    def test_vbr_is_a_ceiling_and_quality_first(self):
        with tempfile.TemporaryDirectory() as d:
            b = self.build(d)
            # a busy scene: VBR meets the same ceiling as CBR does (within the 5 % of the CBR test)
            for kbps, cplx in ((1600, 20000), (1600, 5000), (250, 1500)):
                mean, qp, out = self.run_rc(b, kbps, 500, cplx, 1)
                self.assertLess(mean / kbps, 1.05, out)
            # a still scene: the QP stays at the quality QP (qmin 22 + 2), the bit rate is under the ceiling and under CBR
            mean, qp, out = self.run_rc(b, 1600, 500, 1500, 1)
            cbr = self.run_rc(b, 1600, 500, 1500, 0)[0]
            self.assertEqual(qp[0], 24, out)
            self.assertLess(mean, cbr * 0.9, out)
            self.assertLess(mean, 1600, out)

    def test_qp_floor_is_respected_and_released(self):
        with tempfile.TemporaryDirectory() as d:
            b = self.build(d)
            mean, qp, out = self.run_rc(b, 1600, 500, 1500, 1, 26)    # floor 26 until picture 125, then released
            self.assertGreaterEqual(qp[0], 26, out)
            self.assertEqual(qp[2], 24, out)                           # released: back to the quality QP at once
            self.assertLess(mean, self.run_rc(b, 1600, 500, 1500, 1)[0], out)


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


class ListGen(unittest.TestCase):
    """listgen.h (the C lists of h265live, no capture needed) is gen_listgen.py's output for cmdlist.py as it is now"""

    def test_up_to_date(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, 'src/h265enc/gen_listgen.py')], capture_output=True,
                             text=True, check=True).stdout
        self.assertEqual(out, open(os.path.join(ROOT, 'src/h265enc/listgen.h')).read(),
                         'run: python3 src/h265enc/gen_listgen.py > src/h265enc/listgen.h')

    @unittest.skipUnless(shutil.which('gcc'), 'gcc')
    def test_vendor_templates_give_the_same_lists(self):
        # h265live --dry with H265_VENDOR_LISTS=1 (templates) and without (listgen.h): the same words
        d = H265liveDry
        d.setUpClass()
        try:
            a = subprocess.run([d.bin, '--dry', '-q', '33', d.tmp, '/dev/null'], capture_output=True, text=True).stdout
            b = subprocess.run([d.bin, '--dry', '-q', '33', d.tmp, '/dev/null'], capture_output=True, text=True,
                               env=dict(os.environ, H265_VENDOR_LISTS='1')).stdout
            self.assertEqual(a, b)
            self.assertIn('picture 2 list:', a)
        finally:
            d.tearDownClass()


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class WorkTable(unittest.TestCase):
    """worktab.h computes the 25 600-byte "work" buffer (rate-distortion weights, default scaling lists, quantisation
    factors) exactly as the vendor software fills it: its SHA-256 is the IPCAM2 capture's of 2026-11-07 (the capture
    itself, vendor data, is not in the repository)"""
    VENDOR_SHA256 = '11eeadf9753c75bed9d6884ab51c3156c2e606f4eb2799894c5874b84c8a77f9'

    def test_same_as_the_vendor(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            b = os.path.join(d, 'wttest')
            subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', b,
                            os.path.join(ROOT, 'src/h265enc/wttest.c'), '-lm'], check=True)
            out = subprocess.run([b], capture_output=True, check=True).stdout
            self.assertEqual(len(out), 0x6400)
            self.assertEqual(hashlib.sha256(out).hexdigest(), self.VENDOR_SHA256)
            # the parts that are the standard's: the 8x8 intra default list in raster order, a quantisation factor
            self.assertEqual(list(out[0x100:0x108]), [16, 16, 16, 16, 17, 18, 21, 24])
            self.assertEqual(struct.unpack_from('<I', out, 0x520)[0], (1 << 24) // (16 * 40))

    def test_h264_same_as_the_vendor(self):
        # the H.264 sub stream's: the 52 x 4 rate-distortion weights only (IPCAM2 capture of 2026-11-07)
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            b = os.path.join(d, 'wttest')
            subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', b,
                            os.path.join(ROOT, 'src/h265enc/wttest.c'), '-lm'], check=True)
            out = subprocess.run([b, '264'], capture_output=True, check=True).stdout
            self.assertEqual(hashlib.sha256(out).hexdigest(), '18cbd8e6d2acf94feadfda8184c029e51a6c32c30fcc36a312670feebf6260f3')
            self.assertEqual(out[52 * 4:], bytes(0x6400 - 52 * 4))


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class H264liveDry(unittest.TestCase):
    """h264live --dry (the 640x360 H.264 sub stream, 2026-11-07): our SPS / PPS and slice headers are the vendor's bytes
    (the IPCAM2 sub stream captures: IDR QP 36, P frame 1 QP 42, P frame 3 QP 34), and the lists are
    cmdlist.PROFILE_H264_360P's (the vendor's lists but their addresses and sp_d8)"""
    PARAMS = ('00000001274d0028e7405017fcb25050505f00000300010000030032b10003d08000b71bffff0280'
              '0000000128ee3c80')

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'h264live-host')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-DH265LIVE_NO_DEVICE', '-I', os.path.join(ROOT, 'src/h265enc'),
                        '-o', cls.bin, os.path.join(ROOT, 'src/h265enc/h264live.c'), '-lm'], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def dry(self, qp):
        r = subprocess.run([self.bin, '--dry', '-q', str(qp), '/dev/null'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        params = [l.split(':')[1].replace(' ', '') for l in lines if l.startswith('params:')][0]
        lists = [[int(x, 16) for x in l.split(':')[1].split()] for l in lines if ' list:' in l]
        heads = [l.split(':')[1].replace(' ', '') for l in lines if ' head:' in l]
        return params, lists, heads

    def test_params_are_the_vendors(self):
        self.assertEqual(self.dry(32)[0], self.PARAMS)

    def test_slice_headers_are_the_vendors(self):
        self.assertEqual(self.dry(36)[2][0], '0000000125b84000296f')     # IDR, QP 36
        self.assertEqual(self.dry(42)[2][1], '0000000121e2010820b7')     # P, frame 1, QP 42
        # P frame 2 QP 34: ours (frame_num 2, POC 4; the vendor's frame 3 at QP 34 is 21 e6 03 08 42 df)
        self.assertEqual(self.dry(34)[2][2][:16], '0000000121e40208')

    def test_lists_are_the_profile(self):
        _, lists, _ = self.dry(36)
        for k, got in enumerate(lists):
            f = dict(c.PROFILE_H264_360P)
            f.update(c.H264_IDR_FIELDS if k == 0 else c.H264_P_FIELDS)
            f.update({'qp': 36, 'sp_38': 36, 'sp_8c': c.h264_sp_8c(36), 'sp_98': 2 * k,
                      'sp_9c': max(0, 2 * k - 2), 'sp_ac': max(0, 2 * k - 2),
                      'sp_b4': 2 * k - 4 if k >= 2 else 0xffffffff})
            want = c.encode(f)
            self.assertEqual(['%08x' % x for x in got[:32]], ['%08x' % x for x in want[:32]], k)
            # the stream buffer only in words 0x3c-0x3f (0x30-0x33 are H.265's)
            self.assertEqual(got[0x30:0x34], [0, 0, 0, 0])
            self.assertEqual(got[0x3d:0x40], [0xdf80, 0x820, 0xdf80 - 0x1040])
            self.assertEqual(got[0x22], 640)
            if k == 0:
                self.assertEqual([got[0x28], got[0x29], got[0x2c], got[0x38]], [0, 0, 0, 0])


@unittest.skipUnless(shutil.which('gcc'), 'gcc')
class FreeEnc(unittest.TestCase):
    """freeenc.h (the free encoder inside tc100_rtsp, RTSP_FREE_ENC=1) on a simulated core (src/h265enc/fetest.c): the
    same parameter words and slice headers as h265live / h264live (tested on IPCAM2), an IDR every GOP with its
    parameter sets, and each access unit in one piece: start code, headers, then the core's slice data"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'fetest')
        subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'src/h265enc'), '-o', cls.bin,
                        os.path.join(ROOT, 'src/h265enc/fetest.c')], check=True)
        cls.live = {}
        for name in ('h265live', 'h264live'):
            b = os.path.join(cls.tmp, name)
            subprocess.run(['gcc', '-O1', '-Wall', '-Wextra', '-DH265LIVE_NO_DEVICE', '-I', os.path.join(ROOT, 'src/h265enc'),
                            '-o', b, os.path.join(ROOT, 'src/h265enc/%s.c' % name), '-lm'], check=True)
            cls.live[name] = b

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_fe(self, codec, n, qp, gop, *extra):
        out = subprocess.run([self.bin, codec, str(n), str(qp), str(gop)] + [str(x) for x in extra], capture_output=True, text=True,
                             check=True).stdout
        pics = []
        lines = out.splitlines()
        for a, b in zip(lines[0::2], lines[1::2]):
            f = a.split()
            pics.append({'idr': int(f[3]), 'len': int(f[5]), 'list': [int(x, 16) for x in f[7:]],
                         'data': bytes.fromhex(b.split()[1])})
        return pics

    def dry(self, name, qp):
        args = [self.live[name], '--dry', '-q', str(qp)] + ([self.tmp] if name == 'h265live' else []) + ['/dev/null']
        out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines()
        lists = [[int(x, 16) for x in l.split(':')[1].split()] for l in out if ' list:' in l]
        heads = [bytes.fromhex(l.split(':')[1].replace(' ', '')) for l in out if ' head:' in l]
        return lists, heads

    def test_same_words_and_headers_as_the_live_tools(self):
        for codec, name in (('hevc', 'h265live'), ('avc', 'h264live')):
            pics = self.run_fe(codec, 3, 34, 50)
            lists, heads = self.dry(name, 34)
            for k in range(3):
                self.assertEqual(pics[k]['list'][:0x20], lists[k][:0x20], (codec, k))
                self.assertEqual(pics[k]['list'][0x22], 1920 if codec == 'hevc' else 640)
                d = pics[k]['data']
                self.assertTrue(d.endswith(b'\x80' + b'\xab' * (100 + 10 * k - 1)), (codec, k))
                self.assertIn(heads[k], d, (codec, k))
                self.assertTrue(d.startswith(b'\x00\x00\x00\x01'))

    def test_gop_and_parameter_sets(self):
        for codec, ps in (('hevc', b'\x00\x00\x00\x01\x40\x01'), ('avc', b'\x00\x00\x00\x01\x27\x4d')):
            pics = self.run_fe(codec, 12, 30, 5)
            self.assertEqual([p['idr'] for p in pics], [1, 0, 0, 0, 0] * 2 + [1, 0])
            for p in pics:
                self.assertEqual(p['data'].startswith(ps), bool(p['idr']), codec)
                self.assertEqual(len(p['data']), p['len'])
            # the POC restarts at each IDR: word 0x0c = 2 x pictures since the IDR
            self.assertEqual([p['list'][0x0c] for p in pics], [0, 2, 4, 6, 8] * 2 + [0, 2])
            # reconstruction and reference take turns: a P picture references the previous reconstruction
            for a, b in zip(pics, pics[1:]):
                if not b['idr']:
                    self.assertEqual(b['list'][0x28], a['list'][0x24])

    @staticmethod
    def idrs(pics):
        return [k for k, p in enumerate(pics) if p['idr']]

    @staticmethod
    def qp(p):
        return (p['list'][0x03] >> 16) & 0xff

    def test_smart_off_is_the_old_pattern(self):
        """cbr, vbr alone, and smart asked without VBR (not active): the fixed GOP, whatever the scene says"""
        for codec in ('hevc', 'avc'):
            want = list(range(0, 60, 7))
            for mode in ('cbr', 'vbr'):
                pics = self.run_fe(codec, 60, 30, 7, mode, 's' * 60, 250)
                self.assertEqual(self.idrs(pics), want, (codec, mode))
            self.assertEqual(self.idrs(self.run_fe(codec, 60, 30, 7)), want)
            # 'smart' is VBR + smart: with no still scene it is the fixed GOP too
            self.assertEqual(self.idrs(self.run_fe(codec, 60, 30, 7, 'smart', 'm' * 60, 250)), want)

    def test_smart_long_gop_on_a_still_scene(self):
        for codec in ('hevc', 'avc'):
            pics = self.run_fe(codec, 90, 30, 5, 'smart', 's' * 90, 20)
            self.assertEqual(self.idrs(pics), [0, 20, 40, 60, 80], codec)
            # never more keyframes than the fixed GOP gives
            self.assertLessEqual(len(self.idrs(pics)), len(self.idrs(self.run_fe(codec, 90, 30, 5))))
            for p in pics:
                self.assertEqual(p['data'].startswith(b'\x00\x00\x00\x01\x40\x01' if codec == 'hevc' else b'\x00\x00\x00\x01\x27\x4d'),
                                 bool(p['idr']), codec)

    def test_smart_motion_ends_the_long_gop_at_the_base_gop(self):
        # still for 7 pictures, then motion: the base GOP (5) is over, the keyframe is the next picture; then every 5
        pics = self.run_fe('hevc', 30, 30, 5, 'smart', 'sssssssm', 50)
        self.assertEqual(self.idrs(pics), [0, 7, 12, 17, 22, 27])

    def test_smart_client_wait_asks_a_keyframe_at_the_base_gop_at_the_latest(self):
        # a client waits at picture 3 (GOP 5, still scene): no keyframe before the base GOP is over, then one at once
        pics = self.run_fe('hevc', 40, 30, 5, 'smart', 'ssswssssssssssssssssssssssssssssssssssss', 25)
        self.assertEqual(self.idrs(pics), [0, 5, 30])
        # a request in the middle of a long GOP, the base GOP long over: the very next picture is a keyframe
        pics = self.run_fe('hevc', 30, 30, 5, 'smart', 'sssssssssssw', 25)
        self.assertEqual(self.idrs(pics), [0, 11])

    def test_smart_time_cap_at_a_low_frame_rate(self):
        # 5 fps (200 ms a picture, IDLE_FPS): 250 frames would be 50 s; the default cap is 10 s = every 50 pictures
        pics = self.run_fe('hevc', 120, 30, 5, 'smart', 's' * 120, 250, 45, 200, 10)
        self.assertEqual(self.idrs(pics), [0, 50, 100])
        # the cap is clamped to 2..12 s: asked 1 s -> 2 s (10 pictures); asked 60 s -> 12 s (60 pictures)
        self.assertEqual(self.idrs(self.run_fe('hevc', 30, 30, 5, 'smart', 's' * 30, 250, 45, 200, 1)), [0, 10, 20])
        self.assertEqual(self.idrs(self.run_fe('hevc', 130, 30, 5, 'smart', 's' * 130, 250, 45, 200, 60)), [0, 60, 120])
        # at 25 fps the long GOP (250 = 10 s) and the cap agree; the cap never adds a keyframe before the base GOP
        self.assertEqual(self.idrs(self.run_fe('hevc', 130, 30, 50, 'smart', 's' * 130, 250, 45, 40, 2)), [0, 50, 100])

    def test_smart_time_cap_across_the_32_bit_clock_wrap(self):
        # the clock (ms) wraps after 49.7 days: the cap must keep firing across it (start 3 s before 2^32)
        pics = self.run_fe('hevc', 120, 30, 5, 'smart', 's' * 120, 250, 45, 200, 10, 2 ** 32 - 3000)
        self.assertEqual(self.idrs(pics), [0, 50, 100])

    def test_smart_poc_stays_in_range_at_gop_300(self):
        for codec in ('hevc', 'avc'):
            # asked 1000: limited to 300; 700 still pictures: keyframes at 0, 300, 600, POC at most 2 x 299
            pics = self.run_fe(codec, 700, 30, 50, 'smart', 's' * 700, 1000)
            self.assertEqual(self.idrs(pics), [0, 300, 600], codec)
            self.assertEqual(max(p['list'][0x0c] for p in pics), 598, codec)
            self.assertLess(598, 1 << 10)
            # the slice header's 10-bit POC is the real one (H.265 P pictures write it: no wrap below 1024)
            # gop_long below the base GOP: the base GOP
            pics = self.run_fe(codec, 60, 30, 20, 'smart', 's' * 60, 5)
            self.assertEqual(self.idrs(pics), [0, 20, 40], codec)
        # the default long GOP is 250
        self.assertEqual(self.idrs(self.run_fe('hevc', 520, 30, 50, 'smart', 's' * 520, 0)), [0, 250, 500])

    def test_smart_qp_floor_is_respected_and_released(self):
        # QP range 30..45; the simulated core codes small pictures, so the rate control goes down to its lowest QP
        pics = self.run_fe('hevc', 60, 30, 100, 'smart', 's' * 30 + 'm' * 30, 250, 45)
        still = [self.qp(p) for p in pics[10:30] if not p['idr']]
        moving = [self.qp(p) for p in pics[40:60] if not p['idr']]
        self.assertEqual(min(still), 34, still)                  # qmin + 4 while still
        self.assertEqual(min(moving), 32, moving)                # released: the VBR quality QP (qmin + 2)
        # the same scene without smart (VBR alone) never uses the floor
        plain = [self.qp(p) for p in self.run_fe('hevc', 60, 30, 100, 'vbr', 's' * 60, 250, 45)[10:] if not p['idr']]
        self.assertEqual(min(plain), 32, plain)
        # CBR: down to qmin
        cbr = [self.qp(p) for p in self.run_fe('hevc', 60, 30, 100, 'cbr', 's' * 60, 250, 45)[10:] if not p['idr']]
        self.assertEqual(min(cbr), 30, cbr)

    def test_multi_resolution_h264_and_h265(self):
        for mode, w, h, pitch, ps in (
            ('hevc720', 1280, 720, 0x1400, b'\x00\x00\x00\x01\x40\x01'),
            ('avc720', 1280, 720, 0x1400, b'\x00\x00\x00\x01\x27\x4d'),
            ('avc1080', 1920, 1080, 0x1e00, b'\x00\x00\x00\x01\x27\x4d'),
        ):
            pics = self.run_fe(mode, 4, 32, 3)
            self.assertEqual([p['idr'] for p in pics], [1, 0, 0, 1], mode)
            for p in pics:
                self.assertEqual(p['list'][0x22], w, mode)
                self.assertEqual(p['list'][0x26], pitch, mode)
                self.assertEqual(p['list'][0x21] - p['list'][0x20], w * h, mode)
                self.assertEqual(p['data'].startswith(ps), bool(p['idr']), mode)


class FreeEncSmartWiring(unittest.TestCase):
    """[fe-smart] source checks where the C cannot be run here: rtspserver.conf vbr / smart (RTSP_VBR / RTSP_SMART) reach the
    free encoder; keyframe requests, fixed GOP on the recorded stream and the browser view, thumbnails on the encoder's GOP"""

    @classmethod
    def setUpClass(cls):
        cls.src = open(os.path.join(ROOT, 'src/tc100rtsp/tc100_rtsp.c'), encoding='utf-8').read()

    def test_vbr_reaches_the_free_encoder(self):
        self.assertIn('fe_set_vbr(e, (int)pa->rc_vbr);', self.src)
        self.assertIn('pa->rc_vbr = k ? (vs && *vs ? vs[0] == \'1\' : vm) : vm;', self.src)
        launch = open(os.path.join(ROOT, 'v3/linux66-sd/rtsp-launch.sh'), encoding='utf-8').read()
        self.assertIn('export RTSP_VBR="$RTSP_VBR_CONFIG" RTSP_SMART="$RTSP_SMART_CONFIG"', launch)
        # the new tuning names are not touched by the launcher
        self.assertNotIn('RTSP_FE_SMART', launch)

    def test_smart_only_with_vbr_and_two_is_one(self):
        f = self.src[self.src.index('static void smart_setup('):]
        f = f[:f.index('\n}\n')]
        self.assertLess(f.index('treated as smart=1'), f.index('if (!s->pa.rc_vbr)'))
        self.assertLess(f.index('if (!s->pa.rc_vbr)'), f.index('fe_set_smart('))

    def test_every_wait_idr_asks_the_encoder(self):
        lines = [l for l in self.src.splitlines() if 'wait_idr = 1;' in l]
        self.assertGreaterEqual(len(lines), 5)
        for l in lines:
            self.assertIn('want_idr(', l if 'cl[i].wait_idr = 1;' not in l else self.src[self.src.index(l):self.src.index(l) + 200], l)
        self.assertIn('if (s->idr_want) { s->idr_want = 0; fe_want_idr(s->enc); }', self.src)

    def test_fixed_gop_on_recording_and_live_view_and_thumbnails(self):
        self.assertIn('int fixed = (rec_mode != REC_OFF && k == rsi) || live_wants(k) || lossy[k];', self.src)
        self.assertIn('fe_set_still(fe, !fixed && md_on && !moving);', self.src)
        self.assertIn('(free_enc && rs->enc ? fe_next_idr(rs->enc) : rs->nsent % rs->pa.gop == 0)', self.src)

    def test_lossy_clients_keep_the_base_gop(self):
        self.assertIn('lossy[cl[i].si] = 1;', self.src)
        self.assertIn('if (!cl[i].tcp || ((const unsigned char *)&cl[i].peer)[0] == 127)', self.src)
        self.assertIn('|| live_wants(k) || lossy[k];', self.src)

    def test_no_burst_of_a_gop_longer_than_the_base_gop(self):
        f = self.src[self.src.index('static void play_burst('):]
        f = f[:f.index('\n}\n')]
        self.assertIn('int cok = s->cache_ok && !(s->smart && s->ncache > (int)s->pa.gop);', f)
        self.assertIn('if (cok && s->ncache &&', f)
        self.assertIn('qburst_on && c->tcp && cok &&', f)
        self.assertNotIn('s->cache_ok &&', f.replace('int cok = s->cache_ok &&', ''))
        self.assertIn('c->wait_idr = 1; want_idr(c->si);', f)

    def test_time_cap_and_qp_clamp_and_md_enc_reset(self):
        f = self.src[self.src.index('static void smart_setup('):]
        f = f[:f.index('\n}\n')]
        self.assertIn('"RTSP_FE_SMART_MAXS", FE_SMART_MAXS_DEFAULT', f)
        self.assertIn('ms < 2 ? 2 : ms > 12 ? 12 : ms', f)
        self.assertIn('if (qx > FE_SMART_QP_MAX) qx = FE_SMART_QP_MAX;', f)
        self.assertIn('fe_set_time(fe, (uint32_t)(uint64_t)(t_frame * 1000.0));', self.src)
        # the MD_ENC mean restarts only when the floor was released without motion
        self.assertIn('int moving = md_motion || t_frame - last <= 8.0;', self.src)
        self.assertIn('fe_set_still(fe, !fixed && md_on && !moving);', self.src)
        self.assertIn('if (was && !fe->still && !k && !moving) { md_enc_base = 0; md_enc_hits = 0; }', self.src)
        fe = open(os.path.join(ROOT, 'src/h265enc/freeenc.h'), encoding='utf-8').read()
        self.assertIn('#define FE_SMART_QP_MAX 5', fe)
        self.assertIn('qp_extra > FE_SMART_QP_MAX ? FE_SMART_QP_MAX : qp_extra', fe)

    def test_the_rule_in_the_encoder(self):
        fe = open(os.path.join(ROOT, 'src/h265enc/freeenc.h'), encoding='utf-8').read()
        self.assertIn('idr = fe_next_idr(e);', fe)
        self.assertIn('(!(e->smart && e->still) || e->idr_want || (uint32_t)(e->now_ms - e->idr_ms) >= e->max_ms)', fe)
        self.assertIn('#define FE_SMART_GOP_MAX 300', fe)
