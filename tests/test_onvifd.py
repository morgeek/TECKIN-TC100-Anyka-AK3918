"""tc100-onvifd (src/onvifd), the free ONVIF daemon that replaces bin/monvifd, built for the build host and driven on
localhost with temporary configuration files (every path is moved with ONVIFD_* variables).

  - WS-Discovery: Probe -> ProbeMatches (XAddrs, scopes, stable urn:uuid, RelatesTo), other types ignored, Resolve;
  - the calls that need no credentials (GetSystemDateAndTime, GetServices, GetCapabilities...) and the ones that do
    (ter:NotAuthorized, HTTP 400), PasswordDigest and PasswordText, wrong user / password / stale Created refused;
  - profiles from rtspserver.conf and boot.conf (sizes, codecs, 720p only with the kernel's main_scale parameter, no
    sub-stream), stream and snapshot URIs, Media2 profile with the audio output and decoder (the ONVIF backchannel);
  - an unknown action is ter:ActionNotSupported, a setter a fault, an oversized request is refused, the LAN filter.
Every answer is parsed as XML. Run: python3 -m unittest tests.test_onvifd -v
"""
from pathlib import Path
import base64
import hashlib
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src' / 'onvifd'
HAVE_CC = shutil.which('cc') is not None

S = 'http://www.w3.org/2003/05/soap-envelope'
NS = {'s': S, 'tt': 'http://www.onvif.org/ver10/schema', 'tds': 'http://www.onvif.org/ver10/device/wsdl',
      'trt': 'http://www.onvif.org/ver10/media/wsdl', 'tr2': 'http://www.onvif.org/ver20/media/wsdl',
      'd': 'http://schemas.xmlsoap.org/ws/2005/04/discovery', 'a': 'http://schemas.xmlsoap.org/ws/2004/08/addressing',
      'tev': 'http://www.onvif.org/ver10/events/wsdl', 'wsnt': 'http://docs.oasis-open.org/wsn/b-2'}
WSSE = ('xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
        'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"')
