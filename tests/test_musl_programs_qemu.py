"""The programs of the 3.0 system built against musl 1.2.4 (src/musl.mk, sysroot from v3/musl/build-musl.sh), the C
library of the camera's base system: tc100-mqttd, tc100-onvifd, tc100-supervisord, tc100-logfwd, rwconf and the musl
build of libnetacl. Until 2026-11-07 they ran under the vendor uClibc loader with a stand-in libc.

What is checked: each one needs only libc.so and asks for /lib/ld-musl-arm.so.1 (nothing of the vendor runtime), no
libgcc helper or glibc-only name is left to the loader, and the programs RUN under qemu-arm with the real musl loader and
libc of the same version as the camera's: the LogForwarder tests of tests/test_regressions.py on the ARM build, rwconf
against its host build, the help of the daemons, and the musl libnetacl preloaded into a musl server (filter, children
without LD_PRELOAD, local-only bind).

Skipped where the cross compiler, qemu-arm or the musl sysroot is missing (`sh v3/musl/build-musl.sh` makes it; the CI
runs it before the tests).
"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import tempfile
import unittest

from tests import test_regressions as tr

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('arm-linux-gnueabi-gcc')
READELF = shutil.which('arm-linux-gnueabi-readelf')
QEMU = shutil.which('qemu-arm') or shutil.which('qemu-arm-static')
MUSL = Path(os.environ.get('MUSL', ROOT / 'build/musl'))
NEED = bool(CC and READELF and QEMU and shutil.which('make') and (MUSL / 'bin/musl-gcc').is_file())
WHY = 'needs arm-linux-gnueabi-gcc/readelf, make, qemu-arm and the musl sysroot (sh v3/musl/build-musl.sh)'

PROGRAMS = {'mqttd': 'tc100-mqttd', 'onvifd': 'tc100-onvifd', 'supervisord': 'tc100-supervisord',
            'logfwd': 'tc100-logfwd', 'rwconf': 'rwconf'}

SERVER = r'''
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
int main(int argc, char **argv)
{
    int one = 1, s = socket(AF_INET, SOCK_STREAM, 0), b = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}, c; socklen_t l = sizeof a, cl = sizeof c;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    a.sin_family = AF_INET;
    if (bind(s, (struct sockaddr *)&a, sizeof a) || listen(s, 4) || getsockname(s, (struct sockaddr *)&a, &l)) return 1;
    printf("%d %d\n", ntohs(a.sin_port), getenv("LD_PRELOAD") != NULL); fflush(stdout);
    a.sin_port = htons((unsigned short)atoi(argv[1])); l = sizeof a;
    bind(b, (struct sockaddr *)&a, sizeof a); getsockname(b, (struct sockaddr *)&a, &l);
    printf("%s\n", inet_ntoa(a.sin_addr)); fflush(stdout);
    for (;;) {
        int fd = accept(s, (struct sockaddr *)&c, &cl);
        if (fd < 0 && errno == ECONNABORTED) continue;
        if (fd < 0) return 2;
        printf("accepted %s\n", inet_ntoa(c.sin_addr)); fflush(stdout);
        return 0;
    }
}
'''


def build_all(t):
    """the Makefiles of the repository, in a copy, against MUSL"""
    for sub in list(PROGRAMS) + ['netacl']:
        shutil.copytree(ROOT / 'src' / sub, t / 'src' / sub,
                        ignore=shutil.ignore_patterns('*.o', '*.so', 'imports.txt', 'stubs.c', '*.dbg', *PROGRAMS.values()))
    shutil.copy(ROOT / 'src/musl.mk', t / 'src/musl.mk')
    for sub in PROGRAMS:
        r = subprocess.run(['make', '-C', str(t / 'src' / sub), 'MUSL=%s' % MUSL], capture_output=True, text=True)
        assert r.returncode == 0, (sub, r.stderr[-800:])
    r = subprocess.run(['make', '-C', str(t / 'src/netacl'), 'MUSL=%s' % MUSL, 'musl'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


@unittest.skipUnless(NEED, WHY)
class MuslPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        build_all(cls.tmp)
        cls.bins = {n: cls.tmp / 'src' / d / n for d, n in PROGRAMS.items()}
        cls.netacl = cls.tmp / 'src/netacl/libnetacl-musl.so'
        (cls.tmp / 'srv.c').write_text(SERVER)
        r = subprocess.run(['sh', '-c', 'REALGCC=arm-linux-gnueabi-gcc "$1" -O1 -no-pie -Wl,--dynamic-linker=/lib/ld-musl-arm.so.1 '
                            '-o "$2" "$3"', 'cc', str(MUSL / 'bin/musl-gcc'), str(cls.tmp / 'srv'), str(cls.tmp / 'srv.c')],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def readelf(self, *args):
        return subprocess.run([READELF, *args], check=True, capture_output=True, text=True).stdout

    def qemu(self, prog, *args, env=None):
        cmd = [QEMU, '-L', str(MUSL)]
        for k, v in (env or {}).items():
            cmd += ['-E', '%s=%s' % (k, v)]
        return cmd + [str(prog), *args]

    # ---- structure: what the camera's musl loader will see
    def test_only_the_camera_libc(self):
        for obj in list(self.bins.values()) + [self.netacl]:
            with self.subTest(obj.name):
                dyn = self.readelf('-d', str(obj))
                self.assertEqual(dyn.count('(NEEDED)'), 1, dyn)
                self.assertIn('[libc.so]', dyn)
                for bad in ('libc.so.0', 'ld-uClibc', 'libdl.so', 'libpthread', 'libstdc++', 'libgcc_s'):
                    self.assertNotIn(bad, dyn)
                if obj != self.netacl:
                    self.assertIn('[Requesting program interpreter: /lib/ld-musl-arm.so.1]', self.readelf('-l', str(obj)))
                und = {l.split()[-1].split('@')[0] for l in self.readelf('--dyn-syms', '-W', str(obj)).splitlines()
                       if ' UND ' in l and len(l.split()) >= 8}
                helpers = sorted(n for n in und if n.startswith(('__aeabi', '__bswap', '__udiv', '__div', '__gnu', '__isoc', '__ctype_b_loc')) or n.endswith('_chk'))
                self.assertEqual(helpers, [], 'libgcc helpers and glibc-only names must not be left to the loader')

    def test_every_import_resolves_in_musl(self):
        """each import exists in the libc.so of the sysroot (same version as the camera's): a link check"""
        for obj in list(self.bins.values()) + [self.netacl]:
            und = sorted({l.split()[-1].split('@')[0] for l in self.readelf('--dyn-syms', '-W', str(obj)).splitlines()
                          if ' UND ' in l and len(l.split()) >= 8 and l.split()[-1] != 'Name'} - {'__cxa_finalize', '_ITM_registerTMCloneTable', '_ITM_deregisterTMCloneTable', '__gmon_start__'})
            missing = []
            libc = self.readelf('--dyn-syms', '-W', str(MUSL / 'lib/libc.so'))
            have = {l.split()[-1].split('@')[0] for l in libc.splitlines() if ' UND ' not in l and len(l.split()) >= 8}
            missing = [n for n in und if n not in have and n not in ('accept', 'accept4', 'bind')]
            self.assertEqual(missing, [], obj.name)

    # ---- behaviour under the real musl loader
    def test_daemons_start_and_print_their_usage(self):
        r = subprocess.run(self.qemu(self.bins['tc100-logfwd']), capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 2)
        self.assertIn('-r HOST[:PORT] is required', r.stderr)
        for name, args in (('tc100-onvifd', ('-p', '0', '-w', '1')), ('tc100-mqttd', ('-h',)), ('tc100-supervisord', ('-h',))):
            with self.subTest(name):
                # some start serving whatever the arguments: what matters is that the loader starts them
                pr = subprocess.Popen(self.qemu(self.bins[name], *args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, cwd=self.tmp)
                try:
                    out, err = pr.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    pr.kill(); out, err = pr.communicate()
                self.assertNotIn('Error loading shared library', err)
                self.assertNotIn('Error relocating', err)
                self.assertNotIn('symbol not found', err)
                self.assertNotEqual(pr.returncode, 127, err)

    def test_rwconf_same_as_the_host_build(self):
        host = self.tmp / 'rwconf-host'
        subprocess.run(['gcc', '-O1', '-o', str(host), str(ROOT / 'src/rwconf/rwconf.c')], check=True)
        conf = '# x\nUSERNAME=root\n[0]\nfps=25\ncodec=2\n[1]\n fps = 15 \r\n'
        for args in (('r', '0', 'fps', '1', 'fps', ' ', 'USERNAME', '9', 'none'), ('w', '0', 'fps', '10', ' ', 'PORT', '554')):
            outs = []
            for prog in (host, None):
                f = self.tmp / ('rw-%d.conf' % len(outs))
                f.write_text(conf)
                cmd = [str(host), str(f), *args] if prog else self.qemu(self.bins['rwconf'], str(f), *args)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                outs.append((r.returncode, r.stdout, f.read_text()))
            self.assertEqual(outs[0], outs[1], args)

    def test_netacl_filters_and_never_locks_out(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('192.0.2.1', 9)); me = probe.getsockname()[0]
        except OSError:
            self.skipTest('no non-loopback address')
        finally:
            probe.close()
        if me.startswith('127.'):
            self.skipTest('no non-loopback address')
        st = self.tmp / 'st'
        errf = open(self.tmp / 'err', 'w')
        self.addCleanup(errf.close)

        def run(allow, local_ports=''):
            free = socket.socket(); free.bind(('127.0.0.1', 0)); lp = free.getsockname()[1]; free.close()
            env = {'LD_PRELOAD': str(self.netacl), 'TC100_NET_ALLOW': allow,
                   'TC100_NET_LOCAL_PORTS': local_ports.replace('PORT', str(lp)), 'TC100_NET_STATUS': str(st)}
            pr = subprocess.Popen(self.qemu(self.tmp / 'srv', str(lp), env=env), stdout=subprocess.PIPE, stderr=errf, text=True)
            first = pr.stdout.readline().split()
            if len(first) != 2:
                self.fail((allow, (self.tmp / 'err').read_text(), pr.wait()))
            port, preload = first
            bound = pr.stdout.readline().strip()
            for host in (me, '127.0.0.1'):
                try:
                    socket.create_connection((host, int(port)), timeout=3).close()
                except OSError:
                    pass
            out = pr.stdout.readline().strip()
            pr.kill(); pr.wait(); pr.stdout.close()
            return out, preload, bound

        self.assertEqual(run('')[0], 'accepted ' + me)                  # no list: no filter
        self.assertEqual(run('not-a-network')[0], 'accepted ' + me)     # unreadable list: no filter
        self.assertEqual(run(me + '/32')[0], 'accepted ' + me)
        out, preload, _ = run('203.0.113.0/24')                         # outside: refused (dlsym(RTLD_NEXT) reached libc)
        self.assertEqual(out, 'accepted 127.0.0.1')
        self.assertEqual(preload, '0')                                  # LD_PRELOAD removed by the constructor
        self.assertIn('refused=1 last=' + me, st.read_text())
        self.assertEqual(run('', 'PORT')[2], '127.0.0.1')               # local-only port: bind() interposed
        self.assertEqual(run('', '1')[2], '0.0.0.0')


@unittest.skipUnless(NEED, WHY)
class LogForwarderMusl(tr.LogForwarder):
    """The LogForwarder tests of tests/test_regressions.py (filter, repeats, rate limit, rotation) on the ARM musl build
    under qemu instead of the host build: the behaviour must stay the same."""

    @classmethod
    def setUpClass(cls):
        cls.mtmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / 'src/logfwd', cls.mtmp / 'src/logfwd', ignore=shutil.ignore_patterns('tc100-logfwd', 'tc100-logfwd.dbg', '*.o'))
        shutil.copy(ROOT / 'src/musl.mk', cls.mtmp / 'src/musl.mk')
        subprocess.run(['make', '-C', str(cls.mtmp / 'src/logfwd'), 'MUSL=%s' % MUSL], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.mtmp, ignore_errors=True)

    def setUp(self):
        super().setUp()                                  # host build + socket + log, then swap the binary
        wrapper = self.d / 'logfwd-qemu'
        wrapper.write_text("#!/bin/sh\nexec '%s' -L '%s' '%s' \"$@\"\n" % (QEMU, MUSL, self.mtmp / 'src/logfwd/tc100-logfwd'))
        wrapper.chmod(0o755)
        self.bin = wrapper


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(NEED, WHY)
class Tc100RtspMusl(unittest.TestCase):
    """tc100_rtsp since 3.0.1-rc34: a musl program with libakuio linked in and the free encoder (src/h265enc/freeenc.h),
    the build the release ships. It needs the musl libc.so only (no vendor library, no uClibc runtime), every import
    exists in musl, it keeps the libakuio calls visible to its own dlsym(RTLD_DEFAULT) (--export-dynamic), and the
    real musl loader starts it (under qemu it stops at the missing camera devices, after loading)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for sub in ('tc100rtsp', 'jpegenc', 'h265enc', 'libakuio'):
            shutil.copytree(ROOT / 'src' / sub, cls.tmp / 'src' / sub,
                            ignore=shutil.ignore_patterns('*.o', '*.so', 'imports.txt', 'stubs.c', '*.dbg', 'tc100_rtsp',
                                                          'tc100_rtsp-musl', '__pycache__'))
        shutil.copy(ROOT / 'src/musl.mk', cls.tmp / 'src/musl.mk')
        r = subprocess.run(['make', '-C', str(cls.tmp / 'src/tc100rtsp'), 'MUSL=%s' % MUSL, 'musl'], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-1500:]
        cls.bin = cls.tmp / 'src/tc100rtsp/tc100_rtsp-musl'

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def readelf(self, *args):
        return subprocess.run([READELF, *args], check=True, capture_output=True, text=True).stdout

    def test_only_the_musl_libc(self):
        dyn = self.readelf('-d', str(self.bin))
        self.assertEqual(dyn.count('(NEEDED)'), 1, dyn)
        self.assertIn('[libc.so]', dyn)
        self.assertIn('[Requesting program interpreter: /lib/ld-musl-arm.so.1]', self.readelf('-l', str(self.bin)))
        syms = self.readelf('--dyn-syms', '-W', str(self.bin))
        und = {l.split()[-1].split('@')[0] for l in syms.splitlines() if ' UND ' in l and len(l.split()) >= 8 and l.split()[-1] != 'Name'}
        have = {l.split()[-1].split('@')[0] for l in self.readelf('--dyn-syms', '-W', str(MUSL / 'lib/libc.so')).splitlines()
                if ' UND ' not in l and len(l.split()) >= 8}
        self.assertEqual(sorted(n for n in und if n not in have and not n.startswith(('_ITM', '__gmon'))), [])
        for name in ('akuio_pmem_init', 'akuio_alloc_pmem', 'akuio_free_pmem', 'akuio_vaddr2paddr', 'akuio_wait_irq',
                     'akuio_map_regs', 'akuio_reset_video'):
            self.assertRegex(syms, r' FUNC +GLOBAL +DEFAULT +\d+ %s\n' % name, name)

    def test_the_musl_loader_starts_it(self):
        r = subprocess.run([QEMU, '-L', str(MUSL), str(self.bin), '-p', '0', '-h'], capture_output=True, text=True,
                           timeout=20, cwd=self.tmp)
        for bad in ('Error loading shared library', 'Error relocating', 'symbol not found'):
            self.assertNotIn(bad, r.stderr)
        self.assertNotEqual(r.returncode, 127, r.stderr)
