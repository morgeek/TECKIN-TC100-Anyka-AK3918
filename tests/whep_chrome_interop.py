"""The WHEP daemon against a real Chromium (Playwright), as the owner's Chrome 157 talks to it: DTLS 1.3 offered with a
post-quantum key share, so a ClientHello in several fragments (tc100-whep used to fail with -0x7900, rc28). Run like
tests/whep_interop.py (WHEP_BIN, LD_LIBRARY_PATH); skipped without Playwright's Chromium.
Playwright's Chromium has no H.264 decoder: the offer gets an H.264 line added for the daemon and the answer is mapped
to VP8 for Chromium; only ICE, DTLS and SRTP are checked (packets received), not the picture."""
import asyncio
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import whep_interop as wi  # noqa: E402

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover
    async_playwright = None

TRIALS = {'dtls12': None, 'dtls13-mlkem': '--force-fieldtrials=WebRTC-ForceDtls13/Enabled/WebRTC-EnableDtlsPqc/Enabled/'}

JS_OFFER = '''async()=>{window.pc=new RTCPeerConnection();pc.addTransceiver('video',{direction:'recvonly'});
pc.addTransceiver('audio',{direction:'recvonly'});await pc.setLocalDescription(await pc.createOffer());
await new Promise(r=>{if(pc.iceGatheringState==='complete')r();pc.onicegatheringstatechange=()=>pc.iceGatheringState==='complete'&&r();setTimeout(r,3000)});
return pc.localDescription.sdp}'''
JS_STATS = '''async()=>{const s=await pc.getStats();const o={conn:pc.connectionState};s.forEach(x=>{
if(x.type==='transport')Object.assign(o,{dtls:x.dtlsState,srtp:x.srtpCipher});if(x.type==='inbound-rtp')o[x.kind]=x.packetsReceived});return o}'''


def add_h264(offer):
    out, video = [], False
    for line in offer.split('\r\n'):
        if line.startswith('m='):
            video = line.startswith('m=video')
            if video:
                line = line.replace('SAVPF ', 'SAVPF 102 ', 1)
        out.append(line)
        if video and line.startswith('a=mid:'):
            out += ['a=rtpmap:102 H264/90000', 'a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f']
    return '\r\n'.join(out)


def h264_to_vp8(answer, offer):
    vp8 = re.search(r'a=rtpmap:(\d+) VP8/90000', offer).group(1)
    answer = re.sub(r'm=video (\d+) (\S+) 102', r'm=video \1 \2 ' + vp8, answer).replace('a=rtpmap:102 H264/90000', f'a=rtpmap:{vp8} VP8/90000')
    return '\r\n'.join(l for l in answer.split('\r\n') if not re.match(r'a=(fmtp|rtcp-fb):102', l))


@unittest.skipUnless(wi.BIN and async_playwright, 'needs WHEP_BIN and Playwright')
class ChromeInterop(unittest.TestCase):
    def run_one(self, trial):
        async def go():
            tmp = tempfile.mkdtemp()
            with open(os.path.join(tmp, 'user.pwd'), 'w') as f:
                f.write(wi.RTSP_PW + '\n')
            hp, up, rp = wi.free_port(), wi.free_port(socket.SOCK_DGRAM), wi.free_port()
            rtsp = wi.FakeRtsp(rp)
            await rtsp.start()
            d = subprocess.Popen([wi.BIN, '-i', wi.lan_iface(), '-p', str(hp), '-u', str(up), '-r', str(rp), '-c', tmp,
                                  '-w', os.path.join(tmp, 'user.pwd'), '-m', '2', '-d'], stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(1)
                async with async_playwright() as p:
                    b = await p.chromium.launch(args=[trial] if trial else [])
                    pg = await b.new_page()
                    offer = await pg.evaluate(JS_OFFER)
                    loop = asyncio.get_running_loop()
                    st, _, ans = await loop.run_in_executor(None, lambda: wi.http(
                        'POST', f'http://127.0.0.1:{hp}/whep', add_h264(offer).encode(), {'Content-Type': 'application/sdp'}))
                    self.assertEqual(st, 201, ans)
                    await pg.evaluate('a=>pc.setRemoteDescription({type:"answer",sdp:a})', h264_to_vp8(ans.decode(), offer))
                    await asyncio.sleep(6)
                    stats = await pg.evaluate(JS_STATS)
                    await b.close()
            finally:
                d.terminate()
                err = d.stderr.read()
            return stats, err
        stats, err = asyncio.run(go())
        self.assertEqual(stats.get('dtls'), 'connected', (stats, err[-800:]))
        self.assertGreater(stats.get('video', 0), 50, (stats, err[-800:]))
        self.assertGreater(stats.get('audio', 0), 50, (stats, err[-800:]))
        return err

    def test_dtls12(self):
        self.run_one(TRIALS['dtls12'])

    def test_dtls13_mlkem_fragmented_hello(self):
        err = self.run_one(TRIALS['dtls13-mlkem'])
        self.assertIn('rebuilt from fragments', err)


if __name__ == '__main__':
    unittest.main()
