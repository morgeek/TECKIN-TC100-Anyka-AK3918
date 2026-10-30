#!/usr/bin/env python3
"""Host tests of src/tc100rtsp: util.h (RTSP path -> stream, dBFS meter, motion zones), rec.c (fragmented MP4 recorder) and
livemp4.c (live view: fragmented MP4 to the browser).

Needs gcc only (no ffmpeg): the recorder is fed synthetic H.264 / H.265 access units (real SPS, dummy slices) and its
files are checked with a small ISO box reader below. Run: python3 tests/test_tc100rtsp.py
"""
import base64
import math
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
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
            assert i <= de, 'the samples stay inside the mdat (audio follows them)'
            assert (t90 - base) <= 90000 + 9000, 'one fragment per second at most'
        return out


def alaw_decode(a):
    a ^= 0x55
    t = (a & 0x0f) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t = (t + 0x108) << (seg - 1)
    return t if a & 0x80 else -t


class Mp4Audio:
    """the second track of a recording: sample entry, fragments (second traf of each moof), A-law bytes"""
    def __init__(self, m):
        self.m, b = m, m.b
        traks = [(d, e) for typ, d, e in boxes(b, *m.moov) if typ == 'trak']
        self.traks = traks
        self.ntrak = len(traks)

    def handler(self, k):
        d, e = self.traks[k]
        h = child(self.m.b, d, e, 'mdia', 'hdlr')
        return self.m.b[h[0] + 8:h[0] + 12]

    def entry(self):
        b = self.m.b
        d, e = child(b, *self.traks[1], 'mdia', 'minf', 'stbl', 'stsd')
        typ, sd, se = next(boxes(b, d + 8, e))
        ch, bits, cid, pk, rate = struct.unpack('>HHHHI', b[sd + 16:sd + 28])
        return typ, ch, bits, rate >> 16

    def timescale(self):
        d, e = child(self.m.b, *self.traks[1], 'mdia', 'mdhd')
        return struct.unpack('>I', self.m.b[d + 12:d + 16])[0]

    def fragments(self):
        """(tfdt, [sizes], bytes) per fragment; checks track ids, data offsets and that the mdat holds video then audio"""
        b, out = self.m.b, []
        for start, (md, me), (dd, de) in self.m.frags:
            trafs = [(d, e) for typ, d, e in boxes(b, md, me) if typ == 'traf']
            assert len(trafs) in (1, 2), 'one traf per track per moof (none for audio when a fragment holds no sound)'
            if len(trafs) == 1:
                continue
            ids = []
            for d, e in trafs:
                f = child(b, d, e, 'tfhd')
                ids.append(struct.unpack('>I', b[f[0] + 4:f[0] + 8])[0])
            assert ids == [1, 2], ids
            vr = child(b, *trafs[0], 'trun')
            ar = child(b, *trafs[1], 'trun')
            vflags = struct.unpack('>I', b[vr[0]:vr[0] + 4])[0] & 0xffffff
            aflags = struct.unpack('>I', b[ar[0]:ar[0] + 4])[0] & 0xffffff
            assert (vflags, aflags) == (0x701, 0x301)
            vcount, voff = struct.unpack('>Ii', b[vr[0] + 4:vr[0] + 12])
            acount, aoff = struct.unpack('>Ii', b[ar[0] + 4:ar[0] + 12])
            vbytes = sum(struct.unpack('>I', b[vr[0] + 16 + 12 * k:vr[0] + 20 + 12 * k])[0] for k in range(vcount))
            sizes = []
            for k in range(acount):
                dur, size = struct.unpack('>II', b[ar[0] + 12 + 8 * k:ar[0] + 20 + 8 * k])
                assert dur == size, 'A-law: one tick per byte'
                sizes.append(size)
            assert start + voff == dd and start + aoff == dd + vbytes, 'data offsets'
            assert de - dd == vbytes + sum(sizes), 'mdat = video samples then audio samples'
            t = child(b, *trafs[1], 'tfdt')
            assert b[t[0]] == 1
            base = struct.unpack('>Q', b[t[0] + 4:t[0] + 12])[0]
            out.append((base, sizes, b[aoff + start:aoff + start + sum(sizes)]))
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

    def run_rec(self, d, codec, drop=None, **env):
        args = [str(SRC / 'test_rec'), str(d), codec, '70', '12', '24', '30'] + ([str(drop)] if drop is not None else [])
        r = subprocess.run(args, env=dict(os.environ, REC_TEST_ANY_FS='1', **env), capture_output=True, text=True, timeout=120)
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

    def check_audio(self, files, hole):
        """two tracks (video, 'alaw' 8 kHz mono), audio interleaved in every fragment, on the video clock"""
        total = 0
        for j, f in enumerate(files):
            m = Mp4(f)
            a = Mp4Audio(m)
            self.assertEqual(a.ntrak, 2)
            self.assertEqual((a.handler(0), a.handler(1)), (b'vide', b'soun'))
            self.assertEqual(a.entry(), ('alaw', 1, 16, 8000))
            self.assertEqual(a.timescale(), 8000)
            self.assertEqual(len(list(boxes(m.b, *child(m.b, *m.moov, 'mvex')))), 2, 'a trex per track')
            frags = a.fragments()
            self.assertLessEqual(len(m.frags) - len(frags), 2 if hole is not None else 0, 'fragments without sound')
            pcm, pos = [], None
            for base, sizes, data in frags:
                if pos is not None:
                    self.assertEqual(base, pos, 'audio track continuous (holes are filled with silence)')
                pos = base + sum(sizes)
                self.assertTrue(all(0 < x <= 160 for x in sizes))
                pcm += [alaw_decode(x) for x in data]
            first = frags[0][0]
            self.assertLess(first, 8000 * 0.5, 'the audio starts with the file')
            audio_s = (frags[-1][0] + sum(frags[-1][1])) / 8000
            video_s = m.samples()[-1][0] / 1000
            self.assertLess(abs(audio_s - video_s), 1.5, 'audio and video span the same time')
            # the tone has 0.4 s of silence at 9.0 s, 19.0 s, 29.0 s of the 10 s clock; files start on a multiple of 10 s
            for want in (9.0, 19.0, 29.0):
                if (len(pcm) + first) / 8000 < want + 0.5:
                    continue
                i = int(want * 8000) - first
                self.assertLessEqual(max(abs(x) for x in pcm[i + 200:i + 2800]), 16, 'silence at %.1f s' % want)
                self.assertGreater(max(abs(x) for x in pcm[i - 800:i - 100]), 3000, 'tone before %.1f s' % want)
                self.assertGreater(max(abs(x) for x in pcm[i + 3300:i + 4000]), 3000, 'tone after %.1f s' % want)
                # start of the silence within 20 ms of the video clock
                k = i - 400
                while abs(pcm[k]) > 16 or abs(pcm[k + 1]) > 16 or abs(pcm[k + 2]) > 16:
                    k += 1
                self.assertLess(abs(k - i), 160, 'silence starts at %.1f s (found %.3f)' % (want, (k + first) / 8000))
            w = pcm[2000:10000]
            zc = sum(1 for x, y in zip(w, w[1:]) if (x < 0) != (y < 0)) / 2
            self.assertAlmostEqual(zc, 440, delta=4, msg='440 Hz tone')
            total += len(pcm)
        return total

    def test_audio_track(self):
        for codec in ('h264', 'h265'):
            for kw in ({}, {'drop': 50}, {'hole': 3}):
                with self.subTest(codec=codec, **kw), tempfile.TemporaryDirectory() as d:
                    hole = kw.get('hole')
                    env = {'REC_TEST_AUDIO': '1'}
                    if hole is not None:
                        env['REC_TEST_AUDIO_HOLE'] = str(hole)
                    files = self.run_rec(Path(d), codec, kw.get('drop'), **env)
                    self.assertEqual(len(files), 3)
                    n = self.check_audio(files, hole)
                    self.assertGreater(n, 60 * 8000)
                    st = (Path(d) / 'status').read_text()
                    self.assertIn('audio=alaw', st)

    def test_audio_off_has_one_track(self):
        with tempfile.TemporaryDirectory() as d:
            files = self.run_rec(Path(d), 'h264')
            m = Mp4(files[0])
            self.assertEqual(Mp4Audio(m).ntrak, 1)
            self.assertIn('audio=off', (Path(d) / 'status').read_text())

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


