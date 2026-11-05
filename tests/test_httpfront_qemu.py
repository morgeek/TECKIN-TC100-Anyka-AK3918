"""httpfront (src/httpfront, freestanding ARM) built with arm-linux-gnueabi-gcc and run under qemu-arm.

Skipped where the cross compiler or qemu-arm is missing; `sh tests/docker/local-ci.sh cross` installs both and runs it.
- "GET /" and "GET /metrics" are redirected;
- audit 2026-11-04 R2: at most 8 connections at once from one address (then "503"), a silent connection is closed
  after 2 s, finished children are reaped (the slots come back);
- audit 2026-11-04 W2: TC100_NET_ALLOW (boot.conf NET_LAN_ONLY) closes connections from other networks, 127/8 always
  allowed.
"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('arm-linux-gnueabi-gcc')
QEMU = shutil.which('qemu-arm') or shutil.which('qemu-arm-static')


@unittest.skipUnless(CC and QEMU, 'needs arm-linux-gnueabi-gcc and qemu-arm')
class HttpFront(unittest.TestCase):
    PORT = 18580

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bin = os.path.join(cls.tmp, 'httpfront')
        subprocess.run([CC, '-Os', '-Wall', '-Werror', '-marm', '-march=armv5te', '-nostdlib', '-static', '-fno-builtin',
                        '-fno-pic', '-no-pie', '-s', str(ROOT / 'src/httpfront/httpfront.c'), '-o', cls.bin], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def start(self, allow=None):
        env = {} if allow is None else {'TC100_NET_ALLOW': allow}
        self.proc = subprocess.Popen([QEMU, self.bin, '-p', str(self.PORT), '-h', self.tmp], env=env)
        for _ in range(50):
            try:
                socket.create_connection(('127.0.0.1', self.PORT), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.fail('httpfront did not start')
        time.sleep(2.3)                                   # the probe connection above times out and is reaped

    def tearDown(self):
        self.proc.kill()
        self.proc.wait(5)

    def ask(self, req, host='127.0.0.1'):
        s = socket.create_connection((host, self.PORT), timeout=5)
        try:
            s.sendall(req)
            data = b''
            while True:
                try:
                    d = s.recv(512)
                except ConnectionResetError:
                    break
                if not d:
                    break
                data += d
            return data
        finally:
            s.close()

    def test_redirects(self):
        self.start()
        self.assertIn(b'302 Found\r\nLocation: /index.html\r\n', self.ask(b'GET / HTTP/1.0\r\n\r\n'))
        self.assertIn(b'Location: /cgi-bin/metrics.cgi\r\n', self.ask(b'GET /metrics HTTP/1.0\r\n\r\n'))

    def test_eight_per_address_then_503_and_slots_come_back(self):
        self.start()
        silent = [socket.create_connection(('127.0.0.1', self.PORT), timeout=5) for _ in range(8)]
        try:
            time.sleep(0.3)
            self.assertIn(b'503 Service Unavailable', self.ask(b'GET / HTTP/1.0\r\n\r\n'))
            t = time.time()
            self.assertEqual(silent[0].recv(10), b'')       # a silent connection is closed after ~2 s
            self.assertLess(time.time() - t, 3.5)
        finally:
            for s in silent:
                s.close()
        time.sleep(0.5)
        self.assertIn(b'302 Found', self.ask(b'GET / HTTP/1.0\r\n\r\n'))

    def test_lan_only(self):
        self.start('203.0.113.0/24 300.1.1.1/8')
        self.assertIn(b'302 Found', self.ask(b'GET / HTTP/1.0\r\n\r\n'))          # loopback always
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
        self.assertEqual(self.ask(b'GET / HTTP/1.0\r\n\r\n', me), b'')            # closed, no answer
        self.proc.kill()
        self.proc.wait(5)
        self.start('')                                                              # empty list: no filter
        self.assertIn(b'302 Found', self.ask(b'GET / HTTP/1.0\r\n\r\n', me))


if __name__ == '__main__':
    unittest.main()
