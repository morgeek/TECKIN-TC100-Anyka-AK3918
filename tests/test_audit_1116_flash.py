"""Audit 2026-11-16, flash / boot chain: boot counter saved synchronously after a crash, no restart during a flash
write, atomic update lock, backup only on the first write attempt, space check, backup verified before the erase,
cfg-persist slot check, shared kernel checks in the SD install."""
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class BootGuardSync(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / 'cfg').mkdir()
        (self.d / 'flashmode').write_text('')
        (self.d / 'uptime').write_text('20.00 10.00\n')
        (self.d / 'slow.sh').write_bytes(('sleep 2; echo "$CFG" >> %s\n' % (self.d / 'saves').as_posix()).encode())
        p = lambda n: (self.d / n).as_posix()
        self.env = dict(os.environ, BG_CFG=p('cfg'), BG_FLASHMODE=p('flashmode'), BG_FLAG=p('safemode'), BG_MOTD=p('motd'),
                        BG_UPTIME=p('uptime'), BG_OK_S='3600', BG_NO_TIMER='1', BG_PERSIST='sh ' + p('slow.sh'),
                        BG_LASTREASON=p('last'))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def start(self):
        t0 = time.time()
        r = subprocess.run(['sh', str(ROOT / 'v3/linux66-sd/boot-guard'), 'start'], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return time.time() - t0

    def test_clean_restart_saves_in_the_background(self):
        (self.d / 'last').write_text('requested at 2026-11-16 10:00:00: web UI reboot (1.2.3.4)\n')
        self.assertLess(self.start(), 1.5)

    def test_unclean_previous_run_saves_before_returning(self):
        (self.d / 'last').write_text('UNEXPECTED (hardware watchdog, power loss or crash); last alive x\n')
        self.assertGreaterEqual(self.start(), 1.8)
        self.assertTrue((self.d / 'saves').exists())

    def test_unknown_previous_run_and_missing_file_are_unclean(self):
        (self.d / 'last').write_text('unknown (no heartbeat recorded yet)\n')
        self.assertGreaterEqual(self.start(), 1.8)
        (self.d / 'cfg' / '.boot-guard').unlink()
        (self.d / 'last').unlink()
        self.assertGreaterEqual(self.start(), 1.8)

    def test_count_already_one_saves_before_returning(self):
        (self.d / 'last').write_text('requested at 2026-11-16 10:00:00: MQTT command\n')
        (self.d / 'cfg' / '.boot-guard').write_bytes(b'1\n')
        self.assertGreaterEqual(self.start(), 1.8)

    def test_autorun_comment_is_not_stale(self):
        self.assertNotIn('boot-guard saves the\n#     settings once', text('v3/autorun-linux66.sh'))


class RebootGuards(unittest.TestCase):
    def test_web_reboot_and_shutdown_refuse_during_a_write(self):
        s = text('scripts/action.d/system.sh')
        for case in ('    reboot)\n', '    shutdown)\n'):
            body = s[s.index(case):]
            self.assertLess(body.index('/tmp/update66.running'), body.index('reboot-tracker.sh intent'))
        self.assertEqual(s.count('sh /mnt/scripts/update-locked.sh'), 2)

    def test_scheduled_reboot_cron_line_checks_the_lock(self):
        a = text('www/cgi-bin/action.cgi')
        line = [x for x in a.splitlines() if 'scheduled reboot (REBOOT_SCHEDULE)' in x][0]
        self.assertIn('update-locked.sh', line)
        self.assertLess(line.index('update66.running'), line.index('/sbin/reboot'))

    def test_button_watch_ignores_long_presses_during_a_write(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / 'lock').write_text('')
            env = dict(os.environ, BUTTON_UPDATE_LOCK=(d / 'lock').as_posix(), BUTTON_REBOOT_CMD='echo REBOOT')
            s = text('scripts/button-watch.sh')
            hdr = s[s.index('DEV='):s.index('_bw_log()')]
            fn = s[s.index('_bw_log()'):s.index('# Linux 6.6: poll the GPIO')]
            code = hdr + fn + '\nsh() { :; }\n_bw_action 9\n_bw_action 30\necho done\n'
            r = subprocess.run(['sh', '-c', code], capture_output=True, text=True, env=env)
            self.assertNotIn('REBOOT', r.stdout)
            self.assertIn('done', r.stdout)
            (d / 'lock').unlink()
            r = subprocess.run(['sh', '-c', code], capture_output=True, text=True, env=env)
            self.assertIn('REBOOT', r.stdout)      # without the lock the same press reboots
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_update_scripts_stop_crond_and_the_button_watcher(self):
        for f in ('v3/install/update66.sh', 'v3/install/install66.sh'):
            s = text(f)
            self.assertIn('killall crond', s, f)
            self.assertIn('controlscripts/button-actions stop', s, f)
            self.assertIn('button-watch', s, f)

    def test_update_lock_is_atomic(self):
        c = text('www/cgi-bin/update.cgi')
        self.assertIn('mkdir /tmp/update66.running', c)
        self.assertNotIn(': > /tmp/update66.running', c)
        self.assertNotIn('rm -f /tmp/update66.running', c)
        self.assertIn('stale_lock', c)
        self.assertIn('/tmp/update66.running/pid', c)


class StaleLock(unittest.TestCase):
    def run_lock(self, pid, ts, up='1000.00 5.00', exists=True):
        d = Path(tempfile.mkdtemp())
        try:
            lock = d / 'lock'
            if exists:
                lock.mkdir()
                if pid is not None:
                    (lock / 'pid').write_bytes(pid.encode())
                if ts is not None:
                    (lock / 'ts').write_bytes(ts.encode())
            (d / 'up').write_bytes(up.encode())
            env = dict(os.environ, UPDATE_LOCK=lock.as_posix(), UPDATE_LOCK_UPTIME=(d / 'up').as_posix())
            return subprocess.run(['sh', (ROOT / 'scripts/update-locked.sh').as_posix()], env=env).returncode
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_lock_states(self):
        me = str(os.getpid())
        self.assertEqual(self.run_lock(None, None, exists=False), 1)
        self.assertEqual(self.run_lock(None, None), 0)                 # just made: no pid yet
        self.assertEqual(self.run_lock('999999', '990'), 1)            # dead pid: stale
        self.assertEqual(self.run_lock('', '900'), 0)
        self.assertEqual(self.run_lock('', '1', up='5000.00 5.00'), 1)                    # older than 30 min
        self.assertEqual(self.run_lock('', '950', up='1000.00 5.00'), 0)

    def test_guards_use_it_and_scripts_restore_services(self):
        for f in ('v3/install/update66.sh', 'v3/install/install66.sh'):
            s = text(f)
            self.assertIn('trap restore_guards EXIT', s)
            self.assertIn('button-actions start', s)
        self.assertIn('INSTALL66_SD_FREE_KB', text('v3/install/install66.sh'))
        self.assertNotIn('SD card instead', text('v3/install/imgcheck.sh'))
        u = text('v3/install/update66.sh')
        self.assertLess(u.index('sed 1d); do'), u.index('[ "$free" -ge "$need" ]'))   # prunable backups count as free


class UpdateScript(unittest.TestCase):
    def test_backup_only_on_the_first_attempt_that_reached_the_flash(self):
        s = text('v3/install/update66.sh')
        block = s[s.index('# BEGIN write_part'):s.index('# END write_part')]
        d = Path(tempfile.mkdtemp())
        try:
            # the exit code of attempt N is the Nth word of $RCS; the stub logs its arguments
            (d / 'flashw').write_text(
                '#!/bin/sh\necho "$*" >> "$STUBLOG"\nn=$(wc -l < "$STUBLOG")\n'
                'set -- $RCS; eval "rc=\\${$n}"; exit ${rc:-0}\n')
            (d / 'f').write_bytes(b'x')

            def run(rcs):
                lg = d / 'log'
                if lg.exists():
                    lg.unlink()
                code = 'say() { :; }\nBK="-b /bk"\nLOG=\n' + block + '\nwrite_part initrd "%s/f" aaa; echo rc=$?\n' % d
                env = dict(os.environ, STUBLOG=str(lg), RCS=rcs, FLASHW=str(d / 'flashw'), SIMFAIL=str(d / 'none'),
                           FWLOG=str(d / 'fw.log'), RETRY_SLEEP='0')
                r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, env=env)
                return r.stdout.strip(), lg.read_text().splitlines()
            out, log = run('6 6 0')            # read-back failed twice: the later attempts must not back up again
            self.assertEqual(out, 'rc=0')
            self.assertIn('-b /bk', log[0])
            self.assertNotIn('-b', log[1])
            self.assertNotIn('-b', log[2])
            out, log = run('7 5 0')            # backup failed (nothing erased): the retry keeps -b; after flashcp, no more
            self.assertIn('-b /bk', log[0])
            self.assertIn('-b /bk', log[1])
            self.assertNotIn('-b', log[2])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_space_check_before_anything_is_stopped(self):
        s = text('v3/install/update66.sh')
        self.assertLess(s.index('UPDATE66_SD_FREE_KB'), s.index('exec /bin/sh $R/update66.sh apply-ram'))
        self.assertLess(s.index('UPDATE66_SD_FREE_KB'), s.index('housekeeper.sh stop'))


