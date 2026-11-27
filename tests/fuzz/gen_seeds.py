#!/usr/bin/env python3
"""Writes the seed corpora of tests/fuzz/corpus/<target>/ (stream [up-fuzz]).

The seeds are what real clients send (VLC, ffmpeg, go2rtc, a browser, ONVIF Device Manager, mosquitto, Chrome), plus the
few that need a computation (a Digest response, a WS-Security digest, a STUN message with its integrity and fingerprint,
a fragmented DTLS ClientHello). Each seed starts with the switch byte its harness reads (see the header of
tests/fuzz/fuzz_*.c). Run `python3 tests/fuzz/gen_seeds.py` from the repository root to rebuild them; the output is
deterministic, so a change of the files in git is a change of this script. Inputs a fuzzer found are added by hand
(tests/fuzz/README in docs/linux-port/upgrade-3.2/fuzz.md) as crash-<name> files and are not touched here."""
import base64
import binascii
import datetime
import hashlib
import hmac
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, 'tests', 'fuzz', 'corpus')
CRLF = b'\r\n'
IP = b'192.168.1.11'


def put(target, name, data):
    d = os.path.join(CORPUS, target)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'wb') as f:
        f.write(data)


def md5(s):
    return hashlib.md5(s).hexdigest().encode()


# ---------------------------------------------------------------------------------------------------------- RTSP
URL = b'rtsp://' + IP + b':554/video0_unicast'


def rtsp_req(method, url, cseq, *hdrs):
    return method + b' ' + url + b' RTSP/1.0' + CRLF + b'CSeq: ' + str(cseq).encode() + CRLF + b''.join(h + CRLF for h in hdrs) + CRLF


