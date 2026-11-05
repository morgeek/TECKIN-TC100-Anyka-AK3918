"""src/rwconf/rwconf.c, the free replacement (item 53) of the prebuilt 2.x bin/rwconf, on the build host.

  - fixed expectations for every call form of the repository (the config/rtspserver.conf.dist layout, " " = top level,
    several pairs/triples, values with spaces and %, missing keys/sections/files, CRLF, comments, rewriting order);
  - differential run against the original: tests/rwconf-original/ is the unchanged source of the 2.x rwconf
    (anyka-v4l2rtspserver, Unlicense), built with g++ when it is present; same stdout and same file bytes on the fixtures
    and on a seeded random corpus. Skipped (fixed expectations still run) without g++.
Run: python3 -m unittest tests.test_rwconf -v
"""
from pathlib import Path
import os
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which('cc') or shutil.which('gcc')
CXX = shutil.which('g++') or shutil.which('c++')
TMP = None
MINE = ORIG = None

DIST = (ROOT / 'config/rtspserver.conf.dist').read_bytes()


def setUpModule():
    global TMP, MINE, ORIG
    TMP = tempfile.mkdtemp(prefix='rwconf-test-')
    if CC:
        MINE = os.path.join(TMP, 'rwconf-mine')
        subprocess.run([CC, '-O1', '-Wall', '-Wextra', '-Werror', '-std=gnu11', '-o', MINE, str(ROOT / 'src/rwconf/rwconf.c')], check=True)
    if CXX:
        ORIG = os.path.join(TMP, 'rwconf-orig')
        d = ROOT / 'tests/rwconf-original'
        r = subprocess.run([CXX, '-std=c++11', '-DBUILD_RWCONFIG=1', '-w', '-I', str(d), '-o', ORIG,
                            str(d / 'ReadWriteConfig.cpp'), str(d / 'ConfigFile.cpp')], capture_output=True)
        if r.returncode:
            ORIG = None


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def run(exe, content, args):
    """Run exe on a fresh copy of content (None = no file); returns (stdout, file bytes or None, status)."""
    d = tempfile.mkdtemp(dir=TMP)
    f = os.path.join(d, 'c.conf')
    if content is not None:
        Path(f).write_bytes(content)
    r = subprocess.run([exe, f] + args, capture_output=True, cwd=d)
    out = Path(f).read_bytes() if os.path.exists(f) else None
    return r.stdout, out, r.returncode


