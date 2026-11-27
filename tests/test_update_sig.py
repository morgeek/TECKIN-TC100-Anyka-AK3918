"""[up-sign] Authenticated update packages (docs/linux-port/upgrade-3.2/sign.md).

  - src/sigcheck (tc100-sigcheck, Monocypher Ed25519) built with the host compiler, keys made in the test: valid
    signature, changed file, changed SHA256SUMS, wrong key, truncated / garbage signature, key folders;
  - the updater (v3/install/update66.sh check) with stubs: the signature policy UPDATE_REQUIRE_SIG (unsigned accepted with
    a warning at 0, refused at 1; a BAD signature refused at 0 as well; 1 without any key installed never locks out),
    SHA256SUMS and MD5SUMS checks, the state line the web page shows;
  - scripts/sign_update.py (the owner's tool): keygen, sign, verify, a reproducible package;
  - the wiring: SHA256SUMS in the release script and never a signature, the CGI members, the switch in boot.conf.dist.
Nothing here touches a flash, U-Boot or its environment. Skipped without a C compiler.
Run: python3 -m unittest tests.test_update_sig -v
"""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
TMP = None
TOOL = None
NAMES = ('VERSION', 'stack.sqfs', 'c66.img', 'c66rd.gz', 'MD5SUMS')


def setUpModule():
    global TMP, TOOL
    TMP = Path(tempfile.mkdtemp(prefix='sigtest-'))
    if CC:
        TOOL = TMP / 'tc100-sigcheck-host'
        srcs = [str(ROOT / 'src/sigcheck' / n) for n in ('sigcheck.c', 'monocypher.c', 'monocypher-ed25519.c')]
        subprocess.run([CC, '-O1', '-Wall', '-DSIGCHECK_HOST', '-o', str(TOOL)] + srcs, check=True)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def run(*args, **kw):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=60, **kw)


def keygen(d, name):
    d.mkdir(parents=True, exist_ok=True)
    r = run(TOOL, 'keygen', d / name)
    assert r.returncode == 0, r.stderr
    return d / (name + '.key'), d / (name + '.pub'), r.stdout.strip()


def sign(key, f):
    r = run(TOOL, 'sign', key, f)
    assert r.returncode == 0, r.stderr
    return r.stdout


def make_package(d, sums_files=True):
    """a package the way v3/build-release.sh writes it: sums in the same format as md5sum / sha256sum"""
    d.mkdir(parents=True, exist_ok=True)
    (d / 'VERSION').write_text('3.2.0-test\n')
    (d / 'stack.sqfs').write_bytes(b'hsqs' + os.urandom(256))
    (d / 'c66.img').write_bytes(os.urandom(300))
    (d / 'c66rd.gz').write_bytes(os.urandom(300))
    (d / 'MD5SUMS').write_text(''.join('%s  %s\n' % (hashlib.md5((d / n).read_bytes()).hexdigest(), n)
                                       for n in ('stack.sqfs', 'c66.img', 'c66rd.gz', 'VERSION')))
    if sums_files:
        (d / 'SHA256SUMS').write_text(''.join('%s  %s\n' % (hashlib.sha256((d / n).read_bytes()).hexdigest(), n) for n in NAMES))
    return d


