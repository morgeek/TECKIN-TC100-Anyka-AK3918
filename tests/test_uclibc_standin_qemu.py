"""tc100-logfwd and libnetacl.so as CI builds them (src/logfwd/Makefile, src/netacl/Makefile: glibc cross compiler,
stand-in libc.so.0 / libdl.so.0 made at link time, for the uClibc of the camera), run under qemu-arm.

There is no uClibc loader outside the camera, so the run uses glibc as the stand-in's "real libc": a sysroot where
/lib/ld-uClibc.so.0 is glibc's loader, libc.so.0 and libdl.so.0 are glibc's libc and libdl (so every import of the
stand-in is resolved BY NAME, as uClibc does on the camera) and a 3-line __uClibc_main (what start.S calls) preloaded.
What this proves: the soname/NEEDED wiring, that every import exists by name in a real libc, that no variable is
imported, that the interposed accept/accept4/bind win over libc and dlsym(RTLD_NEXT) reaches the real ones, and the
behaviour of the programs (the LogForwarder tests of tests/test_regressions.py are run again on the stand-in build).
What it cannot prove: that the symbol is spelled the same in uClibc 0.9.33 (checked against the prebuilt binaries,
see the test-queue entry [ci-uclibc]) and uClibc's own init order.

Skipped where the cross compiler or qemu-arm is missing; `sh tests/docker/local-ci.sh cross` installs both.
"""
from pathlib import Path
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from tests import test_regressions as tr

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('arm-linux-gnueabi-gcc')
READELF = shutil.which('arm-linux-gnueabi-readelf')
QEMU = shutil.which('qemu-arm') or shutil.which('qemu-arm-static')
GLIBC = Path('/usr/arm-linux-gnueabi/lib')
NEED = CC and READELF and QEMU and GLIBC.is_dir() and shutil.which('make')

SHIM = r'''
#include <stdlib.h>
extern char **environ;
int __uClibc_main(int (*m)(int, char **, char **), int argc, char **argv) { exit(m(argc, argv, environ)); }
'''

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