def rtsp_seeds():
    vlc = b'User-Agent: LibVLC/3.0.20 (LIVE555 Streaming Media v2016.11.28)'
    ff = b'User-Agent: Lavf60.16.100'
    g2 = b'User-Agent: go2rtc/1.9.4'
    nonce = b'0123456789abcdef0123456789abcdef'
    ha1 = md5(b'root:TC100:s3cret-pass')

    def digest(method, uri):
        ha2 = md5(method + b':' + uri)
        resp = md5(ha1 + b':' + nonce + b':' + ha2)
        return (b'Authorization: Digest username="root", realm="TC100", nonce="' + nonce + b'", uri="' + uri +
                b'", response="' + resp + b'"')

    basic = b'Authorization: Basic ' + base64.b64encode(b'root:s3cret-pass')
    sess = b'Session: 0a1b2c3d'
    tcp = b'Transport: RTP/AVP/TCP;unicast;interleaved=0-1'
    udp = b'Transport: RTP/AVP;unicast;client_port=50000-50001'
    bc = b'Require: www.onvif.org/ver20/backchannel'

    all_sw = bytes([0x1f])   # password on, audio, talk, loopback peer, a nonce held
    open_sw = bytes([0x0e])  # no password, audio, talk, loopback peer
    reqs = {
        'vlc-options': rtsp_req(b'OPTIONS', URL, 1, vlc),
        'vlc-describe': rtsp_req(b'DESCRIBE', URL, 2, vlc, b'Accept: application/sdp'),
        'ffmpeg-options': rtsp_req(b'OPTIONS', URL, 1, ff),
        'ffmpeg-describe-digest': rtsp_req(b'DESCRIBE', URL, 2, ff, b'Accept: application/sdp', digest(b'DESCRIBE', URL)),
        'describe-basic': rtsp_req(b'DESCRIBE', URL, 2, ff, basic),
        'go2rtc-describe-backchannel': rtsp_req(b'DESCRIBE', URL, 2, g2, bc, b'Accept: application/sdp'),
        'setup-tcp-video': rtsp_req(b'SETUP', URL + b'/track1', 3, vlc, tcp),
        'setup-udp-video': rtsp_req(b'SETUP', URL + b'/track1', 3, vlc, udp),
        'setup-tcp-audio': rtsp_req(b'SETUP', URL + b'/track2', 4, vlc, b'Transport: RTP/AVP/TCP;unicast;interleaved=2-3', sess),
        'setup-tcp-backchannel': rtsp_req(b'SETUP', URL + b'/track3', 5, g2, b'Transport: RTP/AVP/TCP;unicast;interleaved=4-5', sess),
        'setup-udp-backchannel': rtsp_req(b'SETUP', URL + b'/track3', 5, g2, b'Transport: RTP/AVP;unicast;client_port=50004-50005', sess),
        'play': rtsp_req(b'PLAY', URL, 6, vlc, sess, b'Range: npt=0.000-'),
        'get-parameter-body': rtsp_req(b'GET_PARAMETER', URL, 7, vlc, sess, b'Content-Type: text/parameters', b'Content-Length: 10')[:-2] + CRLF + b'ping: 1\r\n\n',
        'teardown': rtsp_req(b'TEARDOWN', URL, 8, vlc, sess),
    }
    for k, v in reqs.items():
        put('rtsp_req', k, open_sw + v)
        put('rtsp_req', k + '-auth', all_sw + v)
    # one connection, a whole session: no password, the video over TCP, the backchannel, RTCP and talk frames in between
    rr = b'\x81\xc9\x00\x07' + b'\x00' * 24  # RTCP receiver report
    rtp = b'\x80\x08\x00\x01\x00\x00\x00\xa0\x12\x34\x56\x78' + bytes(range(160))
    sdp_session = (reqs['go2rtc-describe-backchannel'] + reqs['setup-tcp-video'] + reqs['setup-tcp-backchannel'] + reqs['play'] +
                   b'$\x01' + struct.pack('>H', len(rr)) + rr + b'$\x04' + struct.pack('>H', len(rtp)) + rtp +
                   b'\r\n' + reqs['get-parameter-body'] + reqs['teardown'])
    put('rtsp_req', 'session-backchannel-tcp', open_sw + sdp_session)
    # the backchannel needs the password on (talk is refused without one): every request carries a Basic login, 0x0f = password,
    # audio, talk, loopback peer; the talk RTP then reaches talk_rtp() through the "$" frame on channel 4
    ab = lambda m, u, c, *h: rtsp_req(m, u, c, basic, *h)
    talk_session = (ab(b'DESCRIBE', URL, 2, g2, bc) + ab(b'SETUP', URL + b'/track1', 3, g2, tcp) +
                    ab(b'SETUP', URL + b'/track3', 4, g2, b'Transport: RTP/AVP/TCP;unicast;interleaved=4-5', sess) +
                    ab(b'PLAY', URL, 5, g2, sess) + b'$' + struct.pack('>H', len(rr)) + rr + b'$' + struct.pack('>H', len(rtp)) + rtp +
                    b'$' + struct.pack('>H', len(rtp)) + rtp + ab(b'TEARDOWN', URL, 6, g2, sess))
    put('rtsp_req', 'session-backchannel-tcp-talk', bytes([0x0f]) + talk_session)
    put('rtsp_req', 'session-backchannel-udp-talk', bytes([0x0f]) + ab(b'SETUP', URL + b'/track3', 4, g2, b'Transport: RTP/AVP;unicast;client_port=50004-50005', sess) +
        ab(b'PLAY', URL, 5, g2, sess) + ab(b'TEARDOWN', URL, 6, g2, sess))
    put('rtsp_req', 'session-vlc-tcp', open_sw + reqs['vlc-options'] + reqs['vlc-describe'] + reqs['setup-tcp-video'] + reqs['setup-tcp-audio'] + reqs['play'] + reqs['teardown'])
    put('rtsp_req', 'interleaved-only', open_sw + b'$\x04' + struct.pack('>H', len(rtp)) + rtp + b'$\x01\x00\x04abcd')
    # the digest seeds of the fast target: the request text as auth_ok() sees it, a held nonce (bit 4)
    auth = {
        'digest-ok': rtsp_req(b'DESCRIBE', URL, 2, digest(b'DESCRIBE', URL)),
        'digest-other-uri': rtsp_req(b'DESCRIBE', URL, 2, digest(b'DESCRIBE', b'rtsp://' + IP + b':554/video1_unicast')),
        'digest-path-only': rtsp_req(b'DESCRIBE', URL, 2, digest(b'DESCRIBE', b'/video0_unicast')),
        'digest-cnonce': rtsp_req(b'DESCRIBE', URL, 2, digest(b'DESCRIBE', URL) + b', qop=auth, nc=00000001, cnonce="abcdef"'),
        'digest-nonce-in-cnonce': rtsp_req(b'DESCRIBE', URL, 2, b'Authorization: Digest cnonce="x", nonce="' + nonce + b'", username="root", uri="' + URL + b'", response="00"'),
        'basic-ok': rtsp_req(b'DESCRIBE', URL, 2, basic),
        'basic-wrong': rtsp_req(b'DESCRIBE', URL, 2, b'Authorization: Basic ' + base64.b64encode(b'root:nope')),
        'basic-long': rtsp_req(b'DESCRIBE', URL, 2, b'Authorization: Basic ' + base64.b64encode(b'root:' + b'A' * 400)),
        'no-auth': rtsp_req(b'DESCRIBE', URL, 2, vlc),
    }
    for k, v in auth.items():
        put('rtsp_auth', k, bytes([0x10]) + v)
    # talk: RTP, G.711 A-law (PT 8), variants of the header
    pcma = bytes([0xd5 ^ (i * 7 & 0xff) for i in range(160)])
    base = b'\x80\x08\x00\x01\x00\x00\x00\xa0\x12\x34\x56\x78'
    put('rtsp_talk', 'plain', b'\x00' + base + pcma)
    put('rtsp_talk', 'csrc', b'\x00' + b'\x82\x08\x00\x02\x00\x00\x01\x40\x12\x34\x56\x78' + b'\x00' * 8 + pcma)
    put('rtsp_talk', 'extension', b'\x00' + b'\x90\x08\x00\x03\x00\x00\x01\xe0\x12\x34\x56\x78' + b'\xbe\xde\x00\x02' + b'\x00' * 8 + pcma)
    put('rtsp_talk', 'padding', b'\x00' + b'\xa0\x08\x00\x04\x00\x00\x02\x80\x12\x34\x56\x78' + pcma + b'\x00\x00\x00\x04')
    put('rtsp_talk', 'other-client', b'\x01' + base + pcma)
    put('rtsp_talk', 'short', b'\x00' + base[:8])
    put('rtsp_talk', 'pt0', b'\x00' + b'\x80\x00' + base[2:] + pcma)