@unittest.skipUnless(CC, 'needs a C compiler')
class SigcheckTool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = TMP / 'tool'
        cls.k1, cls.p1, cls.id1 = keygen(cls.d / 'a', 'one')
        cls.k2, cls.p2, cls.id2 = keygen(cls.d / 'b', 'two')
        cls.f = cls.d / 'SHA256SUMS'
        cls.f.write_text('0' * 64 + '  VERSION\n')
        cls.sig = cls.d / 'SHA256SUMS.sig'
        cls.sig.write_text(sign(cls.k1, cls.f))

    def verify(self, f=None, sig=None, *keys):
        return run(TOOL, 'verify', f or self.f, sig or self.sig, *(keys or [self.p1]))

    def test_valid_signature(self):
        r = self.verify()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'signed ' + self.id1))

    def test_standard_ed25519(self):
        """not a private format: the same bytes verify with another Ed25519 implementation when one is at hand"""
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:
            self.skipTest('no python cryptography module')
        pub = bytes.fromhex(self.p1.read_text().split()[0])
        sig = bytes.fromhex(self.sig.read_text().split()[2])
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, self.f.read_bytes())

    def test_changed_file_is_bad(self):
        g = self.d / 'changed'
        g.write_text('1' * 64 + '  VERSION\n')
        r = self.verify(g)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertTrue(r.stdout.startswith('bad'))

    def test_one_byte_appended_is_bad(self):
        g = self.d / 'longer'
        g.write_bytes(self.f.read_bytes() + b'\n')
        self.assertEqual(self.verify(g).returncode, 1)

    def test_wrong_key_is_unknown(self):
        r = self.verify(None, None, self.p2)
        self.assertEqual((r.returncode, r.stdout.strip()), (3, 'unknown ' + self.id1))

    def test_key_folder_and_several_keys(self):
        r = self.verify(None, None, self.d / 'a', self.d / 'b')
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.verify(None, None, self.p2, self.p1)         # rotation: the second one is the signer
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_same_id_wrong_signature_is_bad(self):
        """a signature that names an installed key and does not verify is BAD, not 'unknown'"""
        parts = self.sig.read_text().split()
        flipped = parts[2][:-1] + ('0' if parts[2][-1] != '0' else '1')
        g = self.d / 'flipped.sig'
        g.write_text('tc100-sig1 %s %s\n' % (parts[1], flipped))
        self.assertEqual(self.verify(None, g).returncode, 1)

    def test_malformed_signatures_are_bad(self):
        good = self.sig.read_text()
        cases = {'empty': '', 'garbage': 'hello world\n', 'truncated': good[:60] + '\n', 'half': good[:-40],
                 'extra word': good.strip() + ' x\n', 'no tag': good.split(' ', 1)[1], 'non hex': good.replace(good.split()[2][:4], 'zzzz'),
                 'binary': '\x00\x01\x02' * 40, 'old tag': good.replace('sig1', 'sig0')}
        for name, content in cases.items():
            with self.subTest(name):
                g = self.d / 'bad.sig'
                g.write_bytes(content.encode('latin-1'))
                r = self.verify(None, g)
                self.assertEqual(r.returncode, 1, r.stdout)

    def test_no_usable_key(self):
        empty = self.d / 'empty'
        empty.mkdir(exist_ok=True)
        (empty / 'notes.txt').write_text('not a key')
        (empty / 'broken.pub').write_text('zz\n')
        r = self.verify(None, None, empty)
        self.assertEqual((r.returncode, r.stdout.strip()), (4, 'nokey'))
        r = self.verify(None, None, self.d / 'does-not-exist')
        self.assertEqual(r.returncode, 4)

    def test_unreadable_inputs(self):
        self.assertEqual(run(TOOL, 'verify', self.d / 'nope', self.sig, self.p1).returncode, 2)
        self.assertEqual(run(TOOL, 'verify', self.f, self.d / 'nope', self.p1).returncode, 2)
        self.assertEqual(run(TOOL, 'verify').returncode, 2)
        self.assertEqual(run(TOOL, 'frobnicate').returncode, 2)

    def test_pub_with_comments(self):
        g = self.d / 'commented.pub'
        g.write_text('# my key\n\n' + self.p1.read_text())
        self.assertEqual(self.verify(None, None, g).returncode, 0)

    def test_keygen(self):
        d = TMP / 'kg'
        k, p, kid = keygen(d, 'x')
        self.assertEqual(run(TOOL, 'id', p).stdout.strip(), kid)
        self.assertEqual(len(k.read_text().strip()), 64)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(k.stat().st_mode), 0o600)
        r = run(TOOL, 'keygen', d / 'x')                  # never overwrites a private key
        self.assertNotEqual(r.returncode, 0)
        k2, p2, kid2 = keygen(d, 'y')
        self.assertNotEqual(kid, kid2)

    def test_camera_build_has_no_signing_code(self):
        c = (ROOT / 'src/sigcheck/sigcheck.c').read_text()
        self.assertIn('#ifdef SIGCHECK_HOST', c)
        mk = (ROOT / 'src/sigcheck/Makefile').read_text()
        self.assertNotIn('-DSIGCHECK_HOST', mk[:mk.index('host:')])


