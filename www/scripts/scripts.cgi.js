function initScriptsPage() {
  function loadInto(selector, url) {
    var el = document.querySelector(selector);
    if (!el) return;
    fetch(url, { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (html) {
      el.innerHTML = html;
      initScriptsPage();
    }).catch(function (e) { console.error(e); });
  }

  function openQuickview(content) {
    var qv = document.getElementById('quickviewDefault');
    var v = document.getElementById('quicViewContent');
    if (!qv || !v) return;
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

  function updateStatusTag(tag, state) {
    if (!tag) {
      return;
    }

    tag.classList.remove('is-running', 'is-stopped', 'is-error', 'is-unknown');
    switch (state) {
      case 'running':
        tag.classList.add('is-running');
        tag.textContent = 'Running';
        tag.title = 'Current state reported by this script';
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

    updateStatusTag(row.querySelector('.service-status'), state);
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
    function tick() {
      var content = document.getElementById("content");
      if (window.isHostStillActive && !window.isHostStillActive(content)) {
        return;
      }

      fetch('cgi-bin/scripts.cgi?cmd=allstates', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (json) {
          if (!json || json.status !== 'ok' || !json.services) {
            return;
          }
          var rows = Array.prototype.slice.call(document.querySelectorAll('tr[data-script-name]'));
          json.services.forEach(function (stateInfo) {
            var row = rows.find(function (r) { return r.dataset.scriptName === stateInfo.script; });
            if (row) {
              applyServiceState(row, stateInfo);
            }
          });
        })
        .catch(function (err) {
          console.error('Service bulk poll error:', err);
        })
        .finally(function () {
          // Poll every 5 seconds for bulk status, much lighter than 20x 300ms staggered hits.
          setTimeout(tick, 5000);
        });
    }

    tick();
  }

  Array.prototype.slice.call(document.querySelectorAll('button.script_action_toggle,button.script_action_stop,button.script_action_start')).forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var e = ev.currentTarget;
      if (e.disabled) return false;
      e.disabled = true;
      e.classList.add('is-loading');
      var target = e.dataset.target;
      fetch(target, { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (res) {
        openQuickview(res);
        var refreshHost = document.getElementById('embeddedServices') ? '#embeddedServices' : '#content';
        loadInto(refreshHost, 'cgi-bin/scripts.cgi');
      }).catch(function (err) { console.error(err); }).finally(function () { e.disabled = false; e.classList.remove('is-loading'); });
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
      if (qv && qv.classList.contains('is-active')) {
        qv.classList.toggle('is-active');
      }
      if (v) v.innerHTML = 'Loading...';
      var href = e.getAttribute('href');
      if (href && v) fetch(href, { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (html) { v.innerHTML = html; if (qv) qv.classList.toggle('is-active'); }).catch(function (err) { console.error(err); });
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
