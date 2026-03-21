/**
 * PTT (Push-to-Talk) and Two-Way Audio Module
 * Handles microphone recording, speaker playback, and camera audio streaming
 */

(function () {
  // Configuration
  const PTT_MIN_DURATION_MS = 400;
  const PTT_MAX_DURATION_MS = 9000;
  const PTT_UPLOAD_TIMEOUT_MS = 15000;
  const PTT_MAX_BLOB_BYTES = 524288;
  const AUDIO_LEVEL_UPDATE_MS = 50;
  const LISTEN_STREAM_TIMEOUT_MS = 30000;
  const maxSamples = Math.ceil((PTT_MAX_DURATION_MS / 1000) * 8000);
  const VALID_RESPONSES = new Set(["OK", "BUSY", "TOO_LARGE", "INVALID_PCM", "PTT_BIN_MISSING"]);

  // State
  let audioCtx = null;
  let audioSrc = null;
  let scriptProc = null;
  let audioStream = null;
  let pttSamples = new Float32Array(maxSamples);
  let sampleCount = 0;
  let pttActive = false;
  let pttStarting = false;
  let pttHoldRequested = false;
  let pttStartTime = 0;
  let pttResetTimer = null;
  let pttMaxRecordTimer = null;
  let pttLevelUpdateTimer = null;
  let uploadController = null;
  let uploadTimeoutTimer = null;
  let pttServerUnavailable = false;
  let listenActive = false;
  let listenAudio = null;
  let listenStreamTimeout = null;

  // DOM References
  let pttBtn = null;
  let listenBtn = null;
  let pttVol = null;
  let pttTestBtn = null;
  let pttLevelMeter = null;
  let pttMeterWrap = null;

  // Named handlers for cleanup
  function handlePointerUp() { stopRecording(false); }
  function handleMouseUp() { stopRecording(false); }
  function handleTouchEnd() { stopRecording(false); }
  function handleWindowBlur() { stopRecording(false); }
  function handleVisibilityChange() { if (document.hidden) stopRecording(false); }

  function byId(id) {
    return document.getElementById(id);
  }

  function setPttLabel(text) {
    const lbl = pttBtn.querySelector(".ptt-label");
    if (lbl) lbl.textContent = text;
  }

  function setListenLabel(text) {
    const lbl = listenBtn.querySelector(".listen-label");
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

  function clearUploadTimeout() {
    if (uploadTimeoutTimer) {
      clearTimeout(uploadTimeoutTimer);
      uploadTimeoutTimer = null;
    }
  }

  function cancelInFlightUpload() {
    if (uploadController) {
      try { uploadController.abort(); } catch (e) {}
      uploadController = null;
    }
    clearUploadTimeout();
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
    
    let sum = 0;
    for (let i = 0; i < sampleCount; i++) {
      sum += Math.abs(pttSamples[i]);
    }
    const average = sum / sampleCount;
    const levelPercent = Math.min(100, Math.round(average * 200));
    pttLevelMeter.value = levelPercent;
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
          const ACtx = window.AudioContext || window.webkitAudioContext;
          audioCtx = new ACtx();
          audioStream = stream;
          sampleCount = 0;
          const resampleRatio = audioCtx.sampleRate / 8000;
          audioSrc = audioCtx.createMediaStreamSource(stream);
          scriptProc = audioCtx.createScriptProcessor(4096, 1, 1);
          scriptProc.onaudioprocess = function (e) {
            const input = e.inputBuffer.getChannelData(0);
            for (let i = 0; i < input.length && sampleCount < maxSamples; i += resampleRatio) {
              pttSamples[sampleCount++] = input[Math.floor(i)];
            }
          };
          const silentGain = audioCtx.createGain();
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

        let friendlyMessage = "Microphone error";
        let detailedTitle = "";

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
            detailedTitle = `${err.name}: ${err.message}`;
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

    const elapsed = Date.now() - pttStartTime;
    const samples = Array.from(pttSamples.slice(0, sampleCount));
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

    const pcm = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      pcm[i] = Math.max(-32768, Math.min(32767, Math.round(samples[i] * 32767)));
    }
    const blob = new Blob([pcm.buffer], { type: "application/octet-stream" });
    if (blob.size > PTT_MAX_BLOB_BYTES) {
      flashAndReset("Clip too large", "ptt-error", 1800);
      return;
    }

    if (fromMaxDuration) {
      setPttLabel("Sending max clip...");
    } else {
      setPttLabel("Sending...");
    }
    pttBtn.classList.remove("ptt-recording");
    pttBtn.classList.add("is-loading");
    pttBtn.disabled = true;

    cancelInFlightUpload();
    if (window.AbortController) {
      uploadController = new AbortController();
      uploadTimeoutTimer = setTimeout(function () {
        if (uploadController) {
          uploadController.abort();
        }
      }, PTT_UPLOAD_TIMEOUT_MS);
    }

    const requestOptions = {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: blob
    };
    if (uploadController) {
      requestOptions.signal = uploadController.signal;
    }

    fetch("cgi-bin/upload_audio.cgi", requestOptions)
      .then(function (response) {
        // Validate content-type
        const contentType = response.headers.get("content-type");
        if (contentType && !contentType.includes("text/plain")) {
          console.warn("Unexpected content-type: " + contentType);
        }
        return response.text().then(function (payload) {
          return { ok: response.ok, status: response.status, payload: (payload || "").trim() };
        });
      })
      .then(function (result) {
        uploadController = null;
        clearUploadTimeout();
        
        // Check for valid response
        if (!VALID_RESPONSES.has(result.payload)) {
          console.error("Unexpected server response: " + result.payload);
          flashAndReset("Server error", "ptt-error", 1500);
          return;
        }

        // Original logic continues:
        if (result.ok && result.payload === "OK") {
          flashAndReset("Sent!", "ptt-sent", 1400);
          return;
        }
        
        if (result.payload === "BUSY") {
          flashAndReset("Busy", "ptt-error", 1500);
        } else if (result.payload === "TOO_LARGE") {
          flashAndReset("Too large", "ptt-error", 1800);
        } else if (result.payload === "INVALID_PCM") {
          flashAndReset("Bad audio", "ptt-error", 1800);
        } else if (result.payload === "PTT_BIN_MISSING") {
          setPttUnavailable("PTT unavailable", "Camera audio output backend is missing.");
        } else {
          flashAndReset("Error", "ptt-error", 1500);
        }
      })
      .catch(function (err) {
        uploadController = null;
        clearUploadTimeout();
        if (err && err.name === "AbortError") {
          flashAndReset("Timeout", "ptt-error", 1800);
        } else {
          flashAndReset("Error", "ptt-error", 1500);
        }
      });
  }

  function testSpeaker() {
    if (pttBtn.disabled || pttBtn.classList.contains("is-loading")) return;
    
    pttTestBtn.disabled = true;
    pttTestBtn.classList.add("is-loading");
    
    fetch("cgi-bin/action.cgi?cmd=audio_test", { cache: "no-store" })
      .then(function (response) {
        if (response.ok) {
          pttTestBtn.classList.remove("is-loading");
          pttTestBtn.classList.add("ptt-sent");
          setTimeout(function () {
            pttTestBtn.classList.remove("ptt-sent");
            pttTestBtn.disabled = false;
          }, 1500);
        } else {
          throw new Error("Test failed");
        }
      })
      .catch(function (err) {
        console.log("Speaker test error: " + err.message);
        pttTestBtn.classList.remove("is-loading");
        pttTestBtn.classList.add("ptt-error");
        setTimeout(function () {
          pttTestBtn.classList.remove("ptt-error");
          pttTestBtn.disabled = false;
        }, 1500);
      });
  }

  function startListening() {
    // Cleanup any existing listen session first
    if (listenAudio) {
      stopListening();
    }

    if (listenActive) {
      return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setListenLabel("Unsupported");
      listenBtn.disabled = true;
      return;
    }

    listenActive = true;
    listenBtn.classList.add("is-loading");
    setListenLabel("Connecting...");
    listenBtn.disabled = true;

    // Try to connect to audio stream from camera
    const audioElement = document.createElement("audio");
    audioElement.autoplay = true;
    audioElement.controls = false;
    audioElement.style.display = "none";

    const streamUrl = "cgi-bin/audio_stream.cgi?type=mic";
    audioElement.src = streamUrl;
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

    // Start playback with error handling
    const playPromise = audioElement.play();
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

  // Main initialization
  document.addEventListener("DOMContentLoaded", function () {
    pttBtn = byId("ptt_btn");
    listenBtn = byId("listen_btn");
    pttVol = byId("ptt_vol");
    pttTestBtn = byId("ptt_test_btn");
    pttLevelMeter = byId("ptt_level");
    pttMeterWrap = document.querySelector(".ptt-meter-wrap");

    if (!pttBtn || !listenBtn) return;

    // Initialize PTT
    pttBtn.disabled = true;
    setPttLabel("Checking PTT...");
    fetch("cgi-bin/action.cgi?cmd=get_ptt_status", { cache: "no-store" })
      .then(function (response) { return response.text(); })
      .then(function (payload) {
        const status = String(payload || "").trim();
        if (status && status !== "OK") {
          setPttUnavailable("PTT unavailable", "Camera audio output backend is missing.");
          return;
        }
        if (pttVol) {
          pttVol.disabled = false;
          pttVol.title = "";
        }
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
      })
      .catch(function () {
        if (pttVol) {
          pttVol.disabled = false;
          pttVol.title = "";
        }
        resetPttBtn();
      });

    // PTT Event Listeners
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
      if (e.code === "Space" || e.code === "Enter") {
        e.preventDefault();
        startRecording();
      }
    });
    pttBtn.addEventListener("keyup", function (e) {
      if (e.code === "Space" || e.code === "Enter") {
        e.preventDefault();
        stopRecording(false);
      }
    });

    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    // Test Speaker Button
    if (pttTestBtn) {
      pttTestBtn.addEventListener("click", testSpeaker);
    }

    // Listen Button
    listenBtn.addEventListener("click", function () {
      if (listenActive) {
        stopListening();
      } else {
        startListening();
      }
    });

    // Check device capability for audio capture
    fetch("cgi-bin/audio_stream.cgi", { method: "HEAD" })
      .then(function (response) {
        if (response.status === 503) {
          setListenLabel("Not supported");
          listenBtn.disabled = true;
          listenBtn.title = "Audio capture is not available on this device";
        }
      })
      .catch(function () { /* Device offline or no support */ });
  });

  // Module cleanup function
  window.pttModuleCleanup = function() {
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
