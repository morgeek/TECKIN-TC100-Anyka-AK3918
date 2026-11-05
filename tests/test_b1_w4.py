"""Audit 2026-11-04, decisions of 2026-11-05: B1 + B3 (web update: 3 attempts per partition, no automatic reboot after
a final failure, md5 taken from the package's MD5SUMS) and W4 (wizard.cgi needs the CSRF token, .first_boot ends
with the first password)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def update_block():
    s = text('v3/install/update66.sh')
    sum_of = re.search(r'^sum_of\(\) \{.*\}$', s, re.M).group(0)
    block = s[s.index('# BEGIN write_part'):s.index('# END write_part')]
    return sum_of, block


class UpdateWritePath(unittest.TestCase):
    """B1, B3: the write loop of update66.sh with a stub flashw"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        # the stub records its arguments and fails (exit 5) for the partitions listed in $FAIL; a wrong md5 is refused
        # like the real flashw does (exit 4)
        (self.d / 'flashw').write_text(
            '#!/bin/sh\necho "$*" >> "$STUBLOG"\n'
            '[ "$2" = "$WANT" ] || { echo md5; exit 4; }\n'
            'n=$(grep -c "^-m" "$STUBLOG"); case " $FAIL " in *" $3 "*) [ $n -le ${FAILN:-99} ] && exit 5;; esac\n'
            'echo OK\n')
        self.simfail = self.d / 'simfail'

    def tearDown(self):
        self.tmp.cleanup()

    def run_loop(self, md5='a' * 32, fail='', failn='', simfail=None):
        sum_of, block = update_block()
        (self.d / 'log').unlink() if (self.d / 'log').exists() else None
        if simfail is not None:
            self.simfail.write_text(simfail)
        elif self.simfail.exists():
            self.simfail.unlink()
        (self.d / 'MD5SUMS').write_text('%s  initrd.bin\nbad\n' % md5)
        (self.d / 'initrd.bin').write_bytes(b'x')
        code = ('say() { echo "$*" >> "$SAY"; }\nBK=\nLOG=\n' + sum_of + '\n' + block +
                '\nm=$(sum_of "%s" initrd.bin) || exit 9\nwrite_part initrd "%s/initrd.bin" "$m"\necho rc=$?\n'
                % (self.d, self.d))
        env = dict(os.environ, STUBLOG=str(self.d / 'log'), SAY=str(self.d / 'say'), WANT=md5, FAIL=fail, FAILN=failn,
                   FLASHW=str(self.d / 'flashw'), SIMFAIL=str(self.simfail), FWLOG=str(self.d / 'fw.log'), RETRY_SLEEP='0')
        r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, env=env)
        log = (self.d / 'log').read_text() if (self.d / 'log').exists() else ''
        say = (self.d / 'say').read_text() if (self.d / 'say').exists() else ''
        return r.stdout.strip(), log.splitlines(), say

    def test_first_attempt_passes_the_sum_of_the_package(self):
        out, log, say = self.run_loop()
        self.assertEqual(out, 'rc=0')
        self.assertEqual(log, ['-m %s initrd %s/initrd.bin' % ('a' * 32, self.d)])
        self.assertEqual(say, '')

    def test_retries_then_succeeds(self):
        out, log, say = self.run_loop(fail='initrd', failn='2')
        self.assertEqual(out, 'rc=0')
        self.assertEqual(len(log), 3)
        self.assertIn('retrying initrd (attempt 3 of 3)', say)

    def test_three_failures_give_up(self):
        out, log, say = self.run_loop(fail='initrd')
        self.assertEqual(out, 'rc=1')
        self.assertEqual(len(log), 3)

    def test_test_switch_makes_attempts_fail_without_writing(self):
        out, log, _ = self.run_loop(simfail='initrd')
        self.assertEqual(out, 'rc=1')
        self.assertEqual(len(log), 3)
        self.assertTrue(all(l.startswith('-m ' + '0' * 32) for l in log))     # the real flashw refuses this md5 before writing
        out, log, _ = self.run_loop(simfail='initrd 1')                      # only the first attempt fails
        self.assertEqual(out, 'rc=0')
        self.assertEqual(len(log), 2)
        out, log, _ = self.run_loop(simfail='stack')                         # another partition: untouched
        self.assertEqual((out, len(log)), ('rc=0', 1))

    def test_sum_comes_from_md5sums_and_a_missing_one_refuses(self):
        sum_of, _ = update_block()
        (self.d / 'MD5SUMS').write_text('%s  stack.sqfs\n%s *c66.img\nnothex  c66rd.gz\n' % ('1' * 32, '2' * 32))
        def get(name):
            return subprocess.run(SHELL + ['-c', sum_of + '\nsum_of "%s" %s' % (self.d, name)],
                                  capture_output=True, text=True)
        self.assertEqual(get('stack.sqfs').stdout.strip(), '1' * 32)
        self.assertEqual(get('c66.img').stdout.strip(), '2' * 32)
        self.assertNotEqual(get('c66rd.gz').returncode, 0)                   # not a sum
        self.assertNotEqual(get('absent').returncode, 0)

    def test_source_has_no_reboot_after_failure_and_no_self_md5(self):
        s = text('v3/install/update66.sh')
        self.assertNotIn('md5sum < "$f"', s)                                  # B3: the file was compared with itself
        failed = s[s.index('after 3 attempts'):s.index('say "DONE:')]
        self.assertNotIn('reboot', failed)
        self.assertIn('exit 1', failed)
        self.assertIn('Do not cut the power', failed)
        self.assertIn('sum_of "$D" $f', s)                                    # check() needs a sum for every file
        self.assertEqual(subprocess.run(SHELL + ['-n', str(ROOT / 'v3/install/update66.sh')]).returncode, 0)

    def test_safety_checks_kept(self):
        s = text('v3/install/update66.sh')
        for kept in ('md5sum -c MD5SUMS', 'does not fit the', '-eq 2012654', '27 05 19 56', 'hsqs',
                     'FLASHW_ALLOW="stack kernel initrd"', 'is cut short'):
            self.assertIn(kept, s)
        f = text('v3/linux66-sd/flashw')
        self.assertIn('[ "$MD5" = "$want" ]', f)                              # flashw refuses a file with another md5


