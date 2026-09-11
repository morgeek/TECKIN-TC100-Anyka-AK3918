// Execute the production helpers in a small DOM/network fixture, without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../www/scripts/index.bundle.min.js'), 'utf8');
(async () => {
  let calls = [];
  const context = vm.createContext({
    csrfToken: '', Promise, Headers, Object, Error,
    fetch: async (url, opts) => {
      calls.push({url, opts});
      if (url.includes('statusline')) return {ok: true, json: async () => ({csrf_token: 'aabbcc'})};
      return {ok: !url.includes('fail'), status: url.includes('fail') ? 403 : 200};
    }
  });
  vm.runInContext(source.slice(source.indexOf('  var csrfTokenRequest ='), source.indexOf('  function initPttVolumeControls()')), context);
  const options = {headers: {'Content-Type': 'text/plain'}, body: 'KEY=1'};
  await Promise.all([context.csrfFetch('/action', options), context.csrfFetch('/second')]);
  assert.equal(calls.filter(c => c.url.includes('statusline')).length, 1, 'concurrent token bootstrap must be shared');
  const mutation = calls.find(c => c.url === '/action');
  assert.equal(mutation.opts.method, 'POST');
  assert.equal(mutation.opts.body, 'KEY=1');
  assert.equal(mutation.opts.headers.get('X-CSRF-Token'), 'aabbcc');
  assert.equal(mutation.opts.headers.get('Content-Type'), 'text/plain');
  assert.equal(options.method, undefined, 'caller options must remain reusable');
  assert.deepEqual(options.headers, {'Content-Type': 'text/plain'});
  await assert.rejects(context.csrfFetch('/fail'), /HTTP 403/);

  const nodes = {};
  ['dash_cpu_val', 'dash_cpu_bar', 'dash_ram_val', 'dash_ram_bar', 'dash_wifi_val', 'dash_wifi_bar', 'sd_readonly_warning', 'security_warning'].forEach(id => {
    nodes[id] = {textContent: '', style: {}, className: ''};
  });
  let active = true;
  context.window = {isHostStillActive: () => active};
  context.dash = {};
  context.byId = id => nodes[id];
  const start = source.indexOf('dashboardStatusRenderer = function(res)');
  const end = source.indexOf('\n        };', start) + '\n        };'.length;
  vm.runInContext(source.slice(start, end), context);
  context.dashboardStatusRenderer({cpu: 0, ram: 0, wifi_qual: 0});
  assert.equal(nodes.dash_wifi_val.textContent, '0%');
  context.dashboardStatusRenderer({cpu: 10, ram: 20});
  assert.equal(nodes.dash_wifi_val.textContent, '—');
  active = false;
  context.dashboardStatusRenderer({});
  assert.equal(context.dashboardStatusRenderer, null, 'unmounted view must release its renderer');
  let scheduledPolls = 0;
  context.document = {hidden: true};
  context.timeoutJobs = {};
  context.clearJob = () => {};
  context.setTimeout = () => { scheduledPolls++; return 1; };
  context.refreshSysUsage = () => {};
  const scheduleStart = source.indexOf('  function scheduleRefreshSysUsage(interval)');
  const scheduleEnd = source.indexOf('  function updateStatusRefreshUi(state)', scheduleStart);
  vm.runInContext(source.slice(scheduleStart, scheduleEnd), context);
  context.scheduleRefreshSysUsage(10);
  assert.equal(scheduledPolls, 0, 'hidden tabs must not schedule status polling');
  context.document.hidden = false;
  context.scheduleRefreshSysUsage(10);
  assert.equal(scheduledPolls, 1, 'visible tabs must resume status polling');
  assert.match(fs.readFileSync(path.join(__dirname, '../www/scripts/scripts.bundle.min.js'), 'utf8'), /document\.hidden\) clearServiceStatePolling/);
  const home = fs.readFileSync(path.join(__dirname, '../www/index.html'), 'utf8');
  assert.doesNotMatch(home, /<script src="scripts\/ptt-audio/, 'PTT bundle must not load during initial render');
  assert.match(home, /createElement\('script'\)[\s\S]*ptt-audio\.bundle\.min\.js/, 'PTT bundle must load on demand');
  assert.match(source, /diagnostics_toggle/, 'diagnostics remain wired after moving into More tools');

  const cameraNodes = {
    camera_state: {textContent: ''},
    camera_state_dot: {className: ''}
  };
  context.byId = id => cameraNodes[id] || null;
  context.parseCpuPercent = value => value;
  context.parseRamUsage = value => value;
  context.applyUsageClass = () => {};
  context.setAdaptiveLivePreviewProfile = () => {};
  context.applyAdaptivePollingPressure = () => {};
  const usageStart = source.indexOf('  function updateSystemLoadState(');
  const usageEnd = source.indexOf('  function updateSecurityBadge(', usageStart);
  vm.runInContext(source.slice(usageStart, usageEnd), context);
  context.updateSystemLoadState('', 22, 41);
  assert.equal(cameraNodes.camera_state.textContent, 'Camera operational');
  assert.match(cameraNodes.camera_state_dot.className, /is-online/);

  process.stdout.write('CSRF bootstrap, dashboard lifecycle, camera state and background polling: OK\n');
})().catch(error => {console.error(error); process.exitCode = 1;});
