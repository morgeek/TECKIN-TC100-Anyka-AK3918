"""Item 8 of the implementer list: a 1280x720 main stream (Settings -> Main stream -> Resolution).

- kernel patch 0016: the ISP crops the whole 1080p window and scales the main channel to the format; the read-only
  parameter ak39_vi.main_scale tells user space;
- the setting is [0] mainres of rtspserver.conf (720 or 1080), written only by set_video_params: [0] width / height
  hold 1280x720 on cameras where a compatibility profile was applied, and must not change their size at an update;
- state.cgi reports 1280x720 only when mainres is 720 and the kernel scales; the 720p choice is greyed out otherwise.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def function(path, name):
    m = re.search(r'^' + re.escape(name) + r'\(\)\s*\{.*?^}', text(path), re.M | re.S)
    if not m:
        raise AssertionError((path, name))
    return m.group(0)


class KernelPatch(unittest.TestCase):
    def test_crop_is_the_whole_window_and_the_parameter_is_read_only(self):
        p = text('patches/kernel-6.6/series/0016-media-anyka-isp-scale-a-smaller-main-format-from-the.patch')
        self.assertIn('+		ret = ispdrv_vi_set_crop(l, t, CROP_W, CROP_H);', p)
        self.assertIn('-		ret = ispdrv_vi_set_crop(l, t, vi->width, vi->height);', p)
        self.assertIn('+module_param(main_scale, bool, 0444);', p)
        self.assertIn('Sixteen patches', text('patches/kernel-6.6/series/README.md'))


class StreamSummary(unittest.TestCase):
    """state.cgi read_rtsp_stream_summary with the C_* values load_conf_file sets"""

    def summary(self, scale, **conf):
        with tempfile.TemporaryDirectory() as t:
            param = Path(t, 'main_scale')
            if scale:
                param.write_text('Y\n')
            code = '\n'.join(function('www/cgi-bin/state.cgi', n) for n in ('cfg_int', 'codec_name_to', 'read_rtsp_stream_summary'))
            code += ''.join('\nC_%s=%s' % kv for kv in conf.items())
            code += '\nexport TC100_VI_SCALE_PARAM=%s\nread_rtsp_stream_summary\nprintf "%%sx%%s %%s" "$width0" "$height0" "$main_720"' % param
            r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_720p_only_with_mainres_and_a_scaling_kernel(self):
        self.assertEqual(self.summary(True, **{'0_mainres': 720}), '1280x720 true')
        self.assertEqual(self.summary(False, **{'0_mainres': 720}), '1920x1080 false')
        self.assertEqual(self.summary(True), '1920x1080 true')

    def test_width_and_height_of_a_compatibility_profile_change_nothing(self):
        self.assertEqual(self.summary(True, **{'0_width': 1280, '0_height': 720}), '1920x1080 true')


class Wiring(unittest.TestCase):
    def test_launcher_reads_mainres_only(self):
        s = text('v3/linux66-sd/rtsp-launch.sh')
        self.assertIn('[ "$(LD_LIBRARY_PATH=/mnt/lib /mnt/bin/rwconf $CONF r 0 mainres 2>/dev/null)" = 720 ] && export RTSP_WIDTH=1280 RTSP_HEIGHT=720', s)
        self.assertNotIn('r 0 width 0 height', s)
        self.assertLess(s.index('RTSP_WIDTH=1280'), s.index('/mnt/config/rtsp.env'))     # rtsp.env still overrides

    def test_set_video_params_writes_mainres(self):
        v = text('scripts/action.d/video.sh')
        body = v[v.index('    set_video_params)'):v.index('    rtsp-log-off)')]
        self.assertIn('1280x720) [ "$_v720" = 1 ] && raw_size=1280x720 ;;', body)
        self.assertIn('$( [ "$stream_idx" = 0 ] && echo "0 mainres $height" )', body)
        self.assertIn('/sys/module/ak39_vi/parameters/main_scale', body)

    def test_settings_page(self):
        html = text('www/settings.html')
        self.assertIn('<select name="video_size0" id="video_size0"><option value="1920x1080">1920 x 1080 (1080p)</option>'
                      '<option value="1280x720">1280 x 720 (720p, lighter)</option></select>', html)
        js = text('src/webui/index/95-settings-page.js')
        self.assertIn("if (o720) o720.disabled = vid.main_720 !== true;", js)
        self.assertIn('"video":{"rtsp_port":%s,"main_720":%s,"main":{', text('www/cgi-bin/state.cgi'))
        self.assertIn('"$rtsp_port" "$main_720" \\', text('www/cgi-bin/state.cgi'))


class SmartPoolTestKernel(unittest.TestCase):
    """Item 9: a manual CI run with venc_pool builds a test kernel with another compiled encoder pool default; a push
    builds the normal one, and the test artifacts carry the pool in their name"""

    def test_workflow_input(self):
        wf = text('.github/workflows/build-kernel-linux66.yml')
        self.assertIn('      venc_pool:\n', wf)
        self.assertIn('VP="${{ github.event.inputs.venc_pool }}"\n          if [ -n "$VP" ]; then', wf)
        self.assertIn('[ "$n" -ge 4096 ] && [ "$n" -le 12288 ]', wf)
        self.assertIn('sed -i "s/static char \\*pool = \\"9600K\\";/static char *pool = \\"$VP\\";/" drivers/misc/ak39_venc.c', wf)
        self.assertIn("format('-TESTKERNEL-pool{0}', github.event.inputs.venc_pool)", wf)
        self.assertIn('+static char *pool = "9600K";', text('patches/kernel-6.6/series/0015-misc-ak39_venc-encoder-pool-from-a-reusable-CMA-area.patch'))


if __name__ == '__main__':
    unittest.main()