@unittest.skipUnless(NEED, 'needs arm-linux-gnueabi-gcc/readelf, make and qemu-arm with the glibc ARM libraries')
class StandInBuilds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        t = cls.tmp
        for sub in ('logfwd', 'netacl'):
            shutil.copytree(ROOT / 'src' / sub, t / 'src' / sub, ignore=shutil.ignore_patterns('*.o', 'imports.txt', 'stubs.c'))
        (t / 'src/tc100rtsp').mkdir(parents=True)
        shutil.copy(ROOT / 'src/tc100rtsp/start.S', t / 'src/tc100rtsp/start.S')
        for sub, target in (('logfwd', 'tc100-logfwd'), ('netacl', 'libnetacl.so')):
            subprocess.run(['make', '-C', str(t / 'src' / sub), 'CROSS=arm-linux-gnueabi-', target], check=True,
                           capture_output=True)
        cls.logfwd = t / 'src/logfwd/tc100-logfwd'
        cls.netacl = t / 'src/netacl/libnetacl.so'
        # sysroot: the loader and libc names of uClibc, backed by glibc
        sr = cls.sr = t / 'sr'
        (sr / 'lib').mkdir(parents=True)
        for name, real in (('ld-uClibc.so.0', 'ld-linux.so.3'), ('libc.so.0', 'libc.so.6'), ('libdl.so.0', 'libdl.so.2')):
            os.symlink(os.path.realpath(GLIBC / real), sr / 'lib' / name)
        for f in GLIBC.iterdir():                       # the glibc names too (the preloaded shim, the test server)
            if not (sr / 'lib' / f.name).exists():
                os.symlink(os.path.realpath(f), sr / 'lib' / f.name)
        (t / 'shim.c').write_text(SHIM); (t / 'srv.c').write_text(SERVER)
        subprocess.run([CC, '-shared', '-fPIC', '-o', str(sr / 'lib/libshim.so'), str(t / 'shim.c')], check=True)
        subprocess.run([CC, '-O1', '-Wall', '-o', str(t / 'srv'), str(t / 'srv.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def readelf(self, *args):
        return subprocess.run([READELF, *args], check=True, capture_output=True, text=True).stdout

    def qemu(self, prog, *args, preload='', env=None, **kw):
        cmd = [QEMU, '-L', str(self.sr), '-E', 'LD_LIBRARY_PATH=%s/lib' % self.sr]
        pl = ':'.join(x for x in (str(self.sr / 'lib/libshim.so') if prog == self.logfwd else '', preload) if x)
        if pl:
            cmd += ['-E', 'LD_PRELOAD=' + pl]
        for k, v in (env or {}).items():
            cmd += ['-E', '%s=%s' % (k, v)]
        return cmd + [str(prog), *args]

    # ---- structure: what the uClibc loader will see
    def test_logfwd_links_only_libc_so_0_and_the_uclibc_loader(self):
        dyn = self.readelf('-d', str(self.logfwd))
        self.assertEqual(dyn.count('(NEEDED)'), 1)
        self.assertIn('[libc.so.0]', dyn)
        self.assertIn('/lib/ld-uClibc.so.0', self.readelf('-l', str(self.logfwd)))

    def test_netacl_sonames_and_exports(self):
        dyn = self.readelf('-d', str(self.netacl))
        self.assertIn('[libdl.so.0]', dyn)
        self.assertIn('[libc.so.0]', dyn)
        self.assertEqual(dyn.count('(NEEDED)'), 2)
        self.assertIn('(INIT_ARRAY)', dyn)                  # the constructor that removes LD_PRELOAD for children
        syms = self.readelf('--dyn-syms', '-W', str(self.netacl)).splitlines()
        defined = {l.split()[-1] for l in syms if ' FUNC ' in l and ' UND ' not in l}
        for name in ('accept', 'accept4', 'bind'):
            self.assertIn(name, defined)
        und = {l.split()[-1].split('@')[0] for l in syms if ' UND ' in l}
        self.assertIn('dlsym', und)
        self.assertFalse(und & {'accept', 'accept4', 'bind'}, 'the interposers must not import themselves')
        for obj in (self.netacl, self.logfwd):
            helpers = [l for l in self.readelf('--dyn-syms', '-W', str(obj)).splitlines()
                       if ' UND ' in l and l.split()[-1].startswith(('__bswap', '__aeabi', '__gnu', '__udiv', '__div'))]
            self.assertEqual(helpers, [], 'libgcc helpers must be linked in, uClibc does not export them')
            self.assertNotIn(' OBJECT ', ''.join(l for l in self.readelf('--dyn-syms', '-W', str(obj)).splitlines(True)
                                                 if ' UND ' in l), 'a libc variable is imported')

    def test_every_import_exists_by_name_in_a_real_libc(self):
        """The stand-in defines every import, so a typo or a glibc-only symbol would only show at run time on the camera:
        resolve them all against glibc (the best stand-in for uClibc here) with a link check."""
        for obj, ldso in ((self.logfwd, True), (self.netacl, False)):
            und = sorted({l.split()[-1].split('@')[0] for l in self.readelf('--dyn-syms', '-W', str(obj)).splitlines()
                          if ' UND ' in l and len(l.split()) >= 8 and l.split()[-1] != 'Name'} - {'__uClibc_main', '__cxa_finalize'})
            src = self.tmp / ('chk_%s.c' % obj.name)
            src.write_text('int main(void){return 0;}\n' + ''.join('extern void %s(void);\nvoid *p%d = (void *)%s;\n' % (n, i, n)
                           for i, n in enumerate(und)))
            r = subprocess.run([CC, '-shared', '-o', str(self.tmp / 'chk.so'), str(src), '-ldl', '-w', '-Wl,--no-undefined'],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, obj.name + ': ' + r.stderr[:600])

    # ---- behaviour
    def test_logfwd_standin_runs(self):
        r = subprocess.run(self.qemu(self.logfwd), capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 2)
        self.assertIn('-r HOST[:PORT] is required', r.stderr)
        r = subprocess.run(self.qemu(self.logfwd, '-x'), capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, 'usage' in r.stderr), (2, True))

    def test_netacl_standin_filters_and_never_locks_out(self):
        try:
            me = socket.gethostbyname(socket.gethostname())
        except OSError:
            me = ''
        if not me or me.startswith('127.'):
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(('192.0.2.1', 9)); me = probe.getsockname()[0]
            except OSError:
                self.skipTest('no non-loopback address')
            finally:
                probe.close()
        st = self.tmp / 'st'
        self.errf = open(self.tmp / 'err', 'w')
        self.addCleanup(self.errf.close)

        def run(allow, local_ports=''):
            free = socket.socket(); free.bind(('127.0.0.1', 0)); lp = free.getsockname()[1]; free.close()
            env = {'TC100_NET_ALLOW': allow, 'TC100_NET_LOCAL_PORTS': local_ports.replace('PORT', str(lp)),
                   'TC100_NET_STATUS': str(st)}
            pr = subprocess.Popen(self.qemu(self.tmp / 'srv', str(lp), preload=str(self.netacl), env=env),
                                  stdout=subprocess.PIPE, stderr=self.errf, text=True)
            first = pr.stdout.readline().split()
            if len(first) != 2:
                self.fail((allow, (self.tmp / "err").read_text(), pr.wait()))
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


@unittest.skipUnless(NEED, 'needs arm-linux-gnueabi-gcc/readelf, make and qemu-arm with the glibc ARM libraries')
class LogForwarderStandIn(tr.LogForwarder):
    """The LogForwarder tests of tests/test_regressions.py (filter, repeats, rate limit, rotation), on the ARM stand-in
    build under qemu instead of the host build: the behaviour must stay the same."""

    def setUp(self):
        super().setUp()                                  # host build + socket + log, then swap the binary
        b = StandInBuilds
        wrapper = self.d / 'logfwd-qemu'
        wrapper.write_text('#!/bin/sh\nexec %s "$@"\n' % ' '.join(
            "'%s'" % a for a in (QEMU, '-L', b.sr, '-E', 'LD_LIBRARY_PATH=%s/lib' % b.sr, '-E',
                                 'LD_PRELOAD=%s/lib/libshim.so' % b.sr, b.logfwd)))
        wrapper.chmod(0o755)
        self.bin = wrapper

    @classmethod
    def setUpClass(cls):
        if NEED:
            StandInBuilds.setUpClass()

    @classmethod
    def tearDownClass(cls):
        if NEED:
            StandInBuilds.tearDownClass()


if __name__ == '__main__':
    unittest.main()
