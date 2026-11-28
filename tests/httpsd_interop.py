"""Real TLS + HTTP/1.1 Keep-Alive + session-ticket interop test for tc100-httpsd (runs in whep-interop CI)."""
import http.server
import os
import socket
import ssl
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

BIN = os.environ.get('HTTPSD_BIN')


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class BackendHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    seen_proto = None
    seen_xff = None

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        BackendHandler.seen_proto = self.headers.get('X-Forwarded-Proto')
        BackendHandler.seen_xff = self.headers.get('X-Forwarded-For')
        if self.path == '/index.html':
            body = b'<h1>TC100</h1>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/cgi-bin/state.cgi':
            # Deliberately omit Content-Length and force raw HTTP/1.0 response to test chunked Keep-Alive upgrade
            self.wfile.write(b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"ok":true}')
            self.wfile.flush()
            self.close_connection = True
        else:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(n)
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def read_http_response(sock):
    buf = b''
    while b'\r\n\r\n' not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError('EOF before response headers')
        buf += chunk
    hdr_raw, rest = buf.split(b'\r\n\r\n', 1)
    lines = hdr_raw.decode('latin1').split('\r\n')
    status = int(lines[0].split()[1])
    hdrs = {}
    for line in lines[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            hdrs[k.strip().lower()] = v.strip()

    if hdrs.get('transfer-encoding', '').lower() == 'chunked':
        body = b''
        while True:
            while b'\r\n' not in rest:
                rest += sock.recv(4096)
            sz_line, rest = rest.split(b'\r\n', 1)
            sz = int(sz_line.split(b';', 1)[0], 16)
            if sz == 0:
                while not rest.startswith(b'\r\n'):
                    if len(rest) >= 2:
                        break
                    rest += sock.recv(4096)
                break
            while len(rest) < sz + 2:
                rest += sock.recv(4096)
            body += rest[:sz]
            rest = rest[sz + 2:]
        return status, hdrs, body

    cl = int(hdrs.get('content-length', '0'))
    while len(rest) < cl:
        rest += sock.recv(4096)
    return status, hdrs, rest[:cl]


@unittest.skipUnless(BIN and os.path.exists(BIN), 'HTTPSD_BIN not provided')
class HttpsdInteropTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='httpsd-interop-'))
        self.be_port = free_port()
        self.tls_port = free_port()
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', self.be_port), BackendHandler)
        self.srv_thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.srv_thread.start()
        self.proc = subprocess.Popen(
            [
                BIN,
                '-p', str(self.tls_port),
                '-b', str(self.be_port),
                '-c', str(self.tmp),
                '-H', 'camtest',
                '-I', '127.0.0.1',
                '-n', '0',
                '-d',
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if (self.tmp / 'https-cert.pem').exists():
                try:
                    with socket.create_connection(('127.0.0.1', self.tls_port), timeout=0.5):
                        break
                except OSError:
                    pass
            if self.proc.poll() is not None:
                raise AssertionError(f'tc100-httpsd exited early: {self.proc.stderr.read().decode()}')
            time.sleep(0.05)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self.srv.shutdown()
        self.srv.server_close()
        for p in self.tmp.iterdir():
            p.unlink(missing_ok=True)
        self.tmp.rmdir()

    def test_keepalive_chunked_and_resumption(self):
        cert = self.tmp / 'https-cert.pem'
        key = self.tmp / 'https-key.pem'
        self.assertTrue(cert.exists() and key.exists())
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)

        ctx = ssl.create_default_context(cafile=str(cert))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        # 1. Single TLS socket handles fixed CL + CGI without CL (chunked) + POST body via Keep-Alive
        with socket.create_connection(('127.0.0.1', self.tls_port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname='127.0.0.1') as s:
                cipher = s.cipher()
                self.assertIn(cipher[1], ('TLSv1.2', 'TLSv1.3'))
                s.sendall(b'GET /index.html HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
                st, hdrs, body = read_http_response(s)
                self.assertEqual(st, 200)
                self.assertEqual(body, b'<h1>TC100</h1>')
                self.assertEqual(BackendHandler.seen_proto, 'https')
                self.assertEqual(BackendHandler.seen_xff, '127.0.0.1')

                s.sendall(b'GET /cgi-bin/state.cgi HTTP/1.1\r\nHost: camtest.local\r\n\r\n')
                st2, hdrs2, body2 = read_http_response(s)
                self.assertEqual(st2, 200)
                self.assertEqual(hdrs2.get('transfer-encoding'), 'chunked')
                self.assertEqual(hdrs2.get('connection'), 'keep-alive')
                self.assertEqual(body2, b'{"ok":true}')

                payload = b'key=value&action=save'
                s.sendall(
                    f'POST /cgi-bin/echo.cgi HTTP/1.1\r\nHost: camtest\r\nContent-Length: {len(payload)}\r\n\r\n'.encode()
                    + payload
                )
                st3, _, body3 = read_http_response(s)
                self.assertEqual(st3, 200)
                self.assertEqual(body3, payload)
                saved_session = s.session

        # 2. Second connection reuses session ticket / session cache without full ECDHE handshake
        with socket.create_connection(('127.0.0.1', self.tls_port), timeout=5) as raw2:
            with ctx.wrap_socket(raw2, server_hostname='camtest.local', session=saved_session) as s2:
                self.assertTrue(s2.session_reused)
                s2.sendall(b'GET /index.html HTTP/1.1\r\nHost: camtest.local\r\nConnection: close\r\n\r\n')
                st4, _, body4 = read_http_response(s2)
                self.assertEqual(st4, 200)
                self.assertEqual(body4, b'<h1>TC100</h1>')


if __name__ == '__main__':
    unittest.main()