class FlashwAndCfg(unittest.TestCase):
    def test_flashw_compares_the_backup_before_the_erase(self):
        f = text('v3/linux66-sd/flashw')
        a = f.index('does not match $P')
        self.assertLess(f.index('sync;', f.index('backup of $P into')), a)
        self.assertLess(a, f.index('flashcp -v'))
        self.assertIn('exit 7', f[a:a + 300])

    def test_cfg_persist_slot_valid_uses_its_argument_and_the_write_is_verified(self):
        c = text('v3/linux66-sd/cfg-persist')
        fn = c[c.index('slot_valid() {'):c.index('best() {')]
        self.assertNotIn('$SLOT', fn)
        self.assertIn('slot_data "$_sv"', fn)
        self.assertIn('flashcp $T.slot /dev/$m && slot_valid $tgt', c)
        self.assertEqual(subprocess.run(['sh', '-n', str(ROOT / 'v3/linux66-sd/cfg-persist')]).returncode, 0)


class SdInstall(unittest.TestCase):
    def test_install66_uses_the_shared_checks_and_the_published_md5(self):
        s = text('v3/install/install66.sh')
        self.assertIn('imgcheck.sh', s)
        self.assertIn('kernel_img_check', s)
        self.assertIn('initrd_img_check', s)
        self.assertNotIn('-m "$(md5 "$2")"', s)
        self.assertIn('-m "$_wm"', s)
        self.assertLess(s.index('read-back of'), s.index('mv -f "$C/tc100test/c66.img"'))

    def test_imgcheck_functions(self):
        d = Path(tempfile.mkdtemp())
        try:
            lib = (ROOT / 'v3/install/imgcheck.sh').as_posix()
            good = struct.pack('>I', 0x27051956) + b'\0' * 8 + struct.pack('>I', 100) + b'\0' * 48 + b'k' * 100
            (d / 'k').write_bytes(good)
            (d / 'short').write_bytes(good[:-10])
            (d / 'bad').write_bytes(b'x' * 200)
            (d / 'rd').write_bytes(bytes.fromhex('fd377a585a00') + b'\0' * (2012654 - 6))
            (d / 'rd2').write_bytes(b'x' * 10)

            def run(fn, f):
                return subprocess.run(['sh', '-c', '. %s; %s %s/%s' % (lib, fn, d.as_posix(), f)], capture_output=True, text=True)
            self.assertEqual(run('kernel_img_check', 'k').returncode, 0)
            self.assertNotEqual(run('kernel_img_check', 'short').returncode, 0)
            self.assertIn('uImage', run('kernel_img_check', 'bad').stdout)
            self.assertEqual(run('initrd_img_check', 'rd').returncode, 0)
            self.assertNotEqual(run('initrd_img_check', 'rd2').returncode, 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
