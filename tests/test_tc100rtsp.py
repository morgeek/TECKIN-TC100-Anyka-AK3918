#!/usr/bin/env python3
"""Host tests of src/tc100rtsp: util.h (RTSP path -> stream, dBFS meter, motion zones) and rec.c (fragmented MP4 recorder).

Needs gcc only (no ffmpeg): the recorder is fed synthetic H.264 / H.265 access units (real SPS, dummy slices) and its
files are checked with a small ISO box reader below. Run: python3 tests/test_tc100rtsp.py
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


def boxes(b, start, end):
    """(type, data_start, box_end) of the ISO boxes in b[start:end]"""
    i = start
    while i < end:
        size, typ = struct.unpack('>I4s', b[i:i + 8])
        d = i + 8
        if size == 1:
            size = struct.unpack('>Q', b[d:d + 8])[0]
            d += 8
        if size < 8 or i + size > end:
            raise ValueError('box %r at %d runs past its parent' % (typ, i))
        yield typ.decode('latin-1'), d, i + size
        i += size


def child(b, d, e, *path):
    """data range of the box found by following path from b[d:e]"""
    for want in path:
        for typ, cd, ce in boxes(b, d, e):
            if typ == want:
                d, e = cd, ce
                break
        else:
            return None
    return d, e


class Mp4:
    """fragmented MP4: ftyp, moov, then moof + mdat pairs"""
    def __init__(self, path):
        b = path.read_bytes()
        self.b = b
        top = list(boxes(b, 0, len(b)))
        assert top[0][0] == 'ftyp' and b[top[0][1]:top[0][1] + 4] == b'isom', 'ftyp isom first'
        assert top[1][0] == 'moov'
        self.moov = top[1][1:]
        self.frags = []                                     # (moof start, moof range, mdat data range)
        rest = top[2:]
        assert len(rest) % 2 == 0, 'moof/mdat pairs'
        for k in range(0, len(rest), 2):
            mo, md = rest[k], rest[k + 1]
            assert mo[0] == 'moof' and md[0] == 'mdat'
            self.frags.append((mo[1] - 8, mo[1:], md[1:]))
        assert child(b, *self.moov, 'mvex', 'trex'), 'fragments announced'

    def timescale(self):
        d, _ = child(self.b, *self.moov, 'trak', 'mdia', 'mdhd')
        return struct.unpack('>I', self.b[d + 12:d + 16])[0]

    def track(self):
        """sample entry type, its avcC / hvcC payload, width, height"""
        d, e = child(self.b, *self.moov, 'trak', 'mdia', 'minf', 'stbl', 'stsd')
        typ, sd, se = next(boxes(self.b, d + 8, e))         # stsd: version/flags + entry count
        w, h = struct.unpack('>HH', self.b[sd + 24:sd + 28])
        cfg = child(self.b, sd + 78, se, 'hvcC' if typ == 'hvc1' else 'avcC')
        return typ, self.b[cfg[0]:cfg[1]], w, h

    def samples(self):
        """(time_ms, key, nal types) per sample; checks sequence numbers, data offsets and the NAL length framing"""
        out, seq = [], 0
        for start, (md, me), (dd, de) in self.frags:
            f = child(self.b, md, me, 'mfhd')
            n = struct.unpack('>I', self.b[f[0] + 4:f[0] + 8])[0]
            assert n == seq + 1, 'fragment numbers'
            seq = n
            t = child(self.b, md, me, 'traf', 'tfdt')
            assert self.b[t[0]] == 1
            base = struct.unpack('>Q', self.b[t[0] + 4:t[0] + 12])[0]
            r = child(self.b, md, me, 'traf', 'trun')
            flags = struct.unpack('>I', self.b[r[0]:r[0] + 4])[0] & 0xffffff
            assert flags == 0x701
            count, off = struct.unpack('>Ii', self.b[r[0] + 4:r[0] + 12])
            assert start + off == dd, 'data offset points at the mdat payload'
            i, t90 = dd, base
            for k in range(count):
                dur, size, sf = struct.unpack('>III', self.b[r[0] + 12 + 12 * k:r[0] + 24 + 12 * k])
                end, nals = i + size, []
                while i < end:
                    ln = struct.unpack('>I', self.b[i:i + 4])[0]
                    assert ln > 0 and i + 4 + ln <= end, 'NAL length framing'
                    nals.append(self.b[i + 4])
                    i += 4 + ln
                assert i == end
                out.append((t90 * 1000 // 90000, sf == 0x02000000, nals))
                t90 += dur
            assert i == de, 'mdat holds exactly the samples'
            assert (t90 - base) <= 90000 + 9000, 'one fragment per second at most'
        return out


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
        return sorted(d.glob('*.mp4'))

    def check_files(self, files, codec, total):
        self.assertEqual(len(files), 3, files)
        n = 0
        for f in files:
            self.assertRegex(f.name, r'^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.mp4$')
            m = Mp4(f)
            self.assertEqual(m.timescale(), 90000)
            typ, cp, w, h = m.track()
            self.assertEqual((w, h), (640, 360))
            self.assertEqual(typ, 'hvc1' if codec == 'h265' else 'avc1')
            self.assertEqual(cp[0], 1)
            if codec == 'h265':
                self.assertEqual(cp[1:13], bytes([0x01, 0x60, 0, 0, 0, 0x90, 0, 0, 0, 0, 0, 93]))
                self.assertEqual(cp[22], 3)                   # VPS, SPS, PPS arrays
            else:
                self.assertEqual(cp[1:4], bytes([66, 0xc0, 30]))
            blocks = m.samples()
            self.assertTrue(blocks[0][1], 'a file starts with a keyframe')
            times = [t for t, _, _ in blocks]
            self.assertEqual(times, sorted(times))
            self.assertEqual(times[0], 0)
            for t, key, nals in blocks:                       # no parameter sets / AUDs in the samples
                types = [(x >> 1) & 63 if codec == 'h265' else x & 31 for x in nals]
                self.assertTrue(all(not (32 <= x <= 35) if codec == 'h265' else x not in (7, 8, 9) for x in types))
                self.assertEqual(key, (types[0] == 19) if codec == 'h265' else (types[0] == 5))
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
        """a file cut by a power loss: the header and every complete fragment stay readable"""
        with tempfile.TemporaryDirectory() as d:
            f = self.run_rec(Path(d), 'h264')[0]
            b = f.read_bytes()
            m = Mp4(f)
            cut = m.frags[5][0]                                  # cut right before fragment 5
            g = Path(d) / 'cut.mp4'
            g.write_bytes(b[:cut])
            c = Mp4(g)
            self.assertEqual(len(c.frags), 5)
            self.assertTrue(c.samples()[0][1])


class Sources(unittest.TestCase):
    def test_no_uclibc_missing_imports(self):
        """the camera's uClibc 0.9.33 has no __isoc23_* (glibc 2.38 C2x redirects), no libm in tc100_rtsp"""
        for name in ('tc100_rtsp.c', 'rec.c', 'util.h'):
            s = re.sub(r'/\*.*?\*/|//[^\n]*', '', (SRC / name).read_text(), flags=re.S)  # code only
            self.assertIsNone(re.search(r'\b(sscanf|fscanf|strtol|strtoul|atoi|atol|log10|sqrt|lrint)\s*\(', s), name)


if __name__ == '__main__':
    unittest.main()
