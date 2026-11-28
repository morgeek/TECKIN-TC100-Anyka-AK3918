"""[secmode] The secret files of the settings folder are mode 600: scripts/secret-modes.sh (one list, one function) runs
at the three places that write them back (autorun at every boot, cfg-persist after a restore, the settings import of the
web page). chmod only, and only when the mode differs, so a boot with the modes right touches nothing."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']
LIB = ROOT / 'scripts' / 'secret-modes.sh'
SECRETS = ['user.pwd', 'rtspserver.conf', 'mqtt.conf', 'wpa_supplicant.conf', 'telegram.conf', 'notify.conf', 'https-key.pem']


def text(p):
    return (ROOT / p).read_text(encoding='utf-8')


def run_fix(folder):
    code = '. "$1"; secret_modes_fix "$2"'
    return subprocess.run(SH + ['-c', code, 'sh', str(LIB), str(folder)], capture_output=True, text=True)


def mode(p):
    return os.stat(p).st_mode & 0o777


@unittest.skipUnless(os.name == 'posix', 'file modes')
class SecretModes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='secmode-'))
        # PRIVDROP=0: every secret is 600 here; with the privilege drop on, two of them are 640 for the service group
        # (tests/test_privdrop.py)
        (self.tmp / 'boot.conf').write_text('PRIVDROP=0\n')
        os.chmod(self.tmp / 'boot.conf', 0o644)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, name, m):
        p = self.tmp / name
        p.write_text('secret\n')
        os.chmod(p, m)
        return p

    def test_loose_modes_become_600(self):
        made = {}
        for i, name in enumerate(SECRETS):
            made[name] = self.make(name, 0o755 if i % 2 else 0o644)
        r = run_fix(self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name, p in made.items():
            self.assertEqual(mode(p), 0o600, name)
        self.assertEqual(mode(self.tmp / 'boot.conf'), 0o644)

    def test_missing_files_are_fine(self):
        self.make('user.pwd', 0o644)
        r = run_fix(self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(mode(self.tmp / 'user.pwd'), 0o600)
        self.assertFalse((self.tmp / 'mqtt.conf').exists())

    def test_missing_folder_is_fine(self):
        r = run_fix(self.tmp / 'absent')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_fix('')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_files_already_600_are_not_touched(self):
        p = self.make('user.pwd', 0o600)
        past = time.time() - 86400
        os.utime(p, (past, past))
        before = os.stat(p)
        r = run_fix(self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        after = os.stat(p)
        self.assertEqual(after.st_mtime, before.st_mtime)
        self.assertEqual(after.st_ctime, before.st_ctime)     # no chmod at all: the ctime would move
        self.assertEqual(mode(p), 0o600)

    def test_content_is_kept(self):
        p = self.make('wpa_supplicant.conf', 0o644)
        run_fix(self.tmp)
        self.assertEqual(p.read_text(), 'secret\n')

    def test_the_library_only_defines(self):
        # sourcing it must not run anything: no file is changed by the bare source
        p = self.make('user.pwd', 0o644)
        subprocess.run(SH + ['-c', '. "$1"', 'sh', str(LIB)], check=True)
        self.assertEqual(mode(p), 0o644)

    def test_list_names_the_secret_files(self):
        s = text('scripts/secret-modes.sh')
        line = next(x for x in s.splitlines() if x.startswith('SECRET_FILES='))
        for name in SECRETS:
            self.assertIn(name, line.split('"')[1].split())


class SecretModesCallSites(unittest.TestCase):
    def test_library_is_sh_valid(self):
        for f in ['scripts/secret-modes.sh', 'v3/linux66-sd/cfg-persist', 'v3/autorun-linux66.sh']:
            r = subprocess.run(['sh', '-n', str(ROOT / f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + ' ' + r.stderr)

    def test_autorun_creates_the_password_at_600_and_fixes_modes(self):
        s = text('v3/autorun-linux66.sh')
        self.assertIn('( umask 077; cp /mnt/config/user.pwd.dist /mnt/config/user.pwd )', s)
        self.assertIn('. /mnt/scripts/secret-modes.sh && secret_modes_fix /mnt/config', s)
        # after the copy, before the web server starts with the password
        self.assertLess(s.index('secret_modes_fix /mnt/config'), s.index('sh /mnt/v3/linux66-sd/web-auth'))

    def test_cfg_persist_fixes_after_restore_ssh(self):
        s = text('v3/linux66-sd/cfg-persist')
        self.assertIn('secret-modes.sh', s)
        restore = s[s.index('restore)'):s.index('save)')]
        self.assertIn('restore_ssh && { secret_modes_fix "$CFG"; log "settings restored', restore)
        # a fallback keeps the restore working without the library
        self.assertIn('secret_modes_fix() { return 0; }', s)

    def test_cfg_persist_save_untouched(self):
        # the save path, its signature and the slot writes do not know the helper: only the restore branch calls it
        s = text('v3/linux66-sd/cfg-persist')
        self.assertEqual(s.count('secret_modes_fix "$CFG"'), 1)
        save = s[s.index('save)'):]
        self.assertNotIn('secret_modes_fix', save)

    def test_import_fixes_modes_after_the_commit(self):
        s = text('www/cgi-bin/config_exchange.cgi')
        commit = s.index('tc_commit_config_files "$_rs/x/config"')
        fix = s.index('secret_modes_fix "$CONFIG_ROOT"')
        self.assertGreater(fix, commit)
        self.assertLess(fix, s.index('rm -rf "$_rs"', fix))


if __name__ == '__main__':
    unittest.main()