# ---------------------------------------------------------------------------------------------------------- HTTP front
def http_seeds():
    ua = b'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
    auth = b'Authorization: Basic ' + base64.b64encode(b'admin:plainpass')
    bad = b'Authorization: Basic ' + base64.b64encode(b'admin:wrong')

    def get(path, *h, meth=b'GET'):
        return meth + b' ' + path + b' HTTP/1.1' + CRLF + b'Host: ipcam1.local' + CRLF + ua + CRLF + b''.join(x + CRLF for x in h) + CRLF

    # switch: bit0 lockout, bit1 native routes, bits 2-3 conf (0 md5 crypt, 1 plain text, 2 none, 3 broken), bit4 loopback peer
    lock_native_plain = bytes([0b0111])
    lock_native_md5 = bytes([0b0011])
    plain = bytes([0])
    seeds = {
        'get-root': (plain, get(b'/')),
        'head-root': (plain, get(b'/', meth=b'HEAD')),
        'get-root-query': (plain, get(b'/?lang=fr')),
        'get-metrics': (plain, get(b'/metrics')),
        'get-index': (lock_native_plain, get(b'/index.html', b'Accept: text/html,application/xhtml+xml', b'Cookie: csrf=abc123; theme=dark', auth)),
        'statusline-ok': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', auth)),
        'statusline-md5-wrong': (lock_native_md5, get(b'/cgi-bin/statusline.cgi', bad)),
        'dash': (lock_native_plain, get(b'/cgi-bin/dash.cgi', auth)),
        'daynight': (lock_native_plain, get(b'/cgi-bin/state.cgi?cmd=daynight&format=json', auth)),
        'hw-state': (lock_native_plain, get(b'/cgi-bin/action.cgi?cmd=hw_state&format=json', auth)),
        'isp-tune': (lock_native_plain, get(b'/cgi-bin/state.cgi?cmd=isp_tune&format=json', auth)),
        'health': (lock_native_plain, get(b'/cgi-bin/health.cgi', auth)),
        'query-escaped': (lock_native_plain, get(b'/cgi-bin/state.cgi?cmd=day%6eight&format=json&x=%00', auth)),
        'post-form': (lock_native_plain, b'POST /cgi-bin/action.cgi?cmd=snapshot HTTP/1.1' + CRLF + b'Host: ipcam1' + CRLF + auth + CRLF +
                      b'Content-Type: application/x-www-form-urlencoded' + CRLF + b'Content-Length: 11' + CRLF + CRLF + b'a=1&b=2&c=3'),
        'two-authorization': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', auth, bad)),
        'continuation-line': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', b'X-Long: a', b' b', auth)),
        'blank-before-colon': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', b'Authorization : Basic YWRtaW46cGxhaW5wYXNz')),
        'bare-lf': (lock_native_plain, b'GET /cgi-bin/statusline.cgi HTTP/1.0\nAuthorization: Basic YWRtaW46cGxhaW5wYXNz\n\n'),
        'no-login': (lock_native_plain, get(b'/cgi-bin/statusline.cgi')),
        'basic-nopad': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', b'Authorization: BasicYWRtaW46cGxhaW5wYXNz')),
        'long-token': (lock_native_plain, get(b'/cgi-bin/statusline.cgi', b'Authorization: Basic ' + b'QUJD' * 100)),
        'request-line-only': (plain, b'GET /cgi-bin/x.cgi HTTP/1.1\n'),
    }
    for k, (sw, v) in seeds.items():
        put('httpfront', k, sw + v)


