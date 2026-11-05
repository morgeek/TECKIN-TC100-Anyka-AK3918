"""Item 35: tc100-whep against a real WebRTC client. Not part of `unittest discover` (needs aiortc, a built daemon):
run by tests/docker/whep-interop.sh (WHEP_BIN = the daemon). A fake RTSP server plays the part of tc100_rtsp (H.264
640x360 from aiortc's encoder with the SPS/PPS left out of the stream, so only the daemon's insertion can give them to
the decoder; PCMA audio; Basic authentication), aiortc plays the browser: offer, POST /whep, answer, ICE, DTLS-SRTP,
then a decoded video frame and an audio frame, the viewer limit, DELETE."""
import asyncio
import base64
import os
import socket
import struct
import subprocess
import tempfile
import time
import logging
import unittest
import urllib.error
import urllib.request
from fractions import Fraction
from pathlib import Path

try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.codecs.h264 import H264Encoder
except ImportError:  # pragma: no cover
    av = None

BIN = os.environ.get('WHEP_BIN')
if os.environ.get('WHEP_DEBUG'):
    logging.basicConfig(level=logging.DEBUG)
RTSP_PW = 'test-pass'


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def lan_iface():
    """The interface of the default route (aiortc does not offer loopback candidates), else the first one that is not lo."""
    try:
        for line in Path('/proc/net/route').read_text().splitlines()[1:]:
            f = line.split()
            if f[1] == '00000000':
                return f[0]
    except OSError:
        pass
    for n in sorted(os.listdir('/sys/class/net')):
        if n != 'lo':
            return n
    return 'lo'


def nals(payload):
    """NAL unit types inside one RTP payload (single NAL, STAP-A, FU-A)."""
    t = payload[0] & 31
    if t == 24:
        out, i = [], 1
        while i + 2 <= len(payload):
            n = struct.unpack('>H', payload[i:i + 2])[0]
            out.append(payload[i + 2] & 31)
            i += 2 + n
        return out
    if t == 28:
        return [payload[1] & 31]
    return [t]


def stap_parts(payload):
    out, i = [], 1
    while i + 2 <= len(payload):
        n = struct.unpack('>H', payload[i:i + 2])[0]
        out.append(payload[i + 2:i + 2 + n])
        i += 2 + n
    return out


RTP_PAYLOAD = 1400	# src/tc100rtsp/tc100_rtsp.c: a full FU-A packet is 12 + 1400 = 1412 bytes


def as_tc100_rtsp(payloads):
    """aiortc's payloads (single NAL, STAP-A, FU-A cut in equal parts of at most 1300 bytes) put back into NAL units,
    SPS/PPS left out, then cut the way tc100_rtsp does: a NAL unit up to RTP_PAYLOAD bytes alone, a longer one in FU-A
    packets of RTP_PAYLOAD bytes. aiortc's own cut never reached 1400 bytes and hid a daemon that dropped every packet
    over 1400 (no IDR reached the viewer on the camera, 2026-11-05)."""
    units, cur = [], None
    for p in payloads:
        t = p[0] & 31
        if t == 24:
            units += stap_parts(p)
        elif t == 28:
            if p[1] & 0x80:
                cur = bytearray([(p[0] & 0xe0) | (p[1] & 31)])
            cur += p[2:]
            if p[1] & 0x40:
                units.append(bytes(cur))
                cur = None
        else:
            units.append(p)
    out = []
    for u in units:
        if (u[0] & 31) in (7, 8):
            continue
        if len(u) <= RTP_PAYLOAD:
            out.append(u)
            continue
        head, body, i = u[0], u[1:], 0
        while i < len(body):
            chunk = body[i:i + RTP_PAYLOAD - 2]
            fu = 0x80 if i == 0 else 0
            i += len(chunk)
            if i >= len(body):
                fu |= 0x40
            out.append(bytes([(head & 0xe0) | 28, fu | (head & 31)]) + chunk)
    return out


