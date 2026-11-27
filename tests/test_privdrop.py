"""[up-privdrop] Network daemons without root (audit SEC-7, docs/linux-port/upgrade-3.2/privdrop.md).

  - the four daemons that drop root (tc100-onvifd, tc100-whep, tc100-mdnsd, tc100-logfwd): the drop comes after the bind and
    after everything only root can read, every call is checked, a failure stops the daemon; the three libc programs carry
    the same function word for word; the three that stay root (httpfront, tc100-mqttd, tc100_rtsp) carry none;
  - the switch: PRIVDROP in config/boot.conf.dist (single source, on by default), read by scripts/secret-modes.sh; the start
    scripts of mdns, whep, onvif and the syslog forwarder pass "-D uid:gid" through it and nothing when it is 0;
  - the modes of the files the dropped daemons read again (user.pwd, rtspserver.conf: 640 with the service group);
  - the image has the user: v3/buildroot/board/tc100/users.table, same numbers as the scripts;
  - on the build host (gcc, Linux), real processes: tc100-onvifd and tc100-logfwd with -D. A bad specification, and a failing
    setuid (an ordinary user cannot change its identity), stop the daemon; as root (or sudo -n) the process really runs
    as the other user after the bind, still answers, and an unreadable password file never turns into "no password".
Run: python3 -m unittest tests.test_privdrop -v   (as root for the whole set: tests/docker/local-ci.sh runs it that way too)
"""
from pathlib import Path
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
HAVE_CC = shutil.which('cc') is not None
POSIX = os.name == 'posix' and Path('/proc').is_dir()
UID = GID = 1001          # tc100svc: onvifd, whep
NET = 1002                # tc100net: mdnsd, logfwd (no group on any secret)


