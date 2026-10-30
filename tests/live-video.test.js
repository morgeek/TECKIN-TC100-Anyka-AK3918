// The live video code of the web UI (src/webui/index/30-live-view.js, in www/scripts/index.bundle.min.js), run in a small
// DOM/network fixture without a browser: it must fall back to snapshots cleanly when Media Source Extensions are missing, when the
// browser cannot play the camera's profile, when the camera has no H.264 stream or refuses, and when localStorage throws.
// (The real playback is checked in headless Chromium by tests/ui-browser/live-check.mjs.)
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../www/scripts/index.bundle.min.js'), 'utf8');
const start = source.indexOf('  // --- Live view: snapshot refresh');
const endMark = 'function initLiveModeSwitch()';
const endAt = source.indexOf(endMark, start);
assert.ok(start >= 0 && endAt > start, 'the live view section is in the bundle');
const section = source.slice(start, source.indexOf('\n  }\n', endAt) + 5);

function fixture(opts) {
  opts = opts || {};
  const nodes = {};
  const mk = (id) => (nodes[id] = {id, style: {}, attrs: {}, classes: new Set(), listeners: {}, textContent: '',
    classList: {toggle: (c, on) => { on ? nodes[id].classes.add(c) : nodes[id].classes.delete(c); }},
    setAttribute: (k, v) => { nodes[id].attrs[k] = v; }, getAttribute: (k) => nodes[id].attrs[k],
    removeAttribute: () => {}, addEventListener: (ev, fn) => { nodes[id].listeners[ev] = fn; },
    pause() {}, load() {}, play: () => Promise.resolve(), closest: () => null});
  ['liveview', 'liveview_video', 'live_mode', 'live_mode_video', 'live_mode_snap', 'live_toggle'].forEach(mk);
  const timers = [], store = {};
  const fetches = [];
  const ctx = {
    console, Date, Promise, Uint8Array, Error, URL,
    document: {hidden: false},
    window: {},
    timeoutJobs: {}, clearJob: (name) => { delete ctx.timeoutJobs[name]; },
    byId: (id) => nodes[id] || null,
    setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
    setInterval: () => 1, clearInterval: () => {},
    liveFeedEnabled: true, liveViewInViewport: true, uiUltraLiteMode: false,
    liveViewSnapshotEndpoint: 'cgi-bin/currentpic.cgi', liveViewVisibleIntervalMs: 4000, liveViewVisibilityObserver: null,
    fetch: (url) => {
      fetches.push(url);
      return Promise.resolve(opts.info ? opts.info(url) : {ok: false, status: 503, json: async () => ({ok: 0})});
    }
  };
  if (opts.mse) {
    ctx.window.MediaSource = function () {};
    ctx.window.MediaSource.isTypeSupported = opts.mse;
    ctx.window.fetch = ctx.fetch;
    ctx.window.AbortController = function () { this.signal = {}; this.abort = () => {}; };
    ctx.window.ReadableStream = function () {};
    ctx.window.Uint8Array = Uint8Array;
    ctx.window.URL = {createObjectURL: () => 'blob:x'};
    ctx.URL = ctx.window.URL;
  }
  ctx.window.localStorage = opts.storage === 'throws'
    ? {getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }}
    : {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }};
  vm.createContext(ctx);
  vm.runInContext(section, ctx);
  return {ctx, nodes, timers, fetches, store};
}
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  let scheduled = 0;

  { // no Media Source Extensions: snapshots only, nothing to choose, nothing fetched
    const f = fixture();
    f.ctx.scheduleRefreshLiveImage = () => { scheduled++; };
    assert.equal(f.ctx.liveVideoSupported(), false);
    assert.equal(f.ctx.liveVideoWanted(), false);
    assert.equal(f.ctx.canRefreshLiveImageNow(), true, 'snapshots refresh as before');
    f.ctx.initLiveModeSwitch();
    assert.equal(f.nodes.live_mode.style.display, 'none', 'the Video / Snapshots switch is hidden');
    f.ctx.liveVideoSync();
    assert.equal(scheduled, 1, 'the snapshot refresh is scheduled');
    assert.equal(f.fetches.length, 0, 'no request for the video');
    assert.equal(f.ctx.liveVideo.on, false);
  }
  { // Media Source Extensions but not this profile: one info request, then snapshots for a long while
    const f = fixture({mse: () => false, info: () => ({ok: true, status: 200, json: async () => ({ok: 1, codec: 'avc1.64002a'})})});
    scheduled = 0;
    f.ctx.scheduleRefreshLiveImage = () => { scheduled++; };
    f.ctx.initLiveModeSwitch();
    assert.equal(f.nodes.live_mode.style.display, '');
    assert.equal(f.ctx.canRefreshLiveImageNow(), false, 'while the video starts there are no snapshots');
    f.ctx.liveVideoSync();
    assert.equal(f.ctx.liveVideo.on, true);
    await tick(); await tick(); await tick();
    assert.deepEqual(f.fetches, ['cgi-bin/live.cgi?info=1']);
    assert.equal(f.ctx.liveVideo.on, false, 'stopped');
    assert.equal(f.ctx.liveVideoWanted(), false, 'not tried again at once');
    assert.equal(f.ctx.canRefreshLiveImageNow(), true, 'the snapshots are back');
    assert.ok(scheduled >= 1, 'snapshot refresh scheduled');
    f.nodes.live_mode_snap.listeners.click();                   // the user picks Snapshots, then Video again: video is tried again
    assert.equal(f.store['tc100.liveMode'], 'snap');
    f.nodes.live_mode_video.listeners.click();
    assert.equal(f.store['tc100.liveMode'], 'video');
    assert.equal(f.ctx.liveVideoWanted(), true);
  }
  { // 415: neither stream is H.264
    const f = fixture({mse: () => true, info: () => ({ok: false, status: 415, json: async () => ({ok: 0})})});
    f.ctx.scheduleRefreshLiveImage = () => { scheduled++; };
    f.ctx.liveVideoSync();
    await tick(); await tick(); await tick();
    assert.equal(f.ctx.liveVideoWanted(), false, '415 keeps the JPEG view');
    assert.equal(f.ctx.liveVideo.on, false);
  }
  { // 503 (starting, or two viewers already): a few retries, then snapshots for two minutes
    const f = fixture({mse: () => true});
    f.ctx.scheduleRefreshLiveImage = () => { scheduled++; };
    f.ctx.liveVideoSync();
    for (let round = 0; round < 6 && f.ctx.liveVideoWanted(); round++) {
      await tick(); await tick(); await tick();
      const t = f.timers.shift();
      if (t) t.fn();
    }
    await tick(); await tick(); await tick();
    assert.equal(f.ctx.liveVideoWanted(), false, 'gave up after the retries');
    assert.ok(f.fetches.length >= 4, 'it did retry: ' + f.fetches.length);
  }
  { // localStorage that throws (private window, blocked site data)
    const f = fixture({storage: 'throws', mse: () => true});
    f.ctx.scheduleRefreshLiveImage = () => {};
    assert.equal(f.ctx.readLiveMode(), 'video');
    f.ctx.initLiveModeSwitch();
    assert.doesNotThrow(() => f.nodes.live_mode_snap.listeners.click());
    assert.equal(f.ctx.liveMode, 'snap', 'the choice works for this page view');
  }
  { // hidden page or off screen: the video is not started
    const f = fixture({mse: () => true});
    f.ctx.scheduleRefreshLiveImage = () => {};
    f.ctx.document.hidden = true;
    f.ctx.liveVideoSync();
    assert.equal(f.fetches.length, 0);
    f.ctx.document.hidden = false;
    f.ctx.liveViewInViewport = false;
    f.ctx.liveVideoSync();
    assert.equal(f.fetches.length, 0);
    f.ctx.liveViewInViewport = true; f.ctx.liveFeedEnabled = false;   // paused
    f.ctx.liveVideoSync();
    assert.equal(f.fetches.length, 0);
  }
  process.stdout.write('Live video: fallbacks to snapshots (no MediaSource, unsupported profile, 415, 503, no localStorage, hidden page): OK\n');
})().catch((error) => { console.error(error); process.exitCode = 1; });
