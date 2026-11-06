  // --- Siren on the camera's speaker (action.cgi play_sound, sounds/siren.pcm; chime and alert removed 2026-11-06) ---
  function initSoundButtons() {
    var tr = window.tc100T || function (s) { return s; };
    Array.prototype.forEach.call(document.querySelectorAll("[data-sound]"), function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.dataset.sound;
        if (name === "siren" && !confirm(tr("Sound the siren on the camera? It is loud."))) return;
        var vol = byId("ptt_vol");
        var level = vol && !vol.disabled ? parseInt(vol.value, 10) : 90;
        if (isNaN(level)) level = 90;
        btn.classList.add("is-loading");
        csrfFetch("cgi-bin/action.cgi?cmd=play_sound&format=json&sound=" + encodeURIComponent(name) + "&volume=" + level)
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.ok) showResult(tr("Playing on the camera speaker"), "is-success");
            else showResult(tr("The camera did not play the sound"), "is-danger");
          })
          .catch(function () { showResult(tr("The camera did not play the sound"), "is-danger"); })
          .finally(function () { btn.classList.remove("is-loading"); });
      });
    });
  }

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

