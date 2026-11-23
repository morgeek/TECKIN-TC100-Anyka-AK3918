"""[harden] (2026-11-23, audit 2026-11-16) Stack protector and full RELRO in the free programs of the flash image.

- The musl programs (tc100_rtsp, tc100-mqttd, -onvifd, -supervisord, -logfwd, rwconf, libnetacl-musl.so; src/musl.mk) are
  built with -fstack-protector-strong and -Wl,-z,relro,-z,now by default. musl 1.2.4 exports __stack_chk_fail and
  __stack_chk_guard; its loader fills the guard from AT_RANDOM before the program's own copy is made (ARM GCC reads the
  canary from that global: ARMv5 has no thread register). -z now puts the GOT inside GNU_RELRO, which the musl loader
  makes read-only after relocation (musl never binds lazily).
- The freestanding programs (httpfront, tc100-mdnsd, isp_flip: no C library) define both names in
  src/ssp-freestanding.h; their _start fills the guard from AT_RANDOM before run(). A smashed stack prints
  "*** stack smashing detected ***" and ends in SIGABRT. musl's own __stack_chk_fail prints nothing: the process dies of
  SIGILL (a_crash).
- HARDEN=0 (make argument or environment; CI input "harden") builds as before.

Static checks of the Makefiles and CI always run; the build and qemu checks need arm-linux-gnueabi-gcc/readelf, make,
qemu-arm and the musl sysroot (sh v3/musl/build-musl.sh; `sh tests/docker/local-ci.sh cross` has them all).
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('arm-linux-gnueabi-gcc')
READELF = shutil.which('arm-linux-gnueabi-readelf')
QEMU = shutil.which('qemu-arm') or shutil.which('qemu-arm-static')
MUSL = Path(os.environ.get('MUSL', ROOT / 'build/musl'))
HARDENED = os.environ.get('HARDEN') != '0'
NEED = bool(CC and READELF and QEMU and shutil.which('make') and (MUSL / 'bin/musl-gcc').is_file())
WHY = 'needs arm-linux-gnueabi-gcc/readelf, make, qemu-arm and the musl sysroot (sh v3/musl/build-musl.sh)'
FS = ['-Os', '-Wall', '-Werror', '-marm', '-march=armv5te', '-nostdlib', '-static', '-fno-builtin', '-fno-pic', '-no-pie',
      '-Wl,--build-id=none', '-s']
FREESTANDING = {'src/httpfront/httpfront.c': '$P/httpfront', 'src/mdnsd/mdnsd.c': '$P/tc100-mdnsd',
                'src/ispflip/isp_flip.c': 'bin/isp_flip'}
MUSL_MAKEFILES = ('mqttd', 'onvifd', 'supervisord', 'rwconf', 'logfwd')


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


def relro_covers_got(readelf, obj):
    """True when the .got section lies inside the GNU_RELRO segment (full RELRO: read-only once the loader is done)"""
    ph = subprocess.run([readelf, '-lW', str(obj)], check=True, capture_output=True, text=True).stdout
    sh = subprocess.run([readelf, '-SW', str(obj)], check=True, capture_output=True, text=True).stdout
    r = re.search(r'GNU_RELRO\s+0x[0-9a-f]+\s+0x([0-9a-f]+)\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x([0-9a-f]+)', ph)
    g = re.search(r'\]\s+\.got\s+\S+\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)', sh)
    if not r or not g:
        return False
    a, n = int(r.group(1), 16), int(r.group(2), 16)
    ga, gn = int(g.group(1), 16), int(g.group(2), 16)
    return a <= ga and ga + gn <= a + n


class Wiring(unittest.TestCase):
    """the switch and the flags, where every shipped build takes them"""

    def test_musl_mk_hardens_by_default(self):
        mk = text('src/musl.mk')
        self.assertIn('HARDEN ?= 1', mk)
        on = mk[mk.index('ifeq ($(HARDEN),0)'):mk.index('endif')]
        self.assertIn('HARDEN_CFLAGS = -fno-stack-protector', on)                  # HARDEN=0: as before
        self.assertIn('HARDEN_CFLAGS = -fstack-protector-strong', on)
        self.assertIn('HARDEN_LDFLAGS = -Wl,-z,relro,-z,now', on)
        cf = re.search(r'^MUSL_CFLAGS \?=(.*\\\n)*.*$', mk, re.M).group(0)
        ld = re.search(r'^MUSL_LDFLAGS \?=.*$', mk, re.M).group(0)
        self.assertIn('$(HARDEN_CFLAGS)', cf)
        self.assertNotIn('-fno-stack-protector', cf)
        self.assertIn('-U_FORTIFY_SOURCE', cf)          # musl has no fortified headers: _FORTIFY_SOURCE would do nothing
        self.assertIn('-fno-pie', cf)                   # no PIE (measured +8 KB xz, slower code on the ARM926)
        self.assertIn('$(HARDEN_LDFLAGS)', ld)

    def test_every_musl_program_takes_the_flags(self):
        for d in MUSL_MAKEFILES:
            with self.subTest(d):
                mf = text('src/%s/Makefile' % d)
                self.assertIn('include ../musl.mk', mf)
                self.assertIn('$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS)', mf)
        rt = text('src/tc100rtsp/Makefile')
        rule = rt[rt.index('tc100_rtsp-musl.dbg:'):rt.index('tc100_rtsp-musl:', rt.index('tc100_rtsp-musl.dbg:') + 1)]
        self.assertIn('$(MUSL_CC) $(MUSL_CFLAGS)', rule)
        self.assertIn('$(MUSL_LDFLAGS)', rule)
        na = text('src/netacl/Makefile')
        rule = na[na.index('libnetacl-musl.dbg.so:'):na.index('libnetacl-musl.so:', na.index('libnetacl-musl.dbg.so:') + 1)]
        self.assertIn('$(MUSL_CFLAGS)', rule)
        self.assertIn('$(HARDEN_LDFLAGS)', rule)        # a shared object does not take MUSL_LDFLAGS

    def test_freestanding_programs_set_the_canary_first(self):
        h = text('src/ssp-freestanding.h')
        self.assertNotIn('#include <', h)               # still no C library
        self.assertIn('__stack_chk_guard', h)
        self.assertIn('void __stack_chk_fail(void)', h)
        self.assertIn('25 /* AT_RANDOM */', h)
        self.assertIn('no_stack_protector', h)
        for src in FREESTANDING:
            with self.subTest(src):
                c = text(src)
                self.assertIn('#include "../ssp-freestanding.h"', c)
                start = c[c.index('void _start(void)'):]
                self.assertLess(start.index('bl tc100_ssp_init'), start.index('bl run'))

    def test_ci_builds_take_the_switch(self):
        wf = text('.github/workflows/build-kernel-linux66.yml')
        lc = text('tests/docker/local-ci.sh')
        self.assertIn("HARDEN: ${{ github.event.inputs.harden == 'false' && '0' || '1' }}", wf)
        self.assertIn("- 'src/ssp-freestanding.h'", wf)
        self.assertIn('-e HARDEN="${HARDEN:-1}"', lc)
        fssp = 'case "$HARDEN" in 0) FSSP=-fno-stack-protector ;; *) FSSP=-fstack-protector-strong ;; esac'
        self.assertIn(fssp, wf)
        self.assertIn(fssp, lc)
        for src, out in FREESTANDING.items():
            with self.subTest(src):
                line = re.search(r'^.*arm-linux-gnueabi-gcc .*%s -o %s$' % (re.escape(src), re.escape(out)), wf, re.M).group(0)
                self.assertIn(' $FSSP ', line)
                line = re.search(r'^.*arm-linux-gnueabi-gcc .*%s -o /tmp/\S+$' % re.escape(src), lc, re.M).group(0)
                self.assertIn(' $FSSP ', line)
        self.assertIn("grep -q ' __stack_chk_fail$'", wf)     # the CI build fails if the shipped tc100_rtsp lost it
        self.assertIn('python3 -m unittest tests.test_harden', lc)


@unittest.skipUnless(NEED, WHY)
class Built(unittest.TestCase):
    """the ARM builds: the canary is there, it is random, and a smashed stack ends the process"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / 'src/musl.mk', cls.tmp / 'musl.mk')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def readelf(self, *args):
        return subprocess.run([READELF, *args], check=True, capture_output=True, text=True).stdout

    def make_musl(self, name, src, *args):
        """build SRC with the flags of src/musl.mk, as the program Makefiles do"""
        d = self.tmp / name
        d.mkdir()
        (d / 'p.c').write_text(src)
        (d / 'Makefile').write_text('all: p\ninclude ../musl.mk\np: p.c\n\t$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS) p.c -o $@\n')
        r = subprocess.run(['make', '-C', str(d), 'MUSL=%s' % MUSL, *args], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return d / 'p'

    def test_the_switch_turns_both_on_and_off(self):
        for name, args, on in (('on', ('HARDEN=1',), True), ('off', ('HARDEN=0',), False)):   # 1: the default of musl.mk
            with self.subTest(name):
                b = self.make_musl('sw-' + name, '#include <stdio.h>\nint main(int c, char **v)\n{\n\tchar b[16];\n\n'
                                   '\tsnprintf(b, sizeof b, "%s", v[c - 1]);\n\treturn puts(b) < 0;\n}\n', *args)
                self.assertEqual(' __stack_chk_fail' in self.readelf('--dyn-syms', '-W', str(b)), on)
                self.assertEqual('BIND_NOW' in self.readelf('-d', str(b)), on)
                self.assertEqual(relro_covers_got(READELF, b), on)

    @unittest.skipUnless(HARDENED, 'HARDEN=0')
    def test_musl_canary_is_random_and_catches_an_overflow(self):
        b = self.make_musl('canary', r'''
#include <stdio.h>
#include <string.h>
extern unsigned long __stack_chk_guard;
extern char _GLOBAL_OFFSET_TABLE_[];
__attribute__((noinline)) static void f(const char *s) { char b[8]; strcpy(b, s); printf("%d\n", (int)strlen(b)); }
int main(int argc, char **argv)
{
    printf("guard %08lx\n", __stack_chk_guard); fflush(stdout);
    if (argc > 1 && !strcmp(argv[1], "got")) { volatile unsigned *g = (volatile unsigned *)_GLOBAL_OFFSET_TABLE_; g[0] = g[0]; }
    else if (argc > 1) f(argv[1]);
    puts("returned");
    return 0;
}
''')
        run = lambda *a: subprocess.run([QEMU, '-L', str(MUSL), str(b), *a], capture_output=True, text=True, timeout=20)
        g = [run().stdout.split()[1] for _ in range(3)]
        self.assertNotIn('00000000', g)
        self.assertGreater(len(set(g)), 1, g)                          # AT_RANDOM, not a constant
        r = run('short')
        self.assertEqual((r.returncode, r.stdout.split()[-1]), (0, 'returned'))
        r = run('A' * 40)                                               # past the 8 bytes: canary, saved registers
        self.assertLess(r.returncode, 0, r.stdout)                      # killed (SIGILL: musl's a_crash)
        self.assertNotIn('returned', r.stdout)
        r = run('got')                                                  # full RELRO: the GOT is read-only at run time
        self.assertLess(r.returncode, 0, r.stdout)
        self.assertNotIn('returned', r.stdout)

    @unittest.skipUnless(HARDENED, 'HARDEN=0')
    def test_freestanding_canary_is_random_and_catches_an_overflow(self):
        c = self.tmp / 'fs.c'
        c.write_text(r'''
#include "%s"
static long w(const char *s, long n)
{
    register long r7 __asm__("r7") = 4, r0 __asm__("r0") = 1, r1 __asm__("r1") = (long)s, r2 __asm__("r2") = n;
    __asm__ volatile ("svc 0" : "+r"(r0) : "r"(r7), "r"(r1), "r"(r2) : "memory");
    return r0;
}
__attribute__((noinline)) static void f(const char *s) { char b[8]; int i = 0; while (s[i]) { b[i] = s[i]; i++; } b[i] = 0; w(b, 1); }
int run(int argc, char **argv)
{
    char h[10];
    unsigned long g = __stack_chk_guard;
    for (int i = 0; i < 8; i++) h[i] = "0123456789abcdef"[g >> (28 - 4 * i) & 15];
    h[8] = '\n';
    w("guard ", 6); w(h, 9);
    if (argc > 1) f(argv[1]);
    w("\nreturned\n", 10);
    return 0;
}
__attribute__((naked, noreturn)) void _start(void)
{
    __asm__ volatile ("add r0, sp, #4\n" "bl tc100_ssp_init\n" "ldr r0, [sp]\n" "add r1, sp, #4\n" "bl run\n"
                      "mov r7, #1\n" "svc 0\n");
}
''' % (ROOT / 'src/ssp-freestanding.h').as_posix())
        b = self.tmp / 'fs'
        subprocess.run([CC, *FS, '-fstack-protector-strong', str(c), '-o', str(b)], check=True)
        run = lambda *a: subprocess.run([QEMU, str(b), *a], capture_output=True, text=True, timeout=20)
        g = [run().stdout.split()[1] for _ in range(3)]
        self.assertTrue(all(x.endswith('00') and x != '00000000' for x in g), g)   # low byte zeroed, as glibc
        self.assertGreater(len(set(g)), 1, g)
        self.assertEqual(run('x').returncode, 0)
        r = run('A' * 40)
        self.assertEqual(r.returncode, -6, (r.stdout, r.stderr))        # SIGABRT
        self.assertIn('*** stack smashing detected ***', r.stderr)
        self.assertNotIn('returned', r.stdout)

    def test_shipped_freestanding_programs(self):
        """httpfront, tc100-mdnsd and isp_flip build with either setting; the canary is there only when hardened"""
        for src in FREESTANDING:
            for ssp in ('-fstack-protector-strong', '-fno-stack-protector'):
                with self.subTest(src=src, ssp=ssp):
                    b = self.tmp / ('%s%s' % (Path(src).stem, ssp))
                    flags = [f for f in FS if src != 'src/mdnsd/mdnsd.c' or f != '-Werror']   # mdns_pkt.h: unused helpers
                    r = subprocess.run([CC, *flags, ssp, str(ROOT / src), '-o', str(b)], capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr[-1500:])
                    self.assertEqual(b'stack smashing detected' in b.read_bytes(), ssp == '-fstack-protector-strong')
                    self.assertNotIn('__stack_chk', self.readelf('-sW', str(b)))   # stripped, nothing left to a loader


if __name__ == '__main__':
    unittest.main()
