"""[up-sbom] scripts/sbom.py and scripts/cve-report.py: the SBOM (CycloneDX 1.5) and the non-blocking CVE report.

Fixtures are made here (a small Buildroot show-info, a small pins file, a small repository tree): no network.
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sbom = load('tc100_sbom', 'scripts/sbom.py')
cve = load('tc100_cve', 'scripts/cve-report.py')


def text(p):
    with open(os.path.join(ROOT, p), encoding='utf-8', newline='') as f:
        return f.read()


SHOW_INFO = {
    'busybox': {'name': 'busybox', 'type': 'target', 'version': '1.36.1', 'licenses': 'GPL-2.0, bzip2-1.0.4',
                'downloads': [{'source': 'busybox-1.36.1.tar.bz2', 'uris': ['http+https://busybox.net/downloads']}]},
    'mbedtls': {'name': 'mbedtls', 'type': 'target', 'version': '9.9.9', 'licenses': 'Apache-2.0',
                'downloads': [{'source': 'x.tar.gz', 'uris': ['https+https://github.com/Mbed-TLS/mbedtls/releases/download/v9']}]},
    'host-pkgconf': {'name': 'host-pkgconf', 'type': 'host', 'version': '2.0', 'licenses': 'ISC'},
    'virtual-thing': {'name': 'virtual-thing', 'type': 'target', 'virtual': True, 'version': None},
    'tc100-whep': {'name': 'tc100-whep', 'type': 'target', 'version': '1.0', 'licenses': 'GPL-2.0'},
}
PINS = """LINUX_TAG=v6.6
LINUX_COMMIT=ffc253263a1375a65fa6c9f62a893e9767fbebfa
BUILDROOT_TAG=2099.02.1
BUILDROOT_COMMIT=d37527ba498c34508b9f3fede34135686c94581e
MBEDTLS_VERSION=3.6.9
MBEDTLS_SHA256=e85ea97aaf78dd6c0a5ba2e54dd5932ffa15f39abfc189c26beef7684630c02b
LINUX_FIRMWARE_TAG=20241017
RTL8188FU_FW_SHA256=e6189d6d7032b83f0ed4284629c43db66262449a866f33fd329e611239f62e1f
LINUX_URLS="https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git https://github.com/torvalds/linux.git"
MBEDTLS_URL="https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-$MBEDTLS_VERSION/mbedtls-$MBEDTLS_VERSION.tar.bz2"
"""


def make_tree(d):
    def w(rel, content):
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    w('VERSION', '7.7.7-rc1\n')
    w('.github/ci-pins.sh', PINS)
    w('v3/musl/build-musl.sh', 'VER=1.2.9\nURL=${MUSL_URL:-https://musl.libc.org/releases/musl-$VER.tar.gz}\n')
    w('patches/kernel-6.6/series/0001-first.patch', '')
    w('patches/kernel-6.6/series/0002-second.patch', '')
    for s in ('tc100rtsp', 'mqttd', 'whep', 'webui'):
        os.makedirs(os.path.join(d, 'src', s))
    w('src/webui/package-lock.json', json.dumps({'packages': {'node_modules/esbuild': {'version': '0.99.1'}}}))
    w('www/index.html', '')
    w('show-info.json', 'make: noise\n' + json.dumps(SHOW_INFO))


class Sbom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        make_tree(d)
        cls.out = os.path.join(d, 'out', 'sbom')
        cls.rc = sbom.main(['--root', d, '--show-info', os.path.join(d, 'show-info.json'), '--commit', 'a' * 40, '--out', cls.out])
        with open(cls.out + '.cdx.json', encoding='utf-8') as f:
            cls.bom = json.load(f)
        with open(cls.out + '.md', encoding='utf-8') as f:
            cls.md = f.read()
        cls.by = {c['name']: c for c in cls.bom['components']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_required_fields(self):
        b = self.bom
        self.assertEqual(self.rc, 0)
        self.assertEqual((b['bomFormat'], b['specVersion']), ('CycloneDX', '1.5'))
        self.assertRegex(b['serialNumber'], r'^urn:uuid:[0-9a-f-]{36}$')
        self.assertEqual(b['version'], 1)
        self.assertEqual(b['metadata']['component']['version'], '7.7.7-rc1')
        self.assertRegex(b['metadata']['timestamp'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        for c in b['components']:
            self.assertIn(c['type'], ('application', 'framework', 'library', 'container', 'operating-system', 'device', 'firmware', 'file'))
            for k in ('bom-ref', 'name', 'version'):
                self.assertTrue(c.get(k), (k, c))
            self.assertIn(c['scope'], ('required', 'optional', 'excluded'))

    def test_bom_refs_unique_and_dependencies_resolve(self):
        refs = [c['bom-ref'] for c in self.bom['components']] + ['tc100-firmware']
        self.assertEqual(len(refs), len(set(refs)))
        dep = self.bom['dependencies'][0]
        self.assertEqual(dep['ref'], 'tc100-firmware')
        for r in dep['dependsOn']:
            self.assertIn(r, refs)

    def test_kernel_and_free_programs(self):
        k = self.by['linux']
        self.assertEqual(k['version'], '6.6.0')
        self.assertIn('cpe:2.3:o:linux:linux_kernel:6.6.0', k['cpe'])
        pn = [p['value'] for p in k['properties'] if p['name'] == 'tc100:patch']
        self.assertEqual(pn, ['0001-first.patch', '0002-second.patch'])
        for n in ('tc100_rtsp', 'tc100-mqttd', 'tc100-webui'):
            c = self.by[n]
            self.assertEqual(c['version'], '7.7.7-rc1+' + 'a' * 12)
            self.assertEqual(c['licenses'][0]['license']['name'], 'GPL-2.0-only')
        self.assertEqual(self.by['rtl8188fufw']['version'], '20241017')
        self.assertEqual(self.by['rtl8188fufw']['hashes'][0]['content'], 'e6189d6d7032b83f0ed4284629c43db66262449a866f33fd329e611239f62e1f')

    def test_pins_and_musl_are_read_not_hardcoded(self):
        self.assertEqual(self.by['musl']['version'], '1.2.9')
        self.assertEqual(self.by['mbedtls-standalone']['version'], '3.6.9')
        self.assertIn('mbedtls-3.6.9.tar.bz2', self.by['mbedtls-standalone']['externalReferences'][0]['url'])
        self.assertEqual(self.by['buildroot']['version'], '2099.02.1')
        self.assertEqual(self.by['esbuild']['version'], '0.99.1')
        self.assertEqual(self.by['esbuild']['scope'], 'excluded')
        self.assertEqual(self.by['esbuild']['purl'], 'pkg:npm/esbuild@0.99.1')

    def test_buildroot_packages(self):
        self.assertEqual(self.by['busybox']['version'], '1.36.1')
        self.assertEqual([l['license']['name'] for l in self.by['busybox']['licenses']], ['GPL-2.0', 'bzip2-1.0.4'])
        self.assertEqual(self.by['mbedtls']['purl'], 'pkg:github/mbed-tls/mbedtls@9.9.9')
        self.assertNotIn('purl', self.by['busybox'])      # no purl invented where none exists
        self.assertNotIn('host-pkgconf', self.by)          # host tools are not in the image
        self.assertNotIn('virtual-thing', self.by)
        # tc100-whep comes once, from Buildroot (not a second time from src/whep)
        self.assertEqual(sum(1 for c in self.bom['components'] if c['name'] == 'tc100-whep'), 1)
        self.assertEqual(self.by['tc100-whep']['properties'][0]['value'], 'buildroot')

    def test_no_secret_or_local_path_leaks(self):
        blob = json.dumps(self.bom) + self.md
        self.assertNotIn(self.tmp.name, blob)
        self.assertNotRegex(blob, r'\b[A-Za-z]:[\\/](?!/)|/home/|/Users/|/tmp/|\\\\')
        self.assertNotRegex(blob, r'(?i)password|passwd|token|secret|api[_-]?key|BEGIN [A-Z ]*PRIVATE')
        self.assertNotRegex(blob, r'@[A-Za-z][\w-]*\.[A-Za-z]{2,}')

    def test_markdown_table(self):
        self.assertIn('| Component | Version | Licence | Source | Where |', self.md)
        self.assertIn('| linux | 6.6.0 |', self.md)
        self.assertIn('0001-first.patch', self.md)
        self.assertNotIn('\r', self.md)

    def test_without_show_info_it_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d)
            o = os.path.join(d, 'o')
            self.assertEqual(sbom.main(['--root', d, '--out', o, '--commit', 'b' * 40]), 0)
            with open(o + '.md', encoding='utf-8') as f:
                self.assertIn('NOT listed', f.read())

    def test_real_repository(self):
        with tempfile.TemporaryDirectory() as d:
            o = os.path.join(d, 'real')
            self.assertEqual(sbom.main(['--out', o]), 0)
            with open(o + '.cdx.json', encoding='utf-8') as f:
                b = json.load(f)
        names = {c['name'] for c in b['components']}
        self.assertTrue({'linux', 'tc100_rtsp', 'tc100-mqttd', 'musl', 'esbuild'} <= names, names)
        pins = text('.github/ci-pins.sh')
        tag = re.search(r'(?m)^LINUX_TAG=v?(\S+)$', pins).group(1)
        self.assertTrue(next(c for c in b['components'] if c['name'] == 'linux')['version'].startswith(tag))
        self.assertEqual(len({c['bom-ref'] for c in b['components']}), len(b['components']))


class CveReport(unittest.TestCase):
    def run_report(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d)
            o = os.path.join(d, 'sb')
            sbom.main(['--root', d, '--show-info', os.path.join(d, 'show-info.json'), '--commit', 'c' * 40, '--out', o])
            args = ['--sbom', o + '.cdx.json', '--out', os.path.join(d, 'cve')]
            for k, v in kw.items():
                if v is not None:
                    args += ['--' + k.replace('_', '-'), v(d) if callable(v) else v]
            self.assertEqual(cve.main(args), 0)
            with open(os.path.join(d, 'cve.json'), encoding='utf-8') as f:
                j = json.load(f)
            with open(os.path.join(d, 'cve.md'), encoding='utf-8') as f:
                return j, f.read()

    def test_kernel_fact(self):
        def rel(d):
            p = os.path.join(d, 'r.json')
            with open(p, 'w') as f:
                json.dump({'releases': [{'version': '6.6.163'}, {'version': '6.12.9'}, {'version': '6.6.162'}, {'version': '7.0'}]}, f)
            return p
        j, md = self.run_report(releases=rel)
        self.assertEqual(j['kernel']['behind'], 163)
        self.assertIn('kernel 6.6.0, latest 6.6.y is 6.6.163 (163 stable releases behind)', md)

    def test_nothing_fetched_says_so_and_does_not_fail(self):
        j, md = self.run_report()
        self.assertEqual(j['kernel']['state'], 'not-fetched')
        self.assertIn('could not be fetched', md)
        self.assertIn('NOT CHECKED', md)
        self.assertFalse(j['blocking'])
        self.assertTrue(j['data_problems'])

    def test_unreadable_inputs_do_not_fail(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cve.main(['--sbom', os.path.join(d, 'none.json'), '--releases', os.path.join(d, 'nor.json'),
                                       '--pkg-stats', os.path.join(d, 'nop.json'), '--out', os.path.join(d, 'c')]), 0)
            self.assertTrue(os.path.exists(os.path.join(d, 'c.md')))

    def test_pkg_stats_findings(self):
        def ps(d):
            p = os.path.join(d, 'ps.json')
            with open(p, 'w') as f:
                json.dump({'packages': {'busybox': {'version': '1.36.1', 'cves': ['CVE-2099-0001', 'CVE-2099-0001'], 'unsure_cves': []},
                                        'mbedtls': {'version': '9.9.9', 'cves': []}}}, f)
            return p
        j, md = self.run_report(pkg_stats=ps)
        self.assertEqual(j['buildroot_cve_total'], 1)
        self.assertIn('CVE-2099-0001', md)
        st = {r['name']: r['status'] for r in j['buildroot_packages']}
        self.assertEqual((st['busybox'], st['mbedtls'], st['tc100-whep']), ('findings', 'clean', 'no-data'))


class Workflows(unittest.TestCase):
    def test_base_workflow_saves_show_info(self):
        w = text('.github/workflows/build-base-rootfs.yml')
        self.assertIn('show-info > br-out/show-info.json', w)
        self.assertIn('base-out/*', w)
        self.assertIn('br-out/show-info.json', w)

    def test_kernel_workflow_makes_and_ships_the_sbom(self):
        w = text('.github/workflows/build-kernel-linux66.yml')
        self.assertIn('scripts/sbom.py --show-info base-rootfs/show-info.json --out output/release/sbom', w)
        for f in ('sbom.cdx.json', 'sbom.md', 'cve-report.md', 'cve-report.json'):
            self.assertIn('output/release/' + f, w)
            self.assertIn(f, w.split('gh release create')[0].split('EXTRA=')[1].split('\n')[0], f)
        self.assertIn('$EXTRA', w.split('gh release create')[1])

    def test_cve_step_is_non_blocking(self):
        w = text('.github/workflows/build-kernel-linux66.yml')
        i = w.index('- name: CVE report (non-blocking)')
        step = w[i:w.index('\n      - name:', i + 10)]
        self.assertIn('continue-on-error: true', step)
        self.assertIn('scripts/cve-report.sh', step)
        self.assertIn('|| true', step)
        sh = text('scripts/cve-report.sh')
        self.assertTrue(sh.rstrip().endswith('exit 0'))
        self.assertNotIn('set -e', sh)
        self.assertIn('git_clone_pinned "$BUILDROOT_TAG" "$BUILDROOT_COMMIT"', sh)
        self.assertNotRegex(sh, r'(^|\s)(curl|wget)\s')
        # the report script itself ends in exit 0 whatever happens
        py = text('scripts/cve-report.py')
        self.assertIn('except Exception', py)
        self.assertIn('sys.exit(0)', py)

    def test_lf_endings(self):
        for f in ('scripts/sbom.py', 'scripts/cve-report.py', 'scripts/cve-report.sh', 'tests/test_sbom.py',
                  'docs/linux-port/upgrade-3.2/sbom.md'):
            if os.path.exists(os.path.join(ROOT, f)):
                self.assertNotIn('\r', text(f), f)


if __name__ == '__main__':
    unittest.main()
