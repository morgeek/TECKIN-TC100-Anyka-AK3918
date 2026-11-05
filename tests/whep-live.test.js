// Item 35: the WebRTC (WHEP) part of the live view (src/webui/index/30-live-view.js, in www/scripts/index.bundle.min.js), run in
// a small DOM/network fixture without a browser, as tests/live-video.test.js does: WebRTC is tried first, and ANY failure (the
// gateway is off, the offer is refused, no picture, a lost connection) gives the picture to the MP4 live view, without ever
// breaking it. The real playback is checked by tests/whep_interop.py (aiortc as the browser) and on the camera.
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

const resp = (status, body, headers) => ({ok: status >= 200 && status < 300, status, headers: {get: (k) => (headers || {})[k] || null},
  json: async () => JSON.parse(body || '{}'), text: async () => body || ''});

// routes: {'GET cgi-bin/whep.cgi': () => resp(...), ...}; anything else answers 503
function fixture(routes) {
  const nodes = {};
  const mk = (id) => (nodes[id] = {id, style: {}, attrs: {}, classes: new Set(), listeners: {}, textContent: '', srcObject: null,
    muted: false, currentTime: 0, videoWidth: 640,
    classList: {toggle: (c, on) => { on ? nodes[id].classes.add(c) : nodes[id].classes.delete(c); }},
    setAttribute: (k, v) => { nodes[id].attrs[k] = v; }, getAttribute: (k) => nodes[id].attrs[k],
    removeAttribute: () => {}, addEventListener: (ev, fn) => { nodes[id].listeners[ev] = fn; },
    pause() {}, load() {}, play: () => Promise.resolve(), closest: () => null});
  ['liveview', 'liveview_video', 'live_mode', 'live_mode_video', 'live_mode_snap', 'live_toggle'].forEach(mk);
  const timers = [], intervals = [], store = {}, fetches = [], pcs = [];
  class PC {
    constructor(cfg) { this.cfg = cfg; this.closed = false; this.connectionState = 'new'; this.localDescription = null; pcs.push(this); }
    addTransceiver(kind, o) { this.kind = kind; this.dir = o && o.direction; }
    createOffer() { return Promise.resolve({type: 'offer', sdp: 'v=0 OFFER'}); }
    setLocalDescription(o) { this.localDescription = o; return Promise.resolve(); }
    setRemoteDescription(a) { this.remote = a; return Promise.resolve(); }
    close() { this.closed = true; }
  }
  class MS { constructor(tracks) { this.tracks = tracks; } }
  const fetchFn = (url, opts) => {
    const key = ((opts && opts.method) || 'GET') + ' ' + url;
    fetches.push(key);
    const r = routes[key];
    return Promise.resolve(r ? r(opts) : resp(503, '{"ok":0}'));
  };
  const ctx = {
    console: {info() {}, log: console.log}, Date, Promise, Uint8Array, Error, URL,
    document: {hidden: false},
    window: {},
    timeoutJobs: {}, clearJob: (name) => { delete ctx.timeoutJobs[name]; },
    byId: (id) => nodes[id] || null,
    setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; },
    setInterval: (fn) => { intervals.push(fn); return intervals.length; }, clearInterval: () => {},
    liveFeedEnabled: true, liveViewInViewport: true,
    liveViewSnapshotEndpoint: 'cgi-bin/currentpic.cgi', liveViewVisibleIntervalMs: 4000, liveViewVisibilityObserver: null,
    fetch: fetchFn
  };
  const w = ctx.window;
  w.MediaSource = function () {};
  w.MediaSource.isTypeSupported = () => false;           // the MP4 fallback ends in snapshots: enough to see that it was tried
  w.fetch = fetchFn;
  w.AbortController = function () { this.signal = {}; this.abort = () => {}; };
  w.ReadableStream = function () {};
  w.Uint8Array = Uint8Array;
  w.URL = {createObjectURL: () => 'blob:x'};
  ctx.URL = w.URL;
  w.RTCPeerConnection = PC;
  w.MediaStream = MS;
  w.localStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }};
  vm.createContext(ctx);
  vm.runInContext(section, ctx);
  ctx.scheduleRefreshLiveImage = () => {};
  return {ctx, nodes, timers, intervals, fetches, pcs};
}
const tick = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); };
const MP4_INFO = 'GET cgi-bin/live.cgi?info=1';
const okRoutes = () => ({
  'GET cgi-bin/whep.cgi': () => resp(200, '{"viewers":0,"max":2}'),
  'POST cgi-bin/whep.cgi': () => resp(201, 'v=0 ANSWER', {Location: '/cgi-bin/whep.cgi?stop=0123456789abcdef'}),
});

