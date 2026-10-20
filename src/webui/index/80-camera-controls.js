  // --- Camera controls panel and Settings feature switches ---
  // Camera controls (camcontrols.cgi panel/set/mode): the day/night mode and
  // the IR, black & white and LED switches, shown with their real state —
  // under the live picture (#cam_panel) and in Settings → Day/night
  // ([data-cam-panel]). Polled every 30 s while one is on screen and the page
  // is visible (auto mode switches the IR by itself).
  var camPanelTimer = null;
  var camPanelBusy = false;
  function camPanels() {
    return Array.prototype.slice.call(document.querySelectorAll("#cam_panel, [data-cam-panel]"));
  }
  function renderCamPanel(st) {
    if (!st || !st.ok) return;
    camPanels().forEach(function (panel) {
      Array.prototype.slice.call(panel.querySelectorAll("[data-cam-mode]")).forEach(function (b) {
        var on = b.getAttribute("data-cam-mode") === st.mode;
        b.classList.toggle("is-selected", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      Array.prototype.slice.call(panel.querySelectorAll("[data-cam-control]")).forEach(function (b) {
        var on = st[b.getAttribute("data-cam-control")] === 1;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      var status = panel.querySelector(".cam-status");
      if (status) status.textContent = st.mode === "custom" ? "Manual settings" : "";
      panel.classList.remove("is-unavailable");
    });
    var liveFlip = byId("live_flip");
    if (liveFlip && st.flip !== undefined) {
      liveFlip.classList.toggle("is-info", st.flip === 1);
      liveFlip.setAttribute("aria-pressed", st.flip === 1 ? "true" : "false");
    }
  }
  function camPanelFailed() {
    camPanels().forEach(function (panel) {
      panel.classList.add("is-unavailable");
      var status = panel.querySelector(".cam-status");
      if (status) status.textContent = "Camera controls unavailable";
    });
  }
  function refreshCamPanel() {
    if (!camPanels().length || camPanelBusy) return Promise.resolve();
    return fetch("cgi-bin/camcontrols.cgi?cmd=panel", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(renderCamPanel)
      .catch(camPanelFailed);
  }
  function camPanelCommand(body) {
    if (camPanelBusy) return;
    camPanelBusy = true;
    camPanels().forEach(function (p) { p.classList.add("is-busy"); });
    csrfFetch("cgi-bin/camcontrols.cgi", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body
    })
      .then(function (r) { return r.json(); })
      .then(function (st) {
        if (!st || !st.ok) throw new Error((st && st.error) || "failed");
        renderCamPanel(st);
        if (byId("liveview")) refreshLiveImage();
      })
      .catch(function () { showResult("Camera control failed", "is-danger"); })
      .finally(function () {
        camPanelBusy = false;
        camPanels().forEach(function (p) { p.classList.remove("is-busy"); });
      });
  }
  function initCamPanel() {
    var panels = camPanels().filter(function (p) { return !p.dataset.camBound; });
    if (!panels.length) return;
    panels.forEach(function (panel) {
      panel.dataset.camBound = "1";
      panel.addEventListener("click", function (event) {
        var mode = event.target.closest("[data-cam-mode]");
        var ctl = event.target.closest("[data-cam-control]");
        if (mode) {
          camPanelCommand("cmd=mode&value=" + encodeURIComponent(mode.getAttribute("data-cam-mode")));
        } else if (ctl) {
          var on = ctl.getAttribute("aria-pressed") === "true" ? 0 : 1;
          camPanelCommand("cmd=set&control=" + encodeURIComponent(ctl.getAttribute("data-cam-control")) + "&on=" + on);
        }
      });
    });
    refreshCamPanel();
    if (camPanelTimer) return;
    camPanelTimer = setInterval(function () {
      if (!camPanels().length) { clearInterval(camPanelTimer); camPanelTimer = null; return; }
      if (document.visibilityState === "visible") refreshCamPanel();
    }, 30000);
  }

  // On/off switches for features in Settings (.svc-toggle data-service=X):
  // on = started now and at every boot, off = stopped and not started at boot
  // (scripts.cgi start/stop + enable/disable). The state shown is the
  // service's real one.
  function initServiceToggles(root) {
    var toggles = Array.prototype.slice.call((root || document).querySelectorAll("input.svc-toggle[data-service]"));
    if (!toggles.length) return;
    function show(input, info) {
      var note = input.parentNode.querySelector(".svc-toggle-state");
      input.checked = !!(info && (info.running || info.autostart_enabled));
      input.disabled = false;
      if (note) {
        var txt = !info ? "" : info.running ? (info.autostart_enabled ? "" : "(running, not started at boot)")
                  : (info.autostart_enabled ? "(not running)" : "");
        note.textContent = txt;
      }
    }
    fetch("cgi-bin/scripts.cgi?cmd=allstates", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (json) {
        var by = {};
        (json.services || []).forEach(function (svc) { by[svc.script] = svc; });
        toggles.forEach(function (input) { show(input, by[input.getAttribute("data-service")]); });
      })
      .catch(function () { toggles.forEach(function (input) { input.disabled = false; }); });
    toggles.forEach(function (input) {
      if (input.dataset.bound) return;
      input.dataset.bound = "1";
      input.addEventListener("change", function () {
        var name = input.getAttribute("data-service");
        var on = input.checked;
        input.disabled = true;
        var q = function (cmd) {
          return csrfFetch("cgi-bin/scripts.cgi?cmd=" + cmd + "&script=" + encodeURIComponent(name), { method: "POST" });
        };
        (on ? q("enable").then(function () { return q("start"); }) : q("stop").then(function () { return q("disable"); }))
          .then(function () { return fetch("cgi-bin/scripts.cgi?cmd=state&script=" + encodeURIComponent(name), { cache: "no-store" }); })
          .then(function (r) { return r.json(); })
          .then(function (info) { show(input, info); showResult(on ? "Switched on" : "Switched off", "is-success"); })
          .catch(function () { input.checked = !on; input.disabled = false; showResult("Could not switch the service", "is-danger"); });
      });
    });
  }

