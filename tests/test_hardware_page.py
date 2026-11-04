"""Hardware test page (www/hardware.html, roadmap item 49): the commands it calls exist and are routed, the live state
read (action.cgi?cmd=hw_state) answers valid JSON from the LEDs, IR, filter, microphone level and button."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ['busybox', 'ash'] if shutil.which('busybox') else ['sh']


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class HardwarePage(unittest.TestCase):

    def test_page_commands_exist_and_are_routed(self):
        page = text('www/hardware.html')
        action = text('www/cgi-bin/action.cgi')
        cmds = set(re.findall(r"cmd\('([a-z_]+)", page)) | set(re.findall(r"cmd=([a-z_]+)", page))
        cmds |= {'front_led_on', 'front_led_off'}                    # the blink builds them
        cmds -= {'daynight'}                                          # state.cgi
        self.assertTrue({'hw_state', 'ir_cut_on', 'ir_cut_off', 'play_sound', 'sd_card_info', 'red_led_on'} <= cmds, cmds)
        handlers = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'scripts/action.d').glob('*.sh'))
        for c in cmds:
            self.assertRegex(handlers, r'\n\s+(\S*\|)?%s(\|\S*)?\)' % re.escape(c), c)
            self.assertRegex(action, r'[\s|]%s[|)]' % re.escape(c), c)
        self.assertIn('state.cgi?cmd=daynight', page)

    def test_state_read_needs_no_csrf_and_changes_do(self):
        action = text('www/cgi-bin/action.cgi')
        whitelist = re.search(r'\n    (showlog\|[^)]*)\) ;;', action).group(1).split('|')
        self.assertIn('hw_state', whitelist)
        for c in ('front_led_on', 'red_led_on', 'ir_led_on', 'ir_cut_off', 'play_sound'):
            self.assertNotIn(c, whitelist)
        self.assertIn("E.csrfFetch || fetch)(url, { method: 'POST' })", text('www/hardware.html'))

    def test_menu_link(self):
        self.assertIn('data-target="hardware.html">Hardware test</a>', text('www/index.html'))

    def test_stops_polling_when_the_page_is_left(self):
        page = text('www/hardware.html')
        self.assertIn('if (!root.isConnected) { clearTimeout(timer); return; }', page)
        self.assertIn('document.hidden', page)


class HwState(unittest.TestCase):

    def run_state(self, files):
        src = text('scripts/action.d/hardware.sh')
        block = src[src.index('    hw_state)'):src.index('    front_led_on)')]
        body = block[block.index('\n') + 1:block.rindex(';;')]
        with tempfile.TemporaryDirectory() as d:
            for rel, value in files.items():
                p = Path(d) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(value)
            code = body.replace('/sys/class/leds', d + '/leds').replace('/var/run', d + '/run') \
                       .replace('/sys/class/gpio', d + '/gpio')
            r = subprocess.run(SHELL + ['-c', code], capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_everything_known(self):
        now = int(time.time())
        s = self.run_state({'leds/blue_led/brightness': '1\n', 'leds/red/brightness': '0\n', 'leds/ir/brightness': '1\n',
                            'run/ircut': '0\n', 'run/sound_level': '%d -23\n' % now, 'gpio/gpio522/value': '0\n'})
        self.assertEqual(s, {'ok': True, 'front_led': True, 'red_led': False, 'ir_led': True, 'ir_cut': 0,
                             'auto_daynight': False, 'sound_db': -23, 'button': True})

    def test_nothing_known_gives_nulls(self):
        s = self.run_state({'run/sound_level': '%d -23\n' % (int(time.time()) - 60)})   # too old
        self.assertEqual(s, {'ok': True, 'front_led': None, 'red_led': None, 'ir_led': None, 'ir_cut': None,
                             'auto_daynight': False, 'sound_db': None, 'button': None})


if __name__ == '__main__':
    unittest.main()