DIGEST = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest'
TEXT = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText'


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def security(user, password, digest=True, age=0):
    created = (datetime.now(timezone.utc) - timedelta(seconds=age)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    if digest:
        nonce = secrets.token_bytes(16)
        d = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
        pw = '<wsse:Password Type="%s">%s</wsse:Password><wsse:Nonce>%s</wsse:Nonce><wsu:Created>%s</wsu:Created>' % (
            DIGEST, d, base64.b64encode(nonce).decode(), created)
    else:
        pw = '<wsse:Password Type="%s">%s</wsse:Password>' % (TEXT, password)
    return ('<wsse:Security %s s:mustUnderstand="1"><wsse:UsernameToken><wsse:Username>%s</wsse:Username>%s'
            '</wsse:UsernameToken></wsse:Security>' % (WSSE, user, pw))


@unittest.skipUnless(HAVE_CC, 'needs a C compiler')
class OnvifD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'tc100-onvifd-host')
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-std=gnu11', '-o', cls.bin, str(SRC / 'onvifd.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.procs = []
        self.conf = tempfile.mkdtemp(dir=self.tmp)
        self.password = secrets.token_hex(6)
        self.write('rtspserver.conf', 'PORT=8554\nUSERNAME=root\nUSERPASSWORD=REPLACEME\n[0]\nbps=1600\ncodec=0\nfps=20\nmainres=1080\n'
                   'width=1920\nheight=1080\n[1]\nbps=300\ncodec=2\nfps=10\n')
        self.write('boot.conf', 'RTSP_SUBSTREAM=1\nRTSP_AUDIO=1\nRTSP_LITE_TALK=1\n')
        self.write('user.pwd', self.password + '\n')
        self.write('VERSION', '3.0-test\n')
        self.write('mac', '02:11:22:33:44:55\n')
        self.write('timezone.conf', '# zone\nCET-1CEST,M3.5.0,M10.5.0/3\n')

    def tearDown(self):
        for p in self.procs:
            p.kill()
            p.wait(5)

    def write(self, name, text):
        Path(self.conf, name).write_text(text)

    def start(self, extra_env=None, args=None):
        self.port = free_port()
        self.dport = free_port(socket.SOCK_DGRAM)
        env = dict(os.environ, ONVIFD_CONF_DIR=self.conf, ONVIFD_VERSION_FILE=os.path.join(self.conf, 'VERSION'),
                   ONVIFD_SERIAL_FILE=os.path.join(self.conf, 'none'), ONVIFD_SCALE_PARAM=os.path.join(self.conf, 'main_scale'),
                   ONVIFD_MAC_FILE=os.path.join(self.conf, 'mac'), ONVIFD_IFACE='lo0', ONVIFD_DISCOVERY_PORT=str(self.dport),
                   ONVIFD_MOTION_FILE=os.path.join(self.conf, 'rec_control'))
        env.pop('TC100_NET_ALLOW', None)
        env.update(extra_env or {})
        cmd = [self.bin, '-p', str(self.port), '-w', '80', '-wp', 'http', '-r', '554', '-hwn', 'AK3918', '-vnn', 'Anyka',
               '-loc', 'Earth', '-dn', 'Teckin', '-mod', 'TC100'] + (args or [])
        proc = subprocess.Popen(cmd, env=env, stderr=subprocess.DEVNULL)
        self.procs.append(proc)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=1).close()
                return proc
            except OSError:
                time.sleep(0.1)
        self.fail('tc100-onvifd did not start')

    def http(self, raw, host='127.0.0.1'):
        s = socket.create_connection((host, self.port), timeout=15)
        try:
            try:
                s.sendall(raw)
            except OSError:
                pass
            data = b''
            while True:
                try:
                    d = s.recv(65536)
                except ConnectionResetError:
                    break
                if not d:
                    break
                data += d
            return data
        finally:
            s.close()

    def soap(self, body, svc='device_service', auth=True, header='', host='127.0.0.1'):
        """(status, parsed Body child or None, raw text); a well-formed answer is part of every test"""
        if auth is True:
            header = security('root', self.password) + header
        elif auth:
            header = auth + header
        env = ('<s:Envelope xmlns:s="%s" xmlns:tds="%s" xmlns:trt="%s" xmlns:tr2="%s" xmlns:tt="%s"><s:Header>%s</s:Header><s:Body>%s</s:Body></s:Envelope>'
               % (S, NS['tds'], NS['trt'], NS['tr2'], NS['tt'], header, body))
        req = ('POST /onvif/%s HTTP/1.1\r\nHost: x\r\nContent-Type: application/soap+xml; charset=utf-8\r\nContent-Length: %d\r\n\r\n'
               % (svc, len(env.encode()))).encode() + env.encode()
        raw = self.http(req, host)
        head, _, text = raw.partition(b'\r\n\r\n')
        status = int(head.split()[1])
        self.assertIn(b'Connection: close', head)
        m = re.search(rb'Content-Length: (\d+)', head)
        self.assertEqual(int(m.group(1)), len(text))
        root = ET.fromstring(text)                       # well-formed
        self.assertEqual(root.tag, '{%s}Envelope' % S)
        return status, root.find('s:Body', NS)[0], text.decode()

    def fault_sub(self, node):
        return [e.text for e in node.iter('{%s}Value' % S)]

    # ---- WS-Discovery -------------------------------------------------------------------------------------------

    def probe(self, types='dn:NetworkVideoTransmitter', timeout=2.0, msg='Probe'):
        mid = 'uuid:' + secrets.token_hex(8)
        if msg == 'Probe':
            body = '<d:Probe><d:Types>%s</d:Types></d:Probe>' % types
            act = 'Probe'
        else:
            body = '<d:Resolve><a:EndpointReference><a:Address>%s</a:Address></a:EndpointReference></d:Resolve>' % types
            act = 'Resolve'
        pkt = ('<?xml version="1.0"?><s:Envelope xmlns:s="%s" xmlns:a="%s" xmlns:d="%s" xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
               '<s:Header><a:MessageID>%s</a:MessageID><a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>'
               '<a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/%s</a:Action></s:Header><s:Body>%s</s:Body></s:Envelope>'
               % (S, NS['a'], NS['d'], mid, act, body))
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.settimeout(timeout)
        try:
            u.sendto(pkt.encode(), ('127.0.0.1', self.dport))
            data, _ = u.recvfrom(65535)
        except socket.timeout:
            return mid, None
        finally:
            u.close()
        return mid, ET.fromstring(data)

    def test_probe_match(self):
        self.start()
        mid, root = self.probe()
        self.assertIsNotNone(root)
        self.assertEqual(root.find('s:Header/a:RelatesTo', NS).text, mid)
        self.assertTrue(root.find('s:Header/a:Action', NS).text.endswith('/ProbeMatches'))
        pm = root.find('s:Body/d:ProbeMatches/d:ProbeMatch', NS)
        self.assertEqual(pm.find('d:XAddrs', NS).text, 'http://127.0.0.1:%d/onvif/device_service' % self.port)
        uuid = pm.find('a:EndpointReference/a:Address', NS).text
        self.assertRegex(uuid, r'^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        self.assertIn('021122334455', uuid)               # from the MAC address
        self.assertIn('NetworkVideoTransmitter', pm.find('d:Types', NS).text)
        sc = pm.find('d:Scopes', NS).text
        for item in ('Profile/Streaming', 'Profile/T', 'hardware/AK3918', 'name/Teckin', 'location/Earth', 'type/video_encoder', 'type/audio_encoder'):
            self.assertIn('onvif://www.onvif.org/' + item, sc)
        _, again = self.probe(types='')                   # an empty Types matches too, and the uuid is stable
        self.assertEqual(again.find('s:Body/d:ProbeMatches/d:ProbeMatch/a:EndpointReference/a:Address', NS).text, uuid)
        _, other = self.probe(types='x:Something')
        self.assertIsNone(other)
        _, tds = self.probe(types='tds:Device')
        self.assertIsNotNone(tds)

    def test_resolve(self):
        self.start()
        _, root = self.probe()
        uuid = root.find('s:Body/d:ProbeMatches/d:ProbeMatch/a:EndpointReference/a:Address', NS).text
        mid, r = self.probe(types=uuid, msg='Resolve')
        self.assertIsNotNone(r)
        self.assertEqual(r.find('s:Body/d:ResolveMatches/d:ResolveMatch/d:XAddrs', NS).text.split(':')[0], 'http')
        _, none = self.probe(types='urn:uuid:other', msg='Resolve')
        self.assertIsNone(none)

    def test_bye_on_sigterm(self):
        mc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        mc.bind(('127.0.0.1', 0))
        mc.settimeout(3)
        # Hello / Bye go to the multicast group on the configured port: only the clean exit is checked here
        p = self.start(extra_env={'ONVIFD_IP': '127.0.0.1'})
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(5), 0)
        mc.close()

    # ---- authentication -----------------------------------------------------------------------------------------

    def test_open_calls_without_credentials(self):
        self.start()
        st, n, _ = self.soap('<tds:GetSystemDateAndTime/>', auth=False)
        self.assertEqual(st, 200)
        self.assertEqual(n.tag, '{%s}GetSystemDateAndTimeResponse' % NS['tds'])
        self.assertEqual(n.find('.//tt:TZ', NS).text, 'CET-1CEST,M3.5.0,M10.5.0/3')
        self.assertEqual(int(n.find('.//tt:UTCDateTime/tt:Date/tt:Year', NS).text), datetime.now(timezone.utc).year)
        for body in ('<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>', '<tds:GetCapabilities/>',
                     '<tds:GetServiceCapabilities/>'):
            st, n, _ = self.soap(body, auth=False)
            self.assertEqual(st, 200, body)
        st, n, _ = self.soap('<trt:GetServiceCapabilities/>', 'media_service', auth=False)
        self.assertEqual(st, 200)

    def test_needs_credentials(self):
        self.start()
        for body, svc in (('<trt:GetProfiles/>', 'media_service'), ('<tds:GetDeviceInformation/>', 'device_service'),
                          ('<tr2:GetProfiles/>', 'media2_service'), ('<tds:GetScopes/>', 'device_service')):
            st, n, _ = self.soap(body, svc, auth=False)
            self.assertEqual(st, 400, body)
            self.assertEqual(n.tag, '{%s}Fault' % S)
            self.assertIn('ter:NotAuthorized', self.fault_sub(n))

    def test_wrong_credentials(self):
        self.start()
        for hdr in (security('root', 'not-the-password'), security('admin', self.password), security('root', 'x', digest=False),
                    security('root', self.password, age=3600),                 # created an hour ago: replay
                    '<wsse:Security %s><wsse:UsernameToken><wsse:Username>root</wsse:Username></wsse:UsernameToken></wsse:Security>' % WSSE):
            st, n, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=hdr)
            self.assertEqual(st, 400)
            self.assertIn('ter:NotAuthorized', self.fault_sub(n))

    def test_password_text_and_digest(self):
        self.start()
        st, n, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=security('root', self.password, digest=False))
        self.assertEqual(st, 200)
        st, n, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=security('root', self.password))
        self.assertEqual(st, 200)

    def test_user_from_config_and_no_password_means_open(self):
        self.write('rtsp.env', 'RTSP_USER=camuser\n')
        self.start()
        st, _, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=security('root', self.password))
        self.assertEqual(st, 400)
        st, _, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=security('camuser', self.password))
        self.assertEqual(st, 200)
        self.write('user.pwd', '\n')
        self.procs[0].send_signal(signal.SIGHUP)
        time.sleep(0.5)
        st, _, _ = self.soap('<trt:GetProfiles/>', 'media_service', auth=False)
        self.assertEqual(st, 200)

    # ---- profiles -----------------------------------------------------------------------------------------------

    def profiles(self, svc='media_service', body='<trt:GetProfiles/>'):
        st, n, _ = self.soap(body, svc)
        self.assertEqual(st, 200)
        return n

    def test_media_profiles_from_config(self):
        self.start()
        n = self.profiles()
        ps = n.findall('trt:Profiles', NS)
        self.assertEqual(len(ps), 2)
        main, sub = ps
        self.assertEqual((main.get('token'), sub.get('token')), ('profile_1', 'profile_2'))
        v = main.find('tt:VideoEncoderConfiguration', NS)
        self.assertEqual(v.find('tt:Encoding', NS).text, 'H264')
        self.assertEqual((v.find('tt:Resolution/tt:Width', NS).text, v.find('tt:Resolution/tt:Height', NS).text), ('1920', '1080'))
        self.assertEqual(v.find('tt:RateControl/tt:FrameRateLimit', NS).text, '20')
        self.assertEqual(v.find('tt:RateControl/tt:BitrateLimit', NS).text, '1600')
        self.assertIsNotNone(v.find('tt:H264', NS))
        w = sub.find('tt:VideoEncoderConfiguration', NS)
        self.assertEqual(w.find('tt:Encoding', NS).text, 'H265')
        self.assertEqual((w.find('tt:Resolution/tt:Width', NS).text, w.find('tt:Resolution/tt:Height', NS).text), ('640', '360'))
        self.assertEqual(w.find('tt:RateControl/tt:FrameRateLimit', NS).text, '10')
        self.assertEqual(w.find('tt:RateControl/tt:BitrateLimit', NS).text, '300')
        self.assertIsNotNone(main.find('tt:AudioEncoderConfiguration', NS))
        self.assertEqual(main.find('tt:AudioEncoderConfiguration/tt:Encoding', NS).text, 'G711')
        self.assertIsNotNone(main.find('tt:Extension/tt:AudioOutputConfiguration', NS))
        self.assertIsNotNone(main.find('tt:Extension/tt:AudioDecoderConfiguration', NS))
        self.assertEqual(main.find('tt:VideoSourceConfiguration/tt:UseCount', NS).text, '2')

    def test_720p_needs_main_scale_parameter(self):
        self.write('rtspserver.conf', '[0]\nmainres=720\ncodec=2\nfps=16\nbps=1200\n[1]\ncodec=0\n')
        self.start()
        size = lambda n: n.find('trt:Profiles/tt:VideoEncoderConfiguration/tt:Resolution/tt:Width', NS).text
        n = self.profiles()
        self.assertEqual(size(n), '1920')                                         # no kernel parameter: the stream stays 1080p
        self.assertEqual(n.find('trt:Profiles/tt:VideoEncoderConfiguration/tt:RateControl/tt:FrameRateLimit', NS).text, '15')   # 16 -> 15
        self.write('main_scale', '1\n')
        self.procs[0].send_signal(signal.SIGHUP)
        time.sleep(0.5)
        n = self.profiles()
        self.assertEqual(size(n), '1280')
        self.assertEqual(n.find('trt:Profiles/tt:VideoEncoderConfiguration/tt:Resolution/tt:Height', NS).text, '720')
        self.assertEqual(n.find('trt:Profiles/tt:VideoEncoderConfiguration/tt:Encoding', NS).text, 'H265')

    def test_no_substream(self):
        self.write('boot.conf', 'RTSP_SUBSTREAM="0"\nRTSP_AUDIO=0\n')
        self.start()
        n = self.profiles()
        self.assertEqual(len(n.findall('trt:Profiles', NS)), 1)
        self.assertIsNone(n.find('trt:Profiles/tt:AudioEncoderConfiguration', NS))
        self.assertIsNone(n.find('trt:Profiles/tt:Extension', NS))

    def test_stream_policy_and_command_line_streams(self):
        self.start(args=['-sp', 'sub-primary'])
        n = self.profiles()
        self.assertEqual(n.find('trt:Profiles/tt:VideoEncoderConfiguration/tt:Resolution/tt:Width', NS).text, '640')
        self.assertEqual(n.find('trt:Profiles/tt:VideoSourceConfiguration/tt:Bounds', NS).get('width'), '1920')
        self.procs[0].kill()
        self.procs[0].wait(5)
        self.start(args=['-rp1', 'video0_unicast', '-vw1', '1600', '-vh1', '900', '-vc1', 'H265', '-vcb1', '777', '-fps1', '12', '-en2', '0'])
        n = self.profiles()
        self.assertEqual(len(n.findall('trt:Profiles', NS)), 1)
        v = n.find('trt:Profiles/tt:VideoEncoderConfiguration', NS)
        self.assertEqual((v.find('tt:Encoding', NS).text, v.find('tt:Resolution/tt:Width', NS).text, v.find('tt:RateControl/tt:BitrateLimit', NS).text),
                         ('H265', '1600', '777'))

    def test_stream_and_snapshot_uri(self):
        self.start(args=['-r', '8554'])                  # the RTSP port of the command line
        for tok, path in (('profile_1', 'video0_unicast'), ('profile_2', 'video1_unicast')):
            st, n, _ = self.soap('<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>'
                                 '<trt:ProfileToken>%s</trt:ProfileToken></trt:GetStreamUri>' % tok, 'media_service')
            self.assertEqual(st, 200)
            self.assertEqual(n.find('.//tt:Uri', NS).text, 'rtsp://127.0.0.1:8554/' + path)
            st, n, _ = self.soap('<tr2:GetStreamUri><tr2:Protocol>RTSP</tr2:Protocol><tr2:ProfileToken>%s</tr2:ProfileToken></tr2:GetStreamUri>' % tok, 'media2_service')
            self.assertEqual(n.find('tr2:Uri', NS).text, 'rtsp://127.0.0.1:8554/' + path)
        st, n, _ = self.soap('<trt:GetSnapshotUri><trt:ProfileToken>profile_1</trt:ProfileToken></trt:GetSnapshotUri>', 'media_service')
        self.assertEqual(n.find('.//tt:Uri', NS).text, 'http://127.0.0.1/cgi-bin/currentpic.cgi')
        st, n, _ = self.soap('<tr2:GetSnapshotUri><tr2:ProfileToken>profile_2</tr2:ProfileToken></tr2:GetSnapshotUri>', 'media2_service')
        self.assertEqual(n.find('tr2:Uri', NS).text, 'http://127.0.0.1/cgi-bin/currentpic.cgi')
        st, n, _ = self.soap('<trt:GetStreamUri><trt:ProfileToken>nope</trt:ProfileToken></trt:GetStreamUri>', 'media_service')
        self.assertEqual(st, 400)
        self.assertIn('ter:NoProfile', self.fault_sub(n))

    def test_media2_profile_has_the_backchannel_configurations(self):
        self.start()
        n = self.profiles('media2_service', '<tr2:GetProfiles><tr2:Type>All</tr2:Type></tr2:GetProfiles>')
        ps = n.findall('tr2:Profiles', NS)
        self.assertEqual(len(ps), 2)
        c = ps[0].find('tr2:Configurations', NS)
        self.assertIsNotNone(c.find('tr2:AudioOutput', NS))
        self.assertEqual(c.find('tr2:AudioOutput/tt:OutputToken', NS).text, 'AudioOutput_1')
        self.assertIsNotNone(c.find('tr2:AudioDecoder', NS))
        self.assertEqual(c.find('tr2:AudioEncoder/tt:Encoding', NS).text, 'PCMA')
        v = c.find('tr2:VideoEncoder', NS)
        self.assertEqual(v.find('tt:Encoding', NS).text, 'H264')
        self.assertEqual(v.find('tt:Resolution/tt:Width', NS).text, '1920')
        self.assertEqual(ps[1].find('tr2:Configurations/tr2:VideoEncoder/tt:Encoding', NS).text, 'H265')
        # the same in the lists
        for act, tag in (('GetAudioOutputConfigurations', 'AudioOutput'), ('GetAudioDecoderConfigurations', 'AudioDecoder'),
                         ('GetAudioEncoderConfigurations', 'AudioEncoder'), ('GetVideoEncoderConfigurations', 'VideoEncoder'),
                         ('GetAudioSourceConfigurations', 'AudioSource'), ('GetVideoSourceConfigurations', 'VideoSource')):
            st, r, _ = self.soap('<tr2:%s/>' % act, 'media2_service')
            self.assertEqual(st, 200, act)
            self.assertGreaterEqual(len(r.findall('tr2:Configurations', NS)), 1, act)
        # no talk (boot.conf RTSP_LITE_TALK=0): no audio output
        self.write('boot.conf', 'RTSP_LITE_TALK=0\n')
        self.procs[0].send_signal(signal.SIGHUP)
        time.sleep(0.5)
        n = self.profiles('media2_service', '<tr2:GetProfiles/>')
        self.assertIsNone(n.find('tr2:Profiles/tr2:Configurations/tr2:AudioOutput', NS))

    def test_every_call_is_well_formed(self):
        self.start()
        ok = {'device_service': ['GetSystemDateAndTime', 'GetDeviceInformation', 'GetCapabilities', 'GetServices', 'GetServiceCapabilities',
                                 'GetScopes', 'GetHostname', 'GetNetworkInterfaces', 'GetDNS', 'GetNTP', 'GetUsers', 'GetDiscoveryMode', 'GetWsdlUrl'],
              'media_service': ['GetServiceCapabilities', 'GetProfiles', 'GetVideoSources', 'GetAudioSources', 'GetAudioOutputs',
                                'GetGuaranteedNumberOfVideoEncoderInstances', 'GetVideoSourceConfigurations', 'GetVideoEncoderConfigurations',
                                'GetAudioSourceConfigurations', 'GetAudioEncoderConfigurations', 'GetAudioOutputConfigurations',
                                'GetAudioDecoderConfigurations', 'GetCompatibleVideoSourceConfigurations', 'GetCompatibleVideoEncoderConfigurations',
                                'GetCompatibleAudioSourceConfigurations', 'GetCompatibleAudioEncoderConfigurations',
                                'GetCompatibleAudioOutputConfigurations', 'GetCompatibleAudioDecoderConfigurations'],
              'media2_service': ['GetServiceCapabilities', 'GetProfiles']}
        for svc, acts in ok.items():
            pre = {'device_service': 'tds', 'media_service': 'trt', 'media2_service': 'tr2'}[svc]
            for a in acts:
                with self.subTest(svc=svc, act=a):
                    st, n, _ = self.soap('<%s:%s/>' % (pre, a), svc)
                    self.assertEqual(st, 200)
                    self.assertTrue(n.tag.endswith(a + 'Response'), n.tag)
        st, n, _ = self.soap('<tds:GetDeviceInformation/>')
        self.assertEqual([n.find('tds:' + k, NS).text for k in ('Manufacturer', 'Model', 'FirmwareVersion', 'SerialNumber', 'HardwareId')],
                         ['Anyka', 'TC100', '3.0-test', '021122334455', 'AK3918'])
        st, n, _ = self.soap('<trt:GetVideoSourceConfiguration><trt:ConfigurationToken>VideoSourceConfig_1</trt:ConfigurationToken></trt:GetVideoSourceConfiguration>', 'media_service')
        self.assertEqual(st, 200)
        self.assertIsNotNone(n.find('trt:Configuration', NS))
        st, n, _ = self.soap('<trt:GetVideoEncoderConfiguration><trt:ConfigurationToken>zzz</trt:ConfigurationToken></trt:GetVideoEncoderConfiguration>', 'media_service')
        self.assertEqual(st, 400)
        st, n, _ = self.soap('<tds:GetServices><tds:IncludeCapability>true</tds:IncludeCapability></tds:GetServices>', auth=False)
        self.assertEqual(len(n.findall('tds:Service', NS)), 4)
        self.assertEqual(len(n.findall('tds:Service/tds:Capabilities', NS)), 4)
        self.assertIn('/onvif/media2_service', n.findall('tds:Service/tds:XAddr', NS)[2].text)

    def test_hostile_values_are_escaped(self):
        self.start(args=['-dn', 'A <b>&"x y', '-loc', "O'Neil"])
        st, n, _ = self.soap('<tds:GetScopes/>')
        items = [e.text for e in n.iter('{%s}ScopeItem' % NS['tt'])]
        self.assertIn('onvif://www.onvif.org/name/A%20%3Cb%3E%26%22x%20y', items)

    # ---- Events (PullPoint) -------------------------------------------------------------------------------------

    EV = 'xmlns:tev="http://www.onvif.org/ver10/events/wsdl"'

    def subscribe(self, term=None):
        t = '<tev:InitialTerminationTime>%s</tev:InitialTerminationTime>' % term if term else ''
        st, n, _ = self.soap('<tev:CreatePullPointSubscription %s>%s</tev:CreatePullPointSubscription>' % (self.EV, t), 'event_service')
        if st != 200:
            return None
        addr = n.find('tev:SubscriptionReference/{http://www.w3.org/2005/08/addressing}Address', NS).text
        self.assertRegex(addr, r'^http://127\.0\.0\.1:%d/onvif/subscription\?id=\d+$' % self.port)
        self.assertIsNotNone(n.find('wsnt:CurrentTime', NS))
        self.assertIsNotNone(n.find('wsnt:TerminationTime', NS))
        return addr.split('/onvif/')[1]

    def pull(self, sub, timeout='PT1S'):
        st, n, _ = self.soap('<tev:PullMessages %s><tev:Timeout>%s</tev:Timeout><tev:MessageLimit>10</tev:MessageLimit></tev:PullMessages>' % (self.EV, timeout), sub)
        self.assertEqual(st, 200)
        return [(m.find('.//tt:Message', NS).get('PropertyOperation'), m.find('wsnt:Topic', NS).text,
                 m.find('.//tt:Data/tt:SimpleItem', NS).get('Name'), m.find('.//tt:Data/tt:SimpleItem', NS).get('Value'))
                for m in n.findall('wsnt:NotificationMessage', NS)]

    def motion(self, v):
        Path(self.conf, 'rec_control').write_text('%d\n' % v)

    def test_events_advertised_and_properties(self):
        self.start()
        st, n, _ = self.soap('<tds:GetCapabilities/>', auth=False)
        self.assertEqual(n.find('.//tt:Events/tt:WSPullPointSupport', NS).text, 'true')
        self.assertIn('/onvif/event_service', n.find('.//tt:Events/tt:XAddr', NS).text)
        st, n, _ = self.soap('<tds:GetServices><tds:IncludeCapability>true</tds:IncludeCapability></tds:GetServices>', auth=False)
        ev = [s for s in n.findall('tds:Service', NS) if s.find('tds:Namespace', NS).text == NS['tev']]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].find('tds:Capabilities/tev:Capabilities', NS).get('WSPullPointSupport'), 'true')
        st, n, _ = self.soap('<tev:GetServiceCapabilities %s/>' % self.EV, 'event_service', auth=False)
        self.assertEqual(st, 200)
        self.assertEqual(n.find('tev:Capabilities', NS).get('MaxPullPoints'), '4')
        st, n, raw = self.soap('<tev:GetEventProperties %s/>' % self.EV, 'event_service')
        self.assertEqual(st, 200)
        self.assertIn('MotionAlarm', raw)
        self.assertIn('CellMotionDetector', raw)
        self.assertIn('Name="IsMotion"', raw)
        self.assertIn('Name="State"', raw)
        st, n, _ = self.soap('<tev:CreatePullPointSubscription %s/>' % self.EV, 'event_service', auth=False)   # login needed
        self.assertEqual(st, 400)
        self.assertIn('ter:NotAuthorized', self.fault_sub(n))

    def test_pullpoint_motion_flow(self):
        self.motion(0)
        self.start()
        sub = self.subscribe()
        first = self.pull(sub)
        self.assertEqual(sorted(first), sorted([
            ('Initialized', 'tns1:VideoSource/MotionAlarm', 'State', 'false'),
            ('Initialized', 'tns1:RuleEngine/CellMotionDetector/Motion', 'IsMotion', 'false')]))
        t = time.time()
        self.assertEqual(self.pull(sub, 'PT1S'), [])                       # nothing changed: empty after the timeout
        self.assertGreater(time.time() - t, 0.8)
        res = {}
        th = threading.Thread(target=lambda: res.update(m=self.pull(sub, 'PT10S'), t=time.time()))
        th.start()
        time.sleep(0.4)
        t0 = time.time()
        self.motion(1)
        th.join(8)
        self.assertLess(res['t'] - t0, 1.6)
        self.assertEqual(sorted((m[0], m[2], m[3]) for m in res['m']), [('Changed', 'IsMotion', 'true'), ('Changed', 'State', 'true')])
        self.assertEqual(self.pull(sub, 'PT0S'), [])                        # already reported
        self.motion(0)
        time.sleep(0.8)
        self.assertEqual(sorted(m[3] for m in self.pull(sub, 'PT0S')), ['false', 'false'])      # a pull with no wait sees it too
        st, n, _ = self.soap('<tev:SetSynchronizationPoint %s/>' % self.EV, sub)
        self.assertEqual(st, 200)
        self.assertEqual({m[0] for m in self.pull(sub)}, {'Initialized'})
        # a second subscription starts with Initialized on its own
        sub2 = self.subscribe()
        self.assertEqual({m[0] for m in self.pull(sub2)}, {'Initialized'})
        self.motion(1)                                                        # motion already on when the daemon starts
        time.sleep(0.8)
        sub3 = self.subscribe()
        self.assertEqual({m[3] for m in self.pull(sub3)}, {'true'})

    def test_pull_does_not_block_the_server(self):
        self.motion(0)
        self.start()
        sub = self.subscribe()
        self.pull(sub)
        res = {}
        th = threading.Thread(target=lambda: res.update(m=self.pull(sub, 'PT10S'), t=time.time()))
        t0 = time.time()
        th.start()
        time.sleep(0.5)
        t = time.time()
        st, n, _ = self.soap('<tds:GetSystemDateAndTime/>', auth=False)
        self.assertEqual(st, 200)
        self.assertLess(time.time() - t, 1.0)
        th.join(15)
        self.assertGreater(res['t'] - t0, 9)                               # the wait is bounded: ~10 s then an empty answer
        self.assertEqual(res['m'], [])

    def test_renew_unsubscribe_limit_expiry(self):
        self.start()
        subs = [self.subscribe() for _ in range(4)]
        self.assertTrue(all(subs))
        self.assertIsNone(self.subscribe())                                  # at most 4
        st, n, _ = self.soap('<tev:CreatePullPointSubscription %s/>' % self.EV, 'event_service')
        self.assertEqual(n.tag, '{%s}Fault' % S)
        st, n, _ = self.soap('<wsnt:Renew xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"><wsnt:TerminationTime>PT120S</wsnt:TerminationTime></wsnt:Renew>', subs[0])
        self.assertEqual(st, 200)
        self.assertEqual(n.tag, '{%s}RenewResponse' % NS['wsnt'])
        st, n, _ = self.soap('<wsnt:Unsubscribe xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"/>', subs[1])
        self.assertEqual(st, 200)
        self.assertEqual(n.tag, '{%s}UnsubscribeResponse' % NS['wsnt'])
        st, n, _ = self.soap('<tev:PullMessages %s><tev:Timeout>PT1S</tev:Timeout></tev:PullMessages>' % self.EV, subs[1])
        self.assertEqual(st, 400)
        self.assertIn('ter:ResourceUnknown', self.fault_sub(n))
        self.assertIsNotNone(self.subscribe(term='PT5S'))                    # the freed slot
        st, n, _ = self.soap('<tev:PullMessages %s><tev:Timeout>PT0S</tev:Timeout></tev:PullMessages>' % self.EV, 'subscription?id=99999')
        self.assertEqual(st, 400)
        time.sleep(6.5)                                                       # the 5 s subscription has expired, the renewed one has not
        self.assertEqual(self.pull(subs[0], 'PT0S')[0][0], 'Initialized')
        self.assertIsNotNone(self.subscribe())                                # its slot is free again

    # ---- faults, limits, LAN filter -----------------------------------------------------------------------------

    def test_unknown_action_and_setter(self):
        self.start()
        st, n, _ = self.soap('<tds:FlyToTheMoon/>')
        self.assertEqual(st, 500)
        self.assertIn('ter:ActionNotSupported', self.fault_sub(n))
        st, n, _ = self.soap('<trt:SetVideoEncoderConfiguration/>', 'media_service')
        self.assertEqual(n.tag, '{%s}Fault' % S)
        self.assertNotEqual(st, 200)
        st, n, _ = self.soap('<tr2:CreateProfile/>', 'media2_service')
        self.assertEqual(n.tag, '{%s}Fault' % S)

    def test_garbage_and_plain_get(self):
        self.start()
        raw = self.http(b'POST /onvif/device_service HTTP/1.1\r\nContent-Length: 5\r\n\r\nhello')
        self.assertIn(b' 400 ', raw.split(b'\r\n')[0])
        self.assertIn(b' 200 ', self.http(b'GET / HTTP/1.0\r\n\r\n').split(b'\r\n')[0])      # the control script's health check
        self.assertIn(b' 405 ', self.http(b'PUT / HTTP/1.0\r\n\r\n').split(b'\r\n')[0])

    def test_oversized_request_refused(self):
        self.start()
        big = b'<x>' + b'A' * 20000 + b'</x>'
        raw = self.http(b'POST /onvif/device_service HTTP/1.1\r\nContent-Length: %d\r\n\r\n' % len(big) + big)
        self.assertTrue(raw == b'' or b' 413 ' in raw.split(b'\r\n')[0], raw[:80])
        # without a Content-Length announcing it: still bounded
        raw = self.http(b'POST /onvif/device_service HTTP/1.1\r\nContent-Length: 100\r\n\r\n' + b'B' * 20000)
        self.assertTrue(raw == b'' or b' 413 ' in raw.split(b'\r\n')[0] or b' 400 ' in raw.split(b'\r\n')[0])
        # the daemon is still there
        st, n, _ = self.soap('<tds:GetSystemDateAndTime/>', auth=False)
        self.assertEqual(st, 200)

    def test_silent_connection_is_closed(self):
        self.start()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=8)
        t = time.time()
        self.assertEqual(s.recv(10), b'')
        self.assertLess(time.time() - t, 7)
        s.close()

    def test_connection_limit(self):
        self.start()
        silent = [socket.create_connection(('127.0.0.1', self.port), timeout=5) for _ in range(6)]
        try:
            time.sleep(0.3)
            self.assertIn(b' 503 ', self.http(b'GET / HTTP/1.0\r\n\r\n').split(b'\r\n')[0])
        finally:
            for s in silent:
                s.close()
        time.sleep(0.3)
        self.assertIn(b' 200 ', self.http(b'GET / HTTP/1.0\r\n\r\n').split(b'\r\n')[0])

    def test_lan_only(self):
        self.start(extra_env={'TC100_NET_ALLOW': '203.0.113.0/24 300.1.1.1/8'})
        self.assertIn(b' 200 ', self.http(b'GET / HTTP/1.0\r\n\r\n').split(b'\r\n')[0])        # loopback always
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.connect(('192.0.2.1', 9))
            me = u.getsockname()[0]
        except OSError:
            me = '127.0.0.1'
        finally:
            u.close()
        if me.startswith('127.'):
            self.skipTest('no address but loopback')
        self.assertEqual(self.http(b'GET / HTTP/1.0\r\n\r\n', me), b'')                    # closed, no answer
        self.procs[0].kill()
        self.procs[0].wait(5)
        self.start(extra_env={'TC100_NET_ALLOW': ''})                                       # empty list: no filter
        self.assertIn(b' 200 ', self.http(b'GET / HTTP/1.0\r\n\r\n', me).split(b'\r\n')[0])
        self.procs[-1].kill()
        self.procs[-1].wait(5)
        self.start(extra_env={'TC100_NET_ALLOW': me + '/32'})
        self.assertIn(b' 200 ', self.http(b'GET / HTTP/1.0\r\n\r\n', me).split(b'\r\n')[0])


class Sources(unittest.TestCase):
    def test_no_uclibc_missing_imports(self):
        """the camera's uClibc 0.9.33 has no __isoc23_* (glibc 2.38 C2x redirects), no libm in tc100-onvifd"""
        s = re.sub(r'/\*.*?\*/|//[^\n]*', '', (SRC / 'onvifd.c').read_text(), flags=re.S)  # code only
        self.assertIsNone(re.search(r'\b(sscanf|fscanf|strtol|strtoul|strtoll|strtod|atoi|atol|log10|sqrt|lrint|memmem|ntohl|htonl)\s*\(', s))

    def test_wiring(self):
        """the control script keeps monvifd by default and starts the C daemon only on ONVIF_IMPL=c"""
        conf = (ROOT / 'config' / 'onvif.conf.dist').read_text()
        self.assertRegex(conf, r'(?m)^ONVIF_IMPL=c$')   # the free daemon by default since the rc28
        script = (ROOT / 'controlscripts' / 'onvif').read_text()
        self.assertIn('/mnt/tc100test/tc100-onvifd', script)
        self.assertIn('/mnt/bin/monvifd', script)


if __name__ == '__main__':
    unittest.main()
