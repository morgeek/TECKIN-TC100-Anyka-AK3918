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
  process.stdout.write('CSRF bootstrap, POST headers, HTTP failures and dashboard lifecycle: OK\n');
})().catch(error => {console.error(error); process.exitCode = 1;});