class FakeRtsp:
    """The RTSP side of tc100_rtsp: DESCRIBE / SETUP (TCP interleaved) / PLAY, then RTP frames."""

    def __init__(self, port):
        self.port = port
        self.sps = self.pps = None
        self.sessions = 0
        self.bad_auth = 0
        self.server = None
        self.want = 'Basic ' + base64.b64encode(f'root:{RTSP_PW}'.encode()).decode()

    async def start(self):
        enc = H264Encoder()
        for n in range(3):
            frame = self.frame(n)
            payloads, _ = enc.encode(frame, force_keyframe=n == 0)
            for p in payloads:
                if (p[0] & 31) == 24:
                    for sub in stap_parts(p):
                        if (sub[0] & 31) == 7: self.sps = sub
                        if (sub[0] & 31) == 8: self.pps = sub
                elif (p[0] & 31) == 7: self.sps = p
                elif (p[0] & 31) == 8: self.pps = p
        assert self.sps and self.pps, 'the encoder gave no SPS/PPS'
        self.server = await asyncio.start_server(self.client, '127.0.0.1', self.port)

    @staticmethod
    def frame(n):
        f = av.VideoFrame(640, 360, 'yuv420p')
        base = bytes(range(256)) * 900
        f.planes[0].update(base[n % 256:] + base[:n % 256] + b'\0' * (f.planes[0].buffer_size - 230400))
        f.planes[1].update(b'\x80' * f.planes[1].buffer_size)
        f.planes[2].update(b'\x80' * f.planes[2].buffer_size)
        f.pts = n * 9000
        f.time_base = Fraction(1, 90000)
        return f

    async def client(self, r, w):
        self.sessions += 1
        pump = None
        try:
            while True:
                head = await r.readuntil(b'\r\n\r\n')
                lines = head.decode().split('\r\n')
                method, url, _ = lines[0].split(' ')
                hdr = {l.split(':', 1)[0].lower(): l.split(':', 1)[1].strip() for l in lines[1:] if ':' in l}
                cseq = hdr.get('cseq', '0')
                if hdr.get('authorization') != self.want:
                    self.bad_auth += 1
                    w.write(f'RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\nWWW-Authenticate: Basic realm="TC100"\r\n\r\n'.encode())
                    continue
                body = ''
                extra = ''
                if method == 'DESCRIBE':
                    sprop = base64.b64encode(self.sps).decode() + ',' + base64.b64encode(self.pps).decode()
                    body = ('v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=TC100\r\nc=IN IP4 0.0.0.0\r\nt=0 0\r\na=control:*\r\n'
                            'm=video 0 RTP/AVP 96\r\na=rtpmap:96 H264/90000\r\n'
                            f'a=fmtp:96 packetization-mode=1;profile-level-id=42e01f;sprop-parameter-sets={sprop}\r\n'
                            'a=control:track1\r\nm=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\na=control:track2\r\n')
                    extra = f'Content-Type: application/sdp\r\nContent-Length: {len(body)}\r\n'
                elif method == 'SETUP':
                    ch = hdr['transport'].split('interleaved=')[1].split('-')[0]
                    extra = f'Transport: RTP/AVP/TCP;unicast;interleaved={ch}-{int(ch) + 1}\r\nSession: 12345678;timeout=60\r\n'
                elif method == 'PLAY':
                    extra = 'Range: npt=0.000-\r\nSession: 12345678\r\n'
                w.write(f'RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\n{extra}\r\n{body}'.encode())
                await w.drain()
                if method == 'PLAY':
                    pump = asyncio.ensure_future(self.media(w))
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if pump:
                pump.cancel()
            w.close()

    async def media(self, w):
        enc = H264Encoder()
        seq, aseq, n = 1000, 500, 0
        try:
            while True:
                payloads, ts = enc.encode(self.frame(n), force_keyframe=n % 30 == 0)
                send = as_tc100_rtsp(payloads)	# packets as tc100_rtsp makes them, no SPS/PPS in the stream
                for i, p in enumerate(send):
                    pkt = struct.pack('>BBHII', 0x80, (0x80 if i == len(send) - 1 else 0) | 96, seq & 0xffff, ts, 0x11223344) + p
                    seq += 1
                    w.write(b'$' + bytes([0]) + struct.pack('>H', len(pkt)) + pkt)
                for k in range(5):	# 100 ms of audio, 20 ms packets
                    pkt = struct.pack('>BBHII', 0x80, 8, aseq & 0xffff, (n * 800 + k * 160) & 0xffffffff, 0x55667788) + b'\xd5' * 160
                    aseq += 1
                    w.write(b'$' + bytes([2]) + struct.pack('>H', len(pkt)) + pkt)
                await w.drain()
                n += 1
                await asyncio.sleep(0.1)
        except (ConnectionError, asyncio.CancelledError):
            pass


