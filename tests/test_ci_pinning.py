"""Item CI-PIN (audit 2026-11-16): the CI inputs are pinned and the builds are reproducible.

- every `uses:` of the workflows is a full commit SHA (local actions `./` excepted);
- every download of the workflows and of the build scripts is followed by a hash check (one place: .github/ci-pins.sh);
- SOURCE_DATE_EPOCH reaches the build jobs and the tools that write times into the images;
- the `vendor` flash partition has a CI budget check.
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINS = os.path.join(ROOT, '.github', 'ci-pins.sh')


def text(p):
    with open(os.path.join(ROOT, p), encoding='utf-8', newline='') as f:
        return f.read()


def code_lines(p):
    """the lines of a script or workflow that are not comments"""
    return [l for l in text(p).splitlines() if not l.lstrip().startswith('#')]


WORKFLOWS = sorted(os.path.relpath(f, ROOT).replace(os.sep, '/')
                   for f in glob.glob(os.path.join(ROOT, '.github', 'workflows', '*.yml')))
# scripts that fetch something at build time (the camera-side scripts use curl at run time: not builds)
BUILD_SCRIPTS = (['.github/ci-pins.sh', 'scripts/build-kernel-docker.sh', 'tests/docker/local-ci.sh', 'tests/ci-vendor-budget.sh']
                 + sorted(os.path.relpath(f, ROOT).replace(os.sep, '/')
                          for pat in ('tests/docker/*.sh', 'v3/build-*.sh', 'v3/musl/*.sh')
                          for f in glob.glob(os.path.join(ROOT, pat))))
BUILD_SCRIPTS = sorted(set(BUILD_SCRIPTS))
DOWNLOAD = re.compile(r'(^|[\s;|&(`])(curl|wget)\s+-')
CLONE = re.compile(r'\bgit\s+clone\b')


class ActionsPinned(unittest.TestCase):
    def test_workflows_found(self):
        self.assertEqual(len(WORKFLOWS), 3, WORKFLOWS)

    def test_every_uses_is_a_full_sha(self):
        n = 0
        for w in WORKFLOWS:
            for i, l in enumerate(code_lines(w)):
                m = re.match(r'\s*(?:-\s*)?uses:\s*(\S+)(.*)$', l)
                if not m:
                    continue
                ref = m.group(1)
                if ref.startswith('./'):
                    continue
                n += 1
                self.assertRegex(ref, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$', '%s: %s' % (w, l))
                # the tag it stands for, for the reader and for the next update
                self.assertRegex(m.group(2), r'^\s+#\s*v\d+(\.\d+)*\s*$', '%s: %s has no "# vX.Y.Z" comment' % (w, l))
        self.assertGreaterEqual(n, 10)


class DownloadsChecked(unittest.TestCase):
    def test_pin_values(self):
        s = text('.github/ci-pins.sh')
        for k in ('LINUX_COMMIT', 'BUILDROOT_COMMIT'):
            self.assertRegex(s, r'(?m)^%s=[0-9a-f]{40}$' % k)
        for k in ('MBEDTLS_SHA256', 'RTL8188FU_FW_SHA256'):
            self.assertRegex(s, r'(?m)^%s=[0-9a-f]{64}$' % k)
        # the firmware checksum of the kernel series README is the same one (a single value to keep)
        m = re.search(r'(?m)^RTL8188FU_FW_SHA256=(\w+)$', s)
        readme = text('patches/kernel-6.6/series/README.md')
        self.assertTrue('ci-pins.sh' in readme or m.group(1) in readme)
        self.assertRegex(text('v3/musl/build-musl.sh'), r'(?m)^SHA=[0-9a-f]{64}$')

    def test_kernel_base_is_a_stable_release(self):
        # the series is applied on a 6.6.y stable tag (not the bare v6.6); the torvalds mirror has no stable tags,
        # so a stable mirror must be among the sources, and no script may hardcode a base tag of its own
        s = text('.github/ci-pins.sh')
        self.assertRegex(s, r'(?m)^LINUX_TAG=v6\.6\.\d+$')
        self.assertRegex(s, r'(?m)^LINUX_URLS=.*(stable/linux\.git|gregkh/linux\.git)')
        local = text('tests/docker/local-ci.sh')
        self.assertNotIn('/k/v6.6', local)
        self.assertNotIn('--hard v6.6', local)

    def test_each_file_that_downloads_checks_a_hash(self):
        for f in WORKFLOWS + BUILD_SCRIPTS:
            lines = code_lines(f)
            body = '\n'.join(lines)
            if f == '.github/ci-pins.sh':
                # the helper itself: curl is followed by sha256sum -c, a clone by the comparison of HEAD
                self.assertIn('sha256sum -c', body)
                self.assertIn('rev-parse HEAD', body)
                continue
            for l in lines:
                if DOWNLOAD.search(l):
                    # a direct download is only allowed in a script that checks a SHA-256 afterwards
                    self.assertIn('sha256sum -c', body, '%s: %s' % (f, l.strip()))
                    self.assertNotRegex(l, r'\|\s*(tar|sh|bash|python3?)\b', '%s pipes a download into a tool: %s' % (f, l.strip()))
                if CLONE.search(l):
                    self.fail('%s clones without git_clone_pinned (tag and commit): %s' % (f, l.strip()))

    def test_downloads_go_through_the_helpers(self):
        for f in ('.github/workflows/build-kernel-linux66.yml', '.github/workflows/build-base-rootfs.yml',
                  'scripts/build-kernel-docker.sh', 'tests/docker/whep-interop.sh', 'tests/docker/whep-musl.sh',
                  'tests/docker/local-ci.sh'):
            self.assertIn('ci-pins.sh', text(f), f)
        self.assertIn('git_clone_pinned "$LINUX_TAG" "$LINUX_COMMIT"', text('.github/workflows/build-kernel-linux66.yml'))
        self.assertIn('git_clone_pinned "$BUILDROOT_TAG" "$BUILDROOT_COMMIT"', text('.github/workflows/build-base-rootfs.yml'))
        self.assertIn('fetch_sha256 "$RTL8188FU_FW_SHA256"', text('.github/workflows/build-kernel-linux66.yml'))
        for f in ('tests/docker/whep-interop.sh', 'tests/docker/whep-musl.sh'):
            self.assertIn('fetch_sha256 "$MBEDTLS_SHA256"', text(f))

    def test_pip_is_hash_pinned(self):
        for f in WORKFLOWS + BUILD_SCRIPTS:
            for l in code_lines(f):
                if re.search(r'\bpip3?\s+install\b', l):
                    self.assertIn('--require-hashes', l, '%s: %s' % (f, l.strip()))
        req = text('tests/docker/requirements-whep-interop.txt')
        names = re.findall(r'(?m)^([A-Za-z0-9_.-]+)==\S+ \\$', req)
        self.assertIn('aiortc', names)
        # every pinned package carries hashes
        for block in re.split(r'(?m)^(?=[A-Za-z0-9_.-]+==)', req)[1:]:
            self.assertIn('--hash=sha256:', block.split('\n', 1)[0] + '\n' + block, block[:40])
        self.assertEqual(len(re.findall(r'(?m)^[A-Za-z0-9_.-]+==', req)), len(names))

    def test_npm_uses_the_lock_file(self):
        for f in WORKFLOWS + BUILD_SCRIPTS:
            for l in code_lines(f):
                self.assertNotRegex(l, r'\bnpm\s+(install|i)\b(?!.*--package-lock-only)', '%s: %s' % (f, l.strip()))
        self.assertIn('npm ci --prefix src/webui', text('.github/workflows/build-kernel-linux66.yml'))
        lock = text('src/webui/package-lock.json')
        self.assertEqual(lock.count('"resolved"'), lock.count('"integrity"'))
        self.assertIn('"node_modules/esbuild"', lock)
        self.assertIn('"version": "0.25.12"', lock)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('sh') and shutil.which('curl') and shutil.which('sha256sum'), 'needs POSIX sh, curl, sha256sum')
    def test_fetch_sha256_refuses_a_wrong_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'src.bin')
            with open(src, 'wb') as f:
                f.write(b'tc100')
            good = subprocess.run(['sha256sum', src], capture_output=True, text=True).stdout.split()[0]
            script = '. "$1"; fetch_sha256 "$2" "$3" "file://$4"'
            out = os.path.join(d, 'out.bin')
            ok = subprocess.run(['sh', '-c', script, 'x', PINS, good, out, src], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertTrue(os.path.exists(out))
            os.remove(out)
            bad = subprocess.run(['sh', '-c', script, 'x', PINS, '0' * 64, out, src], capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(os.path.exists(out), 'a file with the wrong hash must be removed')

    @unittest.skipUnless(os.name == 'posix' and shutil.which('sh') and shutil.which('git'), 'needs POSIX sh, git')
    def test_git_clone_pinned_checks_the_commit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, 'r')
            g = ['git', '-c', 'user.name=t', '-c', 'user.email=t@localhost', '-C', repo]
            os.mkdir(repo)
            subprocess.run(['git', 'init', '-q', repo], check=True)
            subprocess.run(g + ['commit', '-q', '--allow-empty', '-m', 'one'], check=True)
            subprocess.run(g + ['tag', 'v1'], check=True)
            head = subprocess.run(g + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
            script = '. "$1"; git_clone_pinned v1 "$2" "$3" "file://$4"'
            dst = os.path.join(d, 'c')
            ok = subprocess.run(['sh', '-c', script, 'x', PINS, head, dst, repo], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            bad = subprocess.run(['sh', '-c', script, 'x', PINS, 'f' * 40, dst, repo], capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(os.path.exists(dst))


class Reproducible(unittest.TestCase):
    def test_build_jobs_set_source_date_epoch(self):
        k = text('.github/workflows/build-kernel-linux66.yml')
        self.assertIn('SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)', k)
        self.assertIn('>> "$GITHUB_ENV"', k)
        for v in ('KBUILD_BUILD_USER', 'KBUILD_BUILD_HOST', 'KBUILD_BUILD_TIMESTAMP', 'TZ: UTC'):
            self.assertIn(v, k)
        # set before the first build step (the kernel is compiled after it)
        self.assertLess(k.index('SOURCE_DATE_EPOCH=$(git log'), k.index('Compile zImage'))
        b = text('.github/workflows/build-base-rootfs.yml')
        self.assertIn('export SOURCE_DATE_EPOCH=', b)
        # BR2_REPRODUCIBLE is left off (review of CI-PIN: it changes the build flags of every base binary)
        self.assertNotRegex(text('v3/buildroot/configs/tc100_defconfig'), r'(?m)^BR2_REPRODUCIBLE=y$')
        self.assertIn('sudo env SOURCE_DATE_EPOCH=', text('.github/workflows/build-kernel-linux66.yml'))
        self.assertNotIn('-mem 8M', text('tests/ci-vendor-budget.sh'))

    def test_image_tools_get_the_time(self):
        self.assertRegex(text('v3/build-stack.sh'), r'-mkfs-time \$SOURCE_DATE_EPOCH -all-time \$SOURCE_DATE_EPOCH')
        # mksquashfs 4.6 refuses the variable together with the options
        self.assertIn('env -u SOURCE_DATE_EPOCH mksquashfs', text('v3/build-stack.sh'))
        r = text('v3/build-rootfs66.sh')
        for v in ('--reproducible', 'LC_ALL=C sort', 'touch -h -d "@$SOURCE_DATE_EPOCH"'):
            self.assertIn(v, r)
        rel = text('v3/build-release.sh')
        for v in ('--mtime="@$SOURCE_DATE_EPOCH"', '--owner=0', '--group=0', '--numeric-owner', 'LC_ALL=C sort'):
            self.assertIn(v, rel)

    def test_gzip_leaves_no_name_or_time(self):
        for f in WORKFLOWS + BUILD_SCRIPTS:
            for l in code_lines(f):
                for m in re.finditer(r'\bgzip\b([^|;&]*)', l):
                    args = m.group(1)
                    if re.search(r'(^|\s)-\w*d', args) or 'dc' in args.split()[:1]:
                        continue       # decompression
                    if re.search(r'\bgzip\b', l) and not re.search(r'(^|\s)-\w*n', args):
                        self.fail('%s: gzip without -n: %s' % (f, l.strip()))


class VendorBudget(unittest.TestCase):
    def test_ci_runs_the_vendor_budget(self):
        k = text('.github/workflows/build-kernel-linux66.yml')
        self.assertIn('sh tests/ci-vendor-budget.sh', k)
        self.assertIn('scripts/flash_budget.py --kernel output/oipc.img --initrd', k)
        s = text('tests/ci-vendor-budget.sh')
        self.assertIn('flash_budget.py', s)
        self.assertIn('--vendor', s)

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('sh'), 'needs mksquashfs')
    def test_vendor_stand_in_fits(self):
        r = subprocess.run(['sh', os.path.join(ROOT, 'tests', 'ci-vendor-budget.sh')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('vendor', r.stdout)
        self.assertIn('OK', r.stdout)


if __name__ == '__main__':
    unittest.main()
