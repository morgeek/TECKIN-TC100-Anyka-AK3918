document.addEventListener('DOMContentLoaded', function () {
  function loadInto(selector, url) {
    var el = document.querySelector(selector);
    if (!el) return;
    fetch(url).then(function (r) { return r.text(); }).then(function (html) { el.innerHTML = html; }).catch(function (e) { console.error(e); });
  }

  Array.prototype.slice.call(document.querySelectorAll('button.script_action_stop,button.script_action_start')).forEach(function (btn) {
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      var e = ev.currentTarget;
      if (e.disabled) return false;
      e.disabled = true;
      e.classList.add('is-loading');
      var target = e.dataset.target;
      fetch(target).then(function (r) { return r.text(); }).then(function (res) {
        var show = document.getElementById('show_' + e.dataset.script);
        if (show) show.innerHTML = res;
        loadInto('#content', 'cgi-bin/scripts.cgi');
      }).catch(function (err) { console.error(err); }).finally(function () { e.disabled = false; e.classList.remove('is-loading'); });
      return false;
    });
  });

  Array.prototype.slice.call(document.querySelectorAll('input.autostart')).forEach(function (inp) {
    inp.addEventListener('click', function (ev) {
      ev.preventDefault();
      var e = ev.currentTarget;
      e.disabled = true;
      var url = e.checked ? e.dataset.checked : e.dataset.unchecked;
      fetch(url).then(function (r) { try { return r.json(); } catch (ex) { return r.text(); } }).then(function (res) {
        e.disabled = false;
        if (res && res.status == 'ok') {
          e.checked = !e.checked;
        }
      }).catch(function (err) { e.disabled = false; console.error(err); });
      return false;
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
      if (href && v) fetch(href).then(function (r) { return r.text(); }).then(function (html) { v.innerHTML = html; if (qv) qv.classList.toggle('is-active'); }).catch(function (err) { console.error(err); });
      return false;
    });
  });
});
