#!/usr/bin/env python3
"""Host tests of src/tc100rtsp: util.h (RTSP path -> stream, dBFS meter, motion zones) and rec.c (Matroska recorder).

Needs gcc only (no ffmpeg): the recorder is fed synthetic H.264 / H.265 access units (real SPS, dummy slices) and its
files are checked with a small EBML reader below. Run: python3 tests/test_tc100rtsp.py
"""
import os
import re
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'tc100rtsp'


def vint(b, i, keep_marker):
    first = b[i]
    n = 1
    while n <= 8 and not first & (0x80 >> (n - 1)):
        n += 1
    if n > 8:
        raise ValueError('bad vint at %d' % i)
    v = first if keep_marker else first & (0xff >> n)
    for k in range(1, n):
        v = v << 8 | b[i + k]
    unknown = not keep_marker and v == (1 << (7 * n)) - 1
    return v, n, unknown


def elements(b, start, end):
    """(id, data_start, data_end) of the elements in b[start:end]; an unknown size runs to end"""
    i = start
    while i < end:
        eid, n1, _ = vint(b, i, True)
        size, n2, unknown = vint(b, i + n1, False)
        d = i + n1 + n2
        e = end if unknown else d + size
        if e > end:
            raise ValueError('element %x at %d runs past its parent' % (eid, i))
        yield eid, d, e
        i = e


def uint(b, d, e):
    v = 0
    for x in b[d:e]:
        v = v << 8 | x
    return v


def child(b, d, e, want):
    for eid, cd, ce in elements(b, d, e):
        if eid == want:
            return cd, ce
    return None


class Mkv:
    def __init__(self, path):
        b = path.read_bytes()
        self.b = b
        top = list(elements(b, 0, len(b)))
        assert top[0][0] == 0x1A45DFA3, 'EBML header first'
        h = top[0]
        dt = child(b, h[1], h[2], 0x4282)
        assert b[dt[0]:dt[1]] == b'matroska'
        seg = [t for t in top if t[0] == 0x18538067]
        assert len(seg) == 1
        _, sd, se = seg[0]
        self.seg_data = sd
        # the size written when the file was closed (8-byte EBML size; all ones = unknown: a file not closed)
        self.seg_size_patched = b[sd - 8] == 0x01 and b[sd - 7:sd] != b'\xff' * 7
        self.seg_size = uint(b, sd - 7, sd) if self.seg_size_patched else None
        self.info = self.tracks = self.seekhead = self.cues = None
        self.clusters = []
        for eid, d, e in elements(b, sd, se):
            if eid == 0x1549A966:
                self.info = (d, e)
            elif eid == 0x1654AE6B:
                self.tracks = (d, e)
            elif eid == 0x114D9B74:
                self.seekhead = (d, e)
            elif eid == 0x1C53BB6B:
                self.cues = (d, e)
            elif eid == 0x1F43B675:
                self.clusters.append((d - 4 - 4, d, e))      # element start (4-byte id + 4-byte size)
            elif eid != 0xEC:
                raise AssertionError('unexpected element %x' % eid)

    def timescale(self):
        d, e = self.info
        ts = child(self.b, d, e, 0x2AD7B1)
        return uint(self.b, *ts)

    def duration(self):
        d, e = self.info
        du = child(self.b, d, e, 0x4489)
        return struct.unpack('>d', self.b[du[0]:du[1]])[0] if du else None

    def track(self):
        d, e = self.tracks
        te = child(self.b, d, e, 0xAE)
        cid = child(self.b, te[0], te[1], 0x86)
        cp = child(self.b, te[0], te[1], 0x63A2)
        v = child(self.b, te[0], te[1], 0xE0)
        w = uint(self.b, *child(self.b, v[0], v[1], 0xB0))
        h = uint(self.b, *child(self.b, v[0], v[1], 0xBA))
        return self.b[cid[0]:cid[1]].decode(), self.b[cp[0]:cp[1]], w, h

    def blocks(self):
        """(time_ms, key, nal types) per SimpleBlock; checks the 4-byte NAL length framing"""
        out = []
        for start, d, e in self.clusters:
            tc = child(self.b, d, e, 0xE7)
            base = uint(self.b, *tc)
            for eid, bd, be in elements(self.b, d, e):
                if eid != 0xA3:
                    continue
                assert self.b[bd] == 0x81
                rel = struct.unpack('>h', self.b[bd + 1:bd + 3])[0]
                key = bool(self.b[bd + 3] & 0x80)
                i, nals = bd + 4, []
                while i < be:
                    n = struct.unpack('>I', self.b[i:i + 4])[0]
                    assert n > 0 and i + 4 + n <= be, 'NAL length framing'
                    nals.append(self.b[i + 4])
                    i += 4 + n
                assert i == be
                out.append((base + rel, key, nals))
        return out

    def cue_points(self):
        if not self.cues:
            return []
        res = []
        for eid, d, e in elements(self.b, *self.cues):
            assert eid == 0xBB
            t = uint(self.b, *child(self.b, d, e, 0xB3))
            tp = child(self.b, d, e, 0xB7)
            pos = uint(self.b, *child(self.b, tp[0], tp[1], 0xF1))
            res.append((t, pos))
        return res


def build(target):
    subprocess.run(['make', '-s', '-C', str(SRC), target], check=True)