FAKE_ARECORD = r"""#!/usr/bin/env python3
# stands in for arecord: a 440 Hz tone, S16_LE 8 kHz mono, 512-byte periods in real time
import math, os, signal, struct, sys, time
signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
open(os.environ['FAKE_ARECORD_PID'], 'w').write(str(os.getpid()))
n, t0 = 0, time.time()
while True:
    b = struct.pack('<256h', *[int(8000 * math.sin(2 * math.pi * 440 * (n + i) / 8000)) for i in range(256)])
    n += 256
    time.sleep(max(0, t0 + n / 8000 - time.time()))
    try:
        os.write(1, b)
    except OSError:
        os._exit(0)
"""
FAKE_APLAY = r"""#!/bin/sh
# stands in for aplay: appends its input to $FAKE_APLAY_OUT, its arguments to $FAKE_APLAY_OUT.args
echo "$@" >> "$FAKE_APLAY_OUT.args"
cat >> "$FAKE_APLAY_OUT"
"""


def rtp(seq, payload, pt=8, ts=None, marker=0):
    ts = seq * 160 if ts is None else ts
    return struct.pack('>BBHII', 0x80, (marker << 7) | pt, seq & 0xffff, ts & 0xffffffff, 0x1234) + payload


def alaw_enc(s):
    mask = 0xD5
    if s < 0:
        mask = 0x55
        s = -s - 1
    s = min(s, 32767)
    if s < 256:
        return ((s >> 4) ^ mask) & 0xff
    e = 1
    while e < 7 and s >= (512 << (e - 1)):
        e += 1
    return (((e << 4) | ((s >> (e + 3)) & 0x0f)) ^ mask) & 0xff


def tone_alaw(hz, start, n):
    return bytes(alaw_enc(int(8000 * math.sin(2 * math.pi * hz * (start + i) / 8000))) for i in range(n))


def freq(pcm_bytes):
    """frequency of an S16_LE mono 8 kHz signal from its zero crossings"""
    v = struct.unpack('<%dh' % (len(pcm_bytes) // 2), pcm_bytes[:len(pcm_bytes) // 2 * 2])
    zc = sum(1 for a, b in zip(v, v[1:]) if (a < 0) != (b < 0))
    return zc / 2 / (len(v) / 8000)


class RtspClient:
    def __init__(self, port, auth=True):
        self.s = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.cseq = 0
        self.auth = auth
        self.extra = b''

    def request(self, method, url, *headers, expect=200):
        self.cseq += 1
        h = ['%s %s RTSP/1.0' % (method, url), 'CSeq: %d' % self.cseq] + list(headers)
        if self.auth:
            h.append('Authorization: Basic ' + base64.b64encode(b'root:pw').decode())
        self.s.sendall(('\r\n'.join(h) + '\r\n\r\n').encode())
        buf = self.extra
        while b'\r\n\r\n' not in buf:
            buf += self.s.recv(4096)
        head, _, rest = buf.partition(b'\r\n\r\n')
        lines = head.decode().split('\r\n')
        code = int(lines[0].split()[1])
        hd = {k.lower(): v.strip() for k, v in (ln.split(':', 1) for ln in lines[1:])}
        n = int(hd.get('content-length', 0))
        while len(rest) < n:
            rest += self.s.recv(4096)
        self.extra = rest[n:]
        if expect:
            assert code == expect, (method, url, code, head)
        return code, hd, rest[:n].decode()

    def interleaved(self, ch, pkt):
        self.s.sendall(b'$' + bytes([ch]) + struct.pack('>H', len(pkt)) + pkt)

    def frames(self, seconds):
        """interleaved frames (channel, payload) received during <seconds>"""
        out, buf, end = [], self.extra, time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.s], [], [], 0.1)
            if r:
                d = self.s.recv(65536)
                if not d:
                    break
                buf += d
            while len(buf) >= 4 and buf[0] == 0x24:
                n = struct.unpack('>H', buf[2:4])[0]
                if len(buf) < 4 + n:
                    break
                out.append((buf[1], buf[4:4 + n]))
                buf = buf[4 + n:]
        self.extra = buf
        return out

    def close(self):
        self.s.close()


