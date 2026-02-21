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
      var desiredState = e.checked;
      var url = desiredState ? e.dataset.checked : e.dataset.unchecked;
      e.disabled = true;
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.status !== 'ok') {
            e.checked = !desiredState;
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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initScriptsPage);
} else {
  initScriptsPage();
}
