// Item 36: the recordings timeline of view_records (www/scripts/view_records.bundle.min.js), drawn in the browser
// from viewrecords.cgi?cmd=day_index: spans from the index, a click goes to the right file and second.
// Run: node --test tests/records-timeline.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '../www/scripts/view_records.bundle.min.js'), 'utf8');
const part = src.slice(src.indexOf('  var tl = {'), src.indexOf('  function onDateChanged() {'));

function load() {
  const nodes = {
    timeline24_hint: {textContent: ''},
    recordselect: {value: '', options: ['10-00-00.mp4', '10-05-00.mp4', '12-00-00.mp4']},
    rpl: {readyState: 0, currentTime: 0, play() { return null; }},
  };
  Object.defineProperty(nodes.recordselect, 'value', {
    get() { return this._v || ''; },
    set(v) { this._v = this.options.includes(v) ? v : ''; },
  });
  const calls = [];
  const ctx = {
    byId: id => nodes[id] || null, T: s => s, selectedDate: () => '2026-11-05', autoPlayEnabled: false,
    onRecordChanged: off => calls.push([nodes.recordselect.value, off]),
    window: {}, document: {documentElement: {}}, getComputedStyle: () => ({getPropertyValue: () => ''}),
    setTimeout: () => 0, Date, Math, isFinite, parseInt, String, Array, Infinity,
  };
  vm.createContext(ctx);
  vm.runInContext(part + '\nthis.tl = tl; this.tlSetIndex = tlSetIndex; this.tlSeek = tlSeek; this.tlZoom = tlZoom;', ctx);
  return {ctx, nodes, calls};
}

const INDEX = {seg: 300, files: [
  {t: '10-00-00', x: 'mp4', d: 300, kb: 9000, e: [12, 40, 250, -1]},
  {t: '10-05-00', x: 'mp4', d: -1, kb: 4000, e: []},
  {t: '12-00-00', x: 'mp4', d: 120, kb: 3000},
]};

test('spans from the day index', () => {
  const {ctx} = load();
  ctx.tlSetIndex(INDEX);
  const spans = ctx.tl.spans.map(s => [s.rec, s.s, s.end, s.ev.map(e => e.slice())]);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(spans)), [
    ['10-00-00.mp4', 36000, 36300, [[36012, 36040, 0], [36250, 36300, 0]]],
    ['10-05-00.mp4', 36300, 36600, [[36300, 36600, 1]]],			// unknown length: one segment; old marker
    ['12-00-00.mp4', 43200, 43320, []],
  ]);
  assert.strictEqual(ctx.byId('timeline24_hint').textContent, '00:00 - 24:00');
});

test('names alone when the index is missing', () => {
  const {ctx} = load();
  ctx.tl.records = ['10-00-00.mp4', '10-02-00.mp4'];
  ctx.tlSetIndex(null);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.tl.spans.map(s => [s.s, s.end]))), [[36000, 36120], [36120, 36420]]);
});

test('a click loads the file and asks for the second; a gap goes to the next file; same file: no reload', () => {
  const {ctx, nodes, calls} = load();
  ctx.tlSetIndex(INDEX);
  ctx.tlSeek(36000 + 95);
  assert.deepStrictEqual(calls.pop(), ['10-00-00.mp4', 95]);
  ctx.tlSeek(40000);				// between 10:10 and 12:00
  assert.deepStrictEqual(calls.pop(), ['12-00-00.mp4', 0]);
  ctx.tl.cur = '12-00-00.mp4'; nodes.rpl.readyState = 1;
  ctx.tlSeek(43200 + 30);
  assert.strictEqual(calls.length, 0);
  assert.strictEqual(nodes.rpl.currentTime, 30);
  ctx.tlSeek(50000);				// after the last file: nothing
  assert.strictEqual(calls.length, 0);
});

test('zoom keeps inside the day', () => {
  const {ctx} = load();
  ctx.tlZoom(3600, 300);
  assert.deepStrictEqual([ctx.tl.v0, ctx.tl.v1], [0, 3600]);
  ctx.tlZoom(900, 86000);
  assert.deepStrictEqual([ctx.tl.v0, ctx.tl.v1], [85500, 86400]);
});
