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

