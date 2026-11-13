// Minify the web UI of a BUILD TREE (audit 2026-11-06 S5, owner: JS and HTML only; the shell stays readable on the
// camera). Run by v3/build-stack.sh on its copy of www/ before the .gz step; git keeps the readable files, which the
// tests and src/webui/build-index.sh compare.
//   node src/webui/minify.mjs DIR        (DIR = the www folder of the build tree)
// - every *.js: esbuild transform, minified, target es2018, UTF-8 kept (fr.js), top-level names kept (a script's
//   globals are used by the others and by onclick attributes: esbuild does not rename them without an output format);
// - every *.html: the inline <script> blocks without src (classic JavaScript only) and the <style> blocks; the markup
//   itself is left alone (the French dictionary matches its text, <pre> blocks, spacing between inline elements).
// Needs esbuild (npm install --prefix src/webui): without it, says so and exits 3, and the caller keeps the files.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
let esbuild;
try {
  esbuild = createRequire(path.join(here, 'package.json'))('esbuild');
} catch (e) {
  console.error('minify: esbuild is not installed (npm install --prefix src/webui): web files left as they are');
  process.exit(3);
}

const JS = { minify: true, target: 'es2018', charset: 'utf8', loader: 'js', legalComments: 'inline' };
const CSS = { minify: true, charset: 'utf8', loader: 'css', legalComments: 'inline' };

export function minifyJs(code) { return esbuild.transformSync(code, JS).code.trimEnd(); }
export function minifyCss(code) { return esbuild.transformSync(code, CSS).code.trimEnd(); }

// inline blocks of an HTML page; an attribute list with src= or a non-JavaScript type is left alone
export function minifyHtml(html) {
  const blocks = [];
  html = html.replace(/<(script|style|pre|textarea)(\s[^>]*)?>([\s\S]*?)<\/\1>/gi, (all, tag, attrs = '', body) => {
    const low = tag.toLowerCase();
    let out = all;
    if (low === 'script' && !/\bsrc\s*=/i.test(attrs) && body.trim()) {
      const t = /\btype\s*=\s*["']?([^"'\s>]+)/i.exec(attrs);
      if (!t || /^(text|application)\/(javascript|ecmascript)$/i.test(t[1])) {
        out = `<script${attrs}>${minifyJs(body)}</script>`;
      }
    } else if (low === 'style' && body.trim()) {
      out = `<style${attrs}>${minifyCss(body)}</style>`;
    }
    blocks.push(out);
    return `\x00BLK${blocks.length - 1}\x00`;
  });
  html = html.replace(/<!--[\s\S]*?-->/g, '').replace(/^[ \t]+|[ \t]+$/gm, '').replace(/\n{2,}/g, '\n');
  return html.replace(/\x00BLK(\d+)\x00/g, (_, i) => blocks[+i]);
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out); else out.push(p);
  }
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const dir = process.argv[2];
  if (!dir || !fs.existsSync(dir)) { console.error('usage: node src/webui/minify.mjs WWW_DIR'); process.exit(2); }
  let before = 0, after = 0, n = 0;
  for (const f of walk(dir)) {
    const ext = path.extname(f);
    if (ext !== '.js' && ext !== '.html') continue;
    const src = fs.readFileSync(f, 'utf8');
    const out = ext === '.js' ? minifyJs(src) + '\n' : minifyHtml(src);
    if (out.length < src.length) { fs.writeFileSync(f, out); n++; }
    before += Buffer.byteLength(src); after += Buffer.byteLength(out.length < src.length ? out : src);
  }
  console.log(`minify: ${n} files, ${before} -> ${after} bytes`);
}
