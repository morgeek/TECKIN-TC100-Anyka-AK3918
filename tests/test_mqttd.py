"""tc100-mqttd (src/mqttd), the C replacement of the shell MQTT bridge, on the build host: no camera, no real broker.

  - the daemon is built with the host compiler and run against a small fake broker (MQTT 3.1.1 in Python): CONNECT
    (client id, login, retained Will), availability, subscription, commands handed to the worker script as one
    argument, records of the worker published, the FIFO of the other scripts, CONNACK refusals in the status file of
    the web UI, reconnection, clean shutdown;
  - the worker (scripts/mqtt-bridge.sh, run in a sandbox with its paths moved) gives the same discovery topics and
    payloads whether they go to the C daemon (MQTT_SINK) or are forged for nc (the shell bridge).
Run: python3 -m unittest tests.test_mqttd -v
"""
from pathlib import Path
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAVE_CC = shutil.which('cc') is not None
HAVE_BASH = shutil.which('bash') is not None
# the camera's shell is busybox ash (its printf keeps the backslash of \" that bash and dash drop): use it when present
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['bash']


def varint(n):
    out = b''
    while True:
        d, n = n % 128, n // 128
        out += bytes([d | 128 if n else d])
        if not n:
            return out


def parse_packets(buf):
    """(first byte, body) pairs of an MQTT byte stream, and the rest."""
    pkts = []
    while len(buf) >= 2:
        i, rem, mult = 1, 0, 1
        while True:
            if i >= len(buf):
                return pkts, buf
            d = buf[i]
            i += 1
            rem += (d & 127) * mult
            mult *= 128
            if not d & 128:
                break
        if len(buf) < i + rem:
            break
        pkts.append((buf[0], buf[i:i + rem]))
        buf = buf[i + rem:]
    return pkts, buf


def mstr(b, i):
    n = (b[i] << 8) | b[i + 1]
    return b[i + 2:i + 2 + n], i + 2 + n


