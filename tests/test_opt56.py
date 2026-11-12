"""Item 56: serial console timer (v3/linux66-sd/console-timer), VM tuning (VM_TUNE), the smart mode switch that
already exists (rtspserver.conf vbr / smart); validators and export rows of the new boot.conf keys."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
TTY = '/dev/ttySAK0'


def text(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


class ConsoleTimer(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / 'proc' / 'self').mkdir(parents=True)
        self.env = dict(os.environ, CT_BOOTCONF=str(self.d / 'boot.conf'), CT_SAFE=str(self.d / 'safemode'),
                        CT_KEEP=str(self.d / 'keep'), CT_OFF=str(self.d / 'off'), CT_PROC=str(self.d / 'proc'),
                        CT_TTY=TTY, CT_DELAY='0', CT_POLL='1', CT_MAXPOLL='2')
        (self.d / 'kills').write_text('')

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def proc(self, pid, cmd, tty=TTY):
        p = self.d / 'proc' / str(pid)
        (p / 'fd').mkdir(parents=True)
        os.symlink(tty, p / 'fd' / '0')
        (p / 'cmdline').write_bytes(cmd.replace(' ', '\0').encode() + b'\0')

    def run_timer(self):
        # kill is replaced by a function that records the pid (no real process involved)
        code = 'kill() { echo "$1" >> %s; }\n. %s' % (shlex.quote(str(self.d / 'kills')),
                                                      shlex.quote(str(ROOT / 'v3/linux66-sd/console-timer')))
        r = subprocess.run(SH + ['-c', code], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def off(self):
        return (self.d / 'off').exists()

    def kills(self):
        return (self.d / 'kills').read_text().split()

    def test_idle_getty_is_stopped_after_the_delay(self):
        self.proc(11, '/sbin/getty -L ttySAK0 115200 vt100')
        self.proc(12, 'sleep 1', tty='/dev/null')
        self.run_timer()
        self.assertTrue(self.off())
        self.assertEqual(self.kills(), ['11'])

    def test_open_session_is_never_cut(self):
        self.proc(11, '/sbin/getty -L ttySAK0 115200 vt100')
        self.proc(21, '-sh')
        self.run_timer()
        self.assertFalse(self.off())
        self.assertEqual(self.kills(), [])

    def test_waits_for_the_session_to_end(self):
        self.proc(11, '/sbin/getty -L ttySAK0 115200 vt100')
        self.proc(21, '-sh')
        self.env['CT_MAXPOLL'] = '0'
        # the session goes away during the first pause: a background helper removes it
        helper = subprocess.Popen(SH + ['-c', 'sleep 0.5; rm -rf %s' % (self.d / 'proc' / '21')])
        self.run_timer()
        helper.wait()
        self.assertTrue(self.off())

    def test_safe_mode_keeps_the_console(self):
        self.proc(11, '/sbin/getty -L ttySAK0 115200 vt100')
        (self.d / 'safemode').write_text('boot loop\n')
        self.run_timer()
        self.assertFalse(self.off())
        self.assertEqual(self.kills(), [])

    def test_keep_flag_and_switch_on_keep_the_console(self):
        self.proc(11, '/sbin/getty -L ttySAK0 115200 vt100')
        (self.d / 'keep').write_text('')
        self.run_timer()
        self.assertFalse(self.off())
        (self.d / 'keep').unlink()
        (self.d / 'boot.conf').write_text('SERIAL_CONSOLE="on"\n')
        self.run_timer()
        self.assertFalse(self.off())
        (self.d / 'boot.conf').write_text('SERIAL_CONSOLE=auto\n')
        self.run_timer()
        self.assertTrue(self.off())

    def test_unreadable_proc_keeps_the_console(self):
        shutil.rmtree(self.d / 'proc')
        self.run_timer()
        self.assertFalse(self.off())

    def test_wiring(self):
        s39 = text('v3/S39tc100-linux66')
        self.assertIn('while [ ! -f /tmp/console-off ]; do /sbin/getty -L ttySAK0 115200 vt100', s39)
        auto = text('v3/autorun-linux66.sh')
        self.assertIn('sh /mnt/v3/linux66-sd/console-timer', auto)
        # after boot-guard (the safe mode flag), long before the 5 minutes are over
        self.assertLess(auto.index('linux66-sd/boot-guard start'), auto.index('linux66-sd/console-timer'))
        for f in ('v3/S39tc100-linux66', 'v3/autorun-linux66.sh', 'v3/linux66-sd/console-timer'):
            self.assertEqual(subprocess.run(SH + ['-n', str(ROOT / f)]).returncode, 0, f)


class VmTune(unittest.TestCase):
    def test_autorun_block_runs_and_respects_switch(self):
        src = text('v3/autorun-linux66.sh')
        a = src.index('case "$(sed -n \'s/^VM_TUNE=')
        b = src.index('esac', a) + 4
        block = src[a:b]
        for want in ('150 > /proc/sys/vm/vfs_cache_pressure', '5 > /proc/sys/vm/dirty_background_ratio',
                     '10 > /proc/sys/vm/dirty_ratio'):
            self.assertIn(want, block)
        d = Path(tempfile.mkdtemp())
        try:
            for conf, applied in (('', True), ('VM_TUNE=1\n', True), ('VM_TUNE="0"\n', False), ('VM_TUNE=off\n', False)):
                (d / 'boot.conf').write_text(conf)
                (d / 'vm').mkdir(exist_ok=True)
                code = block.replace('/mnt/config/boot.conf', str(d / 'boot.conf')).replace('/proc/sys/vm', str(d / 'vm'))
                for n in ('vfs_cache_pressure', 'dirty_background_ratio', 'dirty_ratio'):
                    (d / 'vm' / n).write_text('0\n')
                r = subprocess.run(SH + ['-c', code], capture_output=True, text=True, timeout=10)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = [(d / 'vm' / n).read_text().strip() for n in ('vfs_cache_pressure', 'dirty_background_ratio', 'dirty_ratio')]
                self.assertEqual(got, ['150', '5', '10'] if applied else ['0', '0', '0'], (conf, got))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Validators(unittest.TestCase):
    def norm(self, typ, val):
        code = '. %s\ntc_normalize_and_validate %s %s' % (shlex.quote(str(ROOT / 'scripts/config-transaction.sh')),
                                                          shlex.quote(typ), shlex.quote(val))
        return subprocess.run(['/bin/sh', '-c', code], capture_output=True, timeout=10).returncode == 0

    def test_serial_console(self):
        for v in ('auto', 'on'):
            self.assertTrue(self.norm('serial_console', v), v)
        for v in ('', 'off', '1', 'AUTO', 'on;id'):
            self.assertFalse(self.norm('serial_console', v), v)

    def test_smart_mode(self):
        for v in ('0', '1', '2'):
            self.assertTrue(self.norm('smart_mode', v), v)
        for v in ('', '3', 'x'):
            self.assertFalse(self.norm('smart_mode', v), v)

    def test_checks_and_export_rows(self):
        ct = text('scripts/config-transaction.sh')
        self.assertIn('tc_check_flat "$_tc_file" SERIAL_CONSOLE serial_console', ct)
        self.assertIn('tc_check_flat "$_tc_file" VM_TUNE bool', ct)
        self.assertIn('"$_tc_section" smart smart_mode', ct)
        cgi = text('www/cgi-bin/config_exchange.cgi')
        rows = [l for l in cgi.splitlines() if l.strip().startswith('row("')]
        files = [l.split('"')[1] for l in rows]
        for k in ('"SERIAL_CONSOLE"', '"VM_TUNE"'):
            self.assertTrue(any(k in l and l.startswith('    row("boot.conf"') for l in rows), k)
        # the new rows sit inside the boot.conf run that holds BOOT_STEALTH / ISP_TUNE (no other file in between)
        i = [n for n, l in enumerate(rows) if '"BOOT_STEALTH"' in l][0]
        j = [n for n, l in enumerate(rows) if '"VM_TUNE"' in l][0]
        self.assertEqual(set(files[i:j + 1]), {'boot.conf'})

    def test_dist_documents_the_switches(self):
        dist = text('config/boot.conf.dist')
        self.assertIn('\nSERIAL_CONSOLE=auto\n', dist)
        self.assertIn('\nVM_TUNE=1\n', dist)


class SmartMode(unittest.TestCase):
    """Item 56.5: smart mode is global by default and stays off unless rtspserver.conf [0] enables it with VBR."""

    def test_switch_is_off_by_default_and_wired(self):
        dist = text('config/rtspserver.conf.dist')
        self.assertIn('\nvbr=0\n', dist)
        self.assertIn('\nsmart=0\n', dist)
        launch = text('v3/linux66-sd/rtsp-launch.sh')
        self.assertIn('RTSP_SMART_CONFIG=$2', launch)
        src = text('src/tc100rtsp/tc100_rtsp.c')
        self.assertIn('smart_setup(', src)
        self.assertNotIn('SMART_LTR_NEED', src)


if __name__ == '__main__':
    unittest.main()