@unittest.skipUnless(CC, 'no C compiler')
class Expectations(unittest.TestCase):
    def rd(self, content, *a):
        out, _, st = run(MINE, content, ['r'] + list(a))
        self.assertEqual(st, 0)
        return out.decode()

    def wr(self, content, *a):
        out, f, st = run(MINE, content, ['w'] + list(a))
        self.assertEqual((out, st), (b'', 0))
        return f

    def test_read_forms_of_the_scripts(self):
        self.assertEqual(self.rd(DIST, ' ', 'PORT'), '554\n')                      # rtsp-launch.sh, network.sh
        self.assertEqual(self.rd(DIST, '0', 'fps'), '15\n')
        self.assertEqual(self.rd(DIST, '0', 'codec', '0', 'bps', ' ', 'PORT'), '2 1600 554\n')
        self.assertEqual(self.rd(DIST, '0', 'minqp', '0', 'maxqp', '0', 'goplen', '1', 'goplen'), '25 48 30 30\n')
        self.assertEqual(self.rd(DIST, '0', 'vbr', '0', 'smart'), ' \n')               # two missing keys: " " between
        self.assertEqual(self.rd(DIST, ' ', 'osdtext'), '%H:%M:%S %d.%m.%Y\n')           # value with spaces/percent
        self.assertEqual(self.rd(DIST, ' ', 'volume', ' ', 'imageflip'), '10 0\n')
        self.assertEqual(self.rd(DIST, '0', 'mainres'), '1080\n')

    def test_onvif_read_ten_values(self):
        out = self.rd(DIST, '0', 'width', '0', 'height', '0', 'codec', '0', 'fps', '0', 'bps',
                      '1', 'width', '1', 'height', '1', 'codec', '1', 'fps', '1', 'bps', ' ', 'PORT', '0', 'mainres')
        self.assertEqual(out, '1920 1080 2 15 1600 352 200 0 15 250 554 1080\n')

    def test_read_missing(self):
        self.assertEqual(self.rd(DIST, 'nosuch', 'x'), '\n')
        self.assertEqual(self.rd(DIST, ' ', 'nosuch'), '\n')
        self.assertEqual(self.rd(None, ' ', 'PORT'), '\n')                           # no file: empty, status 0
        self.assertEqual(self.rd(b'', ' ', 'PORT'), '\n')
        self.assertEqual(self.rd(DIST, ' ', 'PORT', ' ', 'nosuch', ' ', 'volume'), '554  10\n')

    def test_read_does_not_touch_the_file(self):
        _, f, _ = run(MINE, DIST, ['r', ' ', 'PORT'])
        self.assertEqual(f, DIST)
        _, f, _ = run(MINE, None, ['r', ' ', 'PORT'])
        self.assertIsNone(f)

    def test_trim_crlf_comments(self):
        c = b'# comment\r\n  PORT = 8554 \r\n\r\n[ s ]\r\n k = v w \r\nnoequals\r\n#x=1\r\na=\r\nab=\r\n'
        self.assertEqual(self.rd(c, ' ', 'PORT'), '8554\n')
        self.assertEqual(self.rd(c, 's', 'k'), 'v w\n')
        self.assertEqual(self.rd(c, ' s ', ' k '), 'v w\n')                          # names trimmed too
        self.assertEqual(self.rd(c, 's', '#x'), '1\n')                               # a comment with '=' is a key
        self.assertEqual(self.rd(c, 's', 'a'), '\n')                                 # "a=" is only 2 characters: ignored
        self.assertEqual(self.rd(c, 's', 'ab'), '\n')                                # "ab=" kept, empty value
        self.assertEqual(self.rd(b'x=1\nx=2\n', ' ', 'x'), '2\n')                    # last duplicate wins
        self.assertEqual(self.rd(b'a=b=c\n', ' ', 'a'), 'b=c\n')                     # first '=' splits
        self.assertEqual(self.rd(b'last=7', ' ', 'last'), '7\n')                     # no final newline

    def test_write_sorts_and_rewrites(self):
        f = self.wr(DIST, ' ', 'PORT', '8554')
        self.assertTrue(f.startswith(b'PORT=8554\nRTSPLOGENABLED=0\nUSERNAME=root\nUSERPASSWORD=REPLACEME\nchannels=1\n'))
        self.assertEqual(f.count(b'['), 4)
        self.assertIn(b'[0]\nbps=1600\nbrmode=1\ncodec=2\nfps=15\n', f)
        self.assertEqual(f.split(b'\n[0]\n')[0].count(b'\n'), 23)                  # 24 top level keys

    def test_write_forms_of_the_scripts(self):
        f = self.wr(DIST, '0', 'width', '1280', '0', 'height', '720', ' ', 'osdtext', '%H:%M  %d/%m', '1', 'fps', '12')
        out, _, _ = run(MINE, f, ['r', '0', 'width', '0', 'height', ' ', 'osdtext', '1', 'fps', '0', 'fps'])
        self.assertEqual(out, b'1280 720 %H:%M  %d/%m 12 15\n')

    def test_write_value_with_spaces_and_trim(self):
        f = self.wr(None, ' ', 'osdtext', '  hello  world ')
        self.assertEqual(f, b'osdtext=hello  world\n')

    def test_write_creates_file_and_sections(self):
        f = self.wr(None, '0', 'codec', '1', ' ', 'daynight', '3')
        self.assertEqual(f, b'daynight=3\n[0]\ncodec=1\n')

    def test_write_converts_crlf_and_drops_comments(self):
        f = self.wr(b'# c\r\nb=2\r\na=1\r\n[s]\r\nz=9\r\n', ' ', 'a', '5')
        self.assertEqual(f, b'a=5\nb=2\n[s]\nz=9\n')

    def test_no_change_no_write(self):
        c = b'# keep me\nb=2\na=1\n'
        self.assertEqual(self.wr(c, ' ', 'a', '1'), c)                               # same value: file untouched
        self.assertIsNone(self.wr(None, ' ', 'a', ''))                               # empty value for a new key: no file

    def test_write_empty_value_of_new_key_when_something_changes(self):
        self.assertEqual(self.wr(b'a=1\n', ' ', 'b', '', ' ', 'a', '2'), b'a=2\nb=\n')

    def test_incomplete_groups_ignored(self):
        self.assertEqual(self.wr(b'a=1\n', ' ', 'a', '2', ' ', 'b'), b'a=2\n')
        self.assertEqual(self.rd(b'a=1\nb=2\n', ' ', 'a', ' '), '1\n')

    def test_help(self):
        for args in ([], ['r'], ['r', ' '], ['x', ' ', 'x', 'y'], ['', ' ', 'x', 'y']):
            out, f, st = run(MINE, b'a=1\n', args)
            self.assertEqual(st, 0)
            self.assertTrue(out.startswith(b'Read/Write ini-file utility\nParams:\n'), args)
            self.assertEqual(f, b'a=1\n')

    def test_mode_is_the_first_letter(self):
        out, _, _ = run(MINE, b'a=1\n', ['read', ' ', 'a'])
        self.assertEqual(out, b'1\n')

    def test_unwritable_target_is_silent(self):
        d = tempfile.mkdtemp(dir=TMP)
        r = subprocess.run([MINE, os.path.join(d, 'no', 'such', 'c.conf'), 'w', ' ', 'a', '1'], capture_output=True)
        self.assertEqual((r.stdout, r.returncode), (b'', 0))


