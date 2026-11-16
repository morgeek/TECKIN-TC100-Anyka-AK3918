"""[recovery] AUDIT-1116-RECOVERY: the rescue mode of the initramfs (v3/initrd-rescue, S39tc100 step 1a) when the user
space of the flash ("stack") is damaged or gives no access: detection without a full read, settings slots read-only,
telnet for the private networks only, the watcher, the switch INITRD_RESCUE, and nothing that writes the flash."""
import gzip
import hashlib
import io
import os
import re
import shutil
import socket
import struct
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
RESCUE = ROOT / 'v3/initrd-rescue'
STACK_SIZE = 0x2b3000


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def sqfs(used=200000, total=None, fill=b'\x5a'):
    """a file that looks like a squashfs: magic, bytes_used at offset 40, then data up to bytes_used and 0xff after"""
    head = b'hsqs' + b'\0' * 36 + struct.pack('<Q', used) + b'\0' * 48
    body = head + fill * (used - len(head))
    return body + b'\xff' * ((total or used) - used)


def slot(seq, files, damage=False):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as t:
        for name, data in files.items():
            i = tarfile.TarInfo('config/' + name)
            i.size = len(data)
            t.addfile(i, io.BytesIO(data))
    tgz = gzip.compress(buf.getvalue())
    md5 = hashlib.md5(tgz).hexdigest()
    if damage:
        tgz = tgz[:20] + bytes([tgz[20] ^ 0xff]) + tgz[21:]
    raw = b'TC1CFG %d %d %s\n' % (seq, len(tgz), md5.encode()) + tgz
    return raw + b'\xff' * (36864 - len(raw))


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)	# setUp is also called inside loops
        for n in ('sys', 'dev', 'bin', 'run'):
            (self.d / n).mkdir()
        self.parts = {}
        self.env = dict(os.environ, RS_SYS=self.p('sys'), RS_DEV=self.p('dev'), RS_TCP=self.p('tcp'),
                        RS_CONSOLE=self.p('console'), RS_FLAG=self.p('rescue-mode'), RS_PIDFILE=self.p('run/telnet.pid'),
                        RS_MOTD=self.p('motd'), RS_WAIT='0', RS_STEP='0', RS_PROCS='',
                        PATH=self.p('bin') + os.pathsep + os.environ['PATH'])
        (self.d / 'tcp').write_text('  sl  local_address rem_address   st tx_queue\n')
        # tcpsvd stand-in: records its arguments, stays alive a moment like a server
        self.stub('tcpsvd', 'echo "$@" > %s\nsleep 2\n' % self.p('tcpsvd.args'))

    def p(self, n):
        return (self.d / n).as_posix()

    def stub(self, name, body):
        f = self.d / 'bin' / name
        f.write_bytes(('#!/bin/sh\n' + body).encode())
        f.chmod(0o755)

    def part(self, name, data, size=None):
        n = len(self.parts)
        self.parts[name] = n
        (self.d / 'sys' / ('mtd%d' % n)).mkdir()
        (self.d / 'sys' / ('mtd%dro' % n)).mkdir()
        (self.d / 'sys' / ('mtd%d' % n) / 'name').write_text(name + '\n')
        (self.d / 'sys' / ('mtd%d' % n) / 'size').write_text('%d\n' % (size or len(data)))
        (self.d / 'dev' / ('mtd%dro' % n)).write_bytes(data)

    def run_rs(self, *args, env=None):
        e = dict(self.env)
        e.update(env or {})
        return subprocess.run(SHELL + [RESCUE.as_posix()] + list(args), capture_output=True, text=True, env=e, timeout=60)

    def listen(self, port):
        with open(self.d / 'tcp', 'a') as f:
            f.write('   0: 00000000:%04X 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1\n' % port)