class Broker:
    """Just enough of a broker: records what the client does."""

    def __init__(self, connack=None):
        self.connack = list(connack or [])   # CONNACK codes of the next connections; then 0
        self.lock = threading.RLock()
        self.connects, self.subs, self.pubs, self.log = [], [], [], []
        self.pong = True
        self.conn = None
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.alive = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.alive:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        buf = b''
        with self.lock:
            self.conn = c
        try:
            while True:
                d = c.recv(65536)
                if not d:
                    break
                buf += d
                pkts, buf = parse_packets(buf)
                for first, body in pkts:
                    self._packet(c, first, body)
        except OSError:
            pass
        with self.lock:
            self.log.append('closed')

    def _packet(self, c, first, b):
        t = first >> 4
        if t == 1:
            proto, i = mstr(b, 0)
            level, flags, keep = b[i], b[i + 1], (b[i + 2] << 8) | b[i + 3]
            i += 4
            cid, i = mstr(b, i)
            c1 = {'proto': proto, 'level': level, 'flags': flags, 'keepalive': keep, 'cid': cid.decode()}
            if flags & 4:
                wt, i = mstr(b, i)
                wp, i = mstr(b, i)
                c1['will'] = (wt.decode(), wp.decode(), bool(flags & 0x20), (flags >> 3) & 3)
            if flags & 0x80:
                u, i = mstr(b, i)
                c1['user'] = u.decode()
            if flags & 0x40:
                p, i = mstr(b, i)
                c1['pass'] = p.decode()
            with self.lock:
                self.connects.append(c1)
                code = self.connack.pop(0) if self.connack else 0
            c.sendall(bytes([0x20, 2, 0, code]))
            if code:
                c.close()
        elif t == 8:
            pid = b[:2]
            i, qos = 2, []
            while i < len(b):
                tp, i = mstr(b, i)
                qos.append((tp.decode(), b[i]))
                i += 1
            with self.lock:
                self.subs.extend(qos)
            c.sendall(bytes([0x90, 2 + len(qos)]) + pid + bytes(0 for _ in qos))
        elif t == 3:
            tp, i = mstr(b, 0)
            with self.lock:
                self.pubs.append((tp.decode(), b[i:], bool(first & 1)))
        elif t == 12:
            with self.lock:
                self.log.append('ping')
            if self.pong:
                c.sendall(b'\xd0\x00')
        elif t == 14:
            with self.lock:
                self.log.append('disconnect')

    def send_publish(self, topic, payload):
        tb = topic.encode()
        body = len(tb).to_bytes(2, 'big') + tb + payload
        self.conn.sendall(b'\x30' + varint(len(body)) + body)

    def drop(self):
        self.conn.shutdown(socket.SHUT_RDWR)
        self.conn.close()

    def wait(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                if pred(self):
                    return True
            time.sleep(0.05)
        return False

    def pub(self, topic):
        with self.lock:
            return [p for p in self.pubs if p[0] == topic]

    def close(self):
        self.alive = False
        self.srv.close()
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass


FAKE = r'''#!/bin/bash
# stands for scripts/mqtt-bridge.sh: the worker modes of tc100-mqttd
d=$(cd "$(dirname "$0")" && pwd)
case "$1" in
  print-config) cat "$d/conf" ;;
  startup)
    printf 'P1%s\000%s\000' t/discovery/a '{"x":1}' >&3
    printf 'P1%s\000\000' t/discovery/gone >&3
    printf 'P0%s\000%s\000' t/env "$MQTT_SINK|$MQTT_HOST_RESOLVED" >&3 ;;
  health-cycle)
    printf 'P1%s\000%s\000' t/health '{"cpu":1}' >&3
    printf 'F0%s\000%s\000' t/file "$d/blob" >&3 ;;
  command)
    printf '%s|%s\n' "$2" "$3" >> "$d/cmds"
    printf 'P0%s\000%s\000' t/command/result "$2" >&3
    [ "$2" = slow ] && sleep 30 ;;
  log-event) printf '%s %s\n' "$2" "$3" >> "$d/events" ;;
esac
exit 0
'''


@unittest.skipUnless(HAVE_CC and HAVE_BASH, 'needs cc and bash')
class Daemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bd = Path(tempfile.mkdtemp())
        cls.bin = cls.bd / 'tc100-mqttd'
        r = subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-std=gnu11', '-o', str(cls.bin), str(ROOT / 'src/mqttd/mqttd.c')],
                           capture_output=True, text=True)
        assert r.returncode == 0 and not r.stderr, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.bd, ignore_errors=True)

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.broker = None
        self.proc = None
        self.script = self.d / 'bridge.sh'
        self.script.write_text(FAKE)
        self.script.chmod(0o755)
        (self.d / 'blob').write_bytes(b'\xff\xd8binary\x00jpeg\xff\xd9')

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        if self.broker:
            self.broker.close()
        shutil.rmtree(self.d, ignore_errors=True)

    def conf(self, broker, **kw):
        c = {'MQTT_ENABLE': '1', 'MQTT_HOST': '127.0.0.1', 'MQTT_PORT': str(broker.port), 'MQTT_USER': '',
             'MQTT_PASSWORD': '', 'MQTT_CLIENT_ID': 'cam1', 'MQTT_TOPIC_ROOT': 'cam1', 'MQTT_TOPIC_COMMAND': 'cam1/command',
             'MQTT_HEALTH_INTERVAL_SECONDS': '300', 'MQTT_KEEPALIVE_PING_SECONDS': '30',
             'MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS': '1', 'MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS': '2',
             'MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER': '2', 'MQTT_CIRCUIT_BREAKER_THRESHOLD': '50',
             'MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS': '300'}
        c.update(kw)
        (self.d / 'conf').write_text(''.join('%s=%s\n' % kv for kv in c.items()))

    def start(self, broker=None, **kw):
        self.broker = broker or Broker()
        self.conf(self.broker, **kw)
        self.proc = subprocess.Popen([str(self.bin), '-s', str(self.script), '-l', str(self.d / 'log'), '-t', str(self.d / 'status'),
                                      '-f', str(self.d / 'fifo'), '-p', str(self.d / 'pid')], stdin=subprocess.DEVNULL)
        return self.broker

    def status(self):
        try:
            return (self.d / 'status').read_text().split()[1:]
        except (OSError, IndexError):
            return None

    def test_connect_will_availability_subscribe_and_status(self):
        b = self.start(MQTT_USER='user1', MQTT_PASSWORD='pw')
        self.assertTrue(b.wait(lambda b: b.subs and b.pub('cam1/availability')))
        c = b.connects[0]
        self.assertEqual((c['proto'], c['level'], c['keepalive'], c['cid']), (b'MQTT', 4, 60, 'cam1-sub'))
        self.assertEqual(c['flags'] & 0x02, 2)                                      # clean session
        self.assertEqual(c['will'], ('cam1/availability', 'offline', True, 0))      # retained Will, QoS 0
        self.assertEqual((c['user'], c['pass']), ('user1', 'pw'))
        self.assertEqual(b.subs, [('cam1/command', 0)])
        self.assertEqual(b.pub('cam1/availability')[0][1:], (b'online', True))
        self.assertEqual(self.status(), ['ok'])
        self.assertEqual((self.d / 'pid').read_text().strip(), str(self.proc.pid))
        self.assertTrue(stat.S_ISFIFO(os.stat(self.d / 'fifo').st_mode))
        # no login when none is configured: no user/password flags
        self.proc.terminate()
        self.proc.wait(5)
        b2 = self.start()
        self.assertTrue(b2.wait(lambda b: b.connects))
        self.assertEqual(b2.connects[0]['flags'] & 0xC0, 0)

    def test_startup_and_health_records_are_published_with_their_retain_flag(self):
        b = self.start(MQTT_HOST='localhost')
        self.assertTrue(b.wait(lambda b: b.pub('t/health') and b.pub('t/file') and b.pub('t/env')))
        self.assertEqual(b.pub('t/discovery/a')[0][1:], (b'{"x":1}', True))
        self.assertEqual(b.pub('t/discovery/gone')[0][1:], (b'', True))             # empty retained payload = entity removed
        self.assertEqual(b.pub('t/health')[0][1:], (b'{"cpu":1}', True))
        self.assertEqual(b.pub('t/file')[0][1:], (b'\xff\xd8binary\x00jpeg\xff\xd9', False))   # file records keep NUL bytes
        self.assertEqual(b.pub('t/env')[0][1], b'1|localhost')                      # MQTT_SINK and the resolved broker host
        order = [p[0] for p in b.pubs]
        self.assertLess(order.index('t/discovery/a'), order.index('t/health'))     # discovery before the first health
        self.assertIn('info MQTT bridge started', (self.d / 'events').read_text())

    def test_command_is_one_argument_and_its_results_are_published(self):
        b = self.start()
        self.assertTrue(b.wait(lambda b: b.subs and b.pub('t/health')))
        evil = '{"cmd":"x"}\n"; touch %s/pwned #$(touch %s/pwned2) `id`' % (self.d, self.d)
        b.send_publish('cam1/command', evil.encode())
        b.send_publish('cam1/command', b'   \r\n ')                                  # blank: nothing to do
        b.send_publish('cam1/command', b'reboot')
        self.assertTrue(b.wait(lambda b: len(b.pub('t/command/result')) == 2))
        lines = (self.d / 'cmds').read_text().split('\n')
        self.assertEqual(lines[0], evil.replace('\n', ' ') + '|mqtt')               # one line, newline -> space, nothing executed
        self.assertEqual(lines[1], 'reboot|mqtt')
        self.assertFalse((self.d / 'pwned').exists() or (self.d / 'pwned2').exists())
        self.assertEqual(len(lines), 3)

    def test_fifo_of_the_other_scripts_publishes_and_survives_garbage(self):
        b = self.start()
        self.assertTrue(b.wait(lambda b: b.pub('t/health')))
        fd = os.open(self.d / 'fifo', os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, b'P1cam1/motion/state\x00ON\x00')
        os.write(fd, b'P0cam1/event\x00{"type":"x"}\x00')
        self.assertTrue(b.wait(lambda b: b.pub('cam1/event')))
        self.assertEqual(b.pub('cam1/motion/state')[0][1:], (b'ON', True))
        os.write(fd, b'garbage without a record type')
        time.sleep(0.3)                                                             # (a bad record empties what was buffered)
        os.write(fd, b'P1cam1/after\x00still ok\x00')
        self.assertTrue(b.wait(lambda b: b.pub('cam1/after')))
        os.close(fd)

    def test_refused_login_is_in_the_status_file_then_recovers(self):
        b = self.start(broker=Broker(connack=[5, 4]))
        self.assertTrue(b.wait(lambda b: len(b.connects) >= 1))
        time.sleep(0.3)
        self.assertEqual(self.status(), ['fail', '5'])
        self.assertTrue(b.wait(lambda b: len(b.connects) >= 2))
        time.sleep(0.3)
        self.assertEqual(self.status(), ['fail', '4'])
        self.assertTrue(b.wait(lambda b: b.subs, 15))                               # third attempt is accepted
        self.assertEqual(self.status(), ['ok'])
        self.assertIn('recovered after 2 error(s)', (self.d / 'log').read_text())
        self.assertIn('error MQTT connection failed (attempt 1', (self.d / 'events').read_text())

    def test_no_broker_is_a_plain_fail_and_the_daemon_keeps_trying(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        self.broker = Broker()
        self.broker.close()
        self.conf(self.broker, MQTT_PORT=str(port))
        self.proc = subprocess.Popen([str(self.bin), '-s', str(self.script), '-l', str(self.d / 'log'), '-t', str(self.d / 'status'),
                                      '-f', str(self.d / 'fifo'), '-p', str(self.d / 'pid')])
        end = time.time() + 5
        while time.time() < end and self.status() != ['fail']:
            time.sleep(0.1)
        self.assertEqual(self.status(), ['fail'])
        self.assertIsNone(self.proc.poll())

    def test_reconnects_after_the_broker_drops_and_after_a_bad_frame(self):
        b = self.start()
        self.assertTrue(b.wait(lambda b: b.subs))
        b.drop()
        self.assertTrue(b.wait(lambda b: len(b.connects) == 2 and len(b.subs) == 2))
        self.assertEqual(len(b.pub('cam1/availability')), 2)                        # online again with the new session
        b.send_publish('cam1/command', b'x' * 5000)                                 # over 4 KiB: rejected like the shell decoder
        self.assertTrue(b.wait(lambda b: len(b.connects) == 3))
        b.send_publish('cam1/command', b'a\x00b')                                   # a NUL byte: rejected
        self.assertTrue(b.wait(lambda b: len(b.connects) == 4))
        self.assertFalse((self.d / 'cmds').exists())

    def test_keepalive_ping_and_dead_link(self):
        b = self.start(MQTT_KEEPALIVE_PING_SECONDS='5')
        self.assertTrue(b.wait(lambda b: 'ping' in b.log, 9))
        b.pong = False                                                              # a broker that stops answering
        self.assertTrue(b.wait(lambda b: len(b.connects) == 2, 40))

    def test_sigterm_says_offline_and_cleans_up(self):
        b = self.start()
        self.assertTrue(b.wait(lambda b: b.subs and b.pub('t/health')))
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(5), 0)
        self.assertTrue(b.wait(lambda b: 'disconnect' in b.log))
        self.assertEqual(b.pub('cam1/availability')[-1][1:], (b'offline', True))
        self.assertFalse((self.d / 'fifo').exists() or (self.d / 'pid').exists())
        self.assertIn('MQTT bridge stopping', (self.d / 'log').read_text())

    def test_a_stuck_command_does_not_block_the_connection(self):
        b = self.start(MQTT_KEEPALIVE_PING_SECONDS='5')
        self.assertTrue(b.wait(lambda b: b.pub('t/health')))
        b.send_publish('cam1/command', b'slow')
        self.assertTrue(b.wait(lambda b: b.pub('t/command/result')))
        fd = os.open(self.d / 'fifo', os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, b'P0cam1/while/slow\x00x\x00')
        self.assertTrue(b.wait(lambda b: b.pub('cam1/while/slow')))                 # published while the worker sleeps
        self.assertTrue(b.wait(lambda b: 'ping' in b.log, 9))
        os.close(fd)
        self.proc.send_signal(signal.SIGTERM)
        self.assertEqual(self.proc.wait(5), 0)                                      # and the stop kills the worker

    def test_disabled_config_exits_quietly_and_missing_script_fails(self):
        self.broker = Broker()
        self.conf(self.broker, MQTT_ENABLE='0')
        r = subprocess.run([str(self.bin), '-s', str(self.script), '-l', str(self.d / 'log'), '-t', str(self.d / 'status'),
                            '-f', str(self.d / 'fifo'), '-p', str(self.d / 'pid')], timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn('disabled in config', (self.d / 'log').read_text())
        self.assertFalse(self.broker.connects)
        r = subprocess.run([str(self.bin), '-s', str(self.d / 'nope'), '-l', str(self.d / 'log')], timeout=10)
        self.assertEqual(r.returncode, 1)

    def test_log_is_rotated_in_ram(self):
        self.broker = Broker()
        self.conf(self.broker)
        (self.d / 'log').write_text(''.join('%d line %d\n' % (i, i) for i in range(9000)))
        self.assertGreater((self.d / 'log').stat().st_size, 65536)
        self.proc = subprocess.Popen([str(self.bin), '-s', str(self.script), '-l', str(self.d / 'log'), '-t', str(self.d / 'status'),
                                      '-f', str(self.d / 'fifo'), '-p', str(self.d / 'pid')])
        self.assertTrue(self.broker.wait(lambda b: b.subs))
        time.sleep(0.5)
        lines = (self.d / 'log').read_text().split('\n')
        self.assertLessEqual(len(lines), 110)
        self.assertIn('8999 line 8999', lines)
        self.assertTrue(any('MQTT connected' in l for l in lines))
        self.assertNotIn('password', (self.d / 'log').read_text())


def sandbox(tmp):
    """The shell side with /mnt, /tmp and /var/run moved under tmp, a config and two shims (nc, sleep)."""
    mnt, t, run, shim = tmp / 'mnt', tmp / 'tmp', tmp / 'run', tmp / 'shim'
    for d in (mnt / 'config', t, run, shim, mnt / 'bin'):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'scripts', mnt / 'scripts')
    (mnt / 'VERSION').write_text('3.0.1-test\n')
    (mnt / 'config' / 'mqtt.conf').write_text(
        'MQTT_ENABLE=1\nMQTT_HOST=broker.test\nMQTT_PORT=1883\nMQTT_CLIENT_ID=Cam-One\nMQTT_TOPIC_ROOT=cam/one\n'
        'MQTT_HA_DISCOVERY_ENABLE=1\nMQTT_HA_CAMERA_ENTITY_ENABLE=1\nMQTT_USER=u\nMQTT_PASSWORD=p\n')
    for f in (mnt / 'scripts').rglob('*'):
        if f.is_file():
            try:
                s = f.read_text()
            except UnicodeDecodeError:
                continue
            where = {'mnt': str(mnt), 'tmp': str(t), 'var/run': str(run)}
            s = re.sub(r'/(mnt|tmp|var/run)/', lambda m: where[m.group(1)] + '/', s)
            # busybox runs its own nc and sleep applets before looking at PATH: name the shims
            s = re.sub(r'\bnc -w', str(shim) + '/nc -w', s)
            s = re.sub(r'(?<![\w/.-])sleep (?=[\d"$])', str(shim) + '/sleep ', s)
            f.write_text(s)
    # nc: keeps what it is sent (one file per connection) and answers CONNACK "accepted"
    (shim / 'nc').write_text('#!/bin/sh\nn=$(ls "%s" | grep -c "^nc\\.")\ncat > "%s/nc.$(printf %%05d $n).bin"\n'
                             'printf "\\040\\002\\000\\000"\n' % (t, t))
    (shim / 'sleep').write_text('#!/bin/sh\nexit 0\n')
    for f in shim.iterdir():
        f.chmod(0o755)
    return mnt, t, shim


