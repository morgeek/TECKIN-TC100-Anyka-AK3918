"""Command list of the H.265 encoder core (src/h265enc): field table, builder, register sequence."""
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
