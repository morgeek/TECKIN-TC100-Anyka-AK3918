  // --- Live view: snapshot refresh, paused when hidden or off screen ---
  function setLiveToggleButtonState() {
    var toggle = byId("live_toggle");
    if (!toggle) {
      return;
    }
    if (uiUltraLiteMode && !liveFeedEnabled) {
      toggle.textContent = "Resume Live (manual)";
      return;
    }
    toggle.textContent = liveFeedEnabled ? "Pause Live" : "Resume Live";
  }

  function canRefreshLiveImageNow() {
    if (!liveFeedEnabled) {
      return false;
    }
    if (document.hidden) {
      return false;
    }
    if (!liveViewInViewport) {
      return false;
    }
    if (liveVideoWanted()) {
      return false; // the video plays (or is about to): no snapshots meanwhile
    }
    return true;
  }

  function setLiveViewInViewport(inViewport) {
    var next = !!inViewport;
    if (next === liveViewInViewport) {
      return;
    }

    liveViewInViewport = next;
    if (!liveFeedEnabled) {
      return;
    }
    liveVideoSync();

    if (canRefreshLiveImageNow()) {
      scheduleRefreshLiveImage(150);
      return;
    }

    clearJob("refreshLiveImage");
  }

  function initLiveViewVisibilityObserver() {
    var liveview = byId("liveview");
    if (!liveview) {
      return;
    }

    var observeTarget = liveview.closest(".liveview-wrap") || liveview;
    if (!window.IntersectionObserver) {
      liveViewInViewport = true;
      return;
    }

    liveViewVisibilityObserver = new window.IntersectionObserver(function (entries) {
      var entry = entries && entries.length ? entries[0] : null;
      if (!entry) {
        return;
      }
      setLiveViewInViewport(entry.isIntersecting && entry.intersectionRatio > 0);
    }, { threshold: 0.05 });

    liveViewVisibilityObserver.observe(observeTarget);
  }

  function refreshLiveImage() {
    var liveview = byId("liveview");
    if (!liveview) {
      clearJob("refreshLiveImage");
      return;
    }
    if (!canRefreshLiveImageNow()) {
      clearJob("refreshLiveImage");
      return;
    }
    // We only change the src here. The onload/onerror handlers
    // will schedule the NEXT refresh once this one finishes.
    liveview.src = liveViewSnapshotEndpoint + "?" + Date.now();
  }

  function scheduleRefreshLiveImage(interval) {
    if (!canRefreshLiveImageNow()) {
      clearJob("refreshLiveImage");
      return;
    }
    clearJob("refreshLiveImage");
    timeoutJobs.refreshLiveImage = setTimeout(refreshLiveImage, interval);
  }

  // --- Live video: the camera's H.264 stream as fragmented MP4 (cgi-bin/live.cgi) through Media Source Extensions ---
  // Order of preference for the picture on this page: this video (Video mode, when the browser plays the camera's
  // H.264 profile), else snapshots. The "Smooth live" button (Frigate) stays what it is, a link that opens Frigate in
  // another tab: it cannot be shown in this page, so it is offered next to the picture, not tried first.
  // Latency: the camera sends one fragment per frame and the page jumps to the newest frame whenever it is more than
  // 1 s behind; older data is removed from the buffer (10 s kept). The video stops when the page is hidden or off screen
  // (the camera then stops encoding the sub-stream), and any failure falls back to snapshots.
  var LIVE_MODE_KEY = "tc100.liveMode";
  var LIVE_LAG_JUMP_S = 1.0;
  var LIVE_KEEP_S = 10;
  var liveVideoFailedUntil = 0;
  var liveVideoRetries = 0;
  var liveVideo = { on: false, gen: 0, playing: false, startedAt: 0, lastData: 0, playedAt: 0, ctl: null, reader: null, ms: null,
                    sb: null, url: "", queue: [], queued: 0, timer: 0, bound: false };
  var liveMode = readLiveMode();

  function liveStoreGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }

  function liveStoreSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private mode: the choice is not kept */ }
  }

  function readLiveMode() {
    return liveStoreGet(LIVE_MODE_KEY) === "snap" ? "snap" : "video";
  }

  function liveVideoSupported() {
    try {
      return !!(window.MediaSource && typeof window.MediaSource.isTypeSupported === "function" && window.fetch &&
        window.AbortController && window.ReadableStream && window.Uint8Array && window.URL && window.URL.createObjectURL);
    } catch (e) {
      return false;
    }
  }

  // The video is the picture of the live view while it is selected, possible here and not failed lately.
  function liveVideoWanted() {
    return liveMode === "video" && liveVideoSupported() && Date.now() >= liveVideoFailedUntil;
  }

  function liveModeRender() {
    var videoBtn = byId("live_mode_video");
    var snapBtn = byId("live_mode_snap");
    var group = byId("live_mode");
    if (group) {
      group.style.display = liveVideoSupported() ? "" : "none"; // no Media Source Extensions: snapshots only, nothing to choose
    }
    if (videoBtn) {
      videoBtn.classList.toggle("is-on", liveMode === "video");
      videoBtn.setAttribute("aria-pressed", liveMode === "video" ? "true" : "false");
    }
    if (snapBtn) {
      snapBtn.classList.toggle("is-on", liveMode === "snap");
      snapBtn.setAttribute("aria-pressed", liveMode === "snap" ? "true" : "false");
    }
  }

  function liveShowVideo(show) {
    var video = byId("liveview_video");
    var img = byId("liveview");
    if (video) {
      video.style.display = show ? "block" : "none";
    }
    if (img) {
      img.style.display = show ? "none" : "";
    }
  }

  function liveVideoStop() {
    var video = byId("liveview_video");
    liveVideo.gen += 1;
    liveVideo.on = false;
    liveVideo.playing = false;
    if (liveVideo.timer) {
      clearInterval(liveVideo.timer);
      liveVideo.timer = 0;
    }
    try { if (liveVideo.reader) { liveVideo.reader.cancel(); } } catch (e) { /* already closed */ }
    try { if (liveVideo.ctl) { liveVideo.ctl.abort(); } } catch (e2) { /* nothing to abort */ }
    liveVideo.reader = null;
    liveVideo.ctl = null;
    liveVideo.sb = null;
    liveVideo.ms = null;
    liveVideo.queue = [];
    liveVideo.queued = 0;
    if (video) {
      try { video.pause(); } catch (e3) { /* ignore */ }
      video.removeAttribute("src");
      try { video.load(); } catch (e4) { /* ignore */ }
    }
    if (liveVideo.url) {
      try { URL.revokeObjectURL(liveVideo.url); } catch (e5) { /* ignore */ }
      liveVideo.url = "";
    }
    liveShowVideo(false);
  }

  // A failure of this connection: retry a few times (the camera may be busy or starting), then snapshots for a while.
  // holdMs > 0: no retry, snapshots for that long (unsupported profile, no H.264 stream).
  function liveVideoFail(gen, why, holdMs) {
    if (gen !== liveVideo.gen) {
      return;
    }
    liveVideoStop();
    clearJob("liveVideoRetry");
    if (holdMs > 0) {
      liveVideoFailedUntil = Date.now() + holdMs;
    } else {
      liveVideoRetries += 1;
      if (liveVideoRetries > 3) {
        liveVideoRetries = 0;
        liveVideoFailedUntil = Date.now() + 120000;
      } else {
        timeoutJobs.liveVideoRetry = setTimeout(liveVideoSync, 700 * liveVideoRetries);
        return;
      }
    }
    if (window.console && console.info) {
      console.info("Live video off (" + why + "): snapshots");
    }
    liveVideoSync();
    // the video is tried again once the hold is over
    timeoutJobs.liveVideoRetry = setTimeout(liveVideoSync, Math.max(1000, liveVideoFailedUntil - Date.now() + 200));
  }

  function liveVideoEnded(gen) {
    if (gen !== liveVideo.gen) {
      return;
    }
    var played = liveVideo.playing ? Date.now() - liveVideo.playedAt : 0;
    if (played >= 5000) { // the camera ends a stream after 10 minutes: connect again at once
      liveVideoRetries = 0;
      liveVideoStop();
      clearJob("liveVideoRetry");
      timeoutJobs.liveVideoRetry = setTimeout(liveVideoSync, 150);
      return;
    }
    liveVideoFail(gen, "stream ended", 0);
  }

  function liveVideoPump(gen) {
    var sb = liveVideo.sb;
    var video = byId("liveview_video");
    if (gen !== liveVideo.gen || !sb || !video || sb.updating || !liveVideo.queue.length) {
      return;
    }
    if (!liveVideo.ms || liveVideo.ms.readyState !== "open") {
      return;
    }
    var buffered = sb.buffered;
    try {
      if (buffered.length && video.currentTime - buffered.start(0) > LIVE_KEEP_S + 2) {
        sb.remove(buffered.start(0), video.currentTime - LIVE_KEEP_S); // 'updateend' pumps again
        return;
      }
    } catch (e) { /* removal refused: keep appending */ }
    var chunk;
    if (liveVideo.queue.length === 1) {
      chunk = liveVideo.queue[0];
    } else {
      chunk = new Uint8Array(liveVideo.queued);
      var at = 0;
      for (var i = 0; i < liveVideo.queue.length; i++) {
        chunk.set(liveVideo.queue[i], at);
        at += liveVideo.queue[i].length;
      }
    }
    var saved = liveVideo.queue;
    var savedBytes = liveVideo.queued;
    liveVideo.queue = [];
    liveVideo.queued = 0;
    try {
      sb.appendBuffer(chunk);
    } catch (err) {
      if (err && err.name === "QuotaExceededError" && buffered.length && buffered.start(0) < video.currentTime - 1) {
        liveVideo.queue = saved; // buffer full: drop what was played, try again
        liveVideo.queued = savedBytes;
        try { sb.remove(buffered.start(0), video.currentTime - 1); } catch (e2) { liveVideoFail(gen, "append failed", 0); }
        return;
      }
      liveVideoFail(gen, "append failed", 0);
    }
  }

  // Twice a second: keep the picture close to the newest frame, start playback, watch for silence.
  function liveVideoTick(gen) {
    var video = byId("liveview_video");
    if (gen !== liveVideo.gen || !video) {
      return;
    }
    var now = Date.now();
    var b = video.buffered;
    if (b.length) {
      var last = b.length - 1;
      var end = b.end(last);
      var cur = video.currentTime;
      var inRange = false;
      for (var i = 0; i < b.length; i++) {
        if (cur >= b.start(i) - 0.05 && cur <= b.end(i) + 0.05) {
          inRange = true;
        }
      }
      var lag = end - cur;
      if (!inRange || lag > LIVE_LAG_JUMP_S) {
        try { video.currentTime = Math.max(b.start(last), end - 0.2); } catch (e) { /* not seekable yet */ }
      } else {
        try { video.playbackRate = lag > 0.5 ? 1.1 : 1; } catch (e2) { /* ignore */ }
      }
      if (video.paused) {
        var pr = video.play();
        if (pr && pr.catch) { pr.catch(function () { /* autoplay refused: a muted video normally plays */ }); }
      }
    }
    if (liveVideo.playing && now - liveVideo.playedAt > 3000) {
      liveVideoRetries = 0;
    }
    if (now - liveVideo.lastData > 5000) {
      liveVideoFail(gen, "no data", 0);
    } else if (!liveVideo.playing && now - liveVideo.startedAt > 12000) {
      liveVideoFail(gen, "no picture", 0);
    }
  }

  function liveVideoRead(gen) {
    var ctl = liveVideo.ctl;
    fetch("cgi-bin/live.cgi", { cache: "no-store", credentials: "same-origin", signal: ctl.signal })
      .then(function (resp) {
        if (gen !== liveVideo.gen) {
          return null;
        }
        if (!resp.ok || !resp.body || !resp.body.getReader) {
          throw new Error("HTTP " + resp.status);
        }
        var reader = resp.body.getReader();
        liveVideo.reader = reader;
        var step = function () {
          return reader.read().then(function (res) {
            if (gen !== liveVideo.gen) {
              return null;
            }
            if (res.done) {
              liveVideoEnded(gen);
              return null;
            }
            liveVideo.lastData = Date.now();
            liveVideo.queue.push(res.value);
            liveVideo.queued += res.value.length;
            if (liveVideo.queued > 4 * 1024 * 1024) {
              liveVideoFail(gen, "too slow", 0);
              return null;
            }
            liveVideoPump(gen);
            return step();
          });
        };
        return step();
      })
      .catch(function (err) {
        if (gen === liveVideo.gen) {
          liveVideoFail(gen, err && err.message ? err.message : "network", 0);
        }
      });
  }

  function liveVideoOpen(gen, type) {
    var video = byId("liveview_video");
    var ms;
    try {
      ms = new window.MediaSource();
    } catch (e) {
      liveVideoFail(gen, "MediaSource", 600000);
      return;
    }
    liveVideo.ms = ms;
    ms.addEventListener("sourceopen", function () {
      if (gen !== liveVideo.gen || liveVideo.sb) {
        return;
      }
      var sb;
      try {
        sb = ms.addSourceBuffer(type);
      } catch (err) {
        liveVideoFail(gen, "SourceBuffer", 600000);
        return;
      }
      liveVideo.sb = sb;
      sb.addEventListener("updateend", function () { liveVideoPump(gen); });
      sb.addEventListener("error", function () { liveVideoFail(gen, "buffer error", 0); });
      liveVideoRead(gen);
    });
    liveVideo.url = URL.createObjectURL(ms);
    video.src = liveVideo.url;
    liveVideo.startedAt = Date.now();
    liveVideo.lastData = Date.now();
    liveVideo.timer = setInterval(function () { liveVideoTick(gen); }, 500);
    var pr = video.play();
    if (pr && pr.catch) { pr.catch(function () { /* started by the tick once data is there */ }); }
  }

  function liveVideoBind(video) {
    if (liveVideo.bound) {
      return;
    }
    liveVideo.bound = true;
    video.addEventListener("playing", function () {
      if (!liveVideo.on || liveVideo.playing) {
        return;
      }
      liveVideo.playing = true;
      liveVideo.playedAt = Date.now();
      liveShowVideo(true);
    });
    video.addEventListener("error", function () {
      if (liveVideo.on) {
        liveVideoFail(liveVideo.gen, "video error", 0);
      }
    });
  }

  function liveVideoStart() {
    var video = byId("liveview_video");
    if (!video || !liveVideoSupported()) {
      liveVideoFailedUntil = Date.now() + 3600000;
      return;
    }
    liveVideoBind(video);
    liveVideo.gen += 1;
    var gen = liveVideo.gen;
    liveVideo.on = true;
    liveVideo.playing = false;
    liveVideo.queue = [];
    liveVideo.queued = 0;
    liveVideo.startedAt = Date.now();
    var ctl = new window.AbortController();
    liveVideo.ctl = ctl;
    // What does the camera send, and does this browser play it? (a small JSON; 415: no H.264 stream, 503: starting)
    fetch("cgi-bin/live.cgi?info=1", { cache: "no-store", credentials: "same-origin", signal: ctl.signal })
      .then(function (resp) {
        if (resp.status === 415) {
          throw new Error("415");
        }
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (info) {
        if (gen !== liveVideo.gen) {
          return;
        }
        if (!info || !info.ok || typeof info.codec !== "string" ||
            !window.MediaSource.isTypeSupported('video/mp4; codecs="' + info.codec + '"')) {
          liveVideoFail(gen, "profile not supported by this browser", 600000);
          return;
        }
        liveVideoOpen(gen, 'video/mp4; codecs="' + info.codec + '"');
      })
      .catch(function (err) {
        if (gen !== liveVideo.gen) {
          return;
        }
        liveVideoFail(gen, err && err.message ? err.message : "network", err && err.message === "415" ? 600000 : 0);
      });
  }

  // Start or stop the video (or give the picture back to the snapshots) after the page state changed.
  function liveVideoSync() {
    var should = liveFeedEnabled && !document.hidden && liveViewInViewport && liveVideoWanted();
    if (should) {
      if (!liveVideo.on) {
        liveVideoStart();
      }
    } else {
      var wasOn = liveVideo.on;
      if (wasOn) {
        liveVideoStop();
      }
      if (canRefreshLiveImageNow()) {
        scheduleRefreshLiveImage(wasOn ? 50 : 100);
      } else {
        clearJob("refreshLiveImage");
        if (wasOn && !document.hidden) {
          var img = byId("liveview");
          if (img) {
            img.src = liveViewSnapshotEndpoint + "?" + Date.now(); // paused: show the latest picture once
          }
        }
      }
    }
    liveModeRender();
  }

  function setLiveMode(mode) {
    liveMode = mode === "snap" ? "snap" : "video";
    liveStoreSet(LIVE_MODE_KEY, liveMode);
    liveVideoFailedUntil = 0; // an explicit choice tries the video again
    liveVideoRetries = 0;
    clearJob("liveVideoRetry");
    liveVideoSync();
  }

  function initLiveModeSwitch() {
    var videoBtn = byId("live_mode_video");
    var snapBtn = byId("live_mode_snap");
    if (videoBtn) {
      videoBtn.addEventListener("click", function () { setLiveMode("video"); });
    }
    if (snapBtn) {
      snapBtn.addEventListener("click", function () { setLiveMode("snap"); });
    }
    liveModeRender();
  }
