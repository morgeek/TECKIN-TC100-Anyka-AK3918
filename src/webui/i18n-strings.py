#!/usr/bin/env python3
"""List the English strings of the web UI that www/i18n/fr.js must translate.

Sources: text nodes and placeholder/title/aria-label/data-message attributes
of www/*.html, the HTML that the page CGIs print, and the UI messages set from
the two main scripts (textContent/title/placeholder/... assignments).

Usage: src/webui/i18n-strings.py            print the strings, one per line
       src/webui/i18n-strings.py --missing  only those without a translation
The regression tests run --missing and fail on any output.
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WWW = ROOT / 'www'
ATTRS = ('placeholder', 'title', 'aria-label', 'data-message', 'data-content')
# CGIs whose output is JSON / plain text, or that only include helpers.
CGI_SKIP = {'action.cgi', 'state.cgi', 'func.cgi'}
JS_FILES = ('scripts/index.bundle.min.js', 'scripts/scripts.bundle.min.js')
JS_UI = re.compile(r'(?:textContent|innerText|title|placeholder|label)\s*[=(:]\s*'
                   r'"([^"\\]{3,140})"|(?:textContent|innerText|title|placeholder|label)\s*[=(:]\s*'
                   r"'([^'\\]{3,140})'")

# Labels kept in variables (actionLabel = 'Start') and ternaries of two
# messages (cond ? "High load" : "Online").
JS_LABEL = re.compile(r'(?:Label|Hint|Text|label|hint)\s*=\s*(?:"([^"\\]{2,140})"|'
                      r"'([^'\\]{2,140})')")
JS_TERNARY = re.compile(r'\?\s*"([A-Z][^"\\]{1,100})"\s*:\s*"([A-Za-z][^"\\]{1,100})"')


def norm(s):
    return ' '.join(s.split())


def wanted(s):
    return bool(s) and re.search(r'[A-Za-z]{2}', s) is not None


class Collector(HTMLParser):
    def __init__(self, out):
        super().__init__(convert_charrefs=True)
        self.out = out
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'pre', 'code', 'textarea'):
            self.skip += 1
        for k, v in attrs:
            if k in ATTRS and v and wanted(norm(v)):
                self.out.add(norm(v))

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'pre', 'code', 'textarea') and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and wanted(norm(data)):
            self.out.add(norm(data))


def strings():
    out = set()
    for page in sorted(WWW.glob('*.html')):
        Collector(out).feed(page.read_text(encoding='utf-8'))
    for cgi in sorted((WWW / 'cgi-bin').glob('*.cgi')):
        if cgi.name in CGI_SKIP:
            continue
        text = cgi.read_text(encoding='utf-8', errors='replace')
        for m in re.finditer(r'>([^<>$`{}"\'\\%&|;]{3,120})<', text):
            v = norm(m.group(1))
            if wanted(v) and not v.startswith(('/', '-')):
                out.add(v)
    for rel in JS_FILES:
        text = (WWW / rel).read_text(encoding='utf-8')
        found = [m.group(1) or m.group(2) for m in JS_UI.finditer(text)]
        found += [m.group(1) or m.group(2) for m in JS_LABEL.finditer(text)]
        for m in JS_TERNARY.finditer(text):
            found += [m.group(1), m.group(2)]
        for v in found:
            v = norm(v)
            if re.match(r'^[a-z-]+:[^;]*;', v):      # inline CSS
                continue
            if wanted(v) and not v.startswith(('cgi-bin', 'http', '#', '.', '/')):
                out.add(v)
    return sorted(out)


def main():
    items = strings()
    if '--missing' in sys.argv:
        text = (WWW / 'i18n/fr.js').read_text(encoding='utf-8')
        fr = json.loads(text[text.index('{'):text.rindex('}') + 1])
        known = fr.get('strings', {})
        ignore = set(fr.get('untranslated', []))
        items = [s for s in items if s not in known and s not in ignore]
    for s in items:
        print(s)


if __name__ == '__main__':
    main()