class Util(unittest.TestCase):
    def test_util(self):
        build('test_util')
        r = subprocess.run([str(SRC / 'test_util')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('all OK', r.stdout)


class Recorder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build('test_rec')

    def run_rec(self, d, codec, drop=None):
        args = [str(SRC / 'test_rec'), str(d), codec, '70', '12', '24', '30'] + ([str(drop)] if drop is not None else [])
        r = subprocess.run(args, env=dict(os.environ, REC_TEST_ANY_FS='1'), capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return sorted(d.glob('*.mkv'))

    def check_files(self, files, codec, total):
        self.assertEqual(len(files), 3, files)
        n = 0
        for f in files:
            self.assertRegex(f.name, r'^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.mkv$')
            m = Mkv(f)
            self.assertTrue(m.seg_size_patched, f)
            self.assertEqual(m.seg_size, len(m.b) - m.seg_data, f)
            self.assertEqual(m.timescale(), 1000000)
            cid, cp, w, h = m.track()
            self.assertEqual((w, h), (640, 360))
            self.assertEqual(cid, 'V_MPEGH/ISO/HEVC' if codec == 'h265' else 'V_MPEG4/ISO/AVC')
            self.assertEqual(cp[0], 1)
            if codec == 'h265':
                self.assertEqual(cp[1:13], bytes([0x01, 0x60, 0, 0, 0, 0x90, 0, 0, 0, 0, 0, 93]))
                self.assertEqual(cp[22], 3)                   # VPS, SPS, PPS arrays
            else:
                self.assertEqual(cp[1:4], bytes([66, 0xc0, 30]))
            blocks = m.blocks()
            self.assertTrue(blocks[0][1], 'a file starts with a keyframe')
            times = [t for t, _, _ in blocks]
            self.assertEqual(times, sorted(times))
            self.assertEqual(times[0], 0)
            for t, key, nals in blocks:                       # no parameter sets / AUDs in the blocks
                types = [(x >> 1) & 63 if codec == 'h265' else x & 31 for x in nals]
                self.assertTrue(all(not (32 <= x <= 35) if codec == 'h265' else x not in (7, 8, 9) for x in types))
                self.assertEqual(key, (types[0] == 19) if codec == 'h265' else (types[0] == 5))
            # every cluster that starts with a keyframe is in the index, at its position
            cues = m.cue_points()
            starts = {c[0] - m.seg_data: c for c in m.clusters}
            keyed = 0
            for pos_rel, (start, d, e) in starts.items():
                first = [x for x in elements(m.b, d, e) if x[0] == 0xA3][0]
                if m.b[first[1] + 3] & 0x80:
                    keyed += 1
            self.assertEqual(len(cues), keyed)
            for t, pos in cues:
                self.assertIn(pos, starts)
            # SeekHead -> Cues
            sh = m.seekhead
            self.assertIsNotNone(sh)
            seek = child(m.b, sh[0], sh[1], 0x4DBB)
            sid = child(m.b, seek[0], seek[1], 0x53AB)
            self.assertEqual(m.b[sid[0]:sid[1]], b'\x1c\x53\xbb\x6b')
            sp = uint(m.b, *child(m.b, seek[0], seek[1], 0x53AC))
            self.assertEqual(m.b[m.seg_data + sp:m.seg_data + sp + 4], b'\x1c\x53\xbb\x6b')
            dur = m.duration()
            self.assertTrue(dur and abs(dur - (times[-1] + 66)) < 1, (dur, times[-1]))
            # thumbnail next to the file
            j = f.with_suffix('.jpg')
            self.assertTrue(j.exists(), j)
            self.assertTrue(j.read_bytes().startswith(b'\xff\xd8'))
            n += len(blocks)
        self.assertEqual(n, total)

    def test_h264_h265(self):
        for codec in ('h264', 'h265'):
            for drop in (None, 50):
                with self.subTest(codec=codec, drop=drop), tempfile.TemporaryDirectory() as d:
                    files = self.run_rec(Path(d), codec, drop)
                    # 840 frames, 30 s files cut at keyframes (every 2 s); a lost frame skips to the next keyframe (72)
                    self.check_files(files, codec, 840 if drop is None else 840 - 22)
                    st = (Path(d) / 'status').read_text()
                    self.assertIn('codec=%s' % codec, st)
                    self.assertIn('thumbs=3', st)

    def test_cut_file_still_parses(self):
        """a file cut by a power loss: the header and every complete cluster stay readable"""
        with tempfile.TemporaryDirectory() as d:
            f = self.run_rec(Path(d), 'h264')[0]
            b = f.read_bytes()
            m = Mkv(f)
            cut = m.clusters[5][0]                               # cut right before cluster 5 ...
            g = Path(d) / 'cut.mkv'
            raw = bytearray(b[:cut])
            raw[m.seg_data - 8:m.seg_data] = b'\x01' + b'\xff' * 7   # size unknown, as before the close
            g.write_bytes(bytes(raw))
            c = Mkv(g)
            self.assertFalse(c.seg_size_patched)
            self.assertEqual(len(c.clusters), 5)
            self.assertTrue(c.blocks()[0][1])


class Sources(unittest.TestCase):
    def test_no_uclibc_missing_imports(self):
        """the camera's uClibc 0.9.33 has no __isoc23_* (glibc 2.38 C2x redirects), no libm in tc100_rtsp"""
        for name in ('tc100_rtsp.c', 'rec.c', 'util.h'):
            s = re.sub(r'/\*.*?\*/|//[^\n]*', '', (SRC / name).read_text(), flags=re.S)  # code only
            self.assertIsNone(re.search(r'\b(sscanf|fscanf|strtol|strtoul|atoi|atol|log10|sqrt|lrint)\s*\(', s), name)


if __name__ == '__main__':
    unittest.main()