@unittest.skipUnless(CC and CXX, 'needs a C and a C++ compiler')
class ParityWithOriginal(unittest.TestCase):
    def setUp(self):
        if not ORIG:
            self.skipTest('the original did not build')

    def same(self, content, args):
        a = run(ORIG, content, args)
        b = run(MINE, content, args)
        self.assertEqual(b, a, (content, args))

    def test_fixtures(self):
        contents = [None, b'', b'\n', DIST, DIST.replace(b'\n', b'\r\n'), b'# only a comment\n', b'[s]\n', b'[]\nk=v\n',
                    b'[a]\nx=1\n[b]\nx=2\n[a]\ny=3\n', b'k=v\n[ spaced ]\n k2 = v 2 \n', b'x=1\nx=2\n', b'a=b=c\n',
                    b'\xc3\xa9=\xc3\xa8\n[\xc3\xa9]\nA=1\na=2\n_=3\n', b'last=7', b'   \n\t\n=novalue\n= \nk==\n']
        calls = [['r', ' ', 'PORT'], ['r', '0', 'fps', '0', 'codec', ' ', 'PORT'], ['r', 'a', 'x', 'b', 'x', 'a', 'y'],
                 ['r', ' spaced ', ' k2 '], ['r', 's', 'k'], ['r', '', 'k'], ['r', ' ', 'x'], ['r', ' ', 'a'],
                 ['r', ' ', 'k', ' '], ['rx', ' ', 'k'],
                 ['w', ' ', 'PORT', '8554'], ['w', '0', 'codec', '1', '0', 'bps', ' 99 '], ['w', ' ', 'k', ''],
                 ['w', 's', 'new', 'v v', ' ', 'k', 'w'], ['w', ' ', 'k', 'v', ' ', 'k', 'v2'], ['w', 'a', 'x', '1'],
                 ['w', ' ', 'x', '2'], ['w', '', 'z', '1'], ['w', ' ', '', 'v'], ['w', ' ', 'k', 'a\nb'],
                 ['w', ' ', 'volume', '3', ' ', 'incomplete'], ['w', ' ', 'k'], ['r'], ['r', ' '], ['r', ' ', 'k'],
                 ['wx', ' ', 'q', 'r'], ['z', ' ', 'q', 'r'], ['', ' ', 'q', 'r'],
                 ['w', ' ', 'osdtext', '%H:%M:%S %d.%m.%Y', ' ', 'USERPASSWORD', 'p w "q" $x \\y']]
        for c in contents:
            for a in calls:
                self.same(c, a)

    def test_random_corpus(self):
        rnd = random.Random(53)
        names = ['a', 'b', 'k', 'K', 'PORT', 'x y', ' ', '', '0', '1', '_', '#c', 'é', '[', ']']
        vals = ['', '1', 'v', ' v w ', 'a=b', '[s]', '%H:%M', 'é', '\t', '=']
        for n in range(400):
            lines = []
            for _ in range(rnd.randint(0, 12)):
                t = rnd.random()
                if t < .25:
                    lines.append('[%s]' % rnd.choice(names))
                elif t < .4:
                    lines.append(rnd.choice(['#c', '', '  ', 'junk', ';x', '[', ']', '[]', '[ ]', 'a=', '=', '=v']))
                else:
                    lines.append('%s%s%s' % (rnd.choice(names), rnd.choice(['=', ' = ', '=']), rnd.choice(vals)))
            eol = rnd.choice(['\n', '\r\n'])
            content = (eol.join(lines) + rnd.choice(['', eol])).encode()
            if rnd.random() < .1:
                content = None
            if rnd.random() < .5:
                args = ['r']
                for _ in range(rnd.randint(1, 4)):
                    args += [rnd.choice(names), rnd.choice(names)]
            else:
                args = ['w']
                for _ in range(rnd.randint(1, 3)):
                    args += [rnd.choice(names), rnd.choice(names), rnd.choice(vals)]
            self.same(content, args)


if __name__ == '__main__':
    unittest.main()