class StackCheck(Base):
    def test_good_image(self):
        self.part('stack', sqfs(200000, STACK_SIZE))
        r = self.run_rs('check', 'stack')
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def test_image_that_fills_the_partition_and_small_images(self):
        self.part('stack', sqfs(STACK_SIZE))
        self.assertEqual(self.run_rs('check', 'stack').returncode, 0)
        for used in (96, 100, 4096, 4097, 8192, 8193):
            f = self.d / ('img%d' % used)
            f.write_bytes(sqfs(used, 16384))
            self.assertEqual(self.run_rs('imgcheck', f.as_posix(), '16384').returncode, 0, used)

    def test_erased_partition(self):
        self.part('stack', b'\xff' * STACK_SIZE)
        r = self.run_rs('check', 'stack')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no squashfs', r.stdout)

    def test_write_cut_before_the_end(self):
        """flashcp erases everything, then writes from the start: a power cut leaves the end erased"""
        good = sqfs(1500000, STACK_SIZE)
        for cut in (4096, 700000, 1500000 - 64):
            self.setUp()
            self.part('stack', good[:cut] + b'\xff' * (STACK_SIZE - cut))
            r = self.run_rs('check', 'stack')
            self.assertEqual(r.returncode, 1, cut)
            self.assertIn('stops before its end', r.stdout)

    def test_size_larger_than_the_partition_or_absurd(self):
        self.part('stack', sqfs(200000), size=100000)
        self.assertEqual(self.run_rs('check', 'stack').returncode, 1)
        f = self.d / 'img'
        f.write_bytes(b'hsqs' + b'\0' * 36 + struct.pack('<Q', 1 << 40) + b'\0' * 4000)
        self.assertEqual(self.run_rs('imgcheck', f.as_posix(), str(STACK_SIZE)).returncode, 1)
        f.write_bytes(b'hsqs' + b'\0' * 36 + struct.pack('<Q', 0) + b'\0' * 4000)
        self.assertEqual(self.run_rs('imgcheck', f.as_posix(), str(STACK_SIZE)).returncode, 1)

    def test_no_partition(self):
        r = self.run_rs('check', 'stack')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no stack partition', r.stdout)

    def test_files_of_the_start(self):
        need = ['v3/linux66-sd/flashmode-prep.sh', 'v3/linux66-sd/cfg-persist', 'v3/autorun-linux66.sh', 'scripts/common_functions.sh']
        for n in need:
            (self.d / 'rom' / n).parent.mkdir(parents=True, exist_ok=True)
            (self.d / 'rom' / n).write_text('x\n')
            self.assertTrue((ROOT / n).is_file(), n)	# the names are those of the repository
        self.assertEqual(self.run_rs('files', self.p('rom')).returncode, 0)
        (self.d / 'rom' / need[2]).write_text('')
        r = self.run_rs('files', self.p('rom'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('autorun-linux66.sh', r.stdout)


class Settings(Base):
    FILES = {'wpa_supplicant.conf': b'network={\n ssid="home"\n}\n', 'user.pwd': b'secret1\n', 'boot.conf': b'INITRD_RESCUE=0\n'}

    def test_newest_valid_slot_is_restored_read_only(self):
        self.part('cfga', slot(7, {'user.pwd': b'old\n'}))
        self.part('cfgb', slot(8, self.FILES))
        before = {f.name: f.read_bytes() for f in (self.d / 'dev').iterdir()}
        r = self.run_rs('settings', self.p('out'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.d / 'out/config/user.pwd').read_bytes(), b'secret1\n')
        self.assertIn(b'ssid="home"', (self.d / 'out/config/wpa_supplicant.conf').read_bytes())
        self.assertEqual({f.name: f.read_bytes() for f in (self.d / 'dev').iterdir()}, before)
        if os.name == 'posix':
            self.assertEqual((self.d / 'out').stat().st_mode & 0o077, 0)	# it holds the Wi-Fi key and the password

    def test_damaged_newest_slot_falls_back_to_the_other(self):
        self.part('cfga', slot(7, {'user.pwd': b'old\n'}))
        self.part('cfgb', slot(8, self.FILES, damage=True))
        self.assertEqual(self.run_rs('settings', self.p('out')).returncode, 0)
        self.assertEqual((self.d / 'out/config/user.pwd').read_bytes(), b'old\n')

    def test_no_valid_slot(self):
        self.part('cfga', b'\xff' * 36864)
        self.part('cfgb', b'TC1CFG x y z\n' + b'\xff' * 100)
        self.assertEqual(self.run_rs('settings', self.p('out')).returncode, 1)
        self.assertFalse((self.d / 'out/config').exists())

    def test_same_slot_format_as_cfg_persist(self):
        cp = text('v3/linux66-sd/cfg-persist')
        self.assertIn("printf 'TC1CFG %s %s %s\\n' $new $sz $md", cp)
        self.assertIn('for s in cfga cfgb', cp)
        self.assertIn('TC1CFG', text('v3/initrd-rescue'))

    def test_switch(self):
        c = self.d / 'boot.conf'
        for v, rc in (('INITRD_RESCUE=0\n', 1), ('INITRD_RESCUE="0"\n', 1), ('INITRD_RESCUE=off\n', 1), ('INITRD_RESCUE=1\n', 0),
                      ('#INITRD_RESCUE=0\n', 0), ('OTHER=0\n', 0), ('INITRD_RESCUE=0\nINITRD_RESCUE=1\n', 0)):
            c.write_text(v)
            self.assertEqual(self.run_rs('enabled', c.as_posix()).returncode, rc, v)
        self.assertEqual(self.run_rs('enabled', self.p('missing')).returncode, 0)	# no settings: on
        self.assertIn('\nINITRD_RESCUE=1\n', text('config/boot.conf.dist'))


class Telnet(Base):
    def test_start_opens_the_filtered_telnet_and_marks_the_mode(self):
        r = self.run_rs('start', 'the stack partition does not mount')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('does not mount', (self.d / 'rescue-mode').read_text())
        for _ in range(20):
            if (self.d / 'tcpsvd.args').exists():
                break
            time.sleep(0.1)
        a = (self.d / 'tcpsvd.args').read_text().split()
        self.assertEqual(a[:4], ['-c', '4', '0', '23'])
        self.assertEqual(a[-1], 'gate')		# every connection goes through the address check
        self.assertTrue(a[-2].endswith('initrd-rescue'))
        self.assertTrue(a[-2].startswith('/') or a[-2][1:3] == ':/')	# absolute: tcpsvd runs it from anywhere
        self.assertTrue((self.d / 'run/telnet.pid').read_text().strip().isdigit())
        self.assertIn('RESCUE MODE', (self.d / 'console').read_text())
        self.assertIn('rescue help', (self.d / 'motd').read_text())

    def test_start_leaves_a_telnet_that_already_listens(self):
        self.listen(23)
        self.assertEqual(self.run_rs('start', 'x').returncode, 0)
        time.sleep(0.3)
        self.assertFalse((self.d / 'tcpsvd.args').exists())

    def test_gate_lets_private_addresses_only(self):
        ok = ['192.168.1.20', '10.0.0.7', '172.16.0.1', '172.31.255.254', '169.254.3.4', '127.0.0.1', '100.64.0.1', '100.127.9.9', '10.42.0.12']
        no = ['8.8.8.8', '172.15.0.1', '172.32.0.1', '192.169.1.1', '100.63.0.1', '100.128.0.1', '11.0.0.1', '', '10.0.0.1;id', '::1', '1.10.0.1']
        for ip in ok + no:
            r = self.run_rs('gate', env={'TCPREMOTEADDR': ip + ':40123', 'RS_TELNETD': 'echo LOGIN'})
            self.assertEqual(r.stdout.strip(), 'LOGIN' if ip in ok else '', ip)
        for e in ({}, {'TCPREMOTEADDR': ''}, {'TCPREMOTEADDR': ':40123'}, {'TCPREMOTEIP': '10.0.0.1'}):
            env = {k: v for k, v in dict(self.env, RS_TELNETD='echo LOGIN').items() if not k.startswith('TCPREMOTE')}
            env.update(e)
            r = subprocess.run(SHELL + [RESCUE.as_posix(), 'gate'], capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout, '', e)	# no address from tcpsvd: closed

    def test_same_private_networks_as_the_user_space_filter(self):
        m = re.search(r'^NETACL_PRIVATE="([^"]+)"', text('scripts/common_functions.sh'), re.M)
        self.assertEqual(m.group(1).split(), ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10'])

    @unittest.skipUnless(shutil.which('busybox'), 'needs busybox (tcpsvd)')
    def test_real_tcpsvd_runs_the_gate(self):
        if 'tcpsvd' not in subprocess.run(['busybox', '--list'], capture_output=True, text=True).stdout.split():
            self.skipTest('this busybox has no tcpsvd')
        (self.d / 'bin/tcpsvd').unlink()
        self.stub('tcpsvd', 'exec busybox tcpsvd "$@"\n')
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        env = {'RS_PORT': str(port), 'RS_TELNETD': 'echo LOGIN-FROM-GATE'}
        self.assertEqual(self.run_rs('start', 'test', env=env).returncode, 0)
        pid = None
        try:
            got = b''
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=2) as c:
                        c.settimeout(5)
                        got = c.recv(100)
                    break
                except OSError:
                    time.sleep(0.1)
            self.assertIn(b'LOGIN-FROM-GATE', got)
        finally:
            pid = (self.d / 'run/telnet.pid').read_text().strip()
            subprocess.run(['kill', pid], capture_output=True)


class Watch(Base):
    def test_access_up_means_nothing_to_do(self):
        for port in (80, 22, 23):
            self.setUp()
            self.listen(port)
            self.assertEqual(self.run_rs('watch', self.p('boot.conf')).returncode, 0)
            self.assertFalse((self.d / 'rescue-mode').exists(), port)

    def test_a_running_ssh_server_counts(self):
        self.stub('pidof', '[ "$1" = dropbear ] && echo 123\n')
        env = dict(self.env)
        del env['RS_PROCS']
        # plain sh: busybox ash runs its own pidof applet, not the stand-in
        r = subprocess.run(['sh', RESCUE.as_posix(), 'watch', self.p('boot.conf')], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.d / 'rescue-mode').exists())

    def test_no_access_after_the_wait_opens_the_rescue_telnet(self):
        self.listen(554)	# the video server alone is not a way in
        r = self.run_rs('watch', self.p('boot.conf'), env={'RS_WAIT': '2', 'RS_STEP': '1'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('no web interface, ssh or telnet 2 s after', (self.d / 'rescue-mode').read_text())
        for _ in range(20):
            if (self.d / 'tcpsvd.args').exists():
                break
            time.sleep(0.1)
        self.assertTrue((self.d / 'tcpsvd.args').exists())

    def test_access_that_comes_up_during_the_wait(self):
        e = dict(self.env, RS_WAIT='6', RS_STEP='1')
        pr = subprocess.Popen(SHELL + [RESCUE.as_posix(), 'watch', self.p('boot.conf')], env=e)
        time.sleep(1.5)
        self.listen(80)
        self.assertEqual(pr.wait(timeout=20), 0)
        self.assertFalse((self.d / 'rescue-mode').exists())

    def test_switch_off(self):
        (self.d / 'boot.conf').write_text('INITRD_RESCUE=0\n')
        self.assertEqual(self.run_rs('watch', self.p('boot.conf')).returncode, 0)
        self.assertFalse((self.d / 'rescue-mode').exists())

    def test_same_pid_file_as_web_guard(self):
        """web-guard.sh closes "its" rescue telnet once the web interface is back: the watcher's telnet is that one"""
        self.assertIn('/var/run/rescue-telnetd.pid', text('scripts/web-guard.sh'))
        self.assertIn('PIDF=${RS_PIDFILE:-/var/run/rescue-telnetd.pid}', text('v3/initrd-rescue'))


class WifiTurn(Base):
    def test_next_settings_file_when_the_first_gives_no_link(self):
        a, b, c = self.d / 'a.conf', self.d / 'b.conf', self.d / 'none.conf'
        a.write_text('network={\n ssid="old"\n}\n')
        b.write_text('network={\n ssid="card"\n}\n')
        for n in ('killall', 'wpa_supplicant', 'udhcpc', 'pidof'):
            self.stub(n, 'echo "%s $@" >> %s\n' % (n, self.p('calls')))
        (self.d / 'net').mkdir()
        (self.d / 'net/operstate').write_text('dormant\n')
        env = {'RS_NET': self.p('net'), 'RS_WPA_CONF': self.p('wpa.conf'), 'RS_WIFI_TRY': '0', 'RS_WIFI_ONCE': '1'}
        # plain sh: busybox ash would run its own killall / pidof applets, not the stand-ins
        r = subprocess.run(['sh', RESCUE.as_posix(), 'wifi', a.as_posix(), c.as_posix(), b.as_posix()], capture_output=True,
                           text=True, env=dict(self.env, **env), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('ssid="card"', (self.d / 'wpa.conf').read_text())
        calls = (self.d / 'calls').read_text()
        self.assertIn('killall wpa_supplicant', calls)
        self.assertIn('wpa_supplicant -B -i wlan0 -c ' + self.p('wpa.conf'), calls)

    def test_one_settings_file_is_left_alone(self):
        a = self.d / 'a.conf'
        a.write_text('network={\n ssid="old"\n}\n')
        self.stub('killall', 'echo killall >> %s\n' % self.p('calls'))
        self.assertEqual(self.run_rs('wifi', a.as_posix(), self.p('missing'), env={'RS_WIFI_TRY': '0', 'RS_WIFI_ONCE': '1'}).returncode, 0)
        self.assertFalse((self.d / 'calls').exists())


class Images(Base):
    def test_lists_good_and_bad_images_with_the_command(self):
        self.part('stack', b'\xff' * 400000)
        good, cut, big = self.d / 'stack-1.bin', self.d / 'stack-2.bin', self.d / 'stack-3.bin'
        good.write_bytes(sqfs(200000, 400000))
        cut.write_bytes(sqfs(200000, 400000)[:100000] + b'\xff' * 300000)
        big.write_bytes(sqfs(200000, 500000))
        r = self.run_rs('images', env={'RS_IMAGES': '%s %s %s' % (good.as_posix(), cut.as_posix(), big.as_posix())})
        md5 = hashlib.md5(good.read_bytes()).hexdigest()
        self.assertIn('good  ' + good.as_posix(), r.stdout)
        self.assertIn('FLASHW_ALLOW=stack flashw -m %s stack %s' % (md5, good.as_posix()), r.stdout)
        self.assertIn('BAD   ' + cut.as_posix(), r.stdout)
        self.assertIn('BAD   ' + big.as_posix(), r.stdout)
        self.assertEqual(r.stdout.count('flashw'), 1)

    def test_help_names_the_manual_write(self):
        r = self.run_rs('help')
        self.assertIn('FLASHW_ALLOW=stack flashw -m <md5> stack <file>', r.stdout)
        self.assertIn('Nothing was written to the flash', r.stdout)


def code_lines(s):
    return [l for l in s.splitlines() if not l.lstrip().startswith('#')]


class NeverWritesTheFlash(unittest.TestCase):
    def test_rescue_script_has_no_flash_write(self):
        s = text('v3/initrd-rescue')
        body = s[:s.index("cat <<'EOF'")] + s[s.index('\nEOF\n'):]	# the help text names the manual command
        code = '\n'.join(code_lines(body))
        for w in ('flashcp', 'flash_erase', 'mtdblock', 'saveenv', 'envtool', 'cfg-persist save'):
            self.assertNotIn(w, code, w)
        self.assertEqual(re.findall(r'flashw(?! -m \$\()', code), [])		# only the printed command of "images"
        for m in re.finditer(r'of=|>\s*"?\$DEV', code):
            self.fail('writes a device: ' + code[m.start() - 40:m.end() + 20])
        self.assertEqual(set(re.findall(r'\$DEV/\$\{\w+\}(\w*)', code)), {'ro'})	# read-only device nodes only

    def test_boot_script_only_mounts_read_only_and_never_calls_flashw(self):
        s = '\n'.join(code_lines(text('v3/S39tc100-linux66')))
        for w in ('flashcp', 'flashw', 'flash_erase', 'saveenv', 'envtool'):
            self.assertNotIn(w, s, w)
        self.assertIn('mount -t squashfs -o ro /dev/mtdblock${SM#mtd} /rom', s)


class BootScript(unittest.TestCase):
    """Step 1a of S39tc100, run with the paths moved into a sandbox and mount stubbed."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        for n in ('sd/tc100test', 'sys', 'dev', 'rom', 'bin'):
            (self.d / n).mkdir(parents=True)
        s = text('v3/S39tc100-linux66')
        a = s.index('RS=/etc/tc100/rescue')
        b = s.index('# item 42:')
        blk = s[a:b]
        T = self.d.as_posix()
        for old, new in (('/etc/tc100/rescue', T + '/rs'), ('/proc/cmdline', T + '/cmdline'), ('/sys/class/mtd', T + '/sys'),
                         ('/mnt/sd', T + '/sd'), ('/mnt/config', T + '/mntconfig'), ('/tmp/rescue', T + '/rescue'),
                         ('/tmp/cardmnt', T + '/cardmnt'), ('/rom', T + '/rom'), ('/dev/mtdblock', T + '/dev/mtdblock')):
            blk = blk.replace(old, new)
        pre = ('log() { echo "$*" >> %s/log; }\n'
               'mount() { echo "mount $*" >> %s/calls; [ -f %s/mount-ok ]; }\n'
               'umount() { echo "umount $*" >> %s/calls; }\n'
               'mountpoint() { return 1; }\n' % (T, T, T, T))
        post = '\nfor v in "FM=$FM" "RESCUE=$RESCUE" "CFGD=$CFGD"; do echo "$v"; done > %s/result\n' % T
        (self.d / 'block.sh').write_bytes((pre + blk + post).encode())
        (self.d / 'rs').write_bytes(('#!/bin/sh\nRS_SYS=%s/sys RS_DEV=%s/dev RS_CONSOLE=%s/console exec %s %s "$@"\n'
                                     % (T, T, T, ' '.join(SHELL), RESCUE.as_posix())).encode())
        (self.d / 'rs').chmod(0o755)
        (self.d / 'cmdline').write_text('console=ttySAK0 flashroot=1\n')
        self.n = 0
        for n in ('v3/linux66-sd/cfg-persist', 'v3/autorun-linux66.sh', 'scripts/common_functions.sh'):
            (self.d / 'rom' / n).parent.mkdir(parents=True, exist_ok=True)
            (self.d / 'rom' / n).write_text('x\n')
        (self.d / 'rom/v3/linux66-sd/flashmode-prep.sh').write_text('echo prep >> %s/calls\n' % T)
        (self.d / 'mount-ok').write_text('')

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def part(self, name, data, size=None):
        (self.d / 'sys' / ('mtd%d' % self.n)).mkdir()
        (self.d / 'sys' / ('mtd%dro' % self.n)).mkdir()
        (self.d / 'sys' / ('mtd%d' % self.n) / 'name').write_text(name + '\n')
        (self.d / 'sys' / ('mtd%d' % self.n) / 'size').write_text('%d\n' % (size or len(data)))
        (self.d / 'dev' / ('mtd%dro' % self.n)).write_bytes(data)
        self.n += 1

    def boot(self):
        r = subprocess.run(SHELL + [(self.d / 'block.sh').as_posix()], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = dict(kv.split('=', 1) for kv in (self.d / 'result').read_text().splitlines())
        log = (self.d / 'log').read_text() if (self.d / 'log').exists() else ''
        calls = (self.d / 'calls').read_text() if (self.d / 'calls').exists() else ''
        return res, log, calls

    def settings(self, files):
        self.part('cfga', slot(3, files))
        self.part('cfgb', b'\xff' * 36864)

    def test_good_stack_starts_the_flash_user_space(self):
        self.part('stack', sqfs(200000, 400000))
        res, log, calls = self.boot()
        self.assertEqual(res['FM'], '1')
        self.assertEqual(res['RESCUE'], '')
        self.assertTrue(res['CFGD'].endswith('/mntconfig'))
        self.assertIn('prep', calls)
        self.assertEqual(log, '')

    def test_cut_write_goes_to_rescue_with_the_saved_settings_and_no_mount(self):
        self.part('stack', sqfs(200000, 400000)[:50000] + b'\xff' * 350000)
        self.settings({'user.pwd': b'pw\n', 'wpa_supplicant.conf': b'network={\nssid="x"\n}\n'})
        res, log, calls = self.boot()
        self.assertEqual(res['FM'], '0')
        self.assertIn('stops before its end', res['RESCUE'])
        self.assertTrue(res['CFGD'].endswith('/rescue/config'))
        self.assertTrue((self.d / 'rescue/config/user.pwd').is_file())
        self.assertNotIn('mount -t squashfs', calls)
        self.assertNotIn('prep', calls)

    def test_mount_failure_and_missing_files(self):
        self.part('stack', sqfs(200000, 400000))
        (self.d / 'mount-ok').unlink()
        res, log, calls = self.boot()
        self.assertIn('does not mount', res['RESCUE'])
        (self.d / 'mount-ok').write_text('')
        (self.d / 'rom/v3/autorun-linux66.sh').unlink()
        res, log, calls = self.boot()
        self.assertIn('autorun-linux66.sh', res['RESCUE'])
        self.assertIn('umount', calls)
        self.assertNotIn('prep', calls)

    def test_failed_prep(self):
        self.part('stack', sqfs(200000, 400000))
        (self.d / 'rom/v3/linux66-sd/flashmode-prep.sh').write_text('exit 1\n')
        res, log, calls = self.boot()
        self.assertEqual((res['FM'], res['RESCUE']), ('0', 'flashmode-prep.sh failed'))

    def test_sd_card_user_space_comes_before_the_rescue_mode(self):
        self.part('stack', b'\xff' * 400000)
        (self.d / 'sd/v3').mkdir()
        (self.d / 'sd/v3/autorun-linux66.sh').write_text('x\n')
        res, log, calls = self.boot()
        self.assertEqual((res['FM'], res['RESCUE']), ('0', ''))
        self.assertTrue(res['CFGD'].endswith('/sd/config'))
        self.assertIn('user space of the SD card is started instead', log)

    def test_switch_off_in_the_saved_settings(self):
        self.part('stack', b'\xff' * 400000)
        self.settings({'boot.conf': b'WIFI_COUNTRY=FR\nINITRD_RESCUE=0\n'})
        res, log, calls = self.boot()
        self.assertEqual((res['FM'], res['RESCUE']), ('0', ''))
        self.assertTrue(res['CFGD'].endswith('/sd/config'))
        self.assertIn('INITRD_RESCUE=0', log)

    def test_test_file_pretends_a_bad_stack_without_touching_it(self):
        self.part('stack', sqfs(200000, 400000))
        (self.d / 'sd/v3').mkdir()
        (self.d / 'sd/v3/autorun-linux66.sh').write_text('x\n')
        (self.d / 'sd/tc100test/stackbad').write_text('')
        res, log, calls = self.boot()
        self.assertEqual((res['FM'], res['RESCUE']), ('0', ''))		# the card's user space
        self.assertEqual(calls, '')
        (self.d / 'sd/tc100test/stackbad').write_text('rescue\n')
        res, log, calls = self.boot()
        self.assertIn('tc100test/stackbad', res['RESCUE'])
        self.assertEqual(calls, '')

    def test_sd_mode_is_untouched(self):
        (self.d / 'cmdline').write_text('console=ttySAK0\n')
        res, log, calls = self.boot()
        self.assertEqual((res['FM'], res['RESCUE'], calls, log), ('0', '', '', ''))


class Wiring(unittest.TestCase):
    def test_initramfs_carries_the_rescue_script_and_the_flash_writer(self):
        b = text('v3/build-rootfs66.sh')
        self.assertIn('install -m 755 "$HERE/initrd-rescue" etc/tc100/rescue', b)
        self.assertIn('install -m 755 "$HERE/linux66-sd/flashw" usr/sbin/flashw', b)
        prune = [l.strip() for l in text('v3/initramfs-prune.txt').splitlines()]
        for f in ('etc/tc100', 'etc/tc100/rescue', 'usr/sbin/flashw', 'usr/sbin/wpa_supplicant', 'usr/sbin/telnetd', 'usr/bin/tcpsvd'):
            self.assertNotIn(f, prune)

    def test_applets_the_rescue_needs_are_in_the_initramfs_busybox(self):
        applets = set(text('tests/fixtures/busybox-6.6-applets.txt').split())
        for a in ('tcpsvd', 'telnetd', 'flashcp', 'dd', 'od', 'tr', 'tail', 'head', 'wc', 'md5sum', 'gunzip', 'tar', 'sed',
                  'cat', 'pidof', 'killall', 'udhcpc', 'nc', 'sleep', 'cut', 'chmod', 'mkdir', 'grep', 'login'):
            self.assertIn(a, applets, a)

    def test_boot_script_order(self):
        s = text('v3/S39tc100-linux66')
        i = [s.index(x) for x in ('$RS check stack', 'mount -t squashfs -o ro', '$RS files /rom', 'flashmode-prep.sh; then CFGD=/mnt/config',
                                  '$RS settings /tmp/rescue', 'chpasswd', 'wpa_supplicant -B', '$RS start "$RESCUE"',
                                  '$RS watch $CFGD/boot.conf', 'log "starting $a"')]
        self.assertEqual(i, sorted(i))
        # rescue mode starts no user space
        a = s.index('if [ -z "$RESCUE" ]; then\n# 3b.')
        self.assertLess(a, s.index('log "starting $a"'))
        self.assertLess(s.index('log "starting $a"'), s.index('fi	# not in rescue mode'))

    def test_init_telnet_leaves_port_23_to_the_rescue_telnet(self):
        s = text('v3/S50telnet-linux66')
        self.assertLess(s.index('[ -f /tmp/rescue-mode ]'), s.index('telnetd >/dev/null'))

    def test_documented(self):
        self.assertIn('### AUDIT-1116-RECOVERY', text('docs/linux-port/test-queue.md'))
        self.assertIn('INITRD_RESCUE', text('docs/linux-port/internals.md'))
        self.assertIn('initrd-rescue', text('AGENTS.md'))


if __name__ == '__main__':
    unittest.main()
