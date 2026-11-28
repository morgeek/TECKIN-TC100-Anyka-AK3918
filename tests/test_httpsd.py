"""Unit, static-hardening, packaging, and shell-control tests for tc100-httpsd (3.2.1 HTTPS proxy)."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SH = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


class HttpsdCTests(unittest.TestCase):
    def test_c_unit_suite(self):
        with tempfile.TemporaryDirectory(prefix='httpsd-unit-') as td:
            bin_path = Path(td) / 'httpsd_test'
            cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
            self.assertIsNotNone(cc, 'C compiler required to run src/httpsd/httpsd_test.c')
            res = subprocess.run(
                [cc, '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-o', str(bin_path), str(ROOT / 'src/httpsd/httpsd_test.c')],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            run = subprocess.run([str(bin_path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_low_cpu_and_hardening_design(self):
        src = read('src/httpsd/tc100_httpsd.c')
        hdr = read('src/httpsd/httpsd_http.h')
        # Zero per-connection dynamic heap allocation
        for fn in ('malloc(', 'calloc(', 'realloc('):
            self.assertNotIn(fn, src, f'unexpected dynamic allocation {fn} in tc100_httpsd.c')
            self.assertNotIn(fn, hdr, f'unexpected dynamic allocation {fn} in httpsd_http.h')
        # ChaCha20-Poly1305 ordered before AES-GCM for ARM926EJ-S without AES-NI
        chacha_pos = src.index('MBEDTLS_TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256')
        aes_pos = src.index('MBEDTLS_TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256')
        self.assertLess(chacha_pos, aes_pos)
        self.assertIn('MBEDTLS_SSL_IANA_TLS_GROUP_X25519', src)
        # Session resumption + Keep-Alive + chunked streaming + CPU yield + privdrop
        self.assertIn('mbedtls_ssl_ticket_setup', src)
        self.assertIn('mbedtls_ssl_cache_set_max_entries', src)
        self.assertIn('HTTPSD_BODY_CHUNKED_OUT', src)
        self.assertIn('nice(G.nice_val)', src)
        self.assertIn('setuid(0) == 0', src)
        self.assertIn('HTTPSD_MAX_HS', src)


class HttpsdPackagingAndWiringTests(unittest.TestCase):
    def test_buildroot_and_stack_wiring(self):
        self.assertIn('package/tc100-httpsd/Config.in', read('v3/buildroot/Config.in'))
        self.assertIn('BR2_PACKAGE_TC100_HTTPSD=y', read('v3/buildroot/configs/tc100_defconfig'))
        mk = read('v3/buildroot/package/tc100-httpsd/tc100-httpsd.mk')
        self.assertIn('TC100_HTTPSD_DEPENDENCIES = mbedtls', mk)
        self.assertIn('-lmbedtls -lmbedx509 -lmbedcrypto', mk)
        ext = read('v3/buildroot/external.mk')
        for sym in ('MBEDTLS_CHACHAPOLY_C', 'MBEDTLS_ECP_DP_CURVE25519_ENABLED', 'MBEDTLS_SSL_SESSION_TICKETS', 'MBEDTLS_SSL_CACHE_C'):
            self.assertIn(sym, ext)
        self.assertIn('usr/bin/tc100-httpsd', read('v3/initramfs-prune.txt').splitlines())
        self.assertIn('usr/bin/tc100-httpsd', read('v3/build-stack.sh'))
        self.assertIn("'tc100-httpsd'", read('scripts/sbom.py'))

    def test_runtime_config_and_boot_wiring(self):
        boot_dist = read('config/boot.conf.dist')
        self.assertRegex(boot_dist, r'(?m)^HTTPS=0$')          # off by default (owner 2026-11-28)
        self.assertIn('HTTPS_PORT=443', boot_dist)
        self.assertIn('https-server)', read('scripts/service-switch.sh'))
        self.assertIn('https-key.pem', read('scripts/secret-modes.sh'))
        auto = read('v3/autorun-linux66.sh')
        self.assertIn('svc_on https-server', auto)
        self.assertIn('https-server)', auto)
        diag = read('www/diagnostics.html')
        self.assertIn('cgi-bin/httpscert.cgi', diag)
        cs = read('controlscripts/https-server')
        self.assertIn('privdrop_opt net', cs)
        self.assertIn('netacl_allow_list', cs)


class HttpsdShellBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='httpsd-sh-'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_httpscert_cgi_missing_and_present(self):
        cgi = str(ROOT / 'www/cgi-bin/httpscert.cgi')
        cert = self.tmp / 'https-cert.pem'
        env = dict(os.environ, HTTPS_CERT_FILE=str(cert))

        r_miss = subprocess.run(SH + [cgi], capture_output=True, env=env)
        self.assertEqual(r_miss.returncode, 0)
        self.assertIn(b'Status: 404 Not Found', r_miss.stdout)

        pem = b'-----BEGIN CERTIFICATE-----\nTESTCERT\n-----END CERTIFICATE-----\n'
        cert.write_bytes(pem)
        r_ok = subprocess.run(SH + [cgi], capture_output=True, env=env)
        self.assertEqual(r_ok.returncode, 0)
        self.assertIn(b'Content-Type: application/x-pem-file', r_ok.stdout)
        self.assertIn(b'filename="tc100-https-cert.pem"', r_ok.stdout)
        self.assertTrue(r_ok.stdout.endswith(pem))
        self.assertNotIn('https-key.pem', read('www/cgi-bin/httpscert.cgi'))

    def test_controlscript_disabled_and_start_stop(self):
        cs = str(ROOT / 'controlscripts/https-server')
        conf = self.tmp / 'boot.conf'
        pidf = self.tmp / 'https-server.pid'
        logf = self.tmp / 'https-server.log'
        fake = self.tmp / 'tc100-httpsd'
        args_file = self.tmp / 'args.txt'
        fake.write_text(f'#!/bin/sh\necho "$*" > "{args_file}"\nsleep 30\n')
        os.chmod(fake, 0o755)

        conf.write_text('HTTPS=0\n')
        env = dict(
            os.environ,
            HTTPSD_BIN=str(fake),
            HTTPSD_CONF=str(conf),
            HTTPSD_CERTDIR=str(self.tmp),
            HTTPSD_PIDFILE=str(pidf),
            HTTPSD_LOG=str(logf),
        )
        r_dis = subprocess.run(SH + [cs, 'start'], capture_output=True, text=True, env=env)
        self.assertEqual(r_dis.returncode, 0, r_dis.stderr)
        self.assertIn('disabled in boot.conf', r_dis.stdout)
        self.assertFalse(pidf.exists())

        conf.write_text('HTTPS=1\nHTTPS_PORT=8443\nHTTPS_MAX_CONNS=3\nHTTPS_NICE=6\nWEB_LOCKOUT=1\n')
        try:
            r_st = subprocess.run(SH + [cs, 'start'], capture_output=True, text=True, env=env)
            self.assertEqual(r_st.returncode, 0, r_st.stderr)
            self.assertTrue(pidf.exists())
            deadline = time.time() + 2.0
            while time.time() < deadline and (not args_file.exists() or args_file.stat().st_size == 0):
                time.sleep(0.05)
            recorded = args_file.read_text(encoding='utf-8')
            self.assertIn('-p 8443', recorded)
            self.assertIn('-b 80', recorded)
            self.assertIn('-m 3', recorded)
            self.assertIn('-n 6', recorded)
            self.assertIn('-L', recorded)
        finally:
            subprocess.run(SH + [cs, 'stop'], capture_output=True, env=env)
            self.assertFalse(pidf.exists())


class WebUi32ImprovementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='webui32-'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cpuprofile_cgi_removed(self):
        self.assertFalse((ROOT / 'www/cgi-bin/cpuprofile.cgi').exists())
        self.assertNotIn('/cgi-bin/cpuprofile.cgi', read('docs/api.md'))
        self.assertNotIn('cpuprofile.cgi', read('docs/linux-port/performance.md'))

    def test_ui_security_sd_trial_and_support_bundle_links(self):
        idx = read('www/index.html')
        self.assertIn('id="sd_trial_badge"', idx)
        self.assertIn('data-tab="tab-backup"', idx)
        self.assertIn('sdt.hidden = st.storage === "flash"', read('src/webui/index/10-status.js'))
        diag = read('www/diagnostics.html')
        self.assertIn('id="sec32_diag_facts"', diag)
        self.assertIn('cmd=security_status&format=json', diag)
        sett = read('www/settings.html')
        self.assertIn('href="cgi-bin/supportbundle.cgi"', sett)
        self.assertIn('href="cgi-bin/httpscert.cgi"', sett)
        self.assertIn('id="secSigForm"', sett)
        self.assertIn('name="require_sig"', sett)
        self.assertEqual(sett.count('initSecurityPolicy'), 1)

    def test_i18n_complete_after_ui_changes(self):
        r = subprocess.run(['python3', str(ROOT / 'src/webui/i18n-strings.py'), '--missing'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '', f'missing French i18n keys:\n{r.stdout}')

    def test_security_status_and_policy_handlers(self):
        action_cgi = read('www/cgi-bin/action.cgi')
        self.assertIn('security_status', action_cgi.split('ACTION_GET_READS="')[1].split('"')[0].split())
        self.assertNotIn('set_update_sig_policy', action_cgi.split('ACTION_GET_READS="')[1].split('"')[0].split())

        sys_sh = read('scripts/action.d/system.sh')
        sec_block = sys_sh[sys_sh.index('    security_status)'):sys_sh.rindex('  esac')]
        boot = self.tmp / 'boot.conf'
        boot.write_text('PRIVDROP=1\nUPDATE_REQUIRE_SIG=0\nHTTPS=1\nHTTPS_PORT=8443\n')
        vkeys = self.tmp / 'vkeys'
        vkeys.mkdir()
        (vkeys / 'owner.pub').write_text('00' * 32)
        ckeys = self.tmp / 'ckeys'
        ckeys.mkdir()
        cert = self.tmp / 'https-cert.pem'
        cert.write_text('CERT')
        flash = self.tmp / 'flashmode'
        flash.write_text('1')

        helpers = (
            'wants_json_response() { return 0; }\n'
            'json_body_ok() { printf \'{"ok":true,"message":"%s"}\\n\' "$1"; }\n'
            'json_body_err() { printf \'{"ok":false,"error":"%s","message":"%s"}\\n\' "$1" "$2"; }\n'
            'install_config() { :; }\n'
            'rewrite_config() { grep -q "^$2=" "$1" && sed -i.bak "s/^$2=.*/$2=$3/" "$1" || echo "$2=$3" >> "$1"; }\n'
        )
        env = dict(
            os.environ,
            TC100_BOOT_CONF=str(boot),
            TC100_VENDOR_KEYS=str(vkeys),
            TC100_USER_KEYS=str(ckeys),
            HTTPS_CERT_FILE=str(cert),
            TC100_FLASHMODE_FILE=str(flash),
        )
        st_cmd = f'{helpers}case "security_status" in\n{sec_block}\nesac\n'
        r1 = subprocess.run(SH + ['-c', st_cmd], capture_output=True, text=True, env=env)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        d1 = json.loads(r1.stdout)
        self.assertEqual((d1['privdrop'], d1['update_require_sig'], d1['sig_keys'], d1['https_port'], d1['https_cert'], d1['flashmode']),
                         (1, 0, 1, 8443, 1, 1))
        self.assertEqual(d1['sig_key_ids'], 'owner')

        set_cmd = f'{helpers}F_require_sig=1\ncase "set_update_sig_policy" in\n{sec_block}\nesac\n'
        r2 = subprocess.run(SH + ['-c', set_cmd], capture_output=True, text=True, env=env)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        d2 = json.loads(r2.stdout)
        self.assertEqual((d2['ok'], d2['update_require_sig'], d2['sig_keys'], d2['effective']), (True, 1, 1, 1))
        self.assertIn('UPDATE_REQUIRE_SIG=1', boot.read_text())


if __name__ == '__main__':
    unittest.main()
