  // --- Settings saves: reply checking, read-back, live image tuning ---
  function readSettingsReply(response) {
    return response.text().then(function(text) {
      var data;
      try { data = JSON.parse(text); } catch (e) { /* Legacy handlers still return HTML. */ }
      if (data && data.ok === false) throw new Error(data.error || data.message || "The camera rejected these settings.");
      if (data && data.ok === true) return data;
      var plain = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
      if (/\b(error|failed|unknown|invalid|aborted|denied|rollback)\b/i.test(plain)) {
        throw new Error(plain.slice(0, 240));
      }
      return { ok: false, unconfirmed: true, message: "The camera replied, but saving is not confirmed. Reload settings to check before retrying." };
    });
  }

  function settingsConfigValues(command, params, config) {
    var values = {};
    if (command === "set_video_params") {
      var stream = params.get("stream");
      if (stream !== "0" && stream !== "1") return false;
      var video = config.video && config.video[stream === "1" ? "sub" : "main"];
      if (!video) return false;
      values["video_size" + stream] = video.width + "x" + video.height;
      var mapping = { video_codec: "codec", fps: "fps", brbitrate: "bitrate", goplen: "gop", video_format: "format", minqp: "minqp", maxqp: "maxqp", smartmode: "smartmode" };
      Object.keys(mapping).forEach(function(key) { values[key + stream] = video[mapping[key]]; });
    } else if (command === "conf_audioin") {
      if (!config.audio) return false;
      values = { samplerate: config.audio.samplerate, audioinVol: config.audio.volume, audioCodec0: config.audio.codec_main };
    } else return false;
    return values;
  }

  function settingsReadbackMatches(command, params, config) {
    var values = settingsConfigValues(command, params, config);
    return !!values && Object.keys(values).every(function(key) {
      return values[key] !== undefined && values[key] !== null && params.get(key) === String(values[key]);
    });
  }

  function refreshSettingsVideoForms(dash, config, dirtyForms) {
    ["formVideoAdvanced", "formVideoSub", "formAudioAdvanced"].forEach(function(id) {
      var form = dash.querySelector("#" + id);
      if (!form || dirtyForms.indexOf(form) !== -1) return;
      var params = new URLSearchParams(new FormData(form));
      var command = id === "formAudioAdvanced" ? "conf_audioin" : "set_video_params";
      var values = settingsConfigValues(command, params, config);
      if (!values) return;
      Object.keys(values).forEach(function(name) {
        var field = form.querySelector('[name="' + name + '"]');
        if (field && values[name] !== undefined && values[name] !== null) field.value = String(values[name]);
      });
    });
  }

  // Live image tuning (Image tab). Ranges show their value next to the label;
  // the "applied" line reflects /var/run/isp_tune.status from the camera.
  function ispTuneLabel(input) {
    var out = document.getElementById(input.id + "_out");
    if (!out) return;
    var v = parseInt(input.value, 10) || 0;
    if (input.id === "isp_exposure_max_pct") out.textContent = v ? v + " %" : "off";
    else out.textContent = (v > 0 ? "+" : "") + v;
  }

  function loadIspTune(root) {
    var form = (root || document).querySelector("#formIspTune");
    if (!form) return;
    form.querySelectorAll('input[type="range"]').forEach(function(input) {
      if (!input.dataset.ispBound) {
        input.addEventListener("input", function() { ispTuneLabel(input); });
        input.dataset.ispBound = "1";
      }
    });
    fetch("cgi-bin/state.cgi?cmd=isp_tune&format=json", { cache: "no-store" })
      .then(function(r) { if (!r.ok) throw new Error("isp_tune unavailable"); return r.json(); })
      .then(function(d) {
        var conf = d.conf || {};
        var map = { isp_brightness: "BRIGHTNESS", isp_contrast: "CONTRAST", isp_saturation: "SATURATION",
                    isp_sharpness: "SHARPNESS", isp_hue: "HUE", isp_exposure_max_pct: "EXPOSURE_MAX_PCT" };
        var enable = form.querySelector("#isp_enable");
        if (enable) enable.checked = d.enabled === 1;
        Object.keys(map).forEach(function(id) {
          var input = form.querySelector("#" + id);
          if (!input) return;
          input.value = conf[map[id]] === null || conf[map[id]] === undefined ? 0 : conf[map[id]];
          ispTuneLabel(input);
        });
        var hz = form.querySelector("#isp_power_hz");
        if (hz) hz.value = conf.POWER_HZ ? String(conf.POWER_HZ) : "";
        initPrivacyMasks(form, conf);
        var status = form.querySelector("#isp_tune_applied");
        if (status) {
          var a = d.applied;
          if (d.enabled !== 1) status.textContent = "Live tuning is off.";
          else if (!a) status.textContent = "Waiting for the video server to report applied values…";
          else status.textContent = "Applied on the camera: brightness " + a.BRIGHTNESS + ", contrast " + a.CONTRAST +
            ", saturation " + a.SATURATION + ", sharpness " + a.SHARPNESS + ", hue " + a.HUE +
            (a.POWER_HZ ? ", " + a.POWER_HZ + " Hz" : "") +
            (a.EXPOSURE_NOW ? ", exposure max " + a.EXPOSURE_NOW + (a.EXPOSURE_ORIG ? " / " + a.EXPOSURE_ORIG : "") : "") +
            (a.MASKS ? ", " + a.MASKS + " privacy mask(s)" + (a.MASK_RC ? " (error " + a.MASK_RC + ")" : "") : "") + ".";
        }
      })
      .catch(function() {
        var status = form.querySelector("#isp_tune_applied");
        if (status) status.textContent = "Image tuning state could not be read.";
      });
  }

  function saveSettingsRequest(action, params, progress) {
    var command = new URL(action, window.location.href).searchParams.get("cmd");
    progress("Saving…", "pending");
    return csrfFetch(action, {
      method: "POST", body: params.toString(),
      headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json" }
    }).then(readSettingsReply).then(function(result) {
      if (result.unconfirmed) return result;
      if (result.restart === "verified") {
        progress("Video check passed. Refreshing current values…", "pending");
        return fetch("cgi-bin/state.cgi?cmd=fullconfig", { cache: "no-store" })
          .then(function(response) { if (!response.ok) throw new Error("Readback unavailable"); return response.json(); })
          .then(function(config) { result.settingsConfig = config; return result; })
          .catch(function() { return { ok: false, unconfirmed: true, message: "The video check passed, but current values could not be refreshed. Reopen Settings before making more changes." }; });
      }
      if (command === "isp_tune") setTimeout(function() { loadIspTune(document); }, 4000);
      if (command !== "set_video_params" && command !== "conf_audioin") return result;
      progress("Checking the saved settings…", "pending");
      // One read after an explicit save; no new background polling loop.
      return fetch("cgi-bin/state.cgi?cmd=fullconfig", { cache: "no-store" })
        .then(function(response) { if (!response.ok) throw new Error("Readback unavailable"); return response.json(); })
        .then(function(config) {
          if (!settingsReadbackMatches(command, params, config)) {
            return { ok: false, unconfirmed: true, message: "The values read from the camera differ from this form. Your edits are kept; reload settings to compare before retrying." };
          }
          return { ok: true, message: "Saved and checked. Video restart was requested; open the camera preview to check playback.", restart: "scheduled" };
        }).catch(function() {
          return { ok: false, unconfirmed: true, message: "The camera accepted the request, but saved values could not be checked. Your edits are kept; reload settings before retrying." };
        });
    });
  }

  function settingsSaveStatus(form, message, kind) {
    var status = form.querySelector(".settings-save-status");
    if (!status) {
      status = document.createElement("p");
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      form.appendChild(status);
    }
    status.className = "settings-save-status" + (kind === "error" ? " has-text-danger" : (kind === "warning" ? " has-text-warning-dark" : ""));
    status.textContent = message;
  }

  function setSettingsFormBusy(form, busy) {
    form.setAttribute("aria-busy", busy ? "true" : "false");
    form.querySelectorAll("input, select, textarea, button").forEach(function(field) {
      if (busy) { field._settingsWasDisabled = field.disabled; field.disabled = true; }
      else if (field._settingsWasDisabled !== undefined) { field.disabled = field._settingsWasDisabled; delete field._settingsWasDisabled; }
    });
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.classList.toggle("is-loading", busy);
  }

