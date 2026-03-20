function initScriptsPage() {
  if (typeof window.__scriptsPageStopPolling === 'function') {
    try {
      window.__scriptsPageStopPolling();
    } catch (e) {
      console.error(e);
    }
  }

  var serviceRefreshTimer = 0;
  var serviceStatesController = null;
  var serviceRowsByScript = {};
  var SERVICE_POLL_VISIBLE_MS = 15000;
  var SERVICE_POLL_HIDDEN_MS = 60000;

  function loadInto(selector, url) {
    var el = document.querySelector(selector);
    if (!el) {
      return;
    }
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        el.innerHTML = html;
        initScriptsPage();
      })
      .catch(function (e) {
        console.error(e);
      });
  }

  function openQuickview(content) {
    var qv = document.getElementById('quickviewDefault');
    var v = document.getElementById('quicViewContent');
    if (!qv || !v) {
      if (window.showResult && window.showResult !== openQuickview) {
        window.showResult(String(content || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
      } else {
        alert(String(content || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
      }
      return;
    }
    v.innerHTML = content;
    if (!qv.classList.contains('is-active')) {
      qv.classList.add('is-active');
    }
  }

  function parseJsonSafe(text) {
    try {
      return JSON.parse(text);
    } catch (e) {
      return null;
    }
  }

  function toBoolInt(value) {
    return value === true || value === 1 || value === '1';
  }

  function isHostActive() {
    var content = document.getElementById('content');
    if (window.isHostStillActive && !window.isHostStillActive(content)) {
      return false;
    }
    return true;
  }

  function clearServiceStatePolling() {
    if (serviceRefreshTimer) {
      clearTimeout(serviceRefreshTimer);
      serviceRefreshTimer = 0;
    }
    if (serviceStatesController) {
      serviceStatesController.abort();
      serviceStatesController = null;
    }
  }

  window.__scriptsPageStopPolling = clearServiceStatePolling;

  function rebuildServiceRowMap() {
    serviceRowsByScript = {};
    Array.prototype.slice.call(document.querySelectorAll('tr[data-script-name]')).forEach(function (row) {
      var scriptName = row.dataset.scriptName || '';
      if (scriptName) {
        serviceRowsByScript[scriptName] = row;
      }
    });
  }

  function getRowByScript(scriptName) {
    if (!scriptName) {
      return null;
    }
    return serviceRowsByScript[scriptName] || null;
  }

  function scheduleServiceStateRefresh(delayMs) {
    if (!isHostActive()) {
      clearServiceStatePolling();
      return;
    }
    if (serviceRefreshTimer) {
      clearTimeout(serviceRefreshTimer);
    }
    var nextDelay = typeof delayMs === 'number'
      ? delayMs
      : (document.hidden ? SERVICE_POLL_HIDDEN_MS : SERVICE_POLL_VISIBLE_MS);
    serviceRefreshTimer = setTimeout(function () {
      serviceRefreshTimer = 0;
      refreshServiceStates();
    }, nextDelay);
  }

  function syncAutorunInput(row, stateInfo) {
    if (!row || !stateInfo) {
      return;
    }
    var autostartInput = row.querySelector('input.autostart');
    if (!autostartInput) {
      return;
    }
    autostartInput.checked = toBoolInt(stateInfo.autostart_enabled);
  }

  function formatUptime(s) {
    if (typeof s !== 'number' || s < 0) return '';
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm';
    var h = Math.floor(m / 60);
    var rm = m % 60;
    if (h < 24) return h + 'h' + (rm ? ' ' + rm + 'm' : '');
    var d = Math.floor(h / 24);
    var rh = h % 24;
    return d + 'd' + (rh ? ' ' + rh + 'h' : '');
  }

  function updateStatusTag(tag, state, uptimeSecs) {
    if (!tag) {
      return;
    }

    tag.classList.remove('is-running', 'is-stopped', 'is-error', 'is-unknown');
    switch (state) {
      case 'running':
        tag.classList.add('is-running');
        var upLabel = formatUptime(uptimeSecs);
        tag.textContent = upLabel ? 'Running \u00b7 ' + upLabel : 'Running';
        tag.title = upLabel ? 'Running for ' + upLabel : 'Current state reported by this script';
        break;
      case 'stopped':
        tag.classList.add('is-stopped');
        tag.textContent = 'Stopped';
        tag.title = 'Current state reported by this script';
        break;
      case 'error':
        tag.classList.add('is-error');
        tag.textContent = 'Error';
        tag.title = 'Status probe returned an error';
        break;
      case 'timeout':
        tag.classList.add('is-error');
        tag.textContent = 'Timeout';
        tag.title = 'Status probe timed out';
        break;
      default:
        tag.classList.add('is-unknown');
        tag.textContent = 'Unknown';
        tag.title = 'Unable to determine service state';
        break;
    }
  }

  function updateActionButton(btn, scriptName, state, hasStart, hasStop) {
    if (!btn || !scriptName) {
      return;
    }

    var actionCmd = 'start';
    var actionLabel = 'Start';
    var actionClass = 'is-link';
    var actionHint = 'Start this service now.';
    var actionDisabled = false;

    if (state === 'running') {
      if (hasStop) {
        actionCmd = 'stop';
        actionLabel = 'Stop';
        actionClass = 'is-danger';
        actionHint = 'Stop this service now.';
      } else {
        actionLabel = 'Running';
        actionClass = 'is-light';
        actionHint = 'This service has no stop handler.';
        actionDisabled = true;
      }
    } else if (!hasStart) {
      actionLabel = 'N/A';
      actionClass = 'is-light';
      actionHint = 'This service has no start handler.';
      actionDisabled = true;
    }

    btn.classList.remove('is-link', 'is-danger', 'is-light');
    btn.classList.add(actionClass);
    btn.textContent = actionLabel;
    btn.title = actionHint;
    btn.dataset.target = 'cgi-bin/scripts.cgi?cmd=' + actionCmd + '&script=' + encodeURIComponent(scriptName);
    btn.disabled = !!actionDisabled;
  }

  function applyServiceState(row, stateInfo) {
    if (!row || !stateInfo) {
      return;
    }

    var scriptName = row.dataset.scriptName || '';
    var state = String(stateInfo.state || 'unknown').toLowerCase();
    var hasStart = toBoolInt(stateInfo.has_start);
    var hasStop = toBoolInt(stateInfo.has_stop);

    updateStatusTag(row.querySelector('.service-status'), state, stateInfo.uptime_s);
    updateActionButton(row.querySelector('button.script_action_toggle'), scriptName, state, hasStart, hasStop);
    syncAutorunInput(row, stateInfo);
  }

  function refreshServiceState(row) {
    if (!row) {
      return Promise.resolve();
    }
    var scriptName = row.dataset.scriptName || '';
    if (!scriptName) {
      return Promise.resolve();
    }

    return fetch('cgi-bin/scripts.cgi?cmd=state&script=' + encodeURIComponent(scriptName), { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (text) {
        var json = parseJsonSafe(text);
        if (!json || json.status !== 'ok') {
          updateStatusTag(row.querySelector('.service-status'), 'unknown');
          return;
        }
        applyServiceState(row, json);
      })
      .catch(function (err) {
        console.error(err);
        updateStatusTag(row.querySelector('.service-status'), 'unknown');
      });
  }

  function refreshServiceStates() {
    if (!isHostActive()) {
      clearServiceStatePolling();
      return;
    }

    if (serviceStatesController) {
      serviceStatesController.abort();
    }
    var controller = new AbortController();
    serviceStatesController = controller;

    fetch('cgi-bin/scripts.cgi?cmd=allstates', { cache: 'no-store', signal: controller.signal })
      .then(function (r) { return r.json(); })
      .then(function (json) {
        if (!isHostActive()) {
          return;
        }
        if (!json || json.status !== 'ok' || !Array.isArray(json.services)) {
          return;
        }
        json.services.forEach(function (stateInfo) {
          var row = getRowByScript(stateInfo.script);
          if (row) {
            applyServiceState(row, stateInfo);
          }
        });
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') {
          return;
        }
        console.error('Service bulk poll error:', err);
      })
      .finally(function () {
        if (serviceStatesController === controller) {
          serviceStatesController = null;
        }
        scheduleServiceStateRefresh();
      });
  }

  rebuildServiceRowMap();

  Array.prototype.slice.call(document.querySelectorAll('button.script_action_toggle,button.script_action_stop,button.script_action_start')).forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var e = ev.currentTarget;
      if (e.disabled) {
        return false;
      }
      e.disabled = true;
      e.classList.add('is-loading');
      var target = e.dataset.target;
      fetch(target, { cache: 'no-store' })
        .then(function (r) { return r.text(); })
        .then(function (res) {
          openQuickview(res);
          clearServiceStatePolling();
          var refreshHost = document.getElementById('embeddedServices') ? '#embeddedServices' : '#content';
          loadInto(refreshHost, 'cgi-bin/scripts.cgi');
        })
        .catch(function (err) {
          console.error(err);
        })
        .finally(function () {
          e.disabled = false;
          e.classList.remove('is-loading');
        });
      return false;
    });
  });

  Array.prototype.slice.call(document.querySelectorAll('input.autostart')).forEach(function (inp) {
    inp.addEventListener('change', function (ev) {
      var e = ev.currentTarget;
      var row = e.closest('tr[data-script-name]');
      var desiredState = e.checked;
      var url = desiredState ? e.dataset.checked : e.dataset.unchecked;
      e.disabled = true;
      fetch(url, { cache: 'no-store' })
        .then(function (r) { return r.text(); })
        .then(function (text) {
          var res = parseJsonSafe(text);
          if (!res || res.status !== 'ok') {
            e.checked = !desiredState;
            return;
          }
          if (typeof res.autostart_enabled !== 'undefined') {
            e.checked = toBoolInt(res.autostart_enabled);
          } else {
            e.checked = desiredState;
          }
          if (row) {
            refreshServiceState(row);
          }
          scheduleServiceStateRefresh(800);
        })
        .catch(function (err) {
          e.checked = !desiredState;
          console.error(err);
        })
        .finally(function () {
          e.disabled = false;
        });
    });
  });

  Array.prototype.slice.call(document.querySelectorAll('.view_script')).forEach(function (el) {
    el.addEventListener('click', function (ev) {
      ev.preventDefault();
      var e = ev.currentTarget;
      var qv = document.getElementById('quickviewDefault');
      var v = document.getElementById('quicViewContent');
      var href = e.getAttribute('href');
      if (!qv || !v) {
        if (href) {
          window.open(href, '_blank', 'noopener');
        }
        return false;
      }
      if (qv && qv.classList.contains('is-active')) {
        qv.classList.toggle('is-active');
      }
      if (v) {
        v.innerHTML = 'Loading...';
      }
      if (href && v) {
        fetch(href, { cache: 'no-store' })
          .then(function (r) { return r.text(); })
          .then(function (html) {
            v.innerHTML = html;
            if (qv) {
              qv.classList.toggle('is-active');
            }
          })
          .catch(function (err) {
            console.error(err);
          });
      }
      return false;
    });
  });

  refreshServiceStates();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initScriptsPage);
} else {
  initScriptsPage();
}
