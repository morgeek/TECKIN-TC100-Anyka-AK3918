// Browser check of the live video of the web UI (src/webui/index/30-live-view.js) in headless Chromium, against a fake camera:
// the real www/ pages, a fake cgi-bin/live.cgi that streams a fragmented MP4 in real time, fake snapshots.
//   node live-check.mjs <repo www dir> <fragmented.mp4> <codec string, e.g. vp09.00.10.08 or avc1.42c01e>
// Run in the Playwright image, e.g. (the mp4 comes from `ffmpeg ... -movflags frag_keyframe+empty_moov+default_base_moof`, or from
// LIVE_KEEP_DIR=<dir> python3 -m unittest tests.test_tc100rtsp.LiveMux for the H.264 stream of the camera's muxer):
//   docker run --rm -v <repo>:/repo:ro -v <dir with the mp4>:/media:ro mcr.microsoft.com/playwright:v1.48.2-jammy sh -c \
//     "mkdir /t && cd /t && npm i playwright@1.48.2 >/dev/null && cp /repo/tests/ui-browser/live-check.mjs . && node live-check.mjs /repo/www /media/vp9.mp4 vp09.00.10.08"
// The Chromium of Playwright has no H.264 decoder: the muxer's H.264 is checked with ffprobe/ffmpeg (tests/test_tc100rtsp.py), the page
// code here with VP9 (same container, same Media Source Extensions path; only the codec string differs).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const [www, media, codec] = process.argv.slice(2);
const mp4 = fs.readFileSync(media);
const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=', 'base64');
const boxes = [];
for (let i = 0; i < mp4.length;) { const n = mp4.readUInt32BE(i); boxes.push(mp4.subarray(i, i + n)); i += n; }
const init = Buffer.concat(boxes.slice(0, 2));
const frags = [];
for (let i = 2; i + 1 < boxes.length; i += 2) frags.push(Buffer.concat([boxes[i], boxes[i + 1]]));

const st = { mode: 'paced', open: 0, opened: 0, snaps: 0, info: 0, endAfterMs: 0 };
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  if (u.pathname === '/__state') { res.end(JSON.stringify(st)); return; }
  if (u.pathname === '/__mode') { st.mode = u.searchParams.get('m'); st.endAfterMs = +(u.searchParams.get('end') || 0); res.end('ok'); return; }
  if (u.pathname === '/cgi-bin/live.cgi') {
    if (u.searchParams.get('info') === '1') {
      st.info++;
      if (st.mode === '415') { res.writeHead(415, { 'Content-Type': 'application/json' }); res.end('{"ok":0,"error":"no H.264 stream"}'); return; }
      if (st.mode === 'badcodec') { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":1,"stream":"sub","codec":"avc1.ffffff","width":640,"height":360}'); return; }
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: 1, stream: 'sub', codec, width: 640, height: 360 }));
      return;
    }
    st.opened++;
    if (st.mode === '503') { res.writeHead(503, { 'Content-Type': 'application/json' }); res.end('{"ok":0}'); return; }
    st.open++;
    res.writeHead(200, { 'Content-Type': 'video/mp4', 'Cache-Control': 'no-store' });
    res.write(init);
    let k = 0, dead = false;
    const t0 = Date.now();
    const send = () => {
      if (dead) return;
      if (st.endAfterMs && Date.now() - t0 > st.endAfterMs) { res.end(); return; }
      res.write(frags[k % frags.length]); k++;
      setTimeout(send, k < 4 ? 5 : 1000);       // 4 fragments at once (the page starts 3 s behind), then real time
    };
    send();
    req.on('close', () => { dead = true; st.open--; });
    return;
  }
  if (u.pathname === '/cgi-bin/currentpic.cgi') { st.snaps++; res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Cache-Control': 'no-store' }); res.end(JPEG); return; }
  if (u.pathname.startsWith('/cgi-bin/')) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}'); return; }
  const f = path.join(www, u.pathname === '/' ? 'index.html' : u.pathname);
  if (!f.startsWith(www) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end(); return; }
  const type = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml' }[path.extname(f)] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': type }); res.end(fs.readFileSync(f));
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = 'http://127.0.0.1:' + server.address().port;

const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const results = [];
const check = (ok, label) => { results.push((ok ? 'ok   ' : 'FAIL ') + label); if (!ok) process.exitCode = 1; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn, ms) => { const t = Date.now(); while (Date.now() - t < ms) { if (await fn()) return true; await sleep(100); } return false; };
const newPage = async (init) => {
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const page = await ctx.newPage();
  if (init) await page.addInitScript(init);
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(base + '/index.html#live');
  await page.waitForSelector('#live_toggle');
  return { page, errors, ctx };
};
const vstate = (page) => page.evaluate(() => { const v = document.getElementById('liveview_video'); const b = v.buffered;
  return { shown: v.style.display === 'block', imgHidden: document.getElementById('liveview').style.display === 'none', t: v.currentTime, ready: v.readyState,
           end: b.length ? b.end(b.length - 1) : 0, ranges: b.length, w: v.videoWidth, paused: v.paused }; });
const get = async (p) => (await fetch(base + p)).text();

