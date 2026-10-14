/* TC100 web UI language switch (English / Français).
 *
 * The pages are written in English. In French, i18n/fr.js is loaded once
 * (cached by version) and every visible text node, placeholder, title,
 * aria-label and confirmation message whose English text is in the
 * dictionary is replaced; a MutationObserver does the same for the parts the
 * scripts load or update later. "rules" handle the few messages built with
 * numbers ("Running for 3 h"). In English nothing runs after the toggle is
 * drawn. The choice is kept per browser (localStorage), defaulting to the
 * browser language. Switching reloads the page.
 */
(function () {
  "use strict";
  var KEY = "tc100_lang";
  var VERSION = "1.8.4-i18n2";
  var lang = null;
  try { lang = window.localStorage.getItem(KEY); } catch (e) { /* storage blocked */ }
  if (lang !== "fr" && lang !== "en") {
    lang = /^fr\b/i.test((navigator.languages && navigator.languages[0]) || navigator.language || "") ? "fr" : "en";
  }
  document.documentElement.lang = lang;

  var ATTRS = ["placeholder", "title", "aria-label", "data-message"];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, PRE: 1, CODE: 1, NOSCRIPT: 1 };
  var dict = null;
  var rules = [];

  function lookup(text) {
    var key = text.replace(/\s+/g, " ").trim();
    if (!key || !/[A-Za-z]/.test(key)) return null;
    if (Object.prototype.hasOwnProperty.call(dict, key)) return dict[key];
    for (var i = 0; i < rules.length; i++) {
      if (rules[i][0].test(key)) return key.replace(rules[i][0], rules[i][1]);
    }
    return null;
  }

  function skipped(el) {
    for (; el && el.nodeType === 1; el = el.parentNode) {
      if (SKIP[el.nodeName] || el.isContentEditable || el.getAttribute("translate") === "no" ||
          (el.classList && el.classList.contains("notranslate"))) return true;
    }
    return false;
  }

  function translateText(node) {
    var v = node.nodeValue;
    if (!v || v.length > 600) return;
    var t = lookup(v);
    if (t === null || t === v.trim()) return;
    var lead = v.match(/^\s*/)[0], trail = v.match(/\s*$/)[0];
    node.nodeValue = lead + t + trail;
  }

  function translateAttrs(el) {
    for (var i = 0; i < ATTRS.length; i++) {
      var a = el.getAttribute(ATTRS[i]);
      if (a) { var t = lookup(a); if (t !== null && t !== a) el.setAttribute(ATTRS[i], t); }
    }
    if (el.nodeName === "INPUT" && /^(button|submit|reset)$/i.test(el.type) && el.value) {
      var tv = lookup(el.value); if (tv !== null) el.value = tv;
    }
  }

  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === 3) { if (!skipped(root.parentNode)) translateText(root); return; }
    if (root.nodeType !== 1 || skipped(root)) return;
    translateAttrs(root);
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (n.nodeType === 1) return SKIP[n.nodeName] || n.getAttribute("translate") === "no" ||
          n.classList.contains("notranslate") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var n;
    while ((n = walker.nextNode())) {
      if (n.nodeType === 3) translateText(n); else translateAttrs(n);
    }
  }

  function start(data) {
    dict = data.strings || {};
    rules = (data.rules || []).map(function (r) { return [new RegExp(r[0]), r[1]]; });
    if (document.title) { var tt = lookup(document.title); if (tt) document.title = tt; }
    translateTree(document.body);
    var pending = [], queued = false;
    function flush() {
      queued = false;
      var list = pending; pending = [];
      for (var i = 0; i < list.length; i++) translateTree(list[i]);
    }
    new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === "characterData") pending.push(m.target);
        else if (m.type === "attributes") pending.push(m.target);
        else for (var j = 0; j < m.addedNodes.length; j++) pending.push(m.addedNodes[j]);
      }
      if (!queued && pending.length) {
        queued = true;
        (window.requestAnimationFrame || setTimeout)(flush);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true,
                                attributes: true, attributeFilter: ATTRS });
  }

  function drawToggle() {
    var btn = document.getElementById("lang_toggle");
    if (!btn) return;
    btn.textContent = lang === "fr" ? "EN" : "FR";
    btn.setAttribute("title", lang === "fr" ? "Switch to English" : "Passer en français");
    btn.setAttribute("translate", "no");
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      try { window.localStorage.setItem(KEY, lang === "fr" ? "en" : "fr"); } catch (e) { return; }
      window.location.reload();
    });
  }

  window.tc100Lang = lang;
  // Lets the scripts translate a message they put somewhere the observer
  // does not see (alert/confirm/prompt).
  window.tc100T = function (s) { if (!dict) return s; var t = lookup(String(s)); return t === null ? s : t; };

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }
  ready(drawToggle);
  if (lang !== "fr") return;
  // Hide the page until it is translated (no flash of English), at most 1.5 s.
  var root = document.documentElement;
  var hide = document.createElement("style");
  hide.textContent = "html.i18n-pending body{visibility:hidden}";
  (document.head || root).appendChild(hide);
  root.classList.add("i18n-pending");
  function reveal() { root.classList.remove("i18n-pending"); }
  setTimeout(reveal, 1500);
  // The dictionary is a script (window.tc100I18nFr): lighttpd serves .js
  // compressed and cached for 30 days under the versioned URL.
  var tag = document.createElement("script");
  tag.src = "/i18n/fr.js?v=" + VERSION;
  tag.onload = function () {
    ready(function () {
      try { if (window.tc100I18nFr) start(window.tc100I18nFr); } finally { reveal(); }
    });
  };
  tag.onerror = reveal;
  (document.head || document.documentElement).appendChild(tag);
})();
