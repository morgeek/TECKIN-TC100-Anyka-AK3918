"""[small] fixes of the 2026-11-24 audit (SMALL-A-1124): R5 one write() per FIFO record, R7 log-cap leaves daynight.log,
W4 health probe takes the 0 exit of `health`, W8 memory.csv flushed from one place. (R6 is in test_supervisord.py, R8 in
test_rwconf.py.)"""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def shfunc(path, name):
    s = (ROOT / path).read_text(encoding='utf-8')
    return re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', s, re.M | re.S).group(0)


class FifoRecords(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'needs mkfifo')
    def test_two_concurrent_writers_never_interleave(self):
        """audit R5: records of ~2.9 KB from two publishers at once reach the FIFO whole"""
        with tempfile.TemporaryDirectory() as t:
            fifo = os.path.join(t, 'pub')
            os.mkfifo(fifo)
            pidf = os.path.join(t, 'pid')
            Path(pidf).write_text('%d\n' % os.getpid())
            fns = shfunc('scripts/mqtt-bridge.sh', '_mqtt_daemon_alive') + '\n' + shfunc('scripts/mqtt-bridge.sh', '_mqtt_sink_send')
            code = fns + ('\nMQTT_SINK=; MQTT_DAEMON_FIFO="%s"; MQTT_DAEMON_PIDFILE="%s"\n'
                          'big=$(printf "%%2800s" ""); big=$(echo "$big" | tr " " "$2")\n'
                          'i=0; while [ $i -lt 60 ]; do _mqtt_sink_send P 0 "t/$1" "$big" || echo fail >&2; i=$((i+1)); done\n'
                          ) % (fifo, pidf)
            got = bytearray()
            stop = threading.Event()

            def reader():
                fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                while not stop.is_set():
                    try:
                        b = os.read(fd, 65536)
                    except BlockingIOError:
                        b = b''
                    if b:
                        got.extend(b)
                    else:
                        stop.wait(0.01)
                os.close(fd)
            th = threading.Thread(target=reader)
            th.start()
            ps = [subprocess.Popen(SH + ['-c', code, 'sh', n, ch], stderr=subprocess.PIPE) for n, ch in (('a', 'A'), ('b', 'B'))]
            errs = [p.communicate(timeout=60)[1] for p in ps]
            n = 0
            while n < 50 and len(got) < 2 * 60 * 2810:
                stop.wait(0.1)
                n += 1
            stop.set()
            th.join()
            self.assertEqual(errs, [b'', b''])
            parts = bytes(got).split(b'\0')
            self.assertEqual(parts.pop(), b'')
            self.assertEqual(len(parts), 2 * 2 * 60, len(parts))
            for i in range(0, len(parts), 2):
                head, payload = parts[i], parts[i + 1]
                self.assertRegex(head.decode(), r'^P0t/[ab]$')
                self.assertEqual(len(payload), 2800)
                self.assertEqual(set(payload), {ord('A') if head.endswith(b'a') else ord('B')})

    def test_record_limit_and_one_write_are_kept(self):
        fn = shfunc('scripts/mqtt-bridge.sh', '_mqtt_sink_send')
        self.assertIn('-lt 3000', fn)
        self.assertIn('bs=4096 count=1', fn)


class LogCapDaynight(unittest.TestCase):
    def test_daynight_log_is_left_alone(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            d = t / 'log'
            d.mkdir()
            (t / 'boot.conf').write_text('LOG_CAP_KB=8\n')
            (d / 'daynight.log').write_text(''.join('line %05d\n' % i for i in range(3000)))
            (d / 'other.log').write_text(''.join('line %05d\n' % i for i in range(3000)))
            r = subprocess.run(SH + [str(ROOT / 'scripts/log-cap.sh'), str(d)], env=dict(os.environ, LC_CONF=str(t / 'boot.conf')),
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len((d / 'daynight.log').read_text().splitlines()), 3000)
            self.assertEqual(len((d / 'other.log').read_text().splitlines()), 200)


class HealthProbe(unittest.TestCase):
    def probe(self, svc, health_out, health_rc, pid_name=None):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'cs').mkdir()
            (t / 'run').mkdir()
            (t / 'conf' / 'autostart').mkdir(parents=True)
            (t / 'conf' / 'autostart' / svc).write_text('')
            log = t / 'calls'
            s = t / 'cs' / svc
            s.write_text('#!/bin/sh\necho "$1" >> %s\ncase "$1" in health) echo "%s"; exit %d ;; status) echo x ;; esac\n'
                         % (log, health_out, health_rc))
            s.chmod(0o755)
            if pid_name:
                (t / 'run' / pid_name).write_text('%d\n' % os.getpid())
            body = '\n'.join(shfunc('scripts/health-probe.sh', n) for n in ('_pf_wanted', '_pf_down', 'probe_service_fast'))
            body = body.replace('/mnt/controlscripts/', str(t / 'cs') + '/').replace('/var/run/', str(t / 'run') + '/')
            code = body + '\nHP_DEEP_FILE=%s/deep; HP_CONF_DIR=%s/conf\nprobe_service_fast %s var; echo "$_pf_status"\n' % (t, t, svc)
            r = subprocess.run(SH + ['-c', code], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = log.read_text().split() if log.exists() else []
            return r.stdout.split()[-1], calls

    def test_healthy_exit_zero_runs_no_status(self):
        self.assertEqual(self.probe('onvif', 'HEALTHY', 0, 'onvif.pid'), ('running', ['health']))
        self.assertEqual(self.probe('rtsp-h26x', 'HEALTHY', 0, 'v4l2rtspserver.pid'), ('running', ['health']))

    def test_unhealthy_exit_and_warn_still_fail(self):
        self.assertEqual(self.probe('onvif', 'HEALTHY', 1, 'onvif.pid')[0], 'unhealthy')
        self.assertEqual(self.probe('onvif', 'warn: slow', 0, 'onvif.pid')[0], 'stopped')

    def test_ssh_server_is_a_pidfile_probe(self):
        self.assertEqual(self.probe('ssh-server', '', 0, 'dropbear.pid'), ('running', []))
        self.assertEqual(self.probe('ssh-server', '', 0, None), ('stopped', []))


class MemwatchOneFlush(unittest.TestCase):
    def test_health_snapshot_flushes_memwatch_only_on_stop_and_flush_command(self):
        s = (ROOT / 'scripts/health-snapshot.sh').read_text()
        self.assertNotIn('MEMWATCH_SCRIPT" flush', shfunc('scripts/health-snapshot.sh', 'stability_flush'))
        self.assertIn('MEMWATCH_SCRIPT" flush', shfunc('scripts/health-snapshot.sh', 'memwatch_flush'))
        self.assertIn("trap 'memwatch_flush; stability_flush;", s)
        self.assertIn('flush) memwatch_flush; stability_flush ;;', s)
        # the sample loop's own flush (the pending count reached) does not touch memwatch
        self.assertIn('[ "$_pending_lines" -ge "$STABILITY_FLUSH_SAMPLES" ] && stability_flush', s)


if __name__ == '__main__':
    unittest.main()