class Server(unittest.TestCase):
    """tc100_rtsp built for the host (make test_rtsp: no camera, no encoder) with fake arecord / aplay: RTSP, the audio
    track, the ONVIF backchannel to the speaker, and the FIFO listeners of the web UI's Listen button"""
    PORT = 18554
    audio = 1
    password = True
    boot_conf = ''
    env = {}
    live_stream = False                                          # feed the browser live view from a synthetic stream

    @classmethod
    def setUpClass(cls):
        build('test_rtsp')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / 'bin').mkdir()
        (t / 'conf').mkdir()
        for name, body in (('arecord', FAKE_ARECORD), ('aplay', FAKE_APLAY), ('amixer', '#!/bin/sh\nexit 0\n')):
            (t / 'bin' / name).write_text(body)
            (t / 'bin' / name).chmod(0o755)
        if self.boot_conf:
            (t / 'conf' / 'boot.conf').write_text(self.boot_conf)
        (t / 'pw').write_text('pw\n' if self.password else '\n')
        self.out = t / 'aplay.out'
        self.pidf = t / 'arecord.pid'
        self.listen = t / 'listen'
        self.live = t / 'live'
        subprocess.run(['rmdir', '/tmp/speaker-play.lock'], stderr=subprocess.DEVNULL)
        env = dict(os.environ, PATH=str(t / 'bin') + os.pathsep + os.environ['PATH'], FAKE_APLAY_OUT=str(self.out),
                   FAKE_ARECORD_PID=str(self.pidf), TC100_LISTEN_DIR=str(self.listen), TC100_LIVE_DIR=str(self.live),
                   TC100_SPEAKER_SCRIPT=str(ROOT / 'scripts' / 'speaker-play.sh'), **self.env)
        if self.live_stream:
            (t / 'live.h264').write_bytes(synthetic_h264())
            env['TC100_LIVE_TEST_FILE'] = str(t / 'live.h264')
        self.log = open(t / 'server.log', 'w')
        shutil.copy(SRC / 'test_rtsp', t / 'bin' / 'tc100_rtsp')           # the CGI finds it by this name (pidof)
        self.proc = subprocess.Popen([str(t / 'bin' / 'tc100_rtsp'), '-p', str(self.PORT), '-w', str(t / 'pw'), '-a', str(self.audio),
                                      '-s', '0', '-S', str(t / 'level')],
                                     cwd=t, env=env, stderr=self.log, stdout=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', self.PORT), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.fail('server did not start')
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        log = Path(self.log.name).read_text()
        self.log.close()
        subprocess.run(['rmdir', '/tmp/speaker-play.lock'], stderr=subprocess.DEVNULL)
        if os.environ.get('TC100_TEST_VERBOSE'):
            print('---- server log of %s ----\n%s' % (self.id(), log))
        self.tmp.cleanup()

    def client(self, auth=True):
        c = RtspClient(self.PORT, auth)
        self.clients.append(c)
        return c

    URL = 'rtsp://127.0.0.1:18554/video0'

    def describe(self, c, require=True):
        h = ['Accept: application/sdp'] + (['Require: www.onvif.org/ver20/backchannel'] if require else [])
        return c.request('DESCRIBE', self.URL, *h)[2]

    def talk_session(self, c, tcp=True, port=None):
        self.describe(c)
        if tcp:
            _, hd, _ = c.request('SETUP', self.URL + '/track3', 'Transport: RTP/AVP/TCP;unicast;interleaved=4-5')
            self.assertIn('interleaved=4-5', hd['transport'])
        else:
            _, hd, _ = c.request('SETUP', self.URL + '/track3', 'Transport: RTP/AVP;unicast;client_port=%d-%d' % (port, port + 1))
            self.assertIn('server_port=5004-5005', hd['transport'])
        c.request('PLAY', self.URL, 'Session: ' + hd['session'].split(';')[0])


class LogRotation(unittest.TestCase):
    """RTSP_LOGFILE: the STAT tick (every 5 s) moves a log larger than RTSP_LOGMAX to <file>.1 and goes on in a new file"""
    PORT = 18561

    @classmethod
    def setUpClass(cls):
        build('test_rtsp')

    def run_server(self, tmp, **env):
        log = Path(tmp) / 'tc100_rtsp.log'
        f = open(log, 'ab')
        proc = subprocess.Popen([str(SRC / 'test_rtsp'), '-p', str(self.PORT), '-a', '0', '-s', '0'], cwd=tmp,
                                env=dict(os.environ, **env), stderr=f, stdout=f)
        f.close()
        return proc, log

    def test_rotates_when_too_big_and_keeps_one_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, log = self.run_server(tmp, RTSP_LOGFILE=str(Path(tmp) / 'tc100_rtsp.log'), RTSP_LOGMAX='100')
            try:
                old = Path(str(log) + '.1')
                for _ in range(120):
                    if old.exists() and log.exists() and b'STAT' in log.read_bytes():
                        break
                    time.sleep(0.1)
                self.assertTrue(old.exists(), 'no rotation')
                self.assertIn(b'tc100_rtsp: rtsp://', old.read_bytes())          # the start-up lines went to the old file
                self.assertTrue(log.read_bytes().startswith(b'log rotated\nSTAT'), log.read_bytes()[:80])
            finally:
                proc.terminate()
                proc.wait(10)

    def test_no_rotation_below_the_limit_or_without_the_variable(self):
        for env in ({'RTSP_LOGFILE': 'x', 'RTSP_LOGMAX': '1000000'}, {}):
            with tempfile.TemporaryDirectory() as tmp:
                if 'RTSP_LOGFILE' in env:
                    env = dict(env, RTSP_LOGFILE=str(Path(tmp) / 'tc100_rtsp.log'))
                proc, log = self.run_server(tmp, **env)
                try:
                    for _ in range(120):
                        if b'STAT' in log.read_bytes():
                            break
                        time.sleep(0.1)
                    self.assertIn(b'STAT', log.read_bytes())
                    self.assertFalse(Path(str(log) + '.1').exists())
                    self.assertNotIn(b'log rotated', log.read_bytes())
                finally:
                    proc.terminate()
                    proc.wait(10)


class Backchannel(Server):
    def test_sdp_offers_the_backchannel_only_when_asked_and_allowed(self):
        c = self.client()
        sdp = self.describe(c, require=True)
        self.assertIn('a=sendonly', sdp)
        self.assertIn('a=control:track3', sdp)
        self.assertEqual(sdp.count('PCMA/8000'), 2, 'listen track and backchannel')
        self.assertIn('m=video', sdp)
        self.assertNotIn('a=sendonly', self.describe(c, require=False))

    def test_tcp_talk_reaches_the_speaker(self):
        c = self.client()
        self.talk_session(c)
        for i in range(60):                                      # 1.2 s of 600 Hz
            c.interleaved(4, rtp(i, tone_alaw(600, i * 160, 160)))
            time.sleep(0.02)
        c.interleaved(5, b'\x80\xc8' + bytes(26))                # RTCP on the odd channel is ignored
        self.assertEqual(c.frames(0.3), [], 'a client that set up only the backchannel gets no video')
        time.sleep(3.5)                                          # 2 s idle, then the player ends
        pcm = self.out.read_bytes()
        self.assertAlmostEqual(len(pcm), 60 * 160 * 2, delta=1600)
        self.assertAlmostEqual(freq(pcm), 600, delta=12)
        args = Path(str(self.out) + '.args').read_text()
        self.assertIn('-D plughw:0,0', args)
        self.assertIn('-r 8000', args)
        self.assertFalse(os.path.isdir('/tmp/speaker-play.lock'), 'the lock is released with the player')
        self.assertIn('talk: client', Path(self.log.name).read_text())

    def test_udp_talk_reaches_the_speaker(self):
        c = self.client()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.bind(('127.0.0.1', 0))
        self.talk_session(c, tcp=False, port=u.getsockname()[1])
        for i in range(40):
            u.sendto(rtp(i, tone_alaw(500, i * 160, 160)), ('127.0.0.1', 5004))
            time.sleep(0.02)
        time.sleep(3.5)
        pcm = self.out.read_bytes()
        self.assertAlmostEqual(len(pcm), 40 * 160 * 2, delta=1600)
        self.assertAlmostEqual(freq(pcm), 500, delta=12)
        u.close()

    def test_a_datagram_from_another_host_is_ignored(self):
        c = self.client()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.bind(('127.0.0.1', 0))
        self.talk_session(c, tcp=False, port=u.getsockname()[1])
        o = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        o.bind(('127.0.0.2', 0))                                # another source address
        for i in range(20):
            o.sendto(rtp(i, tone_alaw(500, i * 160, 160)), ('127.0.0.1', 5004))
            time.sleep(0.02)
        time.sleep(3)
        self.assertFalse(self.out.exists())
        o.close()
        u.close()

    def test_one_talker_at_a_time(self):
        a, b = self.client(), self.client()
        self.talk_session(a)
        self.talk_session(b)
        for i in range(50):
            a.interleaved(4, rtp(i, tone_alaw(400, i * 160, 160)))
            b.interleaved(4, rtp(i, tone_alaw(1000, i * 160, 160)))
            time.sleep(0.02)
        time.sleep(3.5)
        pcm = self.out.read_bytes()
        self.assertAlmostEqual(len(pcm), 50 * 160 * 2, delta=1600, msg='only one of the two')
        self.assertAlmostEqual(freq(pcm), 400, delta=10)

    def test_busy_speaker_drops_the_sound_then_recovers(self):
        os.mkdir('/tmp/speaker-play.lock')                       # a web push-to-talk clip is playing
        c = self.client()
        self.talk_session(c)
        for i in range(30):
            c.interleaved(4, rtp(i, tone_alaw(400, i * 160, 160)))
            time.sleep(0.02)
        time.sleep(3.5)
        self.assertFalse(self.out.exists() and self.out.stat().st_size, 'nothing played while the lock is held')
        os.rmdir('/tmp/speaker-play.lock')
        for i in range(30, 60):
            c.interleaved(4, rtp(i, tone_alaw(400, i * 160, 160)))
            time.sleep(0.02)
        time.sleep(3.5)
        self.assertGreater(self.out.stat().st_size, 20 * 160 * 2, 'plays again once the speaker is free')

    def test_push_to_talk_is_refused_while_a_client_talks(self):
        c = self.client()
        self.talk_session(c)
        c.interleaved(4, rtp(0, tone_alaw(400, 0, 160)))
        time.sleep(1)
        self.assertTrue(os.path.isdir('/tmp/speaker-play.lock'), 'a client talking holds the speaker lock')
        r = subprocess.run(['sh', str(ROOT / 'scripts' / 'speaker-play.sh'), '/dev/null'],
                           env=dict(os.environ, PATH=str(Path(self.tmp.name) / 'bin') + os.pathsep + os.environ['PATH']),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)


class BackchannelNeedsPassword(Server):
    password = False

    def test_no_backchannel_without_a_password(self):
        sdp = self.describe(self.client(auth=False), require=True)
        self.assertNotIn('a=sendonly', sdp)
        self.assertIn('m=video', sdp)


class BackchannelOff(Server):
    boot_conf = 'RTSP_LITE_TALK=0\n'

    def test_switched_off_in_boot_conf(self):
        self.assertNotIn('a=sendonly', self.describe(self.client(), require=True))


class AudioTrack(Server):
    def test_rtsp_audio_track_still_streams(self):
        c = self.client()
        sdp = self.describe(c, require=False)
        self.assertIn('a=control:track2', sdp)
        _, hd, _ = c.request('SETUP', self.URL + '/track1', 'Transport: RTP/AVP/TCP;unicast;interleaved=0-1')
        c.request('SETUP', self.URL + '/track2', 'Transport: RTP/AVP/TCP;unicast;interleaved=2-3', 'Session: ' + hd['session'].split(';')[0])
        c.request('PLAY', self.URL, 'Session: ' + hd['session'].split(';')[0])
        fr = [f for f in c.frames(3) if f[0] == 2]
        self.assertGreater(len(fr), 40)
        self.assertTrue(all(p[1] & 0x7f == 8 and len(p) == 172 for _, p in fr))


class Listen(Server):
    audio = 0                                                    # the RTSP audio track is off: the listener still gets sound
    env = {'TC100_LISTEN_SECONDS': '4'}

    def fifo(self, name):
        path = self.listen / name
        os.mkfifo(path)
        return path

    def read_fifo(self, path, seconds, out):
        def run():
            fd = os.open(path, os.O_RDONLY)                      # blocks until the server has the FIFO open
            t0, buf = time.time(), b''
            while time.time() < t0 + seconds:
                r, _, _ = select.select([fd], [], [], 0.2)
                if r:
                    d = os.read(fd, 65536)
                    if not d:
                        out['eof'] = time.time() - t0
                        break
                    buf += d
            os.close(fd)
            out['data'] = buf
        th = threading.Thread(target=run)
        th.start()
        return th

    def test_listener_gets_the_microphone_and_the_microphone_stops_after_it(self):
        out = {}
        th = self.read_fifo(self.fifo('1.fifo'), 8, out)
        th.join(12)
        self.assertIn('eof', out, 'the server ends the stream at its time limit')
        self.assertAlmostEqual(out['eof'], 4, delta=1.5)
        pcm = out['data']
        self.assertGreater(len(pcm), 2 * 8000 * 2, 'about 3 s of sound')
        self.assertEqual(len(pcm) % 2, 0)
        self.assertAlmostEqual(freq(pcm[16000:]), 440, delta=6)
        self.assertFalse((self.listen / '1.fifo').exists(), 'its FIFO is removed')
        pid = int(self.pidf.read_text())
        for _ in range(200):                                     # 10 s after the last listener the microphone is released
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
                if os.waitpid(pid, os.WNOHANG) != (0, 0):
                    break
            except (ProcessLookupError, ChildProcessError):
                break
        else:
            self.fail('arecord still running 20 s after the last listener')

    def test_stuck_listener_is_dropped_and_extra_listeners_get_end_of_file(self):
        outs = [{}, {}, {}, {}]
        ths = [self.read_fifo(self.fifo('%d.fifo' % i), 3, outs[i]) for i in range(4)]
        for t in ths:
            t.join(8)
        self.assertEqual(sum(1 for o in outs if o.get('eof', 99) < 1.5 and not o['data']), 1,
                         'with three slots the fourth listener is turned away at once: %r' % [(o.get('eof'), len(o['data'])) for o in outs])
        self.assertEqual(sum(1 for o in outs if len(o['data']) > 8000), 3)
        # a reader that never reads: its FIFO is dropped after 1.5 s of backlog
        p = self.fifo('9.fifo')
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        time.sleep(5)
        self.assertFalse(p.exists(), 'a listener that does not read is closed and its FIFO removed')
        os.close(fd)


class ListenCgi(Server):
    """www/cgi-bin/audio_stream.cgi against the running server: a WAV stream from the shared capture"""
    audio = 0

    def cgi(self, method='GET'):
        t = Path(self.tmp.name)
        env = dict(os.environ, REQUEST_METHOD=method, TC100_LISTEN_DIR=str(self.listen), TC100_SND_DEV='/dev/null', PATH=str(t / 'bin') + os.pathsep + os.environ['PATH'])
        return subprocess.Popen(['sh', str(ROOT / 'www' / 'cgi-bin' / 'audio_stream.cgi')], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)

    def test_head_probe(self):
        p = self.cgi('HEAD')
        out = p.communicate(timeout=10)[0]
        self.assertTrue(out.startswith(b'Content-Type: audio/wav'), out)
        self.assertEqual(out.split(b'\r\n\r\n', 1)[1], b'')

    def test_stream_then_the_browser_leaves(self):
        p = self.cgi()
        buf, end = b'', time.time() + 3
        while time.time() < end:
            r, _, _ = select.select([p.stdout], [], [], 0.2)
            if r:
                buf += os.read(p.stdout.fileno(), 65536)
        head, _, body = buf.partition(b'\r\n\r\n')
        self.assertIn(b'audio/wav', head)
        self.assertEqual(body[:4], b'RIFF')
        self.assertEqual(body[8:16], b'WAVEfmt ')
        pcm = body[44:]
        self.assertGreater(len(pcm), 2 * 8000 * 2 * 0.6)
        self.assertAlmostEqual(freq(pcm[8000:]), 440, delta=8)
        p.stdout.close()                                          # the browser goes away
        for _ in range(100):
            if not list(self.listen.glob('*.fifo')) and p.poll() is not None:
                break
            time.sleep(0.1)
        else:
            self.fail('the FIFO or the CGI is still there 10 s after the browser left')
        self.assertFalse(list(self.listen.glob('*.fifo')))

    def test_three_listeners_at_most(self):
        ps = [self.cgi() for _ in range(3)]
        time.sleep(1.5)
        r = self.cgi()
        out = r.communicate(timeout=10)[0]
        self.assertIn(b'503', out.split(b'\r\n')[0], out)
        for p in ps:
            p.kill()
            p.wait()
            p.stdout.close()


def synthetic_h264(n=40, gop=10):
    """Annex B stream, one access unit per frame (AUD first), a 640x360 baseline SPS, dummy slices; the first frame is an IDR"""
    out, seed = bytearray(), 1
    for f in range(n):
        key = f % gop == 0
        out += b'\0\0\1\x09\xf0'
        if key:
            out += b'\0\0\0\1' + bytes([0x67, 0x42, 0xc0, 0x1e, 0xda, 0x02, 0x80, 0xbf, 0xe5, 0x40]) + b'\0\0\0\1\x68\xcc'
        out += b'\0\0\1' + bytes([0x65 if key else 0x41])
        for _ in range(3000 if key else 400):
            seed = (seed * 1103515245 + 12345) & 0xffffffff
            out.append(0x11 + (seed >> 16) % 0xe0)
    return bytes(out)


def whole_boxes(b):
    """the prefix of b made of complete top-level boxes (a stream read in the middle of a fragment)"""
    i = 0
    while i + 8 <= len(b):
        size = struct.unpack('>I', b[i:i + 4])[0]
        if size < 8 or i + size > len(b):
            break
        i += size
    return b[:i]


def live_fragments(m):
    """(frame number written into the slice by the tests, key, tfdt, duration) per one-frame fragment of a live stream"""
    out = []
    for start, (md, me), (dd, de) in m.frags:
        t = child(m.b, md, me, 'traf', 'tfdt')
        base = struct.unpack('>Q', m.b[t[0] + 4:t[0] + 12])[0]
        r = child(m.b, md, me, 'traf', 'trun')
        count = struct.unpack('>I', m.b[r[0] + 4:r[0] + 8])[0]
        assert count == 1, 'one frame per fragment'
        dur, size, flags = struct.unpack('>III', m.b[r[0] + 12:r[0] + 24])
        assert de - dd == size
        fid = (m.b[dd + 5] - 0x11) * 100 + (m.b[dd + 6] - 0x11)
        out.append((fid, flags == 0x02000000, base, dur))
    return out


class LiveMux(unittest.TestCase):
    """src/tc100rtsp/livemp4.c on its own (test_livemp4): frames in, the stream a browser gets out of the viewers' FIFOs"""

    @classmethod
    def setUpClass(cls):
        build('test_livemp4')

    def run_live(self, *args, env=None):
        r = subprocess.run([str(SRC / 'test_livemp4')] + [str(a) for a in args], capture_output=True, text=True, timeout=90,
                           env=dict(os.environ, **(env or {})))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OK', r.stdout)
        return r.stdout

    def test_viewers_get_an_init_segment_then_one_fragment_per_frame_from_the_first_idr(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.run_live('flow', d / 'live', d / 'a.mp4', d / 'b.mp4')
            m = Mp4(d / 'a.mp4')                                    # ftyp + moov first, then moof / mdat pairs, sequence numbers 1..n
            self.assertEqual(m.timescale(), 90000)
            typ, cp, w, h = m.track()
            self.assertEqual((typ, w, h), ('avc1', 640, 360))
            self.assertEqual(cp[1:4], bytes([66, 0xc0, 30]))
            self.assertEqual(m.b[8:12], b'isom')
            self.assertIn(b'avc1', m.b[:64])
            self.assertEqual(len(m.frags), 57, 'frames 3..59: the three P frames before the first IDR are not sent')
            ms = m.samples()
            self.assertTrue(ms[0][1], 'starts with an IDR')
            self.assertEqual([i for i, s in enumerate(ms) if s[1]], [0, 10, 20, 30, 40, 50])
            self.assertTrue(all([n & 31 for n in s[2]] == ([5] if s[1] else [1]) for s in ms), 'only slices: parameter sets and delimiters are out of the samples')
            fr = live_fragments(m)
            self.assertEqual([f[0] for f in fr], list(range(3, 60)))
            for i, f in enumerate(fr):                              # decode times from the frame timestamps, first frame at 0
                self.assertAlmostEqual(f[2] / 90.0, i * 1000 / 15.0, delta=1.0)
            self.assertEqual(fr[0][3], 6000, 'the first frame lasts one nominal frame')
            self.assertTrue(all(abs(f[3] - 6000) <= 2 for f in fr[1:]), [f[3] for f in fr[:5]])
            b = Mp4(d / 'b.mp4')                                    # attached half way: its own init, sequence 1.., starts at the next IDR
            fb = live_fragments(b)
            self.assertEqual([f[0] for f in fb], list(range(33, 60)))
            self.assertTrue(fb[0][1])
            self.assertEqual(fb[0][2], 0, 'times are relative to the viewer\'s first frame')
            self.assertEqual(b.samples()[0][1], True)

    def test_building_the_fragment_in_the_viewers_buffer_gives_the_same_bytes_as_the_payload_copy(self):
        """RTSP_LIVE_DIRECT=0 is the old path (a payload buffer per frame); the output must not change by one byte"""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.run_live('flow', d / 'live0', d / 'a0.mp4', d / 'b0.mp4', env={'RTSP_LIVE_DIRECT': '0'})
            self.run_live('flow', d / 'live1', d / 'a1.mp4', d / 'b1.mp4')
            for n in 'ab':
                old, new = (d / (n + '0.mp4')).read_bytes(), (d / (n + '1.mp4')).read_bytes()
                self.assertGreater(len(old), 10000)
                self.assertEqual(old, new, n + '.mp4 differs between the two paths')

    def test_a_slow_viewer_skips_frames_until_a_keyframe_and_the_time_line_stays_continuous(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.run_live('slow', d / 'live', d / 's.mp4')
            m = Mp4(d / 's.mp4')
            fr = live_fragments(m)
            ids = [f[0] for f in fr]
            self.assertTrue(fr[0][1])
            gaps = [i for i in range(1, len(ids)) if ids[i] != ids[i - 1] + 1]
            self.assertTrue(gaps, 'the viewer could not take all the frames: some were skipped')
            self.assertTrue(all(fr[i][1] for i in gaps), 'the stream resumes at a keyframe')
            self.assertLess(len(ids), 190)
            for a, b in zip(fr, fr[1:]):
                self.assertAlmostEqual(b[2], a[2] + a[3], delta=2, msg='no hole in the decode time line (%d -> %d)' % (a[0], b[0]))
            m.samples()                                             # sequence numbers 1..n, offsets, NAL framing

    def test_stuck_viewer_dropped_removed_fifo_dropped_extra_viewer_refused(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_live('stuck', Path(d) / 'live')

    def test_stream_changes_and_status_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.run_live('change', Path(d) / 'live')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg + ffprobe')
    def test_a_real_h264_stream_decodes_in_ffmpeg(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=15', '-t', '10', '-c:v', 'libx264',
                            '-profile:v', 'baseline', '-level', '3.0', '-g', '15', '-sc_threshold', '0', '-pix_fmt', 'yuv420p',
                            '-x264-params', 'aud=1:repeat-headers=1', '-bsf:v', 'h264_mp4toannexb', '-f', 'h264', str(d / 'in.h264')], check=True)
            self.run_live('flow', d / 'live', d / 'a.mp4', d / 'b.mp4', d / 'in.h264')
            for name, frames in (('a.mp4', 150), ('b.mp4', 60)):   # B joins after frame 75: the next IDR is frame 90
                r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                    'stream=codec_name,profile,width,height,nb_read_frames', '-of', 'default=nw=1', str(d / name)],
                                   capture_output=True, text=True)
                self.assertIn('codec_name=h264', r.stdout, r.stdout + r.stderr)
                self.assertIn('width=640', r.stdout)
                self.assertIn('height=360', r.stdout)
                self.assertIn('nb_read_frames=%d' % frames, r.stdout)
                dec = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(d / name), '-f', 'null', '-'], capture_output=True, text=True)
                self.assertEqual(dec.stderr.strip(), '', 'ffmpeg decodes the stream without a complaint')
                self.assertEqual(len(live_fragments(Mp4(d / name))), frames)
            if os.environ.get('LIVE_KEEP_DIR'):                      # for the browser check (headless Chromium, tests/ui-browser)
                shutil.copy(d / 'a.mp4', Path(os.environ['LIVE_KEEP_DIR']) / 'live-real.mp4')


