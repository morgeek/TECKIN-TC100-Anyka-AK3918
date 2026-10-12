// Build www/css/bulma.1.0.2.purged.min.css from the full Bulma 1.0.2 build,
// keeping only the rules the web UI uses.
//
// The camera's lighttpd has no mod_deflate, so CSS is sent uncompressed:
// the full Bulma was 677 KB on every first load over Wi-Fi.
//
// Run after changing HTML/JS/CGI markup:   cd src/webui && npm install && npm run purge
// tests/test_regressions.py fails if a class used by the UI is missing from
// the purged file (i.e. this step was forgotten).
//
// Class names must appear literally in www/*.html, www/scripts/*.js or
// www/cgi-bin/* (no 'is-' + colour concatenation), or be listed in SAFELIST.
import { PurgeCSS } from 'purgecss';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const www = path.resolve(here, '../../www');
const out = path.join(www, 'css/bulma.1.0.2.purged.min.css');

const SAFELIST = {
  standard: ['html', 'body', ':root'],
  greedy: [/data-theme/, /theme-(dark|light)/],
};

const [result] = await new PurgeCSS().purge({
  content: [`${www}/*.html`, `${www}/scripts/*.js`, `${www}/cgi-bin/*`],
  css: [path.join(here, 'bulma.1.0.2.min.css')],
  variables: true,
  keyframes: true,
  fontFace: true,
  safelist: SAFELIST,
});

const banner = '/*! bulma.io v1.0.2 | MIT License | github.com/jgthms/bulma — purged for the TC100 web UI by src/webui/purge-bulma.mjs, do not edit */\n';
fs.writeFileSync(out, banner + result.css);
console.log(`${path.relative(process.cwd(), out)}: ${fs.statSync(out).size} bytes`);