(async () => {
  { // the gateway runs: probe, offer, answer; the MP4 live view is not started; stop ends the viewer
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    await tick();
    assert.deepEqual(f.fetches, ['GET cgi-bin/whep.cgi', 'POST cgi-bin/whep.cgi'], 'WebRTC first, no live.cgi');
    const pc = f.pcs[0];
    assert.equal(pc.kind, 'video'); assert.equal(pc.dir, 'recvonly');
    assert.equal(JSON.stringify(pc.cfg), '{"iceServers":[]}', 'LAN only: no STUN server');
    assert.equal(pc.localDescription.sdp, 'v=0 OFFER');
    assert.equal(JSON.stringify(pc.remote), '{"type":"answer","sdp":"v=0 ANSWER"}');
    pc.ontrack({streams: [{id: 's'}], track: {}});
    assert.deepEqual(f.nodes.liveview_video.srcObject, {id: 's'});
    assert.equal(f.nodes.liveview_video.muted, true);
    f.nodes.liveview_video.listeners.playing();                 // the browser plays it
    assert.equal(f.ctx.liveVideo.playing, true);
    assert.equal(f.nodes.liveview_video.style.display, 'block', 'the video is shown');
    f.ctx.liveVideoStop();                                       // pause / tab hidden / mode switch
    assert.equal(pc.closed, true);
    assert.equal(f.fetches[2], 'POST /cgi-bin/whep.cgi?stop=0123456789abcdef', 'the viewer is released at once');
    assert.equal(f.nodes.liveview_video.srcObject, null);
  }
  { // the gateway is off (WHEP=0, 503): straight to the MP4 live view, and not asked again for 10 minutes
    const f = fixture({'GET cgi-bin/whep.cgi': () => resp(503, '{"enabled":0}')});
    f.ctx.liveVideoSync();
    await tick();
    assert.deepEqual(f.fetches, ['GET cgi-bin/whep.cgi', MP4_INFO], 'MP4 live view tried right after');
    assert.equal(f.pcs.length, 0, 'no peer connection made');
    assert.ok(f.ctx.liveWhep.offUntil > Date.now() + 500000);
    assert.equal(f.ctx.liveWhep.fails, 0, 'not a failure');
    f.ctx.liveVideoStop(); f.fetches.length = 0;
    f.ctx.liveVideoFailedUntil = 0; f.ctx.liveVideoSync(); await tick();
    assert.deepEqual(f.fetches, [MP4_INFO], 'no new probe');
  }
  { // the offer is refused (429: two viewers already, 415, 500...): MP4 live view, WebRTC off for a minute
    for (const status of [429, 415, 500, 503]) {
      const r = okRoutes();
      r['POST cgi-bin/whep.cgi'] = () => resp(status, 'no');
      const f = fixture(r);
      f.ctx.liveVideoSync();
      await tick();
      assert.deepEqual(f.fetches, ['GET cgi-bin/whep.cgi', 'POST cgi-bin/whep.cgi', MP4_INFO], 'status ' + status);
      assert.equal(f.pcs[0].closed, true, 'the peer connection is closed');
      const off = f.ctx.liveWhep.offUntil - Date.now();
      assert.ok(off > 50000 && off <= 60000, 'a minute: ' + off);
    }
  }
  { // network error on the offer, or a bad answer: the same
    const r = okRoutes();
    r['POST cgi-bin/whep.cgi'] = () => { throw new Error('network'); };
    const f = fixture(r);
    f.ctx.liveVideoSync();
    await tick();
    assert.equal(f.fetches[f.fetches.length - 1], MP4_INFO);
    const r2 = okRoutes();
    const f2 = fixture(r2);
    f2.ctx.window.RTCPeerConnection = class extends f2.ctx.window.RTCPeerConnection {
      setRemoteDescription() { return Promise.reject(new Error('bad answer')); }
    };
    f2.ctx.liveVideoSync();
    await tick();
    assert.equal(f2.fetches[f2.fetches.length - 1], MP4_INFO, 'a bad answer falls back');
  }
  { // an answer but no picture within 8 s: MP4 live view; the second failure in a row keeps WebRTC off for 10 minutes
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    await tick();
    assert.equal(f.fetches.length, 2);
    f.ctx.liveVideo.startedAt = Date.now() - 9000;
    f.intervals[0]();                                            // the 1 s watchdog
    await tick();
    assert.equal(f.fetches[f.fetches.length - 1], MP4_INFO, 'fell back to the MP4 live view');
    assert.equal(f.pcs[0].closed, true);
    assert.equal(f.ctx.liveWhep.fails, 1);
    f.ctx.liveVideoStop(); f.ctx.liveWhep.offUntil = 0;           // a minute later
    f.ctx.liveVideoFailedUntil = 0; f.ctx.liveVideoSync(); await tick();
    f.ctx.liveVideo.startedAt = Date.now() - 9000;
    f.intervals[f.intervals.length - 1]();
    await tick();
    assert.equal(f.ctx.liveWhep.fails, 2);
    assert.ok(f.ctx.liveWhep.offUntil > Date.now() + 500000, 'second failure: 10 minutes');
  }
  { // the connection drops while playing: MP4 live view through the usual retry, WebRTC off for 30 s
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    await tick();
    const pc = f.pcs[0];
    f.nodes.liveview_video.listeners.playing();
    f.fetches.length = 0;
    pc.connectionState = 'failed';
    pc.onconnectionstatechange();
    assert.equal(pc.closed, true);
    assert.equal(f.ctx.liveVideo.on, false);
    assert.ok(f.ctx.liveWhep.offUntil > Date.now() + 25000 && f.ctx.liveWhep.offUntil <= Date.now() + 30000);
    const t = f.timers.shift(); t.fn();                           // liveVideoRetry
    await tick();
    assert.deepEqual(f.fetches.filter((x) => x.startsWith('GET')), [MP4_INFO], 'the retry does not use WebRTC');
  }
  { // rc27 R4: "playing" with sound but no picture (videoWidth 0) is not playing: MP4 live view after 8 s
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    await tick();
    f.nodes.liveview_video.videoWidth = 0;
    f.nodes.liveview_video.listeners.playing();                 // the audio track plays
    f.nodes.liveview_video.currentTime = 5;                      // and moves the clock
    f.intervals[0]();
    assert.equal(f.ctx.liveVideo.on, true, 'waits for a picture first');
    f.ctx.liveVideo.startedAt = Date.now() - 9000;
    f.intervals[0]();
    await tick();
    assert.equal(f.fetches[f.fetches.length - 1], MP4_INFO, 'no picture: MP4 live view');
    assert.equal(f.pcs[0].closed, true);
  }
  { // a frozen picture (4 checks with the same time) counts as lost
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    await tick();
    f.nodes.liveview_video.listeners.playing();
    for (let i = 0; i < 6; i++) f.intervals[0]();
    assert.equal(f.ctx.liveVideo.on, false, 'stopped after the freeze');
    assert.equal(f.pcs[0].closed, true);
  }
  { // no WebRTC in the browser: exactly the old behaviour, no probe
    const f = fixture(okRoutes());
    delete f.ctx.window.RTCPeerConnection;
    f.ctx.liveVideoSync();
    await tick();
    assert.deepEqual(f.fetches, [MP4_INFO]);
  }
  { // stopped while the offer is in flight: nothing is counted as a failure, the viewer is not left on the camera
    const f = fixture(okRoutes());
    f.ctx.liveVideoSync();
    f.ctx.liveVideoStop();
    await tick();
    assert.equal(f.ctx.liveWhep.fails, 0);
    assert.equal(f.ctx.liveWhep.offUntil, 0);
  }
  console.log('whep-live: ok');
})().catch((e) => { console.error(e); process.exit(1); });
