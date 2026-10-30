// Build www/css/ui.bundle.min.css: the three stylesheets of index.html in one file (one request, one httpd exec on
// the camera instead of three), in the order index.html loaded them, so the cascade is unchanged:
//   bulma.1.0.2.purged.min.css, ui-modern.min.css, ui.css (ui.css minified here: comments and layout whitespace only)
// The sources stay as they are and are the ones to edit. The ?v= of the link in www/index.html is the first 8 hex
// digits of the SHA-256 of the built file and is rewritten here.
//   node src/webui/build-css.mjs [--check]     (or: sh src/webui/build-css.sh [--check])
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const css = (f) => path.join(root, 'www/css', f);
const out = css('ui.bundle.min.css');
const indexHtml = path.join(root, 'www/index.html');
const sources = ['bulma.1.0.2.purged.min.css', 'ui-modern.min.css', 'ui.css'];

// Comments out, runs of white space shortened, no space around { } ; and no ';' before '}'. A space after a comma
// stays (custom properties keep their tokens as written). Strings and url() are copied untouched. Spaces around ':' > + ~ stay (selectors and calc() need some of them).
export function minify(text) {
  let o = '';
  let i = 0;
  const n = text.length;
  const space = () => { if (o && !/[\s{};]$/.test(o)) o += ' '; };
  while (i < n) {
    const c = text[i];
    if (c === '/' && text[i + 1] === '*') {
      const e = text.indexOf('*/', i + 2);
      i = e < 0 ? n : e + 2;
      space();
    } else if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < n && text[j] !== c) j += text[j] === '\\' ? 2 : 1;
      o += text.slice(i, j + 1);
      i = j + 1;
    } else if (c === 'u' && text.startsWith('url(', i) && !/[\w-]$/.test(o)) {
      const e = text.indexOf(')', i);
      o += text.slice(i, e + 1);
      i = e + 1;
    } else if (/\s/.test(c)) {
      while (i < n && /\s/.test(text[i])) i++;
      space();
    } else if (c === '{' || c === '}' || c === ';') {
      o = o.replace(/ $/, '');
      if (c === '}') o = o.replace(/;$/, '');
      o += c;
      i++;
    } else {
      o += c;
      i++;
    }
  }
  return o.trim();
}

export function build() {
  const parts = sources.map((f) => fs.readFileSync(css(f), 'utf8'));
  // @charset is only valid first in a file: one for the whole bundle, the sources' own dropped
  for (let k = 0; k < parts.length; k++) parts[k] = parts[k].replace(/@charset "UTF-8";\s*/g, '');
  parts[2] = minify(parts[2]);
  const text = '@charset "UTF-8";\n' + parts.map((p) => p.trim()).join('\n') + '\n';
  const v = crypto.createHash('sha256').update(text).digest('hex').slice(0, 8);
  return { text, v };
}

const LINK = /<link href="css\/ui\.bundle\.min\.css\?v=[^"]*" rel="stylesheet">/;

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { text, v } = build();
  const html = fs.readFileSync(indexHtml, 'utf8');
  const link = `<link href="css/ui.bundle.min.css?v=${v}" rel="stylesheet">`;
  if (!LINK.test(html)) { console.error('www/index.html has no link to css/ui.bundle.min.css'); process.exit(1); }
  if (process.argv[2] === '--check') {
    let ok = true;
    if (!fs.existsSync(out) || fs.readFileSync(out, 'utf8') !== text) { console.error('www/css/ui.bundle.min.css is not built from its sources (run src/webui/build-css.sh)'); ok = false; }
    if (!html.includes(link)) { console.error('the ?v= of the stylesheet link in www/index.html is stale (run src/webui/build-css.sh)'); ok = false; }
    process.exit(ok ? 0 : 1);
  }
  fs.writeFileSync(out, text);
  fs.writeFileSync(indexHtml, html.replace(LINK, link));
  console.log(`${out}: ${text.length} bytes, v=${v}`);
}