# ---------------------------------------------------------------------------------------------------------- ONVIF
def soap(body, header=b'', extra_ns=b''):
    return (b'<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            b'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
            b'xmlns:tr2="http://www.onvif.org/ver20/media/wsdl" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
            b'xmlns:tt="http://www.onvif.org/ver10/schema"' + extra_ns + b'>' +
            (b'<s:Header>' + header + b'</s:Header>' if header else b'') + b'<s:Body>' + body + b'</s:Body></s:Envelope>')


def onvif_seeds():
    created = datetime.datetime.fromtimestamp(1800000100, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ').encode()
    nraw = bytes(range(16))
    dg = base64.b64encode(hashlib.sha1(nraw + created + b's3cret-pass').digest())
    sec_ns = (b' xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
              b'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"')
    sec_digest = (b'<wsse:Security s:mustUnderstand="1"><wsse:UsernameToken><wsse:Username>root</wsse:Username>'
                  b'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">' + dg +
                  b'</wsse:Password><wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">' +
                  base64.b64encode(nraw) + b'</wsse:Nonce><wsu:Created>' + created + b'</wsu:Created></wsse:UsernameToken></wsse:Security>')
    sec_text = (b'<wsse:Security><wsse:UsernameToken><wsse:Username>root</wsse:Username>'
                b'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">s3cret-pass</wsse:Password>'
                b'</wsse:UsernameToken></wsse:Security>')
    ops = {
        'device-getsystemdatetime': (0, soap(b'<tds:GetSystemDateAndTime/>')),
        'device-getcapabilities': (0, soap(b'<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>')),
        'device-getservices': (0, soap(b'<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>')),
        'device-getdeviceinformation-digest': (0, soap(b'<tds:GetDeviceInformation/>', sec_digest, sec_ns)),
        'device-getdeviceinformation-text': (0, soap(b'<tds:GetDeviceInformation/>', sec_text, sec_ns)),
        'device-getdeviceinformation-noauth': (0, soap(b'<tds:GetDeviceInformation/>')),
        'device-getscopes': (0, soap(b'<tds:GetScopes/>', sec_text, sec_ns)),
        'device-getnetworkinterfaces': (0, soap(b'<tds:GetNetworkInterfaces/>', sec_text, sec_ns)),
        'media-getprofiles': (1, soap(b'<trt:GetProfiles/>', sec_text, sec_ns)),
        'media-getstreamuri': (1, soap(b'<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream><tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup><trt:ProfileToken>profile_1</trt:ProfileToken></trt:GetStreamUri>', sec_text, sec_ns)),
        'media-getsnapshoturi': (1, soap(b'<trt:GetSnapshotUri><trt:ProfileToken>profile_2</trt:ProfileToken></trt:GetSnapshotUri>', sec_text, sec_ns)),
        'media-getvideoencoderconfiguration': (1, soap(b'<trt:GetVideoEncoderConfiguration><trt:ConfigurationToken>VideoEncoder_1</trt:ConfigurationToken></trt:GetVideoEncoderConfiguration>', sec_text, sec_ns)),
        'media2-getprofiles': (2, soap(b'<tr2:GetProfiles><tr2:Type>All</tr2:Type></tr2:GetProfiles>', sec_text, sec_ns)),
        'media2-getstreamuri': (2, soap(b'<tr2:GetStreamUri><tr2:Protocol>RTSP</tr2:Protocol><tr2:ProfileToken>profile_1</tr2:ProfileToken></tr2:GetStreamUri>', sec_text, sec_ns)),
        'events-getproperties': (3, soap(b'<tev:GetEventProperties/>', sec_text, sec_ns)),
        'events-createpullpoint': (3, soap(b'<tev:CreatePullPointSubscription><tev:InitialTerminationTime>PT60S</tev:InitialTerminationTime></tev:CreatePullPointSubscription>', sec_text, sec_ns)),
        'sub-pullmessages': (4, soap(b'<tev:PullMessages><tev:Timeout>PT1S</tev:Timeout><tev:MessageLimit>10</tev:MessageLimit></tev:PullMessages>', sec_text, sec_ns)),
        'sub-renew': (4, soap(b'<tev:Renew xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"><wsnt:TerminationTime>PT30S</wsnt:TerminationTime></tev:Renew>', sec_text, sec_ns)),
        'not-soap': (0, b'<html><body>hello</body></html>'),
        'empty-body': (0, soap(b'')),
    }
    for k, (svc, v) in ops.items():
        put('onvif_soap', k, bytes([0x80 | svc]) + v)       # password set, 127.0.0.1 peer
    put('onvif_soap', 'nopassword-getprofiles', bytes([0x80 | 8 | 1]) + ops['media-getprofiles'][1])
    # HTTP framing: what an NVR or the ONVIF Device Manager sends
    def post(path, body, *h):
        return (b'POST ' + path + b' HTTP/1.1' + CRLF + b'Host: ' + IP + b':8081' + CRLF + b'Content-Type: application/soap+xml; charset=utf-8' + CRLF +
                b''.join(x + CRLF for x in h) + b'Content-Length: ' + str(len(body)).encode() + CRLF + CRLF + body)

    http_sw = bytes([0x80 | 1])
    put('onvif_http', 'post-device', http_sw + post(b'/onvif/device_service', ops['device-getdeviceinformation-text'][1]))
    put('onvif_http', 'post-device-digest', http_sw + post(b'/onvif/device_service', ops['device-getdeviceinformation-digest'][1], b'User-Agent: ONVIF Device Manager'))
    put('onvif_http', 'post-media', http_sw + post(b'/onvif/media_service', ops['media-getprofiles'][1]))
    put('onvif_http', 'post-media2', http_sw + post(b'/onvif/media2_service', ops['media2-getprofiles'][1]))
    put('onvif_http', 'post-event', http_sw + post(b'/onvif/event_service', ops['events-createpullpoint'][1]))
    put('onvif_http', 'post-subscription', http_sw + post(b'/onvif/subscription?id=1', ops['sub-pullmessages'][1]))
    put('onvif_http', 'get-root', http_sw + b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
    put('onvif_http', 'delete', http_sw + b'DELETE /onvif/device_service HTTP/1.1\r\nHost: x\r\n\r\n')
    put('onvif_http', 'content-length-too-big', http_sw + b'POST /onvif/device_service HTTP/1.1\r\nContent-Length: 99999\r\n\r\n')
    put('onvif_http', 'split-in-two', bytes([0x80 | 1 | 4 << 1]) + post(b'/onvif/device_service', ops['device-getsystemdatetime'][1]))
    # WS-Discovery
    probe = (b'<?xml version="1.0" encoding="utf-8"?><Envelope xmlns:dn="http://www.onvif.org/ver10/network/wsdl" '
             b'xmlns="http://www.w3.org/2003/05/soap-envelope"><Header><wsa:MessageID xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
             b'uuid:6bc6d0e2-7c2f-4a8f-9f43-2f1d5a1f7e10</wsa:MessageID><wsa:To xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
             b'urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To><wsa:Action xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
             b'http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action></Header><Body><Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
             b'<Types>dn:NetworkVideoTransmitter</Types><Scopes /></Probe></Body></Envelope>')
    resolve = probe.replace(b'Probe', b'Resolve').replace(b'<Types>dn:NetworkVideoTransmitter</Types><Scopes />',
                                                           b'<wsa:EndpointReference xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"><wsa:Address>urn:uuid:7e57c100-0000-4000-8000-021122334455</wsa:Address></wsa:EndpointReference>')
    put('onvif_wsd', 'probe-nvt', b'\x00' + probe)
    put('onvif_wsd', 'probe-any', b'\x00' + probe.replace(b'<Types>dn:NetworkVideoTransmitter</Types>', b''))
    put('onvif_wsd', 'probe-other-type', b'\x00' + probe.replace(b'dn:NetworkVideoTransmitter', b'dn:Printer'))
    put('onvif_wsd', 'resolve-us', b'\x00' + resolve)
    put('onvif_wsd', 'resolve-other', b'\x00' + resolve.replace(b'021122334455', b'ffffffffffff'))
    put('onvif_wsd', 'probe-escaped-id', b'\x00' + probe.replace(b'uuid:6bc6d0e2', b'&lt;x&amp;y&gt;'))


# ---------------------------------------------------------------------------------------------------------- MQTT
def mqtt_seeds():
    def pub(topic, payload, flags=0):
        body = struct.pack('>H', len(topic)) + topic + payload
        n = len(body)
        rl = b''
        while True:
            b = n % 128
            n //= 128
            rl += bytes([b | (128 if n else 0)])
            if not n:
                break
        return bytes([0x30 | flags]) + rl + body

    t = b'tc100/cam/cmd'
    sw_up, sw_wait = b'\x01', b'\x00'
    connack = b'\x20\x02\x00\x00'
    suback = b'\x90\x03\x00\x01\x00'
    pingresp = b'\xd0\x00'
    put('mqttd', 'connack-ok', sw_wait + connack)
    put('mqttd', 'connack-refused', sw_wait + b'\x20\x02\x00\x05')
    put('mqttd', 'connack-then-suback', sw_wait + connack + suback)
    put('mqttd', 'suback', sw_up + suback)
    put('mqttd', 'suback-refused', sw_up + b'\x90\x03\x00\x01\x80')
    put('mqttd', 'pingresp', sw_up + pingresp)
    put('mqttd', 'publish-snapshot', sw_up + pub(t, b'{"cmd":"snapshot"}'))
    put('mqttd', 'publish-reboot-retained', sw_up + pub(t, b'{"cmd":"reboot"}', 1))
    put('mqttd', 'publish-qos1', sw_up + pub(t, b'{"cmd":"x"}', 2))
    put('mqttd', 'publish-pretty-json', sw_up + pub(t, b'{\r\n  "cmd": "set",\r\n  "key": "night_mode",\r\n  "value": "1"\r\n}'))
    put('mqttd', 'publish-two-packets', sw_up + pub(t, b'{"cmd":"a"}') + pingresp + pub(t, b'{"cmd":"b"}'))
    put('mqttd', 'publish-nul-in-payload', sw_up + pub(t, b'{"cmd":"a\x00"}'))
    put('mqttd', 'publish-long-4k', sw_up + pub(t, b'x' * 4000))
    put('mqttd', 'publish-too-long', sw_up + b'\x30\xff\xff\x03' + b'\x00')
    put('mqttd', 'varint-overflow', sw_up + b'\x30\xff\xff\xff\xff\x7f')
    put('mqttd', 'split-publish', bytes([0x01 | 20 << 1]) + pub(t, b'{"cmd":"snapshot"}'))
    put('mqttd', 'publish-bad-topic-len', sw_up + b'\x30\x04\x00\x20ab')


# ---------------------------------------------------------------------------------------------------------- mDNS
def dns_name(n):
    out = b''
    for part in n.split('.'):
        out += bytes([len(part)]) + part.encode()
    return out + b'\x00'


def mdns_q(name, qtype, qclass=1, hdr=b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00'):
    return hdr + dns_name(name) + struct.pack('>HH', qtype, qclass)


def mdns_seeds():
    sw_a = b'\x00'          # host "ipcam1", no services
    sw_sd = b'\x80' + b'\x00'  # services, text strings
    svc = bytes([0x06])     # services on (bits 1-2), host 0
    for name, d in {
        'a-ipcam1': mdns_q('ipcam1.local', 1),
        'a-ipcam1-qu-bit': mdns_q('ipcam1.local', 1, 0x8001),
        'any-ipcam1': mdns_q('ipcam1.local', 255),
        'aaaa-ipcam1': mdns_q('ipcam1.local', 28),
        'a-upper-case': mdns_q('IPCam1.LOCAL', 1),
        'a-other-host': mdns_q('printer.local', 1),
    }.items():
        put('mdns', name, sw_a + d)
        put('mdns', name + '-legacy', b'\x01' + d)
    for name, d in {
        'ptr-services-enum': mdns_q('_services._dns-sd._udp.local', 12),
        'ptr-http': mdns_q('_http._tcp.local', 12),
        'ptr-rtsp': mdns_q('_rtsp._tcp.local', 12),
        'srv-instance': mdns_q('ipcam1._http._tcp.local', 33),
        'txt-instance': mdns_q('ipcam1._rtsp._tcp.local', 16),
        'ptr-onvif': mdns_q('_onvif._tcp.local', 12),
    }.items():
        put('mdns', name, svc + d)
        put('mdns', name + '-txt-legacy', bytes([0x87]) + d)
    # a query with several questions, the later ones pointers (Avahi / macOS): 12 = the first name
    q = mdns_q('ipcam1.local', 1)
    q = q[:5] + b'\x03' + q[6:] + b'\xc0\x0c\x00\x1c\x00\x01' + b'\xc0\x0c\x00\xff\x00\x01'
    put('mdns', 'three-questions-pointers', sw_a + q)
    put('mdns', 'pointer-loop', sw_a + b'\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\xc0\x0c\x00\x01\x00\x01')


# ---------------------------------------------------------------------------------------------------------- WHEP
CHROME_OFFER = (
    b"v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0 1 2\r\n"
    b"a=extmap-allow-mixed\r\na=msid-semantic: WMS\r\n"
    b"m=video 9 UDP/TLS/RTP/SAVPF 96 97 102 103 104\r\nc=IN IP4 0.0.0.0\r\na=rtcp:9 IN IP4 0.0.0.0\r\n"
    b"a=ice-ufrag:Zk9f\r\na=ice-pwd:0123456789abcdef01234567\r\n"
    b"a=fingerprint:sha-256 AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99\r\n"
    b"a=setup:actpass\r\na=mid:0\r\na=recvonly\r\na=rtcp-mux\r\n"
    b"a=rtpmap:96 VP8/90000\r\na=rtpmap:97 rtx/90000\r\na=fmtp:97 apt=96\r\n"
    b"a=rtpmap:102 H264/90000\r\na=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f\r\n"
    b"a=rtpmap:103 H264/90000\r\na=fmtp:103 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=4d001f\r\n"
    b"a=rtpmap:104 H264/90000\r\na=fmtp:104 level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=4d001f\r\n"
    b"m=audio 9 UDP/TLS/RTP/SAVPF 111 63 0 8\r\nc=IN IP4 0.0.0.0\r\na=mid:1\r\na=recvonly\r\na=rtcp-mux\r\n"
    b"a=rtpmap:111 opus/48000/2\r\na=rtpmap:63 red/48000/2\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
    b"m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 0.0.0.0\r\na=mid:2\r\na=sctp-port:5000\r\n")


def stun(attrs, key=b'VOkJxbRl1RmTxUk/WvJxBt', integrity=True, fingerprint=True, tid=bytes(range(1, 13))):
    body = b''
    for t, v in attrs:
        body += struct.pack('>HH', t, len(v)) + v + b'\x00' * (-len(v) % 4)
    head = lambda n: struct.pack('>HHI', 1, n, 0x2112a442) + tid
    msg = head(len(body)) + body
    if integrity:
        mi = hmac.new(key, head(len(body) + 24) + body, hashlib.sha1).digest()
        body += struct.pack('>HH', 8, 20) + mi
        msg = head(len(body) + (8 if fingerprint else 0)) + body
    else:
        msg = head(len(body) + (8 if fingerprint else 0)) + body
    if fingerprint:
        crc = (binascii.crc32(msg) & 0xffffffff) ^ 0x5354554e
        msg += struct.pack('>HHI', 0x8028, 4, crc)
    return msg


def whep_seeds():
    chrome = [(0x0006, b'Zk9f:abcdefgh'), (0x802a, b'\x01' * 8), (0x0024, struct.pack('>I', 1853824767)), (0x0025, b'')]
    put('whep_stun', 'chrome-binding', stun(chrome))
    put('whep_stun', 'chrome-binding-no-candidate', stun(chrome[:3]))
    put('whep_stun', 'no-integrity', stun(chrome, integrity=False))
    put('whep_stun', 'no-fingerprint', stun(chrome, fingerprint=False))
    put('whep_stun', 'long-username', stun([(0x0006, b'u' * 200 + b':v')]))
    put('whep_stun', 'rfc5769-request', binascii.unhexlify(
        '000100582112a442b7e7a701bc34d686fa87dfae802200105354554e20746573742063'
        '6c69656e74002400046e0001ff80290008932ff9b151263b3600060009657674'
        '6a3a68367659202020000800149aeaa70cbfd8cb56781ef2b5b2d3f249c1b571a2'
        '80280004e57a3bcf'))
    firefox = CHROME_OFFER.replace(b'Zk9f', b'a1b2c3d4').replace(b'profile-level-id=42001f', b'profile-level-id=42e01f')
    put('whep_sdp', 'chrome-offer', b'\x00' + CHROME_OFFER)
    put('whep_sdp', 'chrome-offer-audio', b'\x03' + CHROME_OFFER)
    put('whep_sdp', 'firefox-like-offer', b'\x01' + firefox.replace(b'\r\n', b'\n'))
    put('whep_sdp', 'video-only', b'\x00' + CHROME_OFFER[:CHROME_OFFER.index(b'm=audio')])
    put('whep_sdp', 'no-fingerprint', b'\x00' + CHROME_OFFER.replace(b'a=fingerprint', b'a=xfingerprint'))
    put('whep_sdp', 'five-sections', b'\x03' + CHROME_OFFER + b'm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=mid:3\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=mid:4\r\n')
    put('whep_sdp', 'long-lines', b'\x00' + CHROME_OFFER.replace(b'a=mid:0', b'a=mid:' + b'M' * 300).replace(b'a=ice-ufrag:Zk9f', b'a=ice-ufrag:' + b'U' * 300))
    # DTLS ClientHello in three fragments; each datagram is prefixed by its length - 1 (the harness cuts there)
    body = b'\xfe\xfd' + bytes(range(32)) + b'\x00' + b'\x00' + struct.pack('>H', 4) + b'\xc0\x2b\x00\xff' + b'\x01\x00' + \
        struct.pack('>H', 120) + b'\x00\x0a\x00\x04\x00\x02\x00\x1d' + b'\x00\x17\x00\x60' + b'\xab' * 96 + b'\x00\x0b\x00\x02\x01\x00' + b'\x00' * 0
    n = len(body)

    def frag(off, ln, seq):
        hs = b'\x01' + n.to_bytes(3, 'big') + b'\x00\x00' + off.to_bytes(3, 'big') + ln.to_bytes(3, 'big')
        rec = b'\x16\xfe\xfd\x00\x00' + seq.to_bytes(6, 'big') + struct.pack('>H', 12 + ln)
        return rec + hs + body[off:off + ln]

    third = n // 3
    pieces = [frag(0, third, 0), frag(third, third, 1), frag(2 * third, n - 2 * third, 2)]
    assert all(len(p) <= 200 for p in pieces), [len(p) for p in pieces]
    put('whep_hello', 'clienthello-3-fragments', b''.join(bytes([len(p) - 1]) + p for p in pieces))
    put('whep_hello', 'clienthello-reversed', b''.join(bytes([len(p) - 1]) + p for p in reversed(pieces)))
    whole = frag(0, n, 0)
    put('whep_hello', 'clienthello-whole', bytes([len(whole) - 1]) + whole)
    put('whep_misc', 'sprop', b'Z0LAH5ZUBQHtAA==,aM48gA==')
    put('whep_misc', 'net-allow', b'192.168.1.0/24 10.0.0.0/8 172.16.5.4 junk 1.2.3.4/33 300.1.1.1')


# ---------------------------------------------------------------------------------------------------------- main
if __name__ == '__main__':
    rtsp_seeds()
    http_seeds()
    onvif_seeds()
    mqtt_seeds()
    mdns_seeds()
    whep_seeds()
    n = sum(len(f) for _, _, f in os.walk(CORPUS))
    print('seeds written:', n)
