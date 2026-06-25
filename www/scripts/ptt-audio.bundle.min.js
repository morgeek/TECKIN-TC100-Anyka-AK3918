/**
 * PTT (Push-to-Talk) and Two-Way Audio Module — ES5 compatible
 * Speaker (PTT) is functional via ak_ao_demo on AK3918.
 * Listen (microphone stream) is disabled: AK3918 has no ALSA userspace.
 */

(function () {
  // Configuration
  var PTT_MIN_DURATION_MS = 400;
  var PTT_MAX_DURATION_MS = 9000;
  var PTT_UPLOAD_TIMEOUT_MS = 15000;
  var PTT_MAX_BLOB_BYTES = 524288;
  var AUDIO_LEVEL_UPDATE_MS = 50;
  var LISTEN_STREAM_TIMEOUT_MS = 30000;
  var maxSamples = Math.ceil((PTT_MAX_DURATION_MS / 1000) * 8000);
  var VALID_RESPONSES = { "OK": 1, "BUSY": 1, "TOO_LARGE": 1, "INVALID_PCM": 1, "PTT_BIN_MISSING": 1 };

  // State
  var audioCtx = null;
  var audioSrc = null;
  var scriptProc = null;
  var audioStream = null;
  var pttSamples = new Float32Array(maxSamples);
  var sampleCount = 0;
  var pttActive = false;
  var pttStarting = false;
  var pttHoldRequested = false;
  var pttStartTime = 0;
  var pttResetTimer = null;
  var pttMaxRecordTimer = null;
  var pttLevelUpdateTimer = null;
  var uploadXhr = null;
  var pttServerUnavailable = false;
  var listenActive = false;
  var listenAudio = null;
  var listenStreamTimeout = null;

  // DOM References
  var pttBtn = null;
  var listenBtn = null;
  var pttVol = null;
  var pttTestBtn = null;
  var pttLevelMeter = null;
  var pttMeterWrap = null;
  var pttLastSentEl = null;

  // Named handlers for cleanup
  function handlePointerUp() { stopRecording(false); }
  function handleMouseUp() { stopRecording(false); }
  function handleTouchEnd() { stopRecording(false); }
  function handleWindowBlur() { stopRecording(false); }
  function handleVisibilityChange() { if (document.hidden) stopRecording(false); }

  function byId(id) {
    return document.getElementById(id);
  }

  // String.padStart polyfill (not in ES5)
  function padStart(str, len, pad) {
    str = String(str);
    pad = pad || "0";
    while (str.length < len) { str = pad + str; }
    return str;
  }

  function setPttLabel(text) {
    var lbl = pttBtn.querySelector(".ptt-label");
    if (lbl) lbl.textContent = text;
  }

  function updatePttLastSent() {
    if (!pttLastSentEl) return;
    var now = new Date();
    pttLastSentEl.textContent = "Last PTT: " + padStart(now.getHours(), 2) + ":" + padStart(now.getMinutes(), 2);
    pttLastSentEl.style.display = "";
  }

  function setListenLabel(text) {
    var lbl = listenBtn.querySelector(".listen-label");
    if (lbl) lbl.textContent = text;
  }

  function setPttUnavailable(label, title) {
    pttServerUnavailable = true;
    pttHoldRequested = false;
    pttStarting = false;
    pttActive = false;
    clearResetTimer();
    clearMaxRecordTimer();
    clearLevelUpdateTimer();
    cancelInFlightUpload();
    releaseStream();
    pttBtn.classList.remove("is-loading", "ptt-recording", "ptt-sent", "ptt-error");
    pttBtn.disabled = true;
    pttBtn.title = title || "PTT unavailable";
    setPttLabel(label || "PTT unavailable");
    if (pttVol) {
      pttVol.disabled = true;
      pttVol.title = title || "";
    }
    if (pttTestBtn) {
      pttTestBtn.disabled = true;
    }
  }

  function clearResetTimer() {
    if (pttResetTimer) {
      clearTimeout(pttResetTimer);
      pttResetTimer = null;
    }
  }

  function clearMaxRecordTimer() {
    if (pttMaxRecordTimer) {
      clearTimeout(pttMaxRecordTimer);
      pttMaxRecordTimer = null;
    }
  }

  function clearLevelUpdateTimer() {
    if (pttLevelUpdateTimer) {
      clearInterval(pttLevelUpdateTimer);
      pttLevelUpdateTimer = null;
    }
  }

  function cancelInFlightUpload() {
    if (uploadXhr) {
      try { uploadXhr.abort(); } catch (e) {}
      uploadXhr = null;
    }
  }

  function resetPttBtn() {
    clearResetTimer();
    pttBtn.classList.remove("is-loading", "ptt-recording", "ptt-sent", "ptt-error");
    if (pttServerUnavailable) {
      pttBtn.disabled = true;
      return;
    }
    pttBtn.disabled = false;
    pttBtn.title = "Hold to talk to the camera speaker";
    setPttLabel("Hold to Talk");
  }

  function flashAndReset(label, cssClass, delayMs) {
    clearResetTimer();
    pttBtn.classList.remove("is-loading", "ptt-recording", "ptt-sent", "ptt-error");
    pttBtn.classList.add(cssClass);
    setPttLabel(label);
    pttResetTimer = setTimeout(resetPttBtn, delayMs);
  }

  function releaseStream() {
    if (scriptProc) { try { scriptProc.disconnect(); } catch (e) {} scriptProc = null; }
    if (audioSrc) { try { audioSrc.disconnect(); } catch (e) {} audioSrc = null; }
    if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
    if (audioStream) {
      audioStream.getTracks().forEach(function (t) { t.stop(); });
      audioStream = null;
    }
  }

  function updateAudioLevel() {
    if (!pttLevelMeter || sampleCount === 0) return;
    var sum = 0;
    var i;
    for (i = 0; i < sampleCount; i++) {
      sum += Math.abs(pttSamples[i]);
    }
    var average = sum / sampleCount;
    pttLevelMeter.value = Math.min(100, Math.round(average * 200));
  }

  function startRecording() {
    if (pttServerUnavailable || pttActive || pttStarting) return;
    clearResetTimer();
    cancelInFlightUpload();
    pttHoldRequested = true;
    pttStarting = true;
    pttBtn.classList.remove("ptt-sent", "ptt-error");
    setPttLabel("Requesting Mic...");

    if (pttMeterWrap) {
      pttMeterWrap.style.display = "inline-flex";
      pttMeterWrap.style.alignItems = "center";
    }

    navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      .then(function (stream) {
        if (!pttHoldRequested) {
          stream.getTracks().forEach(function (t) { t.stop(); });
          pttStarting = false;
          if (pttMeterWrap) pttMeterWrap.style.display = "none";
          return;
        }

        try {
          var ACtx = window.AudioContext || window.webkitAudioContext;
          audioCtx = new ACtx();
          audioStream = stream;
          sampleCount = 0;
          var resampleRatio = audioCtx.sampleRate / 8000;
          audioSrc = audioCtx.createMediaStreamSource(stream);
          scriptProc = audioCtx.createScriptProcessor(4096, 1, 1);
          scriptProc.onaudioprocess = function (e) {
            var input = e.inputBuffer.getChannelData(0);
            var i;
            for (i = 0; i < input.length && sampleCount < maxSamples; i += resampleRatio) {
              pttSamples[sampleCount++] = input[Math.floor(i)];
            }
          };
          var silentGain = audioCtx.createGain();
          silentGain.gain.value = 0;
          audioSrc.connect(scriptProc);
          scriptProc.connect(silentGain);
          silentGain.connect(audioCtx.destination);
          if (audioCtx.state === "suspended") audioCtx.resume();
        } catch (recErr) {
          console.log("PTT recorder error: " + recErr.message);
          pttActive = false;
          releaseStream();
          if (pttMeterWrap) pttMeterWrap.style.display = "none";
          flashAndReset("Recorder error", "ptt-error", 1800);
          return;
        }

        pttActive = true;
        pttStarting = false;
        pttStartTime = Date.now();
        pttBtn.classList.add("ptt-recording");
        pttBtn.classList.remove("is-loading", "ptt-sent", "ptt-error");
        pttBtn.disabled = false;
        setPttLabel("Recording...");

        clearMaxRecordTimer();
        pttMaxRecordTimer = setTimeout(function () {
          stopRecording(true);
        }, PTT_MAX_DURATION_MS);

        clearLevelUpdateTimer();
        pttLevelUpdateTimer = setInterval(updateAudioLevel, AUDIO_LEVEL_UPDATE_MS);
      })
      .catch(function (err) {
        pttStarting = false;
        pttHoldRequested = false;
        if (pttMeterWrap) pttMeterWrap.style.display = "none";

        var friendlyMessage = "Microphone error";
        var detailedTitle = "";

        switch (err.name) {
          case "NotAllowedError":
            friendlyMessage = "Permission denied";
            detailedTitle = "Allow microphone access in browser settings";
            break;
          case "NotFoundError":
            friendlyMessage = "No microphone";
            detailedTitle = "No microphone detected on this device";
            break;
          case "NotReadableError":
            friendlyMessage = "Mic in use";
            detailedTitle = "Microphone is already in use by another app";
            break;
          case "SecurityError":
            friendlyMessage = "HTTPS required";
            detailedTitle = "Microphone access requires HTTPS or localhost";
            break;
          case "OverconstrainedError":
            friendlyMessage = "Mic incompatible";
            detailedTitle = "Browser cannot use this microphone configuration";
            break;
          default:
            detailedTitle = err.name + ": " + err.message;
        }

        console.log("PTT mic error: " + err.name + " - " + err.message);
        flashAndReset(friendlyMessage, "ptt-error", 2200);
        pttBtn.title = detailedTitle;
      });
  }

  function stopRecording(fromMaxDuration) {
    pttHoldRequested = false;
    if (!pttActive || !scriptProc) {
      if (pttMeterWrap) pttMeterWrap.style.display = "none";
      return;
    }
    pttActive = false;
    clearMaxRecordTimer();
    clearLevelUpdateTimer();
    if (pttMeterWrap) {
      pttMeterWrap.style.display = "none";
      pttLevelMeter.value = 0;
    }

    var elapsed = Date.now() - pttStartTime;
    var samples = pttSamples.slice(0, sampleCount);
    sampleCount = 0;
    releaseStream();

    if (elapsed < PTT_MIN_DURATION_MS) {
      flashAndReset("Too short", "ptt-error", 1200);
      return;
    }

    if (samples.length === 0) {
      flashAndReset("No audio", "ptt-error", 1500);
      return;
    }

    var pcm = new Int16Array(samples.length);
    var i;
    for (i = 0; i < samples.length; i++) {
      pcm[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767)));
    }
    var blob = new Blob([pcm.buffer], { type: "application/octet-stream" });
    if (blob.size > PTT_MAX_BLOB_BYTES) {
      flashAndReset("Clip too large", "ptt-error", 1800);
      return;
    }

    setPttLabel(fromMaxDuration ? "Sending max clip..." : "Sending...");
    pttBtn.classList.remove("ptt-recording");
    pttBtn.classList.add("is-loading");
    pttBtn.disabled = true;

    cancelInFlightUpload();

    uploadXhr = new XMLHttpRequest();
    uploadXhr.open("POST", "cgi-bin/upload_audio.cgi", true);
    uploadXhr.setRequestHeader("Content-Type", "application/octet-stream");
    uploadXhr.timeout = PTT_UPLOAD_TIMEOUT_MS;

    uploadXhr.ontimeout = function () {
      uploadXhr = null;
      flashAndReset("Timeout", "ptt-error", 1800);
    };

    uploadXhr.onerror = function () {
      uploadXhr = null;
      flashAndReset("Error", "ptt-error", 1500);
    };

    uploadXhr.onabort = function () {
      uploadXhr = null;
    };

    uploadXhr.onload = function () {
      var status = uploadXhr ? uploadXhr.status : 0;
      var payload = uploadXhr ? (uploadXhr.responseText || "").trim() : "";
      uploadXhr = null;

      if (!VALID_RESPONSES[payload]) {
        console.error("Unexpected server response: " + payload);
        flashAndReset("Server error", "ptt-error", 1500);
        return;
      }

      if (status >= 200 && status < 300 && payload === "OK") {
        flashAndReset("Sent!", "ptt-sent", 1400);
        updatePttLastSent();
        return;
      }

      if (payload === "BUSY") {
        flashAndReset("Busy", "ptt-error", 1500);
      } else if (payload === "TOO_LARGE") {
        flashAndReset("Too large", "ptt-error", 1800);
      } else if (payload === "INVALID_PCM") {
        flashAndReset("Bad audio", "ptt-error", 1800);
      } else if (payload === "PTT_BIN_MISSING") {
        setPttUnavailable("PTT unavailable", "Camera audio output backend is missing.");
      } else {
        flashAndReset("Error", "ptt-error", 1500);
      }
    };

    uploadXhr.send(blob);
  }

  function testSpeaker() {
    if (pttBtn.disabled || pttBtn.classList.contains("is-loading")) return;
    pttTestBtn.disabled = true;
    pttTestBtn.classList.add("is-loading");

    var xhr = new XMLHttpRequest();
    xhr.open("GET", "cgi-bin/action.cgi?cmd=audio_test", true);
    xhr.onload = function () {
      pttTestBtn.classList.remove("is-loading");
      if (xhr.status >= 200 && xhr.status < 300) {
        pttTestBtn.classList.add("ptt-sent");
        setTimeout(function () {
          pttTestBtn.classList.remove("ptt-sent");
          pttTestBtn.disabled = false;
        }, 1500);
      } else {
        pttTestBtn.classList.add("ptt-error");
        setTimeout(function () {
          pttTestBtn.classList.remove("ptt-error");
          pttTestBtn.disabled = false;
        }, 1500);
      }
    };
    xhr.onerror = function () {
      console.log("Speaker test network error");
      pttTestBtn.classList.remove("is-loading");
      pttTestBtn.classList.add("ptt-error");
      setTimeout(function () {
        pttTestBtn.classList.remove("ptt-error");
        pttTestBtn.disabled = false;
      }, 1500);
    };
    xhr.send();
  }

  function startListening() {
    if (listenAudio) { stopListening(); }
    if (listenActive) { return; }

    listenActive = true;
    listenBtn.classList.add("is-loading");
    setListenLabel("Connecting...");
    listenBtn.disabled = true;

    var audioElement = document.createElement("audio");
    audioElement.autoplay = true;
    audioElement.controls = false;
    audioElement.style.display = "none";
    audioElement.src = "cgi-bin/audio_stream.cgi?type=mic";

    audioElement.onerror = function () {
      console.log("Audio stream error");
      stopListening();
    };

    audioElement.onplay = function () {
      listenAudio = audioElement;
      listenBtn.classList.remove("is-loading");
      listenBtn.classList.add("is-success");
      setListenLabel("Listening...");
      listenBtn.disabled = false;

      clearTimeout(listenStreamTimeout);
      listenStreamTimeout = setTimeout(function () {
        stopListening();
      }, LISTEN_STREAM_TIMEOUT_MS);
    };

    document.body.appendChild(audioElement);

    var playPromise = audioElement.play();
    if (playPromise !== undefined) {
      playPromise.catch(function (err) {
        console.log("Play error: " + err.message);
        stopListening();
      });
    }
  }

  function stopListening() {
    listenActive = false;
    if (listenAudio) {
      try { listenAudio.pause(); } catch (e) {}
      try { listenAudio.src = ""; } catch (e) {}
      try { document.body.removeChild(listenAudio); } catch (e) {}
      listenAudio = null;
    }
    clearTimeout(listenStreamTimeout);
    listenBtn.classList.remove("is-loading", "is-success");
    listenBtn.disabled = false;
    setListenLabel("Listen");
  }

  document.addEventListener("DOMContentLoaded", function () {
    pttBtn = byId("ptt_btn");
    listenBtn = byId("listen_btn");
    pttVol = byId("ptt_vol");
    pttTestBtn = byId("ptt_test_btn");
    pttLevelMeter = byId("ptt_level");
    pttMeterWrap = document.querySelector(".ptt-meter-wrap");

    if (!pttBtn || !listenBtn) return;

    pttLastSentEl = byId("ptt_last_sent");
    if (!pttLastSentEl && pttBtn.parentNode) {
      pttLastSentEl = document.createElement("span");
      pttLastSentEl.id = "ptt_last_sent";
      pttLastSentEl.style.cssText = "display:none;font-size:0.75rem;opacity:0.7;margin-left:0.5rem;";
      pttBtn.parentNode.insertBefore(pttLastSentEl, pttBtn.nextSibling);
    }

    // ── PTT (speaker) ────────────────────────────────────────────────────────
    pttBtn.disabled = true;
    setPttLabel("Checking PTT...");

    var pttStatusXhr = new XMLHttpRequest();
    pttStatusXhr.open("GET", "cgi-bin/action.cgi?cmd=get_ptt_status", true);
    pttStatusXhr.onload = function () {
      var status = (pttStatusXhr.responseText || "").trim();
      if (status && status !== "OK") {
        setPttUnavailable("PTT unavailable", "Camera audio output backend is missing.");
        return;
      }
      if (pttVol) { pttVol.disabled = false; pttVol.title = ""; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setPttLabel("PTT unsupported");
        pttBtn.disabled = true;
        return;
      }
      if (!window.isSecureContext) {
        setPttLabel("PTT needs HTTPS");
        pttBtn.disabled = true;
        pttBtn.title = "Microphone access requires HTTPS or localhost.";
        return;
      }
      resetPttBtn();
    };
    pttStatusXhr.onerror = function () {
      if (pttVol) { pttVol.disabled = false; pttVol.title = ""; }
      resetPttBtn();
    };
    pttStatusXhr.send();

    function isPrimaryActivation(evt) {
      if (!evt) return true;
      if (typeof evt.button === "number" && evt.button !== 0) return false;
      return true;
    }

    if (window.PointerEvent) {
      pttBtn.addEventListener("pointerdown", function (e) {
        if (!isPrimaryActivation(e)) return;
        if (e.pointerType === "touch") e.preventDefault();
        startRecording();
      });
      window.addEventListener("pointerup", handlePointerUp);
      pttBtn.addEventListener("pointercancel", function () { stopRecording(false); });
    } else {
      pttBtn.addEventListener("mousedown", function (e) {
        if (!isPrimaryActivation(e)) return;
        startRecording();
      });
      window.addEventListener("mouseup", handleMouseUp);
      pttBtn.addEventListener("mouseleave", function () { stopRecording(false); });
      pttBtn.addEventListener("touchstart", function (e) { e.preventDefault(); startRecording(); }, { passive: false });
      window.addEventListener("touchend", handleTouchEnd);
      window.addEventListener("touchcancel", function () { stopRecording(false); });
    }

    pttBtn.addEventListener("keydown", function (e) {
      if (e.code === "Space" || e.code === "Enter") { e.preventDefault(); startRecording(); }
    });
    pttBtn.addEventListener("keyup", function (e) {
      if (e.code === "Space" || e.code === "Enter") { e.preventDefault(); stopRecording(false); }
    });

    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    if (pttTestBtn) {
      pttTestBtn.addEventListener("click", testSpeaker);
    }

    // ── Listen (microphone → browser) ────────────────────────────────────────
    // Probe audio_stream.cgi: returns 503 on AK3918 (no ALSA capture binary).
    listenBtn.disabled = true;
    setListenLabel("Checking...");

    listenBtn.addEventListener("click", function () {
      if (listenActive) { stopListening(); } else { startListening(); }
    });

    var capXhr = new XMLHttpRequest();
    capXhr.open("HEAD", "cgi-bin/audio_stream.cgi", true);
    capXhr.onload = function () {
      if (capXhr.status === 503) {
        setListenLabel("Mic unavailable");
        listenBtn.title = "Live microphone streaming is not supported on this hardware. Only speaker (PTT) is available.";
        // leave disabled
      } else {
        setListenLabel("Listen");
        listenBtn.disabled = false;
      }
    };
    capXhr.onerror = function () {
      // Network error: assume available and let the stream fail gracefully
      setListenLabel("Listen");
      listenBtn.disabled = false;
    };
    capXhr.send();
  });

  window.pttModuleCleanup = function () {
    window.removeEventListener("pointerup", handlePointerUp);
    window.removeEventListener("mouseup", handleMouseUp);
    window.removeEventListener("touchend", handleTouchEnd);
    window.removeEventListener("blur", handleWindowBlur);
    document.removeEventListener("visibilitychange", handleVisibilityChange);
    releaseStream();
    stopListening();
    cancelInFlightUpload();
  };
})();
