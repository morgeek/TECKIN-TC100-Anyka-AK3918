"""3D-NR switch (docs/linux-port/plans-2026-11-12.md section 2, test queue NR3D-01).

- the kernel series still applies (every patch, and the anyka-isp files in order on a scratch tree);
- ak39_vi.nr3d is a 0644 module_param_cb, default 0, nr3d_overflow a 0444 counter fed by the ISR;
- program_ref() programs the crop size, not the output size, and refuses a smaller allocation;
- autorun-linux66.sh writes the sysfs switch only when boot.conf says NR3D=1; NR3D lives in boot.conf.dist only;
- the memory map of the device tree was not changed (no second reserved region, encoder area as before).
"""
from pathlib import Path
import glob
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERIES = sorted(glob.glob(str(ROOT / 'patches/kernel-6.6/series/00*.patch')))
ASH = ['busybox', 'ash'] if shutil.which('busybox') else ['/bin/sh']


def patch(prefix):
    return Path(next(p for p in SERIES if Path(p).name.startswith(prefix))).read_text(encoding='utf-8', errors='replace')


def git_apply(args, cwd):
    return subprocess.run(['git', 'apply', '-q', '--whitespace=nowarn'] + args, cwd=cwd, capture_output=True, text=True)


class SeriesApplies(unittest.TestCase):
    def test_every_patch_is_well_formed(self):
        for p in SERIES:
            r = subprocess.run(['git', 'apply', '--stat', p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, (p, r.stderr))

    def test_new_file_hunk_counts(self):
        """Every '@@ -0,0 +1,N @@' of patch 0006 (and of the others) holds exactly N added lines."""
        for p in SERIES:
            lines = Path(p).read_text(encoding='utf-8', errors='replace').split('\n')
            for i, line in enumerate(lines):
                m = re.match(r'@@ -0,0 \+1,(\d+) @@', line)
                if not m:
                    continue
                j = i + 1
                while j < len(lines) and not lines[j].startswith('diff --git') and lines[j] != '-- ':
                    j += 1
                n = sum(1 for x in lines[i + 1:j] if x.startswith('+'))
                self.assertEqual(n, int(m.group(1)), (Path(p).name, i + 1))

    def test_isp_files_apply_in_order(self):
        if not shutil.which('git'):
            self.skipTest('no git')
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git', 'init', '-q', d], check=True)
            for prefix in ('0006', '0011', '0012', '0014', '0016'):
                p = next(x for x in SERIES if Path(x).name.startswith(prefix))
                r = git_apply(['--include=drivers/media/platform/anyka-isp/*', '--include=include/*', p], d)
                self.assertEqual(r.returncode, 0, (prefix, r.stderr))
            src = (Path(d) / 'drivers/media/platform/anyka-isp/ak39_vi.c').read_text(encoding='utf-8')
            prog = src[src.index('static void program_ref('):]
            prog = prog[:prog.index('\n}\n')]
            self.assertNotIn('vi->width', prog)
            self.assertNotIn('vi->height', prog)
            self.assertIn('size_t px = CROP_W * CROP_H;', prog)
            # refuses (noref) an allocation smaller than the crop
            self.assertIn('px * 2 > vi->ref_y_bytes || px > vi->ref_uv_bytes', prog)
            self.assertIn('ispdrv_vp_3d_nr_noref(1);', prog)
            self.assertNotIn('dma_alloc', prog)
            alloc = src[src.index('static int alloc_ref('):]
            alloc = alloc[:alloc.index('\n}\n')]
            self.assertIn('size_t px = CROP_W * CROP_H;', alloc)

    def test_uv_venc_tail_patch_applies(self):
        if not shutil.which('git'):
            self.skipTest('no git')
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git', 'init', '-q', d], check=True)
            for prefix in ('0006', '0008', '0011', '0012', '0014', '0015', '0016', '0017'):
                p = next(x for x in SERIES if Path(x).name.startswith(prefix))
                r = git_apply([
                    '--include=drivers/media/platform/anyka-isp/*',
                    '--include=drivers/misc/ak39_venc.c',
                    '--include=include/*',
                    p,
                ], d)
                self.assertEqual(r.returncode, 0, (prefix, r.stderr))
            vi = (Path(d) / 'drivers/media/platform/anyka-isp/ak39_vi.c').read_text(encoding='utf-8')
            venc = (Path(d) / 'drivers/misc/ak39_venc.c').read_text(encoding='utf-8')
            self.assertIn('ak39_venc_aux_alloc', vi)
            self.assertIn('ref_uv_venc', vi)
            self.assertIn('EXPORT_SYMBOL_GPL(ak39_venc_aux_alloc);', venc)


class KernelSwitch(unittest.TestCase):
    def setUp(self):
        self.p6 = patch('0006')

    def test_nr3d_is_a_writable_callback_param_default_off(self):
        self.assertIn('+static int nr3d;\n', self.p6)
        self.assertIn('+static const struct kernel_param_ops nr3d_ops = {\n+\t.set = nr3d_set,\n+\t.get = param_get_int,\n+};\n'
                      '+module_param_cb(nr3d, &nr3d_ops, &nr3d, 0644);', self.p6)
        self.assertNotIn('module_param(nr3d,', self.p6)
        # the command-line form still allocates at probe
        self.assertIn('+\tif (nr3d)\n+\t\talloc_ref(vi);', self.p6)

    def test_set_callback_rules(self):
        body = self.p6[self.p6.index('+static int nr3d_set('):]
        body = body[:body.index('\n+}\n')]
        self.assertIn('vb2_is_streaming(&vi->q)', body)
        self.assertIn('ret = -EBUSY;', body)
        self.assertIn('ret = alloc_ref(vi);', body)
        self.assertIn('if (v < 0 || v > 1)', body)
        self.assertNotIn('dma_free', body)
        # the driver pointer is published only once probe succeeded, and withdrawn first at remove
        probe = self.p6[self.p6.index('+\tplatform_set_drvdata(pdev, vi);'):]
        self.assertTrue(probe.startswith('+\tplatform_set_drvdata(pdev, vi);\n+\tmutex_lock(&nr3d_lock);\n+\tnr3d_vi = vi;'))
        self.assertIn('+\tstruct ak39_vi *vi = platform_get_drvdata(pdev);\n+\n+\tmutex_lock(&nr3d_lock);\n+\tnr3d_vi = NULL;\n+\tmutex_unlock(&nr3d_lock);', self.p6)
        # 0 while idle gives the memory back; the ISP is touched only while streaming and the setter is NULL-safe
        self.assertIn('} else if (!v) {\n+\t\t\tfree_ref(vi);', body)
        noref = self.p6[self.p6.index('+void ak_isp_set_3d_nr_noref('):]
        noref = noref[:noref.index('\n+}\n')]
        self.assertIn('if (!isp)\n+\t\treturn;', noref)

    def test_overflow_param_refuses_a_command_line_value(self):
        self.assertIn('+static int nr3d_overflow_set(const char *val, const struct kernel_param *kp)\n+{\n+\treturn -EPERM;', self.p6)
        self.assertIn('+\t.set = nr3d_overflow_set,', self.p6)

    def test_overflow_counter(self):
        self.assertIn('+module_param_cb(nr3d_overflow, &nr3d_overflow_ops, NULL, 0444);', self.p6)
        isr = self.p6[self.p6.index('+int ak_isp_irq_work(void)'):]
        isr = isr[:isr.index('\n+}\n')]
        self.assertIn('WRITE_ONCE(tnr_overflow, tnr_overflow + 1);', isr)
        self.assertIn('+EXPORT_SYMBOL(ispdrv_vp_3d_nr_overflow);', self.p6)

    def test_memory_map_unchanged(self):
        dts = patch('0009')
        self.assertEqual(len(re.findall(r'shared-dma-pool', dts)), 2)      # default CMA node + encoder area, nothing new
        self.assertIn('reg = <0x81800000 0xc00000>;', dts)
        self.assertNotIn('nr3d', dts.lower())


class Userspace(unittest.TestCase):
    def block(self):
        s = (ROOT / 'v3/autorun-linux66.sh').read_text(encoding='utf-8')
        i = s.index('  case "${BC_NR3D:-auto}" in')
        j = s.index('  sh $TB/rtsp-launch.sh', i)
        return s[i:j], s, i, j

    def run_block(self, value):
        block, _, _, _ = self.block()
        with tempfile.TemporaryDirectory() as d:
            par = Path(d) / 'parameters'
            par.mkdir()
            (par / 'nr3d').write_text('0\n')
            (par / 'nr3d_overflow').write_text('0\n')
            code = block.replace('/sys/module/ak39_vi/parameters', str(par)).replace('> /dev/console', '>&2')
            code = 'BC_NR3D=%s\n' % value + code
            r = subprocess.run(ASH + ['-c', code], capture_output=True, text=True, timeout=30)
            return (par / 'nr3d').read_text().strip(), r.stderr

    def test_sysfs_written_for_nr3d_1_and_auto(self):
        for v in ('1', 'auto', ''):
            val, err = self.run_block(v)
            self.assertEqual(val, '1', v)
            self.assertIn('3D-NR ready (NR3D=', err, v)
        for v in ('0', 'yes', '2'):
            val, err = self.run_block(v)
            self.assertEqual(val, '0', v)
            self.assertEqual(err, '', v)

    def test_block_runs_before_the_video_server_and_writes_once(self):
        _, s, i, j = self.block()
        self.assertLess(i, s.index('sh $TB/rtsp-launch.sh'))
        self.assertEqual(len(re.findall(r'echo 1 > /sys/module/ak39_vi/parameters/nr3d', s)), 1)

    def test_nr3d_only_in_boot_conf_dist(self):
        boot = (ROOT / 'config/boot.conf.dist').read_text(encoding='utf-8')
        self.assertEqual(len(re.findall(r'^NR3D=auto$', boot, re.M)), 1)
        for p in (ROOT / 'config').glob('*.dist'):
            if p.name == 'boot.conf.dist':
                continue
            self.assertNotRegex(p.read_text(encoding='utf-8'), r'(?m)^#?\s*NR3D', p.name)
        launch = (ROOT / 'v3/linux66-sd/rtsp-launch.sh').read_text(encoding='utf-8')
        self.assertIn('NR3D_CFG=$(bc NR3D); case "${NR3D_CFG:-auto}" in auto) export RTSP_NR3D_AUTO=1 ;; esac', launch)


if __name__ == '__main__':
    unittest.main()
