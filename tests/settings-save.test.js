const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../www/scripts/index.bundle.min.js'), 'utf8');
const reply = body => ({ok: true, text: async () => typeof body === 'string' ? body : JSON.stringify(body)});
(async () => {
  const calls = [];
  let response = {ok: true};
  const main = {width: 1280, height: 720, codec: 0, fps: 20, bitrate: 1200, gop: 40, format: '1', minqp: 20, maxqp: 45, smartmode: 1};
  const sub = {...main, width: 352, height: 200, fps: 8, bitrate: 200, gop: 16};
  let config = {video: {main, sub}, audio: {samplerate: 8000, volume: 10, codec_main: 4}};
  const context = vm.createContext({Promise, URL, URLSearchParams, Object, String, Error,
    window: {location: {href: 'http://camera.test/'}},
    csrfFetch: async (url, opts) => {calls.push({url, opts}); return reply(response);},
    fetch: async (url, opts) => {calls.push({url, opts}); return {ok: true, json: async () => config};}
  });
  vm.runInContext(source.slice(source.indexOf('  // Settings save contract:'), source.indexOf('  function initPttVolumeControls()')), context);
  await assert.rejects(context.readSettingsReply(reply({ok: false, error: 'SD read-only'})), /SD read-only/);
  await assert.rejects(context.readSettingsReply(reply('Rollback failed<br/>')), /Rollback failed/);
  assert.equal((await context.readSettingsReply(reply('<p>Done</p>'))).unconfirmed, true);
  assert.equal((await context.readSettingsReply(reply(''))).unconfirmed, true);
  assert.equal((await context.readSettingsReply(reply({ok: 'true'}))).unconfirmed, true);
  assert.equal((await context.readSettingsReply(reply({ok: true}))).ok, true);

  const params = new URLSearchParams({stream: '1', video_size1: '352x200', video_codec1: '0', fps1: '8', brbitrate1: '200', goplen1: '16', video_format1: '1', minqp1: '20', maxqp1: '45', smartmode1: '1'});
  assert.equal(context.settingsReadbackMatches('set_video_params', params, config), true);
  assert.equal(context.settingsReadbackMatches('set_video_params', new URLSearchParams({...Object.fromEntries(params), stream: '0'}), config), false);
  const progress = [];
  let result = await context.saveSettingsRequest('cgi-bin/action.cgi?cmd=set_video_params', params, text => progress.push(text));
  assert.equal(result.ok, true);
  assert.equal(result.restart, 'scheduled', 'saved values do not prove video recovery');
  assert.equal(calls.length, 2, 'one mutation plus one config read');
  assert.equal(calls[0].opts.headers.Accept, 'application/json');
  assert.equal(new URLSearchParams(calls[0].opts.body).get('stream'), '1');
  assert.equal(progress.length, 2);
  config.video.sub = {...sub, fps: 10};
  result = await context.saveSettingsRequest('cgi-bin/action.cgi?cmd=set_video_params', params, () => {});
  assert.equal(result.unconfirmed, true, 'readback mismatch must preserve edits');
  response = {ok: false, error: 'Write failed'};
  calls.length = 0;
  await assert.rejects(context.saveSettingsRequest('cgi-bin/action.cgi?cmd=set_video_params', params, () => {}), /Write failed/);
  assert.equal(calls.length, 1, 'do not read back a rejected save');
  response = {ok: true};
  context.fetch = async () => {throw new Error('offline');};
  result = await context.saveSettingsRequest('cgi-bin/action.cgi?cmd=set_video_params', params, () => {});
  assert.equal(result.unconfirmed, true, 'a lost readback is not proof that writing failed');
  response = {ok: true, restart: 'verified', message: 'Video checked'};
  context.fetch = async () => ({ok: true, json: async () => config});
  result = await context.saveSettingsRequest('cgi-bin/action.cgi?cmd=set_rtsp_preset', new URLSearchParams({preset: 'medium'}), () => {});
  assert.equal(result.restart, 'verified');
  assert.equal(result.settingsConfig, config, 'profile application must refresh old video values');
  process.stdout.write('Settings response errors, stream routing, readback and restart distinction: OK\n');
})().catch(error => {console.error(error); process.exitCode = 1;});