def text(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def func(src, start='static int priv_drop(const char *spec)'):
    i = src.index(start)
    return src[i:src.index('\n}\n', i) + 3]


def root_prefix():
    """[] when this process is root, ['sudo', '-n'] when passwordless sudo works, None otherwise"""
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        return []
    if shutil.which('sudo') and subprocess.run(['sudo', '-n', 'true'], capture_output=True).returncode == 0:
        return ['sudo', '-n']
    return None


class DropInTheSources(unittest.TestCase):
    def test_onvifd_drops_after_both_binds_before_the_loop(self):
        s = text('src/onvifd/onvifd.c')
        main = s[s.index('\nint main('):]
        call = main.index('if (priv_drop(drop))')
        self.assertLess(main.index('bind(g_lfd'), call)
        self.assertLess(main.index('bind(g_ufd'), call)
        self.assertLess(main.index('cfg_loaded = 1;'), call, 'the settings are read once as root first')
        self.assertLess(call, main.index('while (!g_term)'))
        self.assertIn('return 1;', main[call:call + 200], 'a failed drop stops the daemon')
        self.assertIn('else if (!strcmp(o, "-p"))', main)
        self.assertIn('if (!strcmp(o, "-D")) drop = v;', main)

    def test_whep_drops_after_certificate_and_sockets(self):
        s = text('src/whep/tc100_whep.c')
        main = s[s.index('\nint main('):]
        call = main.index('if (priv_drop(drop))')
        for before in ('cert_init()', 'listen_on(SOCK_STREAM', 'listen_on(SOCK_DGRAM', 'read_pw();'):
            self.assertLess(main.index(before), call, before)
        self.assertLess(call, main.index('while (!G.quit)'))
        self.assertIn('return 1; }', main[call:call + 200])
        self.assertIn('"i:p:u:s:m:a:r:U:w:c:I:D:d"', main)
        self.assertIn("case 'D': drop = optarg; break;", main)
        # the password file is read again at every request, as the service user: an unreadable file keeps the last password
        rp = s[s.index('static void read_pw(void)'):s.index('int main(')]
        self.assertIn('if (errno == ENOENT) G.auth[0] = 0;', rp)

    def test_logfwd_drops_before_the_loop(self):
        s = text('src/logfwd/tc100-logfwd.c')
        main = s[s.index('\nint main('):]
        call = main.index('if (priv_drop(drop))')
        self.assertLess(main.index('if (!g_host[0])'), call)
        self.assertLess(call, main.index('while (!g_stop)'))
        self.assertIn('return 1;', main[call:call + 200])
        self.assertIn('strchr("rflwmD", opt)', main)

    def test_mdnsd_drops_after_bind_and_join(self):
        s = text('src/mdnsd/mdnsd.c')
        run = s[s.index('\nint run('):]
        call = run.index('if (priv_drop(drop))')
        self.assertLess(run.index('sc(SYS_bind'), call)
        self.assertLess(run.index('\tjoin(s);'), call)
        self.assertLess(call, run.index('for (;;)'))
        self.assertIn('return 1; }', run[call:call + 200])
        self.assertIn("argv[i][1] == 'D'", run)

    def test_the_same_function_in_the_three_libc_programs(self):
        a = func(text('src/onvifd/onvifd.c'))
        self.assertEqual(a, func(text('src/whep/tc100_whep.c')))
        self.assertEqual(a, func(text('src/logfwd/tc100-logfwd.c')))
        # order and checks: groups first, then gid, then uid (after setuid the others would be refused), root must not return
        self.assertLess(a.index('setgroups(0, NULL)'), a.index('setgid('))
        self.assertLess(a.index('setgid('), a.index('setuid((uid_t)'))
        self.assertIn('if (setgroups(0, NULL) || setgid((gid_t)v[1]) || setuid((uid_t)v[0])) return -1;', a)
        self.assertIn('if (setuid(0) == 0) return -1;', a)
        self.assertIn('!v[0] || !v[1]', a, 'never "drop" to uid or gid 0')

    def test_mdnsd_function_checks_the_same_things_with_raw_system_calls(self):
        f = func(text('src/mdnsd/mdnsd.c'))
        self.assertLess(f.index('SYS_setgroups32'), f.index('SYS_setgid32'))
        self.assertLess(f.index('SYS_setgid32'), f.index('sc(SYS_setuid32, (long)v[0]'))
        self.assertIn('if (sc(SYS_setgroups32, 0, 0, 0, 0, 0, 0) || sc(SYS_setgid32, (long)v[1], 0, 0, 0, 0, 0) ||', f)
        self.assertIn('sc(SYS_setuid32, (long)v[0], 0, 0, 0, 0, 0)) return -1;', f)
        self.assertIn('sc(SYS_setuid32, 0, 0, 0, 0, 0, 0) == 0) return -1;', f)
        self.assertIn('!v[0] || !v[1]', f)
        s = text('src/mdnsd/mdnsd.c')
        # the ARM EABI numbers of the 32-bit id calls
        for name, n in (('getuid32', 199), ('getgid32', 200), ('geteuid32', 201), ('getegid32', 202), ('setgroups32', 206),
                        ('setuid32', 213), ('setgid32', 214)):
            self.assertIn('#define SYS_%s %d\n' % (name, n), s)

    def test_the_daemons_that_keep_root_say_so_and_do_not_drop(self):
        for f in ('src/httpfront/httpfront.c', 'src/mqttd/mqttd.c', 'src/tc100rtsp/tc100_rtsp.c', 'src/supervisord/supervisord.c'):
            p = ROOT / f
            if p.exists():
                self.assertNotIn('priv_drop', p.read_text(encoding='utf-8'), f)


class TheSwitch(unittest.TestCase):
    def test_boot_conf_dist_has_one_privdrop_key_on_by_default(self):
        dist = text('config/boot.conf.dist')
        self.assertEqual(re.findall(r'(?m)^PRIVDROP=.*$', dist), ['PRIVDROP=1'])
        self.assertIn('PRIVDROP=0: all of them as root', dist)

    def test_one_reader_of_the_switch(self):
        # no script reads the key a second way: the helper of scripts/secret-modes.sh is the only place
        hits = []
        for d in ('scripts', 'controlscripts', 'v3', 'www', 'config'):
            for p in (ROOT / d).rglob('*'):
                if p.is_file() and p.suffix in ('', '.sh', '.cgi', '.dist'):
                    code = [x for x in p.read_text(encoding='utf-8', errors='ignore').splitlines() if not x.lstrip().startswith('#')]
                    if any('PRIVDROP' in x for x in code):
                        hits.append(p.relative_to(ROOT).as_posix())
        self.assertEqual(sorted(hits), ['config/boot.conf.dist', 'scripts/secret-modes.sh'])

    def test_start_scripts_pass_the_option(self):
        self.assertIn('$(privdrop_opt net 2>/dev/null)', text('controlscripts/mdns'))
        self.assertIn('-I 300 $(privdrop_opt 2>/dev/null) </dev/null', text('controlscripts/whep'))
        onv = text('controlscripts/onvif')
        self.assertIn('-sp "$ONVIF_STREAM_POLICY" $(privdrop_opt 2>/dev/null) 2>> "$LOGPATH"', onv)
        cf = text('scripts/common_functions.sh')
        self.assertIn('$_fwd_b $(privdrop_opt net 2>/dev/null) )', cf)
        self.assertIn('. /mnt/scripts/secret-modes.sh', cf)
        # the web server, the MQTT bridge and the video server are started without it
        for f in ('controlscripts/web-server', 'controlscripts/mqtt-bridge', 'controlscripts/rtsp-h26x', 'v3/linux66-sd/rtsp-launch.sh'):
            self.assertNotIn('privdrop_opt', text(f), f)

    def test_scripts_are_valid_sh(self):
        for f in ('scripts/secret-modes.sh', 'scripts/common_functions.sh', 'controlscripts/mdns', 'controlscripts/whep',
                  'controlscripts/onvif'):
            r = subprocess.run(['sh', '-n', str(ROOT / f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + ' ' + r.stderr)


@unittest.skipUnless(POSIX, 'needs a POSIX shell and /proc')
class HelperBehaviour(unittest.TestCase):
    LIB = ROOT / 'scripts' / 'secret-modes.sh'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='privdrop-'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sh(self, code):
        env = dict(os.environ, TC100_CONFIG_DIR=str(self.tmp))
        r = subprocess.run(SH + ['-c', '. "$1"; ' + code, 'sh', str(self.LIB)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def conf(self, body):
        (self.tmp / 'boot.conf').write_text(body)

    def test_default_is_on(self):
        self.assertEqual(self.sh('privdrop_opt'), '-D %d:%d' % (UID, GID))      # no boot.conf at all
        self.conf('NET_LAN_ONLY=1\n')
        self.assertEqual(self.sh('privdrop_opt'), '-D %d:%d' % (UID, GID))      # key absent
        self.conf('PRIVDROP=1\n')
        self.assertEqual(self.sh('privdrop_opt'), '-D %d:%d' % (UID, GID))

    def test_off_values_give_nothing(self):
        for v in ('0', '"0"', 'no', 'off', 'false'):
            self.conf('PRIVDROP=%s\n' % v)
            self.assertEqual(self.sh('privdrop_opt'), '', v)
        self.conf('PRIVDROP=1\nPRIVDROP=0\n')                       # the last line wins, as for the other keys
        self.assertEqual(self.sh('privdrop_opt'), '')
        for line in ('PRIVDROP=0 # why\n', "PRIVDROP='0'\n", 'PRIVDROP="off"  \n', 'PRIVDROP=no\t# tab\n', 'PRIVDROP="0" # x\n'):
            self.conf(line)
            self.assertEqual(self.sh('privdrop_opt'), '', repr(line))
        for line in ('PRIVDROP=1 # on\n', "PRIVDROP='1'\n", 'PRIVDROP=\n', 'PRIVDROP=yes\n'):
            self.conf(line)
            self.assertEqual(self.sh('privdrop_opt'), '-D %d:%d' % (UID, GID), repr(line))
        self.conf('# PRIVDROP=0\n')                                  # a comment is not the key
        self.assertEqual(self.sh('privdrop_opt'), '-D %d:%d' % (UID, GID))

    def test_the_ids_are_the_image_ids(self):
        table = text('v3/buildroot/board/tc100/users.table')
        for name, n in (('tc100svc', UID), ('tc100net', NET)):
            f = next(x for x in table.splitlines() if x.startswith(name + ' ')).split()
            self.assertEqual((f[0], f[1], f[2], f[3]), (name, str(n), name, str(n)))
            self.assertEqual(f[4], '*', 'no password: no login')
        self.assertEqual(self.sh('echo "$TC100_SVC_UID:$TC100_SVC_GID $TC100_NET_UID:$TC100_NET_GID"').strip(),
                         '%d:%d %d:%d' % (UID, GID, NET, NET))
        self.conf('PRIVDROP=1\n')
        self.assertEqual(self.sh('privdrop_opt net'), '-D %d:%d' % (NET, NET))
        self.assertEqual(self.sh('privdrop_opt svc'), '-D %d:%d' % (UID, GID))
        self.conf('PRIVDROP=0\n')
        self.assertEqual(self.sh('privdrop_opt net'), '')

    def test_modes_follow_the_switch(self):
        for n in ('user.pwd', 'rtspserver.conf', 'mqtt.conf', 'wpa_supplicant.conf', 'telegram.conf', 'notify.conf'):
            (self.tmp / n).write_text('x\n')
            os.chmod(self.tmp / n, 0o644)
        self.conf('PRIVDROP=1\n')
        self.sh('secret_modes_fix "$TC100_CONFIG_DIR"')
        for n in ('user.pwd', 'rtspserver.conf'):
            self.assertEqual(os.stat(self.tmp / n).st_mode & 0o777, 0o640, n)
            if os.geteuid() == 0:
                self.assertEqual(os.stat(self.tmp / n).st_gid, GID, n)
        for n in ('mqtt.conf', 'wpa_supplicant.conf', 'telegram.conf', 'notify.conf'):
            self.assertEqual(os.stat(self.tmp / n).st_mode & 0o777, 0o600, n + ' stays owner only: no dropped daemon reads it')
        self.assertEqual(os.stat(self.tmp / 'boot.conf').st_mode & 0o777 & 0o004, 0o004, 'not a secret: left alone')
        # a service restart after PRIVDROP=0 (no reboot): privdrop_opt puts the modes back
        self.conf('PRIVDROP=0\n')
        self.assertEqual(self.sh('privdrop_opt'), '')
        for n in ('user.pwd', 'rtspserver.conf'):
            self.assertEqual(os.stat(self.tmp / n).st_mode & 0o777, 0o600, n)
        # and with it on again
        self.conf('PRIVDROP=1\n')
        self.sh('privdrop_opt')
        self.assertEqual(os.stat(self.tmp / 'user.pwd').st_mode & 0o777, 0o640)

    def test_files_already_right_are_not_touched(self):
        p = self.tmp / 'user.pwd'
        p.write_text('x\n')
        os.chmod(p, 0o640)
        self.conf('PRIVDROP=1\n')
        if os.geteuid() == 0:
            os.chown(p, 0, GID)
        else:
            self.skipTest('the group of the service user needs root')
        before = os.stat(p)
        self.sh('secret_modes_fix "$TC100_CONFIG_DIR"')
        self.assertEqual(os.stat(p).st_ctime, before.st_ctime)

    def test_all_password_leaves_the_new_file_readable_by_the_service_group(self):
        s = text('scripts/common_functions.sh')
        ap = s[s.index('all_password()'):s.index('# Input arg - file with PID')]
        self.assertLess(ap.index('secret_file_attrs /mnt/config/user.pwd.$$.tmp'), ap.index('mv -f /mnt/config/user.pwd.$$.tmp /mnt/config/user.pwd'))


@unittest.skipUnless(POSIX, 'needs a POSIX shell and /proc')
class AttributesBeforeTheRename(unittest.TestCase):
    """secret_file_attrs: owner, group and mode are set on the temporary file, before it replaces the real one"""
    LIB = ROOT / 'scripts' / 'secret-modes.sh'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='privattr-'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sh(self, code, pre=''):
        env = dict(os.environ, TC100_CONFIG_DIR=str(self.tmp))
        r = subprocess.run(SH + ['-c', pre + '. "$1"; ' + code, 'sh', str(self.LIB)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def mk(self, name, mode, body='x\n'):
        p = self.tmp / name
        p.write_text(body)
        os.chmod(p, mode)
        return p

    def test_a_secret_file_gets_the_policy_on_the_temporary_file(self):
        (self.tmp / 'boot.conf').write_text('PRIVDROP=1\n')
        for name in ('user.pwd', 'rtspserver.conf'):
            t = self.mk(name + '.tmp', 0o600)
            self.sh('secret_file_attrs "$TC100_CONFIG_DIR/%s.tmp" "$TC100_CONFIG_DIR/%s"' % (name, name))
            self.assertEqual(os.stat(t).st_mode & 0o777, 0o640, name)
            if os.geteuid() == 0:
                self.assertEqual(os.stat(t).st_gid, GID, name)
        t = self.mk('mqtt.conf.tmp', 0o644)
        self.sh('secret_file_attrs "$TC100_CONFIG_DIR/mqtt.conf.tmp" "$TC100_CONFIG_DIR/mqtt.conf"')
        self.assertEqual(os.stat(t).st_mode & 0o777, 0o600, 'a secret nobody dropped reads: owner only')
        (self.tmp / 'boot.conf').write_text('PRIVDROP=0\n')
        t = self.mk('user.pwd.tmp', 0o644)
        self.sh('secret_file_attrs "$TC100_CONFIG_DIR/user.pwd.tmp" "$TC100_CONFIG_DIR/user.pwd"')
        self.assertEqual(os.stat(t).st_mode & 0o777, 0o600)

    def test_another_file_keeps_the_attributes_of_the_one_it_replaces(self):
        old = self.mk('other.conf', 0o640)
        t = self.mk('other.conf.tmp', 0o600)
        self.sh('secret_file_attrs "$TC100_CONFIG_DIR/other.conf.tmp" "$TC100_CONFIG_DIR/other.conf"')
        self.assertEqual(os.stat(t).st_mode & 0o777, 0o640)
        self.assertEqual(os.stat(t).st_gid, os.stat(old).st_gid)

    def test_rewrite_config_keeps_group_and_mode(self):
        (self.tmp / 'boot.conf').write_text('PRIVDROP=1\n')
        p = self.mk('rtspserver.conf', 0o640, 'PORT=554\nUSERPASSWORD=a\n')
        if os.geteuid() == 0:
            os.chown(p, 0, GID)
        r = subprocess.run(SH + ['-c', '. "$1"; . "$2"; rewrite_config "$3" USERPASSWORD b', 'sh', str(ROOT / 'scripts' / 'secret-modes.sh'),
                                 str(ROOT / 'scripts' / 'common_functions.sh'), str(p)],
                           capture_output=True, text=True, env=dict(os.environ, TC100_CONFIG_DIR=str(self.tmp)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('USERPASSWORD=b', p.read_text())
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o640)
        if os.geteuid() == 0:
            self.assertEqual(os.stat(p).st_gid, GID)

    def test_the_writers_call_it_before_the_rename(self):
        cf = text('scripts/common_functions.sh')
        ap = cf[cf.index('all_password()'):cf.index('# Input arg - file with PID')]
        self.assertLess(ap.index('secret_file_attrs /mnt/config/user.pwd.$$.tmp'), ap.index('mv -f /mnt/config/user.pwd.$$.tmp'))
        rc = cf[cf.index('rewrite_config(){'):cf.index('install_config()')]
        self.assertLess(rc.index('secret_file_attrs "$_rc_tmp"'), rc.index('mv "$_rc_tmp" "$cfg_path"'))
        ct = text('scripts/config-transaction.sh')
        cm = ct[ct.index('tc_commit_config_files()'):]
        self.assertLess(cm.index('secret_file_attrs "${_tc_dest}.tc100-new.$$"'), cm.index('mv -f "${_tc_dest}.tc100-new.$$"'))

    @unittest.skipUnless(HAVE_CC, 'needs a C compiler')
    def test_rwconf_keeps_owner_group_and_mode(self):
        exe = self.tmp / 'rwconf'
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-o', str(exe), str(ROOT / 'src/rwconf/rwconf.c')], check=True)
        p = self.mk('rtspserver.conf', 0o640, '[0]\nfps=15\n')
        root = root_prefix()
        if os.geteuid() == 0:
            os.chown(p, 0, GID)
        elif root is None:
            self.skipTest('the group of another user needs root')
        else:
            subprocess.run(root + ['chown', '0:%d' % GID, str(p)], check=True)
        r = subprocess.run((root or []) + [str(exe), str(p), 'w', '0', 'fps', '20'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('fps=20', p.read_text())
        st = os.stat(p)
        self.assertEqual((st.st_uid, st.st_gid, st.st_mode & 0o777), (0, GID, 0o640))

    def test_rwconf_source_asks_for_the_owner_and_checks_it(self):
        s = text('src/rwconf/rwconf.c')
        save = s[s.index('static void save('):]
        self.assertLess(save.index('fchown(fileno(f), st.st_uid, st.st_gid)'), save.index('rename(tmp, path)'))
        self.assertIn('file unchanged', save[save.index('fchown('):save.index('fchmod(')])



@unittest.skipUnless(POSIX, 'needs a POSIX shell and /proc')
class StartScripts(unittest.TestCase):
    """controlscripts/mdns and /whep started with stubs (as the existing tests do): the daemon is called with -D uid:gid
    when PRIVDROP is on or absent and without it when it is 0."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='privstart-'))
        (self.tmp / 'config').mkdir()
        self.argv = self.tmp / 'argv'
        daemon = self.tmp / 'daemon'
        daemon.write_text('#!/bin/sh\necho "$@" > %s\nsleep 20 &\nwait\n' % self.argv)
        os.chmod(daemon, 0o755)
        # a daemon name that the scripts' status() recognise in /proc/PID/cmdline
        self.mdnsd = self.tmp / 'tc100-mdnsd'
        self.whepd = self.tmp / 'tc100-whep'
        for n in (self.mdnsd, self.whepd):
            shutil.copy(daemon, n)
        self.stub = ('. %s\nnetacl_allow_list() { echo 127.0.0.0/8; }\n' % (ROOT / 'scripts' / 'secret-modes.sh'))

    def tearDown(self):
        for n in ('mdns.pid', 'whep.pid'):
            try:
                os.kill(int((self.tmp / n).read_text()), 9)
            except (OSError, ValueError):
                pass
        for pid in pids_matching(str(self.tmp)):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def kill_all(self, binary):
        for pid in pids_matching(str(binary)):
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def run_script(self, name, boot):
        (self.tmp / 'config' / 'boot.conf').write_text(boot)
        src = text('controlscripts/' + name)
        src = src.replace('. /mnt/scripts/common_functions.sh', self.stub)
        src = src.replace('/mnt/config', str(self.tmp / 'config'))
        src = src.replace('/var/run/', str(self.tmp) + '/').replace('/tmp/logs', str(self.tmp / 'logs'))
        src = src.replace('BIN=/mnt/tc100test/tc100-mdnsd', 'BIN=%s' % self.mdnsd)
        src = src.replace('BIN=/mnt/ext/bin/tc100-whep', 'BIN=%s' % self.whepd).replace('/tmp/whep-start.lock', str(self.tmp / 'lock'))
        src = src.replace('sleep 2\t', 'sleep 1\t')
        ctl = self.tmp / name
        ctl.write_text(src)
        if self.argv.exists():
            self.argv.unlink()
        env = dict(os.environ, TC100_CONFIG_DIR=str(self.tmp / 'config'))
        r = subprocess.run(SH + [str(ctl), 'start'], env=env, capture_output=True, text=True, timeout=60)
        for _ in range(30):
            if self.argv.exists() and self.argv.read_text().strip():
                break
            time.sleep(0.1)
        self.assertTrue(self.argv.exists(), r.stdout + r.stderr)
        return self.argv.read_text().split()

    def test_mdns_on_and_off(self):
        for boot, want in (('', True), ('PRIVDROP=1\n', True), ('PRIVDROP=0\n', False)):
            with self.subTest(boot=boot):
                a = self.run_script('mdns', boot)
                self.assertEqual('-D' in a, want, a)
                if want:
                    self.assertEqual(a[a.index('-D') + 1], '%d:%d' % (NET, NET), 'mdns has its own user, no secret group')
                self.assertEqual(a[:2], ['-i', 'wlan0'])
                subprocess.run(SH + [str(self.tmp / 'mdns'), 'stop'], capture_output=True, env=dict(os.environ))
                self.kill_all(self.mdnsd)
                time.sleep(0.3)

    def test_whep_on_and_off(self):
        for boot, want in (('', True), ('PRIVDROP=0\n', False)):
            with self.subTest(boot=boot):
                a = self.run_script('whep', boot)
                self.assertEqual('-D' in a, want, a)
                if want:
                    self.assertEqual(a[a.index('-D') + 1], '%d:%d' % (UID, GID))
                self.assertIn('-I', a)
                self.assertEqual(a[a.index('-w') + 1], str(self.tmp / 'config' / 'user.pwd'))
                self.kill_all(self.whepd)
                (self.tmp / 'whep.pid').unlink(missing_ok=True)
                time.sleep(0.3)


class TheImage(unittest.TestCase):
    def test_users_table_and_defconfig(self):
        cfg = text('v3/buildroot/configs/tc100_defconfig')
        self.assertIn('BR2_ROOTFS_USERS_TABLES="$(BR2_EXTERNAL_TC100_PATH)/board/tc100/users.table"', cfg)
        table = [x for x in text('v3/buildroot/board/tc100/users.table').splitlines() if x.strip() and not x.startswith('#')]
        self.assertEqual(len(table), 2)
        for line, (name, n) in zip(table, (('tc100svc', '1001'), ('tc100net', '1002'))):
            f = line.split()
            self.assertEqual(f[:5], [name, n, name, n, '*'])
            self.assertEqual(f[5:7], ['-', '/bin/false'], 'no home, no shell')

    def test_post_build_still_locks_root_only(self):
        pb = text('v3/buildroot/board/tc100/post-build.sh')
        self.assertIn("sed -i 's|^root:[^:]*:|root:*:|'", pb)


# ---- real processes on the build host -------------------------------------------------------------------------------

def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def pids_matching(sub):
    """pids whose command line contains sub (no pgrep needed), not this process"""
    found = []
    for d in Path('/proc').iterdir():
        if d.name.isdigit() and int(d.name) != os.getpid():
            try:
                if sub in d.joinpath('cmdline').read_bytes().replace(bytes([0]), b' ').decode(errors='replace'):
                    found.append(int(d.name))
            except OSError:
                pass
    return found


def uid_of(pid):
    for line in Path('/proc/%d/status' % pid).read_text().splitlines():
        if line.startswith('Uid:'):
            return [int(x) for x in line.split()[1:]]
    raise AssertionError('no Uid line')


def gid_groups_of(pid):
    out = {}
    for line in Path('/proc/%d/status' % pid).read_text().splitlines():
        if line.startswith('Gid:'):
            out['gid'] = [int(x) for x in line.split()[1:]]
        if line.startswith('Groups:'):
            out['groups'] = line.split()[1:]
    return out


@unittest.skipUnless(HAVE_CC and POSIX, 'needs a C compiler and Linux')
class RealProcesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='privreal-'))
        os.chmod(cls.tmp, 0o755)
        cls.onvifd = cls.tmp / 'onvifd'
        cls.logfwd = cls.tmp / 'logfwd'
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-std=gnu11', '-o', str(cls.onvifd),
                        str(ROOT / 'src/onvifd/onvifd.c')], check=True)
        subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror', '-std=gnu11', '-D_GNU_SOURCE', '-o', str(cls.logfwd),
                        str(ROOT / 'src/logfwd/tc100-logfwd.c')], check=True)
        cls.root = root_prefix()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.procs = []
        self.work = Path(tempfile.mkdtemp(dir=self.tmp))
        os.chmod(self.work, 0o755)

    def tearDown(self):
        for p in self.procs:
            subprocess.run((self.root or []) + ['kill', '-9', str(p.pid)], capture_output=True)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass

    def onvif_cmd(self, extra, rtsp=True):
        self.port = free_port()
        self.dport = free_port(socket.SOCK_DGRAM)
        env = dict(os.environ, ONVIFD_CONF_DIR=str(self.work), ONVIFD_VERSION_FILE=str(self.work / 'VERSION'),
                   ONVIFD_SERIAL_FILE=str(self.work / 'none'), ONVIFD_SCALE_PARAM=str(self.work / 'main_scale'),
                   ONVIFD_MAC_FILE=str(self.work / 'mac'), ONVIFD_IFACE='lo0', ONVIFD_DISCOVERY_PORT=str(self.dport),
                   ONVIFD_MOTION_FILE=str(self.work / 'rec_control'))
        env.pop('TC100_NET_ALLOW', None)
        cmd = [str(self.onvifd), '-p', str(self.port), '-w', '80', '-wp', 'http'] + (['-r', '554'] if rtsp else []) + [
               '-hwn', 'AK3918', '-vnn', 'Anyka', '-loc', 'Earth', '-dn', 'Teckin', '-mod', 'TC100'] + extra
        return cmd, env

    def write_conf(self, mode=0o644, pw='hunter2\n'):
        (self.work / 'rtspserver.conf').write_text('PORT=8554\nUSERNAME=root\n[0]\nbps=1600\ncodec=0\nfps=20\n[1]\nbps=300\ncodec=2\nfps=10\n')
        (self.work / 'boot.conf').write_text('RTSP_SUBSTREAM=1\n')
        (self.work / 'mac').write_text('02:11:22:33:44:55\n')
        (self.work / 'user.pwd').write_text(pw)
        os.chmod(self.work / 'user.pwd', mode)
        for n in ('rtspserver.conf', 'boot.conf', 'mac'):
            os.chmod(self.work / n, 0o644)

    def soap_status(self, svc, body):
        env = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
               'xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><s:Body>%s</s:Body></s:Envelope>' % body).encode()
        req = ('POST /onvif/%s HTTP/1.1\r\nHost: x\r\nContent-Type: application/soap+xml\r\nContent-Length: %d\r\n\r\n'
               % (svc, len(env))).encode() + env
        s = socket.create_connection(('127.0.0.1', self.port), timeout=15)
        try:
            s.sendall(req)
            data = b''
            while True:
                d = s.recv(65536)
                if not d:
                    break
                data += d
        finally:
            s.close()
        self.last_body = data.decode(errors='replace')
        return int(data.split()[1])

    def wait_port(self):
        for _ in range(60):
            try:
                socket.create_connection(('127.0.0.1', self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.1)
        self.fail('did not start')

    # -- failures: every identity, run by anybody

    def test_onvifd_refuses_bad_specifications(self):
        self.write_conf()
        for spec in ('0:0', '1001:0', '0:1001', 'abc', '1001', '1001:', ':1001', '1001:1001x', '70000:1001', '1001:70000', '-1:5',
                     '1001:1001:5', '1234567:1001'):
            cmd, env = self.onvif_cmd(['-D', spec])
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 1, spec)
            self.assertIn('cannot drop root', r.stderr, spec)
            self.assertNotIn('ONVIF on port', r.stderr, 'nothing runs after a failed drop: ' + spec)

    def test_onvifd_stops_when_setuid_fails(self):
        if os.geteuid() == 0:
            self.skipTest('root can change identity: see test_onvifd_runs_as_the_other_user')
        self.write_conf()
        cmd, env = self.onvif_cmd(['-D', '65000:65000'])
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 1)
        self.assertIn('cannot drop root', r.stderr)

    def test_onvifd_without_the_option_keeps_its_identity(self):
        self.write_conf()
        cmd, env = self.onvif_cmd([])
        p = subprocess.Popen(cmd, env=env, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.wait_port()
        self.assertEqual(uid_of(p.pid), [os.getuid()] * 4)

    def test_logfwd_refuses_bad_specifications_and_a_failing_setuid(self):
        log = self.work / 'messages'
        log.write_text('x\n')
        base = [str(self.logfwd), '-r', '127.0.0.1:9', '-f', str(log)]
        for spec in ('0:0', 'abc', '1001', '1001:', '1001:0'):
            r = subprocess.run(base + ['-D', spec], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 1, spec)
            self.assertIn('cannot drop root', r.stderr, spec)
        if os.geteuid() != 0:
            r = subprocess.run(base + ['-D', '65000:65000'], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 1)
            self.assertIn('cannot drop root', r.stderr)

    # -- the drop itself: as root (or sudo -n)

    def need_root(self):
        if self.root is None:
            self.skipTest('needs root or passwordless sudo (tests/docker/local-ci.sh runs this module as root)')

    def test_onvifd_runs_as_the_other_user_after_the_bind(self):
        self.need_root()
        self.write_conf()
        cmd, env = self.onvif_cmd(['-D', '65000:65001'])
        p = subprocess.Popen(self.root + ['env'] + ['%s=%s' % kv for kv in env.items() if kv[0].startswith('ONVIFD_')] + cmd,
                             stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.wait_port()
        pid = self.child_pid(p, 'onvifd')
        self.assertEqual(uid_of(pid), [65000] * 4)
        g = gid_groups_of(pid)
        self.assertEqual(g['gid'], [65001] * 4)
        self.assertEqual(g['groups'], [], 'no supplementary group (setgroups(0))')
        # it still serves: the call that needs no credentials answers 200
        self.assertEqual(self.soap_status('device_service', '<tds:GetSystemDateAndTime/>'), 200)
        # the UDP socket (WS-Discovery) bound before the drop is still open
        self.assertTrue(any(':%04X ' % self.dport in l for l in Path('/proc/net/udp').read_text().splitlines()[1:]))

    def child_pid(self, p, name):
        # sudo forks the daemon: find the process by its command line (env or the shell exec it: the same pid)
        for _ in range(50):
            pids = pids_matching('%s -p %d' % (getattr(self, name), self.port))
            pids = [x for x in pids if Path('/proc/%d/comm' % x).read_text().strip() == Path(getattr(self, name)).name[:15]]
            if pids:
                return pids[-1]
            time.sleep(0.1)
        self.fail('daemon not found')

    def test_onvifd_unreadable_password_file_never_means_open(self):
        """after the drop the daemon can no longer read a user.pwd at mode 600 of root: the password it read as root stays
        in force (HTTP 400 NotAuthorized), and the reload does not clear it"""
        self.need_root()
        self.write_conf(mode=0o600)
        os.chown(self.work / 'user.pwd', 0, 0) if os.geteuid() == 0 else None
        cmd, env = self.onvif_cmd(['-D', '65000:65001'])
        p = subprocess.Popen(self.root + ['env'] + ['%s=%s' % kv for kv in env.items() if kv[0].startswith('ONVIFD_')] + cmd,
                             stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.wait_port()
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 400, 'password set: refused without credentials')
        # make the daemon reload its files (mtime change; the 2 s poll), as the web UI does after a password change
        time.sleep(0.5)
        future = time.time() + 5
        os.utime(self.work / 'user.pwd', (future, future))
        time.sleep(3.5)
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 400, 'still refused: never open')

    def test_onvifd_reads_a_group_readable_password_after_the_drop(self):
        """user.pwd 640 with the service group: the dropped daemon follows a password change"""
        self.need_root()
        if os.geteuid() != 0:
            self.skipTest('chown to another group needs root')
        self.write_conf(mode=0o640)
        os.chown(self.work / 'user.pwd', 0, 65001)
        cmd, env = self.onvif_cmd(['-D', '65000:65001'])
        p = subprocess.Popen(['env'] + ['%s=%s' % kv for kv in env.items() if kv[0].startswith('ONVIFD_')] + cmd, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.wait_port()
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 400)
        # the password is removed (an empty file: open): the dropped daemon reads it and opens, 2 s poll
        (self.work / 'user.pwd').write_text('')
        future = time.time() + 5
        os.utime(self.work / 'user.pwd', (future, future))
        for _ in range(60):
            if self.soap_status('media_service', '<trt:GetProfiles/>') == 200:
                break
            time.sleep(0.2)
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 200)

    def start_dropped(self, root_cmd=True, rtsp=False):
        cmd, env = self.onvif_cmd(['-D', '65000:65001'], rtsp=rtsp)
        p = subprocess.Popen((self.root if root_cmd else []) + ['env'] + ['%s=%s' % kv for kv in env.items() if kv[0].startswith('ONVIFD_')] + cmd,
                             stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.wait_port()
        return p

    def stream_uri(self):
        self.soap_status('media_service', '<trt:GetStreamUri><trt:StreamSetup><tt:Stream xmlns:tt="http://www.onvif.org/ver10/schema">RTP-Unicast</tt:Stream>'
                         '<tt:Transport xmlns:tt="http://www.onvif.org/ver10/schema"><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>'
                         '<trt:ProfileToken>profile_1</trt:ProfileToken></trt:GetStreamUri>')
        m = re.search(r'rtsp://[^<]+', self.last_body)
        return m.group(0) if m else ''

    def test_onvifd_keeps_the_last_good_rtsp_settings_when_the_file_becomes_unreadable(self):
        """the file replaced by a root 600 one (a writer that did not keep the group): port, streams and user stay, not defaults"""
        self.need_root()
        if os.geteuid() != 0:
            self.skipTest('replacing the file as another owner needs root')
        self.write_conf(mode=0o640, pw='')
        os.chown(self.work / 'user.pwd', 0, 65001)
        (self.work / 'rtspserver.conf').write_text('PORT=8554\nUSERNAME=root\n[0]\nbps=1600\ncodec=0\nfps=20\n[1]\nbps=300\ncodec=2\nfps=10\n')
        os.chmod(self.work / 'rtspserver.conf', 0o640)
        os.chown(self.work / 'rtspserver.conf', 0, 65001)
        self.start_dropped()
        self.assertIn(':8554/', self.stream_uri())
        new = self.work / 'rtspserver.conf.new'
        new.write_text('PORT=9999\nUSERNAME=root\n')
        os.chmod(new, 0o600)                                   # root:root 600: unreadable for the dropped daemon
        os.rename(new, self.work / 'rtspserver.conf')
        time.sleep(3.5)                                        # more than one 2 s poll
        self.assertIn(':8554/', self.stream_uri(), 'still the settings read before: not the default 554, not the new 9999')
        os.chmod(self.work / 'rtspserver.conf', 0o640)         # the group comes: the next poll reads it (ctime is in the signature)
        os.chown(self.work / 'rtspserver.conf', 0, 65001)
        for _ in range(40):
            if ':9999/' in self.stream_uri():
                break
            time.sleep(0.25)
        self.assertIn(':9999/', self.stream_uri())

    def test_onvifd_new_password_that_arrives_unreadable_is_read_once_it_is_readable(self):
        """open at first (empty file); the first password arrives by rename as root 600 and gets its group afterwards: the
        daemon must not record "open" for that file for good (chgrp and chmod change only the ctime)"""
        self.need_root()
        if os.geteuid() != 0:
            self.skipTest('replacing the file as another owner needs root')
        self.write_conf(mode=0o640, pw='')
        os.chown(self.work / 'user.pwd', 0, 65001)
        self.start_dropped()
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 200, 'no password yet: open')
        new = self.work / 'user.pwd.new'
        new.write_text('s3cret\n')
        os.chmod(new, 0o600)
        os.rename(new, self.work / 'user.pwd')
        time.sleep(3.5)                                        # polls that cannot read it: no verdict, tried again
        os.chmod(self.work / 'user.pwd', 0o640)
        os.chown(self.work / 'user.pwd', 0, 65001)
        for _ in range(40):
            if self.soap_status('media_service', '<trt:GetProfiles/>') == 400:
                break
            time.sleep(0.25)
        self.assertEqual(self.soap_status('media_service', '<trt:GetProfiles/>'), 400, 'the password is now in force')

    def test_onvifd_source_never_derives_open_from_a_read_error(self):
        s = text('src/onvifd/onvifd.c')
        lc = s[s.index('static void load_config(void)'):]
        self.assertIn('rd_err && rd_err != ENOENT', lc)
        self.assertIn('ct != cfg_sig[i].ct || ctn != cfg_sig[i].ctn || (retry && cfg_sig[i].retry)', s)
        self.assertIn('if (cfg_poll(1, 0)) load_config();', s, 'a request only looks at the signature')
        self.assertIn('if (cfg_poll(NCFG, 1)) load_config();', s, 'the poll of the loop retries unreadable files')
        self.assertNotIn('cfg_sig[0].retry = 1;		/* emptied', s)
        self.assertIn('rtsp_good', s)

    def test_logfwd_forwards_after_the_drop(self):
        self.need_root()
        log = self.work / 'messages'
        log.write_text('')
        os.chmod(log, 0o644)
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(('127.0.0.1', 0))
        rx.settimeout(10)
        port = rx.getsockname()[1]
        p = subprocess.Popen(self.root + [str(self.logfwd), '-r', '127.0.0.1:%d' % port, '-f', str(log), '-D', '65000:65001'],
                             stderr=subprocess.DEVNULL)
        self.procs.append(p)
        pid = None
        for _ in range(50):
            out = [x for x in pids_matching('%s -r 127.0.0.1:%d' % (self.logfwd, port))
                   if Path('/proc/%d/comm' % x).read_text().strip() == 'logfwd']
            if out:
                pid = out[-1]
                break
            time.sleep(0.1)
        self.assertIsNotNone(pid)
        for _ in range(50):
            if uid_of(pid) == [65000] * 4:
                break
            time.sleep(0.1)
        self.assertEqual(uid_of(pid), [65000] * 4)
        time.sleep(0.5)
        with open(log, 'a') as f:
            f.write('Nov 27 10:00:00 tc100 daemon.err test: after the drop\n')
        data, _ = rx.recvfrom(2048)
        self.assertIn(b'after the drop', data)
        rx.close()


if __name__ == '__main__':
    unittest.main()
