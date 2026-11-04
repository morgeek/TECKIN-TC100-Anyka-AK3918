  // --- Talk volume controls ---
  function initPttVolumeControls() {
    var vol = byId("ptt_vol");
    var lbl = byId("ptt_vol_label");
    if (!vol || !lbl) {
      return;
    }

    // The stored volume is read the first time the talk / listen controls are used or the slider area is touched,
    // not at every page load (one CGI request, ~10 forks, for a control most visits never use).
    var volLoaded = false;
    function loadPttVolume() {
      if (volLoaded) return;
      volLoaded = true;
      fetch("cgi-bin/action.cgi?cmd=get_ptt_vol", { cache: "no-store" })
        .then(function (r) {
          return r.text();
        })
        .then(function (t) {
          var v = parseInt(String(t || "").trim(), 10);
          if (!isNaN(v) && v >= 0 && v <= 100) {
            vol.value = v;
            lbl.textContent = v + "%";
          }
        })
        .catch(function () { volLoaded = false; });
    }
    [byId("ptt_btn"), byId("listen_btn"), byId("ptt_test_btn"), vol.parentNode].forEach(function (el) {
      if (!el) return;
      ["click", "pointerenter", "pointerdown", "focusin", "touchstart"].forEach(function (ev) {
        el.addEventListener(ev, loadPttVolume, { passive: true });
      });
    });

    vol.addEventListener("input", function () {
      lbl.textContent = vol.value + "%";
    });
    vol.addEventListener("change", function () {
      csrfFetch("cgi-bin/action.cgi?cmd=conf_ptt&audiooutVol=" + encodeURIComponent(vol.value))
        .catch(function () {});
    });
  }