console.log('isTypeSupported', codec, await (async () => { const { page, ctx } = await newPage();
  const r = await page.evaluate((c) => MediaSource.isTypeSupported('video/mp4; codecs="' + c + '"'), codec); await ctx.close(); return r; })());

{ // 1. video mode: plays, near the live edge, no snapshots meanwhile; pause closes the connection
  const { page, errors, ctx } = await newPage();
  check(await page.evaluate(() => document.getElementById('live_mode_video').getAttribute('aria-pressed')) === 'true', 'Video is the default mode');
  await page.click('#live_toggle');
  check(await until(async () => { const s = await vstate(page); return s.shown && s.t > 1.5 && s.ready >= 2; }, 20000), 'video plays and replaces the picture');
  let s = await vstate(page);
  check(s.imgHidden && s.w > 0, 'the snapshot image is hidden, the video has a picture (' + s.w + ' px wide)');
  await sleep(2500);
  s = await vstate(page);
  check(s.end - s.t < 1.6, 'near the live edge after a 3 s burst (lag ' + (s.end - s.t).toFixed(2) + ' s)');
  const snaps = JSON.parse(await get('/__state')).snaps;
  await sleep(3000);
  check(JSON.parse(await get('/__state')).snaps === snaps, 'no snapshot requests while the video plays');
  check(JSON.parse(await get('/__state')).open === 1, 'one connection to the camera');
  await page.click('#live_toggle');                                  // Pause Live
  check(await until(async () => JSON.parse(await get('/__state')).open === 0, 3000), 'pause closes the connection to the camera');
  check(!(await vstate(page)).shown, 'the video is hidden after pause');
  await page.click('#live_toggle');
  check(await until(async () => (await vstate(page)).shown, 15000), 'resume plays again');
  // page hidden: the connection is closed, shown again: it opens again
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  check(await until(async () => JSON.parse(await get('/__state')).open === 0, 3000), 'a hidden page closes the connection');
  await page.evaluate(() => { Object.defineProperty(document, 'hidden', { value: false, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
  check(await until(async () => (await vstate(page)).shown, 15000), 'a visible page plays again');
  // switch to snapshots: stored, the video stops, snapshots come
  await page.click('#live_mode_snap');
  check(await until(async () => JSON.parse(await get('/__state')).open === 0, 3000), 'Snapshots mode closes the connection');
  const before = JSON.parse(await get('/__state')).snaps;
  check(await until(async () => JSON.parse(await get('/__state')).snaps > before + 1, 15000), 'snapshots are requested in Snapshots mode');
  check(await page.evaluate(() => localStorage.getItem('tc100.liveMode')) === 'snap', 'the mode is remembered in localStorage');
  check(errors.length === 0, 'no page error: ' + errors.join(' | '));
  await page.reload(); await page.waitForSelector('#live_toggle');
  check(await page.evaluate(() => document.getElementById('live_mode_snap').getAttribute('aria-pressed')) === 'true', 'Snapshots is still selected after a reload');
  await ctx.close();
}
{ // 2. the camera ends the stream (10 minutes on the real one): the page connects again
  await get('/__mode?m=paced&end=4000');
  const before = JSON.parse(await get('/__state')).opened;
  const { page, ctx } = await newPage();
  await page.evaluate(() => localStorage.removeItem('tc100.liveMode')); await page.reload(); await page.waitForSelector('#live_toggle');
  await page.click('#live_toggle');
  check(await until(async () => JSON.parse(await get('/__state')).opened >= before + 2, 25000), 'the page reconnects when the stream ends');
  check(await until(async () => (await vstate(page)).shown, 15000), 'and plays again');
  await get('/__mode?m=paced');
  await ctx.close();
}
for (const [mode, label] of [['415', 'no H.264 stream (415)'], ['badcodec', 'profile the browser cannot play'], ['503', 'the camera refuses (503)']]) {
  await get('/__mode?m=' + mode);
  const { page, ctx } = await newPage();
  await page.evaluate(() => localStorage.removeItem('tc100.liveMode')); await page.reload(); await page.waitForSelector('#live_toggle');
  const before = JSON.parse(await get('/__state')).snaps;
  await page.click('#live_toggle');
  check(await until(async () => JSON.parse(await get('/__state')).snaps > before + 1, 25000), 'falls back to snapshots: ' + label);
  check(!(await vstate(page)).shown, 'no video shown: ' + label);
  await ctx.close();
}
{ // 3. no Media Source Extensions: snapshots, nothing to choose, no error
  await get('/__mode?m=paced');
  const { page, errors, ctx } = await newPage(() => { delete window.MediaSource; delete window.ManagedMediaSource; });
  check(await page.evaluate(() => document.getElementById('live_mode').style.display) === 'none', 'the Video / Snapshots switch is hidden without MediaSource');
  const before = JSON.parse(await get('/__state')).snaps;
  await page.click('#live_toggle');
  check(await until(async () => JSON.parse(await get('/__state')).snaps > before + 1, 15000), 'snapshots without MediaSource');
  check((await vstate(page)).shown === false, 'the video is never shown');
  check(errors.length === 0, 'no page error: ' + errors.join(' | '));
  await ctx.close();
}
console.log(results.join('\n'));
await browser.close();
server.close();