def sink_records(data):
    out = []
    parts = data.split(b'\x00')
    for i in range(0, len(parts) - 1, 2):
        head = parts[i]
        out.append((head[2:].decode(), parts[i + 1], head[1:2] == b'1'))
    return out


@unittest.skipUnless(HAVE_BASH, 'needs bash')
class Worker(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.mnt, self.tmp, self.shim = sandbox(self.d)
        self.script = self.mnt / 'scripts' / 'mqtt-bridge.sh'

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_script(self, *args, env=None, sink=False, timeout=120):
        e = dict(os.environ, PATH='%s:%s' % (self.shim, os.environ['PATH']), LC_ALL='C', **(env or {}))
        if sink:
            e['MQTT_SINK'] = '1'
            sinkf = self.d / 'sink.bin'
            r = subprocess.run([*SHELL, '-c', 'exec 3>"$1"; shift; exec "$@"', 'x', str(sinkf), *SHELL, str(self.script), *args],
                               env=e, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
            return r, sinkf.read_bytes()
        return subprocess.run([*SHELL, str(self.script), *args], env=e, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout), b''

    def forged(self):
        """(topic, payload, retain) of every PUBLISH the shell bridge piped to nc."""
        out = []
        for f in sorted(self.tmp.glob('nc.*.bin')):
            pkts, _ = parse_packets(f.read_bytes())
            for first, body in pkts:
                if first >> 4 == 3:
                    tp, i = mstr(body, 0)
                    out.append((tp.decode(), body[i:], bool(first & 1)))
        return out

    def test_print_config_gives_the_resolved_settings(self):
        r, _ = self.run_script('print-config', env={'MQTT_HOST_RESOLVED': ''})
        self.assertEqual(r.returncode, 0, r.stderr)
        kv = dict(l.split('=', 1) for l in r.stdout.decode().splitlines())
        self.assertEqual((kv['MQTT_ENABLE'], kv['MQTT_HOST'], kv['MQTT_PORT'], kv['MQTT_CLIENT_ID']), ('1', 'broker.test', '1883', 'Cam-One'))
        self.assertEqual((kv['MQTT_TOPIC_ROOT'], kv['MQTT_TOPIC_COMMAND']), ('cam/one', 'cam/one/command'))
        self.assertEqual((kv['MQTT_USER'], kv['MQTT_PASSWORD']), ('u', 'p'))
        for k in ('MQTT_HEALTH_INTERVAL_SECONDS', 'MQTT_KEEPALIVE_PING_SECONDS', 'MQTT_SUBSCRIBE_BACKOFF_INITIAL_SECONDS',
                  'MQTT_SUBSCRIBE_BACKOFF_MAX_SECONDS', 'MQTT_SUBSCRIBE_BACKOFF_MULTIPLIER', 'MQTT_CIRCUIT_BREAKER_THRESHOLD',
                  'MQTT_CIRCUIT_BREAKER_COOLDOWN_SECONDS'):
            self.assertRegex(kv[k], r'^\d+$')
        (self.mnt / 'config' / 'mqtt.conf').write_text('MQTT_ENABLE=0\n')
        r, _ = self.run_script('print-config', env={'MQTT_HOST_RESOLVED': 'h'})
        self.assertIn('MQTT_ENABLE=0', r.stdout.decode())
        self.assertIn('MQTT_HOST=h', r.stdout.decode())                              # the daemon's resolved host wins

    def test_discovery_is_identical_through_the_daemon_sink_and_the_forged_packets(self):
        env = {'MQTT_HOST_RESOLVED': 'broker.test'}
        r, data = self.run_script('discovery', env=env, sink=True)
        self.assertEqual(r.returncode, 0)
        via_sink = [x for x in sink_records(data) if x[0].startswith('homeassistant/')]
        r, _ = self.run_script('discovery', env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        via_nc = [x for x in self.forged() if x[0].startswith('homeassistant/')]
        self.assertGreater(len(via_sink), 40)
        self.assertEqual(via_sink, via_nc)                                           # same topics, bytes, retain flags, order
        topics = [x[0] for x in via_sink]
        for t in ('homeassistant/sensor/Cam-One/cpu/config', 'homeassistant/switch/Cam-One/ir_led/config',
                  'homeassistant/button/Cam-One/reboot/config', 'homeassistant/camera/Cam-One/live/config',
                  'homeassistant/select/Cam-One/profile/config'):
            self.assertIn(t, topics)
        self.assertTrue(all(x[2] for x in via_sink))                                 # discovery is retained
        import json
        if SHELL[0] == 'busybox':
            for _, payload, _ in via_sink:
                if payload:
                    self.assertEqual(json.loads(payload)['dev']['ids'], ['Cam-One'])

    def test_publish_modes_use_the_fifo_of_a_live_daemon_else_the_one_shot_connection(self):
        fifo, pid = self.tmp / 'mqtt-bridge.pub', self.d / 'run' / 'tc100-mqttd.pid'
        os.mkfifo(fifo)
        fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        # stale FIFO, no pid file: one-shot connection (nc shim), nothing in the FIFO
        r, _ = self.run_script('publish', 'event', '{"a":1}', '0', env={'MQTT_HOST_RESOLVED': 'x'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.forged(), [('cam/one/event', b'{"a":1}', False)])
        with self.assertRaises(BlockingIOError):
            os.read(fd, 100)
        # live "daemon" (this test process): the record goes to the FIFO, no connection
        pid.write_text('%d\n' % os.getpid())
        for f in self.tmp.glob('nc.*.bin'):
            f.unlink()
        r, _ = self.run_script('publish', 'motion/state', 'ON', '1', env={'MQTT_HOST_RESOLVED': 'x'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.read(fd, 1000), b'P1cam/one/motion/state\x00ON\x00')
        self.assertEqual(self.forged(), [])
        # a dead pid is not trusted
        pid.write_text('999999\n')
        r, _ = self.run_script('publish', 'event', 'z', '0', env={'MQTT_HOST_RESOLVED': 'x'})
        self.assertEqual(self.forged(), [('cam/one/event', b'z', False)])
        os.close(fd)

    def test_worker_modes_startup_health_and_log_event(self):
        r, data = self.run_script('startup', env={'MQTT_HOST_RESOLVED': 'x'}, sink=True)
        topics = [x[0] for x in sink_records(data)]
        self.assertIn('cam/one/event', topics)                                       # bridge.start
        self.assertTrue(any(t.startswith('homeassistant/') for t in topics))
        self.assertLess(max(i for i, t in enumerate(topics) if t.startswith('homeassistant/')), topics.index('cam/one/event'))
        r, data = self.run_script('health-cycle', env={'MQTT_HOST_RESOLVED': 'x'}, sink=True)
        recs = {x[0]: x for x in sink_records(data)}
        self.assertIn('cam/one/health', recs)
        self.assertTrue(recs['cam/one/health'][2])                                   # retained
        self.assertTrue(recs['cam/one/health'][1].startswith(b'{'))
        self.assertEqual(self.forged(), [])                                          # nothing went to nc in sink mode


class Wiring(unittest.TestCase):
    """The switch, the build and the packaging: static checks (the shell runs under sh -n)."""

    def test_switch_in_mqtt_conf_and_in_the_service_script(self):
        dist = (ROOT / 'config/mqtt.conf.dist').read_text()
        self.assertIn('\nMQTT_BRIDGE_IMPL=shell\n', dist)                            # shell until the cameras pass it
        cs = (ROOT / 'controlscripts/mqtt-bridge').read_text()
        self.assertIn('BIN=/mnt/tc100test/tc100-mqttd', cs)
        self.assertIn('[ "$MQTT_BRIDGE_IMPL" = c ]', cs)
        self.assertIn('[ -x "$BIN" ]', cs)                                           # no binary: shell bridge
        self.assertIn('echo "$!" > "$PIDFILE"', cs)                                  # same pid file for health/watchdog
        self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / 'controlscripts/mqtt-bridge')]).returncode, 0)
        self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / 'scripts/mqtt-bridge.sh')]).returncode, 0)

    def test_built_by_ci_and_packaged(self):
        wf = (ROOT / '.github/workflows/build-kernel-linux66.yml').read_text()
        self.assertIn('make -C src/mqttd CROSS=arm-linux-gnueabi-', wf)
        self.assertIn('cp src/mqttd/tc100-mqttd $P/', wf)
        self.assertIn('"$PACK/tc100-mqttd"', (ROOT / 'v3/build-stack.sh').read_text())
        self.assertIn('src/mqttd', (ROOT / 'tests/docker/local-ci.sh').read_text())

    def test_daemon_has_no_shell_string_and_no_credentials(self):
        src = (ROOT / 'src/mqttd/mqttd.c').read_text()
        for bad in ('system(', 'popen(', 'execl(', 'execlp(', 'sh -c', ' stat(', 'fstat('):
            self.assertNotIn(bad, src)
        self.assertEqual(src.count('execv('), 1)                                     # argv vector only
        self.assertNotIn('C.pass)', src.replace('put_str(&p, C.pass)', ''))          # the password is only sent in CONNECT


if __name__ == '__main__':
    unittest.main()