def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@unittest.skipUnless(av and BIN and Path(BIN).exists(), 'needs aiortc and WHEP_BIN (tests/docker/whep-interop.sh)')
class Interop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, 'user.pwd').write_text(RTSP_PW + '\n')
        self.http_port, self.udp_port, self.rtsp_port = free_port(), free_port(socket.SOCK_DGRAM), free_port()
        self.daemon = subprocess.Popen(
            [BIN, '-i', lan_iface(), '-p', str(self.http_port), '-u', str(self.udp_port), '-r', str(self.rtsp_port),
             '-c', self.tmp.name, '-w', str(Path(self.tmp.name, 'user.pwd')), '-m', '2', '-d'],
            stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                socket.create_connection(('127.0.0.1', self.http_port), 1).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            self.fail('the daemon did not start: ' + self.daemon.stderr.read())

    def tearDown(self):
        self.daemon.terminate()
        try:
            err = self.daemon.communicate(timeout=10)[1]
        except subprocess.TimeoutExpired:
            self.daemon.kill()
            err = ''
        print(err[-1500:])
        self.tmp.cleanup()

    def test_viewer(self):
        asyncio.run(self.viewer())
        key = Path(self.tmp.name, 'whep-key.pem')
        self.assertTrue(key.exists() and (key.stat().st_mode & 0o077) == 0, 'the private key is kept, mode 0600')

    async def offer(self, pc):
        pc.addTransceiver('video', direction='recvonly')
        pc.addTransceiver('audio', direction='recvonly')
        await pc.setLocalDescription(await pc.createOffer())
        loop = asyncio.get_running_loop()
        st, h, body = await loop.run_in_executor(None, lambda: http(
            'POST', f'http://127.0.0.1:{self.http_port}/whep', pc.localDescription.sdp.encode(),
            {'Content-Type': 'application/sdp'}))
        return st, h, body

    async def viewer(self):
        rtsp = FakeRtsp(self.rtsp_port)
        await rtsp.start()
        pcs = []
        loop = asyncio.get_running_loop()
        try:
            pc = RTCPeerConnection()
            pcs.append(pc)
            got = {}

            @pc.on('track')
            def on_track(track):
                got[track.kind] = track

            st, h, body = await self.offer(pc)
            self.assertEqual(st, 201, body)
            self.assertTrue(h['Location'].startswith('/whep/'))
            sdp = body.decode()
            self.assertIn('a=ice-lite', sdp)
            self.assertIn('a=setup:passive', sdp)
            await pc.setRemoteDescription(RTCSessionDescription(sdp, 'answer'))
            self.assertEqual(rtsp.bad_auth, 0, 'the daemon sends the RTSP password at once')
            self.assertIn('video', got)
            try:
                frame = await asyncio.wait_for(got['video'].recv(), 30)
            except asyncio.TimeoutError:
                print('client stats:', {k: v for k, v in (await pc.getStats()).items()})
                raise
            self.assertEqual((frame.width, frame.height), (640, 360))
            self.assertIn('audio', got)
            await asyncio.wait_for(got['audio'].recv(), 15)
            st, _, j = await loop.run_in_executor(None, lambda: http('GET', f'http://127.0.0.1:{self.http_port}/status'))
            self.assertEqual(st, 200)
            self.assertIn(b'"viewers":1', j)

            # a bad offer
            st, _, _ = await loop.run_in_executor(None, lambda: http('POST', f'http://127.0.0.1:{self.http_port}/whep', b'hello'))
            self.assertEqual(st, 400)

            # second viewer fits, the third is refused (WHEP_MAX=2)
            pc2 = RTCPeerConnection(); pcs.append(pc2)
            st2, h2, _ = await self.offer(pc2)
            self.assertEqual(st2, 201)
            pc3 = RTCPeerConnection(); pcs.append(pc3)
            st3, _, _ = await self.offer(pc3)
            self.assertEqual(st3, 429)

            # DELETE frees a slot
            st, _, _ = await loop.run_in_executor(None, lambda: http('DELETE', f'http://127.0.0.1:{self.http_port}{h2["Location"]}'))
            self.assertEqual(st, 200)
            st, _, _ = await loop.run_in_executor(None, lambda: http('DELETE', f'http://127.0.0.1:{self.http_port}{h2["Location"]}'))
            self.assertEqual(st, 404)
            st, h, _ = await self.offer(RTCPeerConnection())
            self.assertEqual(st, 201)
        finally:
            for p in pcs:
                await p.close()
            rtsp.server.close()


if __name__ == '__main__':
    unittest.main()