class LiveServer(Server):
    """tc100_rtsp (host build) with the live view: frames from a file (TC100_LIVE_TEST_FILE, 15 fps), www/cgi-bin/live.cgi"""
    audio = 0
    live_stream = True
    env = {'TC100_LIVE_SECONDS': '6'}

    def cgi(self, query='', method='GET', live=None):
        t = Path(self.tmp.name)
        env = dict(os.environ, REQUEST_METHOD=method, QUERY_STRING=query, TC100_LIVE_DIR=str(live or self.live),
                   PATH=str(t / 'bin') + os.pathsep + os.environ['PATH'])
        return subprocess.Popen(['sh', str(ROOT / 'www' / 'cgi-bin' / 'live.cgi')], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def wait_status(self):
        for _ in range(60):
            if (self.live / 'status').exists() and 'codec=' in (self.live / 'status').read_text():
                return
            time.sleep(0.1)
        self.fail('no live status')

    def read_all(self, p, seconds):
        buf, end = b'', time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([p.stdout], [], [], 0.2)
            if r:
                d = os.read(p.stdout.fileno(), 65536)
                if not d:
                    break
                buf += d
        return buf

    def test_info_json_and_the_stream_of_a_viewer(self):
        self.wait_status()
        out = self.cgi('info=1').communicate(timeout=10)[0]
        head, _, body = out.partition(b'\r\n\r\n')
        self.assertIn(b'application/json', head)
        self.assertRegex(body.decode(), r'^\{"ok":1,"stream":"main","codec":"avc1\.42c01e","width":\d+,"height":\d+\}\n$')
        p = self.cgi()
        buf = self.read_all(p, 3)
        head, _, body = buf.partition(b'\r\n\r\n')
        self.assertIn(b'Content-Type: video/mp4', head)
        self.assertIn(b'Cache-Control: no-store', head)
        f = Path(self.tmp.name) / 'live.mp4'
        f.write_bytes(whole_boxes(body))
        m = Mp4(f)
        fr = live_fragments(m)
        self.assertGreater(len(fr), 20, 'about 3 s at 15 fps')
        self.assertTrue(fr[0][1], 'starts with an IDR')
        self.assertEqual(fr[0][2], 0)
        self.assertEqual(m.track()[0], 'avc1')
        m.samples()
        p.stdout.close()                                           # the browser goes away: the FIFO is removed, the CGI ends
        for _ in range(100):
            if not list(self.live.glob('*.fifo')) and p.poll() is not None:
                break
            time.sleep(0.1)
        else:
            self.fail('the FIFO or the CGI is still there 10 s after the browser left')

    def test_two_viewers_at_most(self):
        self.wait_status()
        ps = [self.cgi() for _ in range(2)]
        time.sleep(1.5)
        out = self.cgi().communicate(timeout=10)[0]
        self.assertIn(b'503', out.split(b'\r\n')[0], out)
        self.assertIn(b'too many viewers', out)
        for p in ps:
            self.assertGreater(len(self.read_all(p, 1)), 1000)
            p.kill()
            p.wait()
            p.stdout.close()

    def test_a_viewer_ends_after_the_time_limit_and_the_page_can_reconnect(self):
        self.wait_status()
        p = self.cgi()
        t0 = time.time()
        buf = self.read_all(p, 12)
        self.assertAlmostEqual(time.time() - t0, 6, delta=2, msg='the server ends the stream (TC100_LIVE_SECONDS=6)')
        self.assertGreater(len(buf), 5000)
        p.wait(5)
        p2 = self.cgi()
        self.assertGreater(len(self.read_all(p2, 2)), 1000, 'a new viewer is served again')
        p2.kill()
        p2.wait()
        p2.stdout.close()

    def test_a_viewer_that_does_not_read_is_dropped(self):
        self.wait_status()
        p = self.live / '9.fifo'
        os.mkfifo(p)
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        time.sleep(0.8)
        self.assertTrue(p.exists())
        for _ in range(60):
            if not p.exists():
                break
            time.sleep(0.1)
        else:
            self.fail('a viewer that does not read is not dropped')
        os.close(fd)

    def test_head_probe_and_the_statuses(self):
        self.wait_status()
        out = self.cgi('', 'HEAD').communicate(timeout=10)[0]
        self.assertTrue(out.startswith(b'Content-Type: video/mp4'), out)
        self.assertEqual(out.split(b'\r\n\r\n', 1)[1], b'')
        other = Path(self.tmp.name) / 'other'
        other.mkdir()
        for status, code in (('stream=none', b'415'), ('stream=pending', b'503'), ('stream=sub codec=avc1.zz width=640 height=360', b'503'),
                             ('stream=sub codec=avc1.42c01e width=6x0 height=360', b'503'), ('garbage', b'503')):
            (other / 'status').write_text(status + '\n')
            out = self.cgi('info=1', live=other).communicate(timeout=10)[0]
            self.assertIn(code, out.split(b'\r\n')[0], (status, out))
            self.assertIn(b'"ok":0', out)
            out = self.cgi('', live=other).communicate(timeout=10)[0]
            self.assertIn(code, out.split(b'\r\n')[0], (status, out))
        (other / 'status').unlink()
        self.assertIn(b'503', self.cgi('info=1', live=other).communicate(timeout=10)[0].split(b'\r\n')[0])
        (other / 'status').write_text('stream=sub codec=avc1.4d401f width=640 height=360\n')
        out = self.cgi('info=1', live=other).communicate(timeout=10)[0]
        self.assertTrue(out.endswith(b'{"ok":1,"stream":"sub","codec":"avc1.4d401f","width":640,"height":360}\n'), out)



def rtp_frame(n, idr, size):
    """the access unit rtp_test_feed (tc100_rtsp.c, host build) makes: NALs after the AUD, as the server sends them"""
    seed = (n * 2654435761 + 1) & 0xffffffff
    body = bytearray([0x11 + (n // 100) % 100, 0x11 + n % 100])
    for _ in range(size):
        seed = (seed * 1103515245 + 12345) & 0xffffffff
        body.append(0x11 + (seed >> 16) % 0xe0)
    return [bytes([6, 5, 0x20]), bytes([0x65 if idr else 0x41]) + bytes(body)]


def rtp_nals(pkts):
    """[(timestamp, [nal bytes], marker seen on the last packet)] from RTP packets (H.264: single NAL and FU-A)"""
    frames, cur, ts = [], None, None
    for p in pkts:
        if p[1] & 0x7f != 96:
            continue
        t = struct.unpack('>I', p[4:8])[0]
        if t != ts:
            cur = [t, [], False, None]
            frames.append(cur)
            ts = t
        pl = p[12:]
        if pl[0] & 31 == 28:
            if pl[1] & 0x80:
                cur[3] = bytearray([(pl[0] & 0xe0) | (pl[1] & 31)])
            cur[3] += pl[2:]
            if pl[1] & 0x40:
                cur[1].append(bytes(cur[3]))
                cur[3] = None
        else:
            cur[1].append(bytes(pl))
        cur[2] = bool(p[1] & 0x80)
    return [(f[0], f[1], f[2]) for f in frames]


class RtpPath(Server):
    """the video RTP path of the server (host build, frames made by TC100_RTP_TEST): the packets of the old path (RTSP_UDPSG=0), the
    scatter-gather path and the sendmmsg path must be the same bytes, over UDP and over the RTSP connection; the client queue limit"""
    audio = 0
    password = False

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def start(self, **env):
        self.env = dict(env)
        Server.setUp(self)

    def stop(self):
        Server.tearDown(self)

    def play(self, tcp, seconds=2.5, port=24000):
        c = self.client(auth=False)
        self.describe(c, require=False)
        u = None
        if tcp:
            _, hd, _ = c.request('SETUP', self.URL + '/track1', 'Transport: RTP/AVP/TCP;unicast;interleaved=0-1')
        else:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
            u.bind(('127.0.0.1', port))
            _, hd, _ = c.request('SETUP', self.URL + '/track1', 'Transport: RTP/AVP;unicast;client_port=%d-%d' % (port, port + 1))
        c.request('PLAY', self.URL, 'Session: ' + hd['session'].split(';')[0])
        if tcp:
            pk = [p for ch, p in c.frames(seconds) if ch == 0]
        else:
            pk, end = [], time.time() + seconds
            while time.time() < end:
                r, _, _ = select.select([u], [], [], 0.1)
                if r:
                    pk.append(u.recv(4096))
            u.close()
        return pk

    @staticmethod
    def normal(pkts):
        """sequence numbers relative to the first one (they start at a time based value)"""
        s0 = struct.unpack('>H', pkts[0][2:4])[0]
        return [p[:2] + struct.pack('>H', (struct.unpack('>H', p[2:4])[0] - s0) & 0xffff) + p[4:] for p in pkts]

    def check_content(self, pkts, nfr, idr_b, p_b, gop=15):
        fr = rtp_nals(pkts)
        self.assertEqual(len(fr), nfr)
        for n, (ts, nals, marker) in enumerate(fr):
            self.assertEqual(ts, n * 6000)
            self.assertTrue(marker, 'marker on the last packet of frame %d' % n)
            if n % gop == 0:                                       # parameter sets in band before the IDR
                self.assertEqual([x[0] & 31 for x in nals], [7, 8, 6, 5])
                nals = nals[2:]
            else:
                self.assertEqual([x[0] & 31 for x in nals], [6, 1])
            self.assertEqual(nals, rtp_frame(n, n % gop == 0, idr_b if n % gop == 0 else p_b), 'frame %d' % n)
        seqs = [struct.unpack('>H', p[2:4])[0] for p in pkts]
        self.assertEqual(seqs, [(seqs[0] + i) & 0xffff for i in range(len(seqs))], 'sequence numbers count up with no hole')

    def test_the_three_paths_send_the_same_packets_over_udp_and_over_the_connection(self):
        feed = '24,20000,3000,50,12'
        got = {}
        for name, env in (('old', {}), ('sg', {'RTSP_UDPSG': '1'}), ('mmsg', {'RTSP_UDPSG': '1', 'RTSP_UDPMMSG': '1'})):
            for tcp in (False, True):
                self.start(TC100_RTP_TEST=feed, **env)
                try:
                    pk = self.play(tcp)
                finally:
                    self.stop()
                self.check_content(pk, 24, 20000, 3000, 12)
                got[name, tcp] = self.normal(pk)
        self.assertGreater(len(got['old', False]), 24 * 2, 'the IDRs are fragmented')
        for tcp in (False, True):
            self.assertEqual(got['sg', tcp], got['old', tcp], 'scatter-gather packets differ from the old path (tcp=%s)' % tcp)
        self.assertEqual(got['mmsg', False], got['old', False], 'sendmmsg packets differ from the old path')
        self.assertEqual(got['old', True], got['old', False], 'UDP and interleaved packets carry the same RTP')

    def first_ids(self, **env):
        """a TCP client that joins at frame ~18 of a stream with a 15 frame GOP: ids of the frames it gets"""
        self.start(TC100_RTP_TEST='1,60000,5000,15,15', TC100_RTP_TEST_REPEAT='1', **env)
        try:
            b = self.play(False, seconds=1.25, port=24100)           # a UDP viewer starts the stream; its IDR is frame 0
            self.assertTrue(b)
            c = self.client(auth=False)
            self.describe(c, require=False)
            _, hd, _ = c.request('SETUP', self.URL + '/track1', 'Transport: RTP/AVP/TCP;unicast;interleaved=0-1')
            c.request('PLAY', self.URL, 'Session: ' + hd['session'].split(';')[0])
            ids = []
            for ts, nals, _ in rtp_nals([p for ch, p in c.frames(1.4) if ch == 0]):
                sl = nals[-1]
                ids.append((sl[1] - 0x11) * 100 + sl[2] - 0x11)
            return ids
        finally:
            self.stop()

    def test_a_late_tcp_joiner_gets_the_whole_gop_when_it_fits_the_queue(self):
        ids = self.first_ids()                                       # default limit: 384 KB or more
        self.assertEqual(ids[:3], [15, 16, 17], ids)
        self.assertEqual(ids, list(range(ids[0], ids[0] + len(ids))), 'no frame lost')

    def test_a_late_tcp_joiner_gets_the_keyframe_at_once_when_the_gop_is_too_big_for_the_queue(self):
        ids = self.first_ids(RTSP_QMAX='64')                         # 64 KB: the IDR (60 KB) fits, the rest of the GOP does not
        self.assertEqual(ids[0], 15, ids)
        self.assertNotIn(16, ids, 'only the keyframe was sent, then it waits for the next IDR')
        self.assertIn(30, ids)

    def test_without_the_partial_burst_the_late_joiner_waits_for_the_next_idr(self):
        ids = self.first_ids(RTSP_QMAX='64', RTSP_QBURST='0')
        self.assertEqual(ids[0], 30, ids)

    def test_vbr_switch_is_in_the_start_line(self):
        for env, want in (({}, 'vbr main 0 sub 0'), ({'RTSP_VBR': '1'}, 'vbr main 1 sub 1'),
                          ({'RTSP_VBR': '1', 'RTSP_VBR_SUB': '0'}, 'vbr main 1 sub 0'), ({'RTSP_VBR_SUB': '1'}, 'vbr main 0 sub 1')):
            self.start(**env)
            try:
                time.sleep(0.3)
                log = Path(self.log.name).read_text()
            finally:
                self.stop()
            self.assertIn(want, log)


class Sources(unittest.TestCase):
    def test_no_uclibc_missing_imports(self):
        """the camera's uClibc 0.9.33 has no __isoc23_* (glibc 2.38 C2x redirects), no libm in tc100_rtsp"""
        for name in ('tc100_rtsp.c', 'rec.c', 'util.h', 'talk.c', 'alisten.c', 'mp4box.c', 'livemp4.c'):
            s = re.sub(r'/\*.*?\*/|//[^\n]*', '', (SRC / name).read_text(), flags=re.S)  # code only
            self.assertIsNone(re.search(r'\b(sscanf|fscanf|strtol|strtoul|atoi|atol|log10|sqrt|lrint)\s*\(', s), name)


if __name__ == '__main__':
    unittest.main()