@unittest.skipUnless(CC, 'needs a C compiler')
class UpdaterCheck(unittest.TestCase):
    """v3/install/update66.sh check, with the flash, the mtd list and the image checks stubbed"""

    @classmethod
    def setUpClass(cls):
        cls.root = TMP / 'upd'
        cls.keys = cls.root / 'keys'
        cls.cfgkeys = cls.root / 'cfgkeys'
        cls.kA, cls.pA, cls.idA = keygen(cls.root / 'priv', 'A')
        cls.kB, cls.pB, cls.idB = keygen(cls.root / 'priv', 'B')
        lib = cls.root / 'lib'
        lib.mkdir(parents=True)
        (lib / 'imgcheck.sh').write_text('initrd_img_check() { echo ok; }\nkernel_img_check() { echo ok; }\n')
        mtd = cls.root / 'mtd'
        for i, (n, size) in enumerate((('stack', 6291456), ('kernel', 2097152), ('initrd', 2097152), ('vendor', 100000))):
            (mtd / ('mtd%d' % i)).mkdir(parents=True)
            (mtd / ('mtd%d' % i) / 'name').write_text(n + '\n')
            (mtd / ('mtd%d' % i) / 'size').write_text('%d\n' % size)
        (cls.root / 'flashmode').write_text('')
        s = (ROOT / 'v3/install/update66.sh').read_text()
        s = s.replace('/tmp/flashmode', str(cls.root / 'flashmode')).replace('/sys/class/mtd', str(mtd))
        cls.script = cls.root / 'update66.sh'
        cls.script.write_text(s)

    def setUp(self):
        self.n = getattr(self, 'n', 0)
        self.work = TMP / ('pkg-%s' % self.id().split('.')[-1])
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.rmtree(self.keys, ignore_errors=True)
        shutil.rmtree(self.cfgkeys, ignore_errors=True)
        self.keys.mkdir(parents=True)
        self.cfgkeys.mkdir(parents=True)
        self.sigst = self.root / 'update66.sig'
        self.sigst.unlink(missing_ok=True)
        self.bootconf = self.root / 'boot.conf'
        self.bootconf.unlink(missing_ok=True)

    def install_key(self, pub, where=None, name=None):
        shutil.copy(pub, (where or self.keys) / (name or pub.name))

    def package(self, key=None, **kw):
        d = make_package(self.work, **kw)
        if key:
            (d / 'SHA256SUMS.sig').write_text(sign(key, d / 'SHA256SUMS'))
        return d

    def check(self, d, require=None, tool=None):
        env = dict(os.environ, UPDATE66_LIB=str(self.root / 'lib'), UPDATE66_SIGCHECK=str(tool or TOOL),
                   UPDATE66_KEYDIRS='%s %s' % (self.keys, self.cfgkeys), UPDATE66_SIGST=str(self.sigst),
                   UPDATE66_BOOTCONF=str(self.bootconf))
        env.pop('UPDATE_REQUIRE_SIG', None)
        if require is not None:
            env['UPDATE_REQUIRE_SIG'] = str(require)
        r = subprocess.run(SH + [str(self.script), 'check', str(d)], capture_output=True, text=True, env=env, timeout=60)
        out = r.stdout.strip()
        return r.returncode, out, (self.sigst.read_text().strip() if self.sigst.exists() else '')

    # ---- signed packages
    def test_valid_signature_both_policies(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        for req in (0, 1):
            with self.subTest(require=req):
                self.assertEqual(self.check(d, req), (0, 'ok', 'signed ' + self.idA))

    def test_key_in_the_config_folder(self):
        self.install_key(self.pA, self.cfgkeys)
        self.assertEqual(self.check(self.package(self.kA), 1), (0, 'ok', 'signed ' + self.idA))

    def test_rotation_two_keys(self):
        self.install_key(self.pA)
        self.install_key(self.pB)
        self.assertEqual(self.check(self.package(self.kB), 1)[2], 'signed ' + self.idB)

    def test_tampered_file_is_refused(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        raw = bytearray((d / 'stack.sqfs').read_bytes())
        raw[100] ^= 1
        (d / 'stack.sqfs').write_bytes(bytes(raw))
        for req in (0, 1):
            rc, out, st = self.check(d, req)
            self.assertEqual(rc, 1)
            self.assertIn('sha256', out)

    def test_tampered_md5sums_is_refused(self):
        """MD5SUMS is covered by SHA256SUMS: replacing it (and the file it vouches for) cannot pass"""
        self.install_key(self.pA)
        d = self.package(self.kA)
        (d / 'c66.img').write_bytes(b'evil')
        (d / 'MD5SUMS').write_text((d / 'MD5SUMS').read_text().replace(
            hashlib.md5(b'x').hexdigest(), 'x'))                      # no-op, then rebuild properly:
        (d / 'MD5SUMS').write_text(''.join('%s  %s\n' % (hashlib.md5((d / n).read_bytes()).hexdigest(), n)
                                           for n in ('stack.sqfs', 'c66.img', 'c66rd.gz', 'VERSION')))
        rc, out, st = self.check(d, 0)
        self.assertEqual(rc, 1, out)

    def test_tampered_sha256sums_is_bad_at_policy_0_too(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        (d / 'stack.sqfs').write_bytes(b'hsqs' + b'evil')
        (d / 'SHA256SUMS').write_text(''.join('%s  %s\n' % (hashlib.sha256((d / n).read_bytes()).hexdigest(), n) for n in NAMES))
        for req in (0, 1):
            rc, out, st = self.check(d, req)
            self.assertEqual(rc, 1, out)
            self.assertIn('signature of the package is not valid', out)
            self.assertTrue(st.startswith('refused'), st)

    def test_wrong_key(self):
        self.install_key(self.pA)
        d = self.package(self.kB)                                      # signed by a key this camera does not have
        rc, out, st = self.check(d, 0)
        self.assertEqual((rc, out), (0, 'ok'))
        self.assertTrue(st.startswith('unsigned signed by an unknown key (%s)' % self.idB), st)
        rc, out, st = self.check(d, 1)
        self.assertEqual(rc, 1)
        self.assertIn('not installed', out)

    def test_forged_signature_with_an_installed_key_id(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        parts = (d / 'SHA256SUMS.sig').read_text().split()
        (d / 'SHA256SUMS.sig').write_text('tc100-sig1 %s %s\n' % (parts[1], 'ab' * 64))
        for req in (0, 1):
            self.assertEqual(self.check(d, req)[0], 1)

    def test_garbage_and_truncated_signatures_are_refused(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        good = (d / 'SHA256SUMS.sig').read_text()
        for name, content in (('garbage', 'not a signature at all\n'), ('truncated', good[:50]), ('empty', ''), ('binary', '\x00' * 200)):
            with self.subTest(name):
                (d / 'SHA256SUMS.sig').write_bytes(content.encode('latin-1'))
                for req in (0, 1):
                    rc, out, st = self.check(d, req)
                    self.assertEqual(rc, 1, (name, req, out))
                    self.assertTrue(st.startswith('refused'), st)

    def test_signature_without_sha256sums_is_refused(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        (d / 'SHA256SUMS').unlink()
        self.assertEqual(self.check(d, 0)[0], 1)

    # ---- unsigned packages
    def test_unsigned_accepted_with_a_warning_at_0(self):
        self.install_key(self.pA)
        d = self.package()
        rc, out, st = self.check(d, 0)
        self.assertEqual((rc, out), (0, 'ok'))
        self.assertTrue(st.startswith('unsigned no signature'), st)

    def test_default_is_0_without_any_setting(self):
        self.install_key(self.pA)
        self.assertEqual(self.check(self.package())[0], 0)

    def test_unsigned_refused_at_1_with_a_key_installed(self):
        self.install_key(self.pA)
        rc, out, st = self.check(self.package(), 1)
        self.assertEqual(rc, 1)
        self.assertIn('not signed', out)
        self.assertTrue(st.startswith('refused'), st)

    def test_require_1_without_a_key_never_locks_out(self):
        rc, out, st = self.check(self.package(), 1)
        self.assertEqual((rc, out), (0, 'ok'))
        self.assertIn('no public key is installed', st)
        # a signed package, still no key: warning, accepted
        d = self.package(self.kA)
        rc, out, st = self.check(d, 1)
        self.assertEqual((rc, out), (0, 'ok'))
        self.assertTrue(st.startswith('unsigned'), st)

    def test_require_1_with_only_unusable_key_files(self):
        (self.keys / 'junk.pub').write_text('zz\n')
        rc, out, st = self.check(self.package(self.kA), 1)
        self.assertEqual((rc, out), (0, 'ok'))

    def test_legacy_package_without_sha256sums(self):
        self.install_key(self.pA)
        d = self.package(sums_files=False)
        self.assertEqual(self.check(d, 0)[:2], (0, 'ok'))
        self.assertEqual(self.check(d, 1)[0], 1)

    def test_missing_verifier(self):
        self.install_key(self.pA)
        d = self.package(self.kA)
        rc, out, st = self.check(d, 0, tool=self.root / 'no-such-tool')
        self.assertEqual((rc, out), (0, 'ok'))
        self.assertIn('could not be checked', st)
        self.assertEqual(self.check(d, 1, tool=self.root / 'no-such-tool')[0], 1)

    # ---- the policy switch
    def test_policy_from_boot_conf(self):
        self.install_key(self.pA)
        d = self.package()
        for line, want in (('UPDATE_REQUIRE_SIG=1\n', 1), ('UPDATE_REQUIRE_SIG="1"\n', 1), ('UPDATE_REQUIRE_SIG=1 # strict\n', 1),
                           ('UPDATE_REQUIRE_SIG=0\n', 0), ('# UPDATE_REQUIRE_SIG=1\n', 0), ('OTHER=1\n', 0),
                           ('UPDATE_REQUIRE_SIG=0\nUPDATE_REQUIRE_SIG=1\n', 1), ('UPDATE_REQUIRE_SIG=yes\n', 1)):
            with self.subTest(line=line):
                self.bootconf.write_text(line)
                self.assertEqual(self.check(d)[0], want)

    def test_environment_wins_over_boot_conf(self):
        self.install_key(self.pA)
        self.bootconf.write_text('UPDATE_REQUIRE_SIG=1\n')
        self.assertEqual(self.check(self.package(), 0)[0], 0)

    # ---- the rest of the package checks still run
    def test_sha256sums_must_list_the_package_files_once(self):
        d = self.package()
        good = (d / 'SHA256SUMS').read_text()
        bad = {'extra file': good + '%s  /dev/zero\n' % ('0' * 64), 'missing file': ''.join(good.splitlines(True)[1:]),
               'twice': good + good.splitlines()[0] + '\n', 'short sum': good.replace(good[:64], good[:60], 1),
               'weird': 'x\t' + good}
        for name, content in bad.items():
            with self.subTest(name):
                (d / 'SHA256SUMS').write_text(content)
                self.assertEqual(self.check(d, 0)[0], 1)

    def test_links_are_refused(self):
        if os.name != 'posix':
            self.skipTest('symlinks')
        d = self.package()
        (d / 'SHA256SUMS.sig').symlink_to('/dev/zero')
        rc, out, st = self.check(d, 0)
        self.assertEqual(rc, 1)
        self.assertIn('link', out)

    def test_md5_check_still_runs(self):
        d = self.package()
        (d / 'MD5SUMS').write_text((d / 'MD5SUMS').read_text().replace('stack.sqfs', 'stack.sqfs', 1))
        # SHA256SUMS now disagrees with MD5SUMS' bytes only if changed: change a file and fix SHA256SUMS to isolate md5
        (d / 'c66.img').write_bytes(b'changed')
        (d / 'SHA256SUMS').write_text(''.join('%s  %s\n' % (hashlib.sha256((d / n).read_bytes()).hexdigest(), n) for n in NAMES))
        rc, out, st = self.check(d, 0)
        self.assertEqual(rc, 1)
        self.assertIn('md5', out)

    def test_check_never_writes_the_flash(self):
        s = (ROOT / 'v3/install/update66.sh').read_text()
        body = s[s.index('\ncheck() {'):s.index('\ncase "$1" in')]
        for word in ('flashw', 'flashcp', 'mtd', 'envtool', 'reboot', 'write_part'):
            if word == 'mtd':
                continue            # part_size reads the partition sizes
            self.assertNotIn(word, body.replace('flashw -b', ''))
        self.assertLess(s.index('verify_sig "$D"'), s.index('md5sum -c MD5SUMS'))
        self.assertLess(s.index('sha256sum -c SHA256SUMS'), s.index('md5sum -c MD5SUMS'))
        apply_ = s[s.index('if [ "$1" = apply ]'):]
        self.assertLess(apply_.index('r=$(check "$D")'), apply_.index('exec /bin/sh $R/update66.sh apply-ram'))

    def test_sigcheck_command_runs_outside_flash_mode(self):
        """the read-only "sigcheck DIR" for a camera started from the SD card (no /tmp/flashmode)"""
        self.install_key(self.pA)
        d = self.package(self.kA)
        (self.root / 'flashmode').rename(self.root / 'flashmode.off')
        try:
            env = dict(os.environ, UPDATE66_LIB=str(self.root / 'lib'), UPDATE66_SIGCHECK=str(TOOL),
                       UPDATE66_KEYDIRS='%s %s' % (self.keys, self.cfgkeys), UPDATE66_SIGST=str(self.sigst),
                       UPDATE66_BOOTCONF=str(self.bootconf), UPDATE_REQUIRE_SIG='1')
            r = subprocess.run(SH + [str(self.script), 'sigcheck', str(d)], capture_output=True, text=True, env=env)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, 'ok'), r.stderr)
            self.assertEqual(self.sigst.read_text().strip(), 'signed ' + self.idA)
            (d / 'SHA256SUMS').write_text((d / 'SHA256SUMS').read_text() + ' ')
            r = subprocess.run(SH + [str(self.script), 'sigcheck', str(d)], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertIn('not valid', r.stdout)
            r = subprocess.run(SH + [str(self.script), 'check', str(d)], capture_output=True, text=True, env=env)
            self.assertIn('not running from its flash', r.stdout)
        finally:
            (self.root / 'flashmode.off').rename(self.root / 'flashmode')

    def test_package_signed_by_the_owner_tool(self):
        """scripts/sign_update.py -> tar -> extracted as the CGI does -> update66.sh check, key installed, policy 1"""
        o = OwnerTool()
        w = TMP / 'owner3'
        w.mkdir(exist_ok=True)
        self.assertEqual(o.py('keygen', w / 'k').returncode, 0)
        signed = w / 's.tar'
        self.assertEqual(o.py('sign', w / 'k.key', o.ci_tar(w / 'pkg'), '-o', signed).returncode, 0)
        d = self.work
        d.mkdir(parents=True)
        with tarfile.open(signed) as t:
            t.extractall(d)
        self.install_key(w / 'k.pub')
        rc, out, st = self.check(d, 1)
        self.assertEqual((rc, out), (0, 'ok'), st)
        self.assertTrue(st.startswith('signed '), st)


class Wiring(unittest.TestCase):
    def test_release_script_adds_sha256sums_and_never_signs(self):
        s = (ROOT / 'v3/build-release.sh').read_text()
        self.assertIn('SHA256SUMS', s)
        self.assertIn('VERSION stack.sqfs c66.img c66rd.gz MD5SUMS SHA256SUMS', s)
        self.assertNotIn('SHA256SUMS.sig', s.replace('# SHA256SUMS.sig is NOT made here', ''))
        self.assertIn('md5sum stack.sqfs', s)                      # kept for flashw

    def test_switch_documented_once(self):
        d = (ROOT / 'config/boot.conf.dist').read_text()
        self.assertEqual(d.count('\nUPDATE_REQUIRE_SIG=0\n'), 1)
        for p in ROOT.glob('config/*.dist'):
            if p.name != 'boot.conf.dist':
                self.assertNotIn('UPDATE_REQUIRE_SIG', p.read_text(), p.name)

    def test_busybox_has_sha256sum(self):
        self.assertIn('CONFIG_SHA256SUM=y', (ROOT / 'v3/buildroot/board/tc100/busybox.fragment').read_text())

    def test_sigcheck_in_the_image_and_ci(self):
        self.assertIn('tc100-sigcheck', (ROOT / 'v3/build-stack.sh').read_text())
        ci = (ROOT / '.github/workflows/build-kernel-linux66.yml').read_text()
        self.assertIn('make -C src/sigcheck', ci)
        self.assertIn("'src/sigcheck/**'", ci)
        self.assertIn('src/sigcheck', (ROOT / 'tests/docker/local-ci.sh').read_text())

    def test_monocypher_vendored_with_licence_and_credits(self):
        self.assertTrue((ROOT / 'src/sigcheck/LICENCE-monocypher.md').is_file())
        self.assertIn('Monocypher version 4.0.2', (ROOT / 'src/sigcheck/monocypher.c').read_text().splitlines()[0])
        self.assertIn('Monocypher', (ROOT / 'CREDITS.md').read_text())

    def test_no_private_key_in_the_repository(self):
        d = ROOT / 'v3/install/update-keys'
        for p in d.iterdir():
            self.assertIn(p.suffix, ('.pub', '.txt'), p.name)
            if p.suffix == '.pub':
                self.assertEqual(len(p.read_text().split()[0]), 64)

    def test_cgi_members(self):
        """update.cgi turns the state line of update66.sh into JSON members; the page shows them"""
        s = (ROOT / 'www/cgi-bin/update.cgi').read_text()
        self.assertIn('SHA256SUMS SHA256SUMS.sig', s)
        js = [l for l in s.splitlines() if l.startswith('js()')][0]
        fn = s[s.index('sig_json() {'):s.index('\n}\n', s.index('sig_json() {')) + 3]
        for line, want in (('signed 1a2b3c4d', {'sig': 'signed', 'sig_info': '1a2b3c4d'}),
                           ('unsigned no signature (SHA256SUMS.sig) in the package', {'sig': 'unsigned', 'sig_info': 'no signature (SHA256SUMS.sig) in the package'}),
                           ('refused the signature of the package is not valid', {'sig': 'refused', 'sig_info': 'the signature of the package is not valid'})):
            with self.subTest(line):
                st = TMP / 'cgi.sig'
                st.write_text(line + '\n')
                r = subprocess.run(SH + ['-c', '%s\nSIGST="%s"\n%s\nprintf "{\\"x\\":1%%s}" "$(sig_json)"' % (js, st, fn)], capture_output=True, text=True)
                self.assertEqual(json.loads(r.stdout), dict(want, x=1), r.stdout + r.stderr)
        st = TMP / 'cgi.none'
        r = subprocess.run(SH + ['-c', '%s\nSIGST="%s"\n%s\nprintf "{\\"x\\":1%%s}" "$(sig_json)"' % (js, st, fn)], capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), {'x': 1})
        page = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        for frag in ("'Signed (key '", "'Unsigned: accepted (warning)'", "'Refused: '", 'id="fwuSig"'):
            self.assertIn(frag, page)

    def test_french_translation(self):
        fr = (ROOT / 'www/i18n/fr.js').read_text(encoding='utf-8')
        self.assertIn('"Unsigned: accepted (warning)": "Non signé', fr)
        self.assertIn('Signé (clé $1)', fr)
        self.assertIn('Refusé : la signature du paquet', fr)


@unittest.skipUnless(CC, 'needs a C compiler')
class OwnerTool(unittest.TestCase):
    """scripts/sign_update.py"""
    tool = ROOT / 'scripts/sign_update.py'

    def py(self, *args):
        return subprocess.run([sys.executable, str(self.tool)] + [str(a) for a in args], capture_output=True, text=True, timeout=120)

    def ci_tar(self, d):
        """an update tar as the CI makes it: GNU tar order, root-owned, one fixed time, no signature"""
        pkg = make_package(d)
        out = d.parent / (d.name + '.tar')
        with tarfile.open(out, 'w:', format=tarfile.GNU_FORMAT) as t:
            for n in NAMES + ('SHA256SUMS',):
                ti = tarfile.TarInfo(n)
                data = (pkg / n).read_bytes()
                ti.size, ti.mtime, ti.mode = len(data), 1700000000, 0o644
                t.addfile(ti, io.BytesIO(data))
        return out

    def test_keygen_sign_verify(self):
        w = TMP / 'owner'
        w.mkdir()
        r = self.py('keygen', w / 'mine')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((w / 'mine.key').is_file() and (w / 'mine.pub').is_file())
        tar = self.ci_tar(w / 'pkg')
        r = self.py('sign', w / 'mine.key', tar, '-o', w / 'signed.tar')
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = self.py('sign', w / 'mine.key', tar, '-o', w / 'signed2.tar')
        self.assertEqual((w / 'signed.tar').read_bytes(), (w / 'signed2.tar').read_bytes())      # reproducible
        with tarfile.open(w / 'signed.tar') as t:
            names = t.getnames()
            self.assertEqual(names, list(NAMES) + ['SHA256SUMS', 'SHA256SUMS.sig'])
            self.assertTrue(all(m.mtime == 1700000000 and m.uid == 0 for m in t.getmembers() if m.name != 'SHA256SUMS.sig'))
        r = self.py('verify', w / 'signed.tar', w / 'mine.pub')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('every file matches', r.stdout)
        # the same package, as the camera extracts it, passes the same check
        d = w / 'out'
        d.mkdir()
        with tarfile.open(w / 'signed.tar') as t:
            t.extractall(d)
        self.assertEqual(run(TOOL, 'verify', d / 'SHA256SUMS', d / 'SHA256SUMS.sig', w / 'mine.pub').returncode, 0)
        # unsigned package, signing twice, another key, a changed member
        self.assertNotEqual(self.py('verify', tar, w / 'mine.pub').returncode, 0)
        self.assertNotEqual(self.py('sign', w / 'mine.key', w / 'signed.tar', '-o', w / 'x.tar').returncode, 0)
        self.py('keygen', w / 'other')
        self.assertNotEqual(self.py('verify', w / 'signed.tar', w / 'other.pub').returncode, 0)
        with tarfile.open(w / 'signed.tar') as t:
            members = [(m, t.extractfile(m).read()) for m in t.getmembers()]
        with tarfile.open(w / 'tampered.tar', 'w:', format=tarfile.GNU_FORMAT) as t:
            for m, data in members:
                if m.name == 'c66.img':
                    data = b'x' + data[1:]
                t.addfile(m, io.BytesIO(data))
        self.assertNotEqual(self.py('verify', w / 'tampered.tar', w / 'mine.pub').returncode, 0)

    def test_refuses_to_sign_an_inconsistent_package(self):
        w = TMP / 'owner2'
        w.mkdir()
        self.py('keygen', w / 'k')
        tar = self.ci_tar(w / 'pkg')
        with tarfile.open(tar) as t:
            members = [(m, t.extractfile(m).read()) for m in t.getmembers()]
        bad = w / 'bad.tar'
        with tarfile.open(bad, 'w:', format=tarfile.GNU_FORMAT) as t:
            for m, data in members:
                if m.name == 'stack.sqfs':
                    data = data[:-1] + b'!'
                t.addfile(m, io.BytesIO(data))
        r = self.py('sign', w / 'k.key', bad, '-o', w / 'o.tar')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((w / 'o.tar').exists())


if __name__ == '__main__':
    unittest.main()
