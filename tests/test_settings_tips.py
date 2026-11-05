"""Item 44: the help tips of Settings (the "?" next to a label): each one points at a field of the page and has its
French translation in www/i18n/fr.js."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SettingsTips(unittest.TestCase):
    def test_tips_point_at_fields_and_are_translated(self):
        page = (ROOT / 'www/settings.html').read_text(encoding='utf-8')
        m = re.search(r'var TIPS = (\{.*?\n\s*\});', page, re.S)
        tips = json.loads(m.group(1))
        self.assertGreaterEqual(len(tips), 60)
        fr = (ROOT / 'www/i18n/fr.js').read_text(encoding='utf-8')
        for field, text in tips.items():
            self.assertIn('id="%s"' % field, page, field)
            self.assertIn('    %s: ' % json.dumps(text, ensure_ascii=False), fr, field)
        self.assertIn('    "Help": ', fr)


if __name__ == '__main__':
    unittest.main()