class WizardCsrf(unittest.TestCase):
    """W4: the POST needs the per-boot token; the page sends it"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        (d / 'config').mkdir()
        (d / 'config/boot.conf').write_text('REC_LOCAL=0\n')
        (d / 'first').write_text('')
        (d / 'csrf').write_text('abcdef0123456789abcdef0123456789\n')
        self.env = dict(os.environ, WZ_CSRF_FILE=str(d / 'csrf'), WZ_FIRST_BOOT_FLAG=str(d / 'first'),
                        WZ_CONFIG=str(d / 'config'), WZ_CARD=str(d), WZ_SCRIPTS=str(d), WZ_WIFI_CONF=str(d / 'w'),
                        TC100_STORAGE_FILE=str(d / 'st'), WZ_FLASHMODE=str(d / 'fm'))

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, token=None, body='profile=standalone&rec=off'):
        env = dict(self.env, REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(body)), QUERY_STRING='')
        if token is not None:
            env['HTTP_X_CSRF_TOKEN'] = token
        r = subprocess.run(SHELL + [str(ROOT / 'www/cgi-bin/wizard.cgi')], input=body.encode(), capture_output=True, env=env)
        head, _, payload = r.stdout.decode().partition('\n\n')
        return head, json.loads(payload)

    def test_post_without_or_with_wrong_token_changes_nothing(self):
        for tok in (None, '', '0' * 32, 'abcdef0123456789abcdef012345678'):
            head, r = self.post(tok)
            self.assertEqual(r, {'ok': False, 'error': 'csrf_invalid'}, tok)
            self.assertIn('403', head)
        self.assertEqual((self.d / 'config/boot.conf').read_text(), 'REC_LOCAL=0\n')
        self.assertTrue((self.d / 'first').exists())
        self.assertFalse((self.d / 'config/.wizard3_done').exists())

    def test_no_stored_token_refuses(self):
        (self.d / 'csrf').unlink()
        self.assertEqual(self.post('abcdef0123456789abcdef0123456789')[1]['error'], 'csrf_invalid')
        self.assertEqual(self.post('')[1]['error'], 'csrf_invalid')

    def test_post_with_token_works_once(self):
        head, r = self.post('abcdef0123456789abcdef0123456789')
        self.assertTrue(r['ok'], r)
        self.assertIn('REC_LOCAL=0', (self.d / 'config/boot.conf').read_text())
        self.assertTrue((self.d / 'config/.wizard3_done').exists())
        self.assertFalse((self.d / 'first').exists())
        self.assertEqual(self.post('abcdef0123456789abcdef0123456789')[1]['error'], 'wizard_already_completed')

    def test_get_and_check_need_no_token(self):
        env = dict(self.env, REQUEST_METHOD='GET', QUERY_STRING='check')
        out = subprocess.run(SHELL + [str(ROOT / 'www/cgi-bin/wizard.cgi')], capture_output=True, text=True, env=env).stdout
        self.assertEqual(json.loads(out.split('\n\n', 1)[1]), {'first_boot': True})

    def test_page_reads_and_sends_the_token(self):
        w = text('www/cgi-bin/wizard.cgi')
        page = w[w.index('<script>\nvar wz'):]
        self.assertIn("'/cgi-bin/statusline.cgi'", page)
        self.assertIn('csrf_token', page)
        self.assertLess(page.index('statusline.cgi'), page.index("'/cgi-bin/wizard.cgi', true"))
        self.assertIn("setRequestHeader('X-CSRF-Token', token)", page)
        self.assertIn('csrf_invalid:', page)
        # statusline.cgi creates the token when no CGI has yet (a first boot, before any password)
        self.assertIn('/tmp/csrf_token', text('www/cgi-bin/statelib.cgi'))


class FirstBootEndsWithPassword(unittest.TestCase):
    """W4: .first_boot is removed when a password is set elsewhere and not recreated at the boot"""

    def test_http_password_closes_the_window(self):
        s = text('scripts/common_functions.sh')
        fn = s[s.index('http_password(){'):s.index('\n}\n', s.index('http_password(){')) + 3]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'web-auth').write_text('#!/bin/sh\nexit ${WA_RC:-0}\n')
            code = fn.replace('/mnt/v3/linux66-sd/web-auth', (d / 'web-auth').as_posix()).replace('/tmp/.first_boot', (d / 'first').as_posix()) + \
                '\nhttp_password secret; echo rc=$?\n'
            env = dict(os.environ, TC100_PWSET_MARK=(d / 'mark').as_posix())
            (d / 'first').write_text('')
            r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, env=dict(env, WA_RC='1'))
            self.assertEqual(r.stdout.strip(), 'rc=1')                          # failure: nothing changes
            self.assertTrue((d / 'first').exists())
            self.assertFalse((d / 'mark').exists())
            r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout.strip(), 'rc=0')
            self.assertFalse((d / 'first').exists())
            self.assertTrue((d / 'mark').exists())

    def test_boot_and_wizard_reset(self):
        a = text('v3/autorun-linux66.sh')
        self.assertIn('[ -f /mnt/config/.wizard3_done ] || [ -f /mnt/config/.password_set ] || : > /tmp/.first_boot', a)
        s = text('scripts/action.d/setup.sh')
        reset = s[s.index('wizard_reset)'):]
        self.assertIn('/mnt/config/.password_set', reset.split('touch /tmp/.first_boot')[0])   # a reset really reopens it
        self.assertIn('touch /tmp/.first_boot', reset)


if __name__ == '__main__':
    unittest.main()
