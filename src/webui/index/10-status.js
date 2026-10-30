  // --- Status line rendering: badges, readings under the live view, version, MQTT ---
  function setPerformanceProfileBadge(token) {
    var badge = byId("perfprofile");
    if (!badge) {
      return;
    }

    var normalized = (token || "").trim().toLowerCase();
    var label = "Balanced";
    if (normalized === "low-cpu") {
      label = "Low CPU";
    } else if (normalized === "rtsp-only") {
      label = "RTSP+ONVIF";
    } else {
      normalized = "balanced";
    }

    badge.textContent = "Profile: " + label;
    badge.classList.remove("profile-balanced", "profile-low-cpu", "profile-rtsp-only");
    badge.classList.add("profile-" + normalized);
    currentPerfProfileToken = normalized;
    tuneUiPollIntervals(normalized);
    if (uiUltraLiteMode) {
      applyUiUltraLiteMode(true);
    }
  }

  function setAdaptiveLivePreviewProfile(cpuPercent, ramPercent) {
    var nextInterval = LIVEVIEW_INTERVAL_VISIBLE_MS;
    var nextEndpoint = "cgi-bin/currentpic.cgi";
    var cpu = typeof cpuPercent === "number" && !isNaN(cpuPercent) ? cpuPercent : 0;
    var ram = typeof ramPercent === "number" && !isNaN(ramPercent) ? ramPercent : 0;
    var pressure = Math.max(cpu, ram);

    if (currentPerfProfileToken === "rtsp-only") {
      nextInterval = Math.max(nextInterval, 5500);
    } else if (currentPerfProfileToken === "low-cpu") {
      nextInterval = Math.max(nextInterval, 4000);
    }

    if (pressure > 80) {
      nextInterval = Math.max(nextInterval, currentPerfProfileToken === "rtsp-only" ? 10000 : 7000);
    } else if (pressure >= 50) {
      nextInterval = Math.max(nextInterval, currentPerfProfileToken === "rtsp-only" ? 7000 : 4500);
    }

    var changed = liveViewVisibleIntervalMs !== nextInterval || liveViewSnapshotEndpoint !== nextEndpoint;
    liveViewVisibleIntervalMs = nextInterval;
    liveViewSnapshotEndpoint = nextEndpoint;

    if (changed && liveFeedEnabled && !document.hidden && liveViewInViewport) {
      scheduleRefreshLiveImage(liveViewVisibleIntervalMs);
    }
  }

  function applyAdaptivePollingPressure(cpuPercent, ramPercent) {
    var cpu = typeof cpuPercent === "number" && !isNaN(cpuPercent) ? cpuPercent : 0;
    var ram = typeof ramPercent === "number" && !isNaN(ramPercent) ? ramPercent : 0;
    var pressure = Math.max(cpu, ram);

    dynamicSysUsageIntervalMs = 0;
    if (pressure > 80) {
      dynamicSysUsageIntervalMs = 20000;
    } else if (pressure >= 50) {
      dynamicSysUsageIntervalMs = 10000;
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function tuneUiPollIntervals(profileToken) {
    var normalized = (profileToken || "").toLowerCase();
    LIVEVIEW_INTERVAL_VISIBLE_MS = LIVEVIEW_INTERVAL_VISIBLE_DEFAULT_MS;
    LIVEVIEW_INTERVAL_HIDDEN_MS = LIVEVIEW_INTERVAL_HIDDEN_DEFAULT_MS;
    SYSUSAGE_INTERVAL_VISIBLE_MS = SYSUSAGE_INTERVAL_VISIBLE_DEFAULT_MS;
    SYSUSAGE_INTERVAL_HIDDEN_MS = SYSUSAGE_INTERVAL_HIDDEN_DEFAULT_MS;
    AUTONIGHT_INTERVAL_VISIBLE_MS = AUTONIGHT_INTERVAL_VISIBLE_DEFAULT_MS;
    AUTONIGHT_INTERVAL_HIDDEN_MS = AUTONIGHT_INTERVAL_HIDDEN_DEFAULT_MS;

    if (normalized === "rtsp-only") {
      LIVEVIEW_INTERVAL_VISIBLE_MS = 5500;
      LIVEVIEW_INTERVAL_HIDDEN_MS = 20000;
      SYSUSAGE_INTERVAL_VISIBLE_MS = 30000;
      SYSUSAGE_INTERVAL_HIDDEN_MS = 120000;
      AUTONIGHT_INTERVAL_VISIBLE_MS = 12000;
      AUTONIGHT_INTERVAL_HIDDEN_MS = 30000;
    } else if (normalized === "low-cpu") {
      LIVEVIEW_INTERVAL_VISIBLE_MS = 4000;
      LIVEVIEW_INTERVAL_HIDDEN_MS = 16000;
      SYSUSAGE_INTERVAL_VISIBLE_MS = 22000;
      SYSUSAGE_INTERVAL_HIDDEN_MS = 90000;
      AUTONIGHT_INTERVAL_HIDDEN_MS = 25000;
    }
  }

  function updateLumAwbLabels(lum, awb) {
    if (typeof lum === "string") {
      lastLumValue = lum;
    }
    if (typeof awb === "string") {
      lastAwbValue = awb;
    }
    byClass("labelLum").forEach(function (node) {
      node.textContent = "Current: " + (lastLumValue || "");
    });
    byClass("labelAWB").forEach(function (node) {
      node.textContent = "Current: " + (lastAwbValue || "");
    });
    updateNightModeBadge(lastLumValue, lastAwbValue);
  }

  function updateNightModeBadge(lum, awb) {
    var badge = byId("nightmodebadge");
    if (!badge) {
      return;
    }

    badge.classList.remove("nightmode-day", "nightmode-twilight", "nightmode-night", "nightmode-unknown");

    var lumStr = typeof lum === "string" ? lum.trim() : "";
    // lum may be a plain integer string e.g. "23" or "145", or empty
    var lumMatch = lumStr.match(/([0-9]+)/);
    if (!lumMatch) {
      badge.textContent = "\uD83C\uDF19 Night: n/a";
      badge.classList.add("nightmode-unknown");
      badge.title = "Luminance data unavailable (auto-night detection not running or /var/run/lum absent).";
      return;
    }

    var lumVal = parseInt(lumMatch[1], 10);
    if (lumVal < 40) {
      badge.textContent = "\uD83C\uDF19 Night";
      badge.classList.add("nightmode-night");
      badge.title = "Low luminance " + lumVal + " — camera is in night mode. AWB: " + (awb || "n/a");
    } else if (lumVal < 120) {
      badge.textContent = "\uD83C\uDF24 Twilight";
      badge.classList.add("nightmode-twilight");
      badge.title = "Mid luminance " + lumVal + " — twilight / transition zone. AWB: " + (awb || "n/a");
    } else {
      badge.textContent = "\u2600\uFE0F Day";
      badge.classList.add("nightmode-day");
      badge.title = "High luminance " + lumVal + " — camera is in day mode. AWB: " + (awb || "n/a");
    }
  }

  function applyUiUltraLiteMode(enabled) {
    var next = !!enabled;
    if (uiUltraLiteMode === next) {
      return;
    }
    uiUltraLiteMode = next;
    document.body.classList.toggle("ui-ultra-lite", uiUltraLiteMode);

    if (uiUltraLiteMode) {
      LIVEVIEW_INTERVAL_VISIBLE_MS = Math.max(LIVEVIEW_INTERVAL_VISIBLE_MS, 9000);
      LIVEVIEW_INTERVAL_HIDDEN_MS = Math.max(LIVEVIEW_INTERVAL_HIDDEN_MS, 25000);
      SYSUSAGE_INTERVAL_VISIBLE_MS = Math.max(SYSUSAGE_INTERVAL_VISIBLE_MS, 30000);
      SYSUSAGE_INTERVAL_HIDDEN_MS = Math.max(SYSUSAGE_INTERVAL_HIDDEN_MS, 120000);
      AUTONIGHT_INTERVAL_VISIBLE_MS = Math.max(AUTONIGHT_INTERVAL_VISIBLE_MS, 15000);
      AUTONIGHT_INTERVAL_HIDDEN_MS = Math.max(AUTONIGHT_INTERVAL_HIDDEN_MS, 35000);
      liveViewSnapshotEndpoint = "cgi-bin/currentpic.cgi";

      if (liveFeedEnabled) {
        liveFeedEnabled = false;
        setLiveToggleButtonState();
      }
      clearJob("refreshLiveImage");
      liveVideoSync();
    } else {
      tuneUiPollIntervals(currentPerfProfileToken);
      setLiveToggleButtonState();
      if (!document.hidden && liveFeedEnabled) {
        scheduleRefreshLiveImage(200);
      }
    }
  }

  function byClass(cls) {
    return Array.prototype.slice.call(document.getElementsByClassName(cls));
  }

  function parseCpuPercent(sysusageText) {
    var match = /CPU:\s*([0-9]{1,3})%/i.exec(sysusageText || "");
    if (!match) {
      return null;
    }
    var cpu = parseInt(match[1], 10);
    return isNaN(cpu) ? null : cpu;
  }

  function parseRamUsage(sysusageText) {
    var match = /RAM:\s*([0-9]+)\s*\/\s*([0-9]+)\s*kB/i.exec(sysusageText || "");
    if (!match) {
      return null;
    }
    var used = parseInt(match[1], 10);
    var total = parseInt(match[2], 10);
    if (isNaN(used) || isNaN(total) || total <= 0) {
      return null;
    }
    var percent = Math.round((used * 100) / total);
    if (percent < 0) {
      percent = 0;
    } else if (percent > 100) {
      percent = 100;
    }
    return { used: used, total: total, percent: percent };
  }

  function applyUsageClass(node, percent) {
    if (!node) {
      return;
    }
    node.classList.remove("usage-low", "usage-mid", "usage-high");
    if (percent > 80) {
      node.classList.add("usage-high");
    } else if (percent >= 50) {
      node.classList.add("usage-mid");
    } else {
      node.classList.add("usage-low");
    }
  }

  function updateSystemLoadState(sysusageText, cpuPercentHint, ramPercentHint) {
    var cpu = cpuPercentHint;
    if (typeof cpu !== "number" || isNaN(cpu)) cpu = parseCpuPercent(sysusageText);
    var ramPercent = ramPercentHint;
    if (typeof ramPercent !== "number" || isNaN(ramPercent)) {
      var ram = parseRamUsage(sysusageText);
      ramPercent = ram ? ram.percent : null;
    }

    if (typeof cpu === "number" && !isNaN(cpu)) {
      cpu = Math.max(0, Math.min(cpu, 100));
      setAdaptiveLivePreviewProfile(cpu, ramPercent);
    }
    if (typeof ramPercent === "number" && !isNaN(ramPercent)) {
      ramPercent = Math.max(0, Math.min(ramPercent, 100));
    }

    var cameraState = byId("camera_state");
    var cameraDot = byId("camera_state_dot");
    if (cameraState && cameraDot) {
      var pressure = Math.max(cpu || 0, ramPercent || 0);
      cameraState.textContent = pressure > 80 ? "High load" : "Online";
      cameraDot.className = "camera-state-dot " + (pressure > 80 ? "is-warning" : "is-online");
    }
    applyAdaptivePollingPressure(cpu, ramPercent);
    return cpu;
  }

  // Instruments under the live picture (css/ui.css), from the statusline poll.
  function renderReadings(st) {
    if (st.hostname) {
      var bh = byId("brand_host");
      if (bh && bh.textContent !== st.hostname) bh.textContent = st.hostname;
      var osd = byId("osd_name");
      if (osd && osd.textContent !== st.hostname) osd.textContent = st.hostname;
    }
    function put(id, text, high) {
      var el = byId(id);
      if (!el) return;
      var b = el.querySelector("b");
      if (b) b.textContent = text;
      el.classList.toggle("is-high", !!high);
    }
    if (typeof st.cpu === "number") put("rd_cpu", st.cpu + " %", st.cpu >= 85);
    if (typeof st.ram_percent === "number") put("rd_ram", st.ram_percent + " %", st.ram_percent >= 85);
    if (typeof st.wifi_qual === "number") put("rd_wifi", st.wifi_qual + " %", st.wifi_qual < 40);
    var sb = byId("storage_badge");
    if (sb) sb.hidden = st.storage !== "flash";
    // Settings kept in the flash (3.0): the last save failed (too big, write error).
    var cs = byId("cfgsave_badge");
    if (cs) {
      cs.hidden = !st.cfg_save || st.cfg_save === "ok";
      if (!cs.hidden) cs.title = "The settings could not be saved to the flash: " + (st.cfg_save_msg || st.cfg_save) + ". They are lost at the next restart.";
    }
    // SD card problems first (sdinfo-sd.sh): a card that garbles
    // writes keeps working for reads, so this is the only early warning.
    var sdBad = { failing: "failing: replace it", readonly: "read-only", errors: "errors" }[st.sd_health];
    if (sdBad) {
      put("rd_sd", sdBad, true);
    } else if (st.storage === "flash") {
      put("rd_sd", st.sd_health === "ok" ? "recordings" : "not used", false);
    } else if (typeof st.sd_total_kb === "number" && st.sd_total_kb > 0) {
      var sdp = (100 * st.sd_used_kb / st.sd_total_kb);
      var sdpStr = sdp > 0 && sdp < 0.1 ? "< 0.1%" : (sdp < 10 ? sdp.toFixed(1) + "%" : Math.round(sdp) + "%");
      put("rd_sd", (st.sd_used_kb / 1048576).toFixed(1) + " / " + Math.round(st.sd_total_kb / 1048576) + " GB (" + sdpStr + ")", st.sd_percent >= 90);
    } else {
      put("rd_sd", "none", false);
    }
    var fb = byId("webfb_badge");
    if (fb) fb.hidden = st.web_fallback !== "http";
    var mq = byId("rd_mqtt");
    if (mq) mq.style.display = st.mqtt_enabled === 1 ? "" : "none";
    if (st.mqtt_enabled === 1) {
      var age = st.mqtt_last_pub_ts > 0 ? Math.floor(Date.now() / 1000) - st.mqtt_last_pub_ts : -1;
      put("rd_mqtt", st.mqtt_last_pub_ok === 1 && age >= 0 && age < 900 ? "connected" : "no recent publish", st.mqtt_last_pub_ok !== 1);
    }
    var prof = byId("osd_profile");
    if (prof && typeof st.perfprofile === "string") prof.textContent = "Profile " + st.perfprofile;
    var light = byId("osd_light");
    if (light && st.lum) light.textContent = "Light " + st.lum;
    var fl = byId("live_frigate");
    if (fl) {
      var flUrl = typeof st.frigate_live === "string" && /^https?:\/\//.test(st.frigate_live) ? st.frigate_live : "";
      fl.hidden = !flUrl;
      if (flUrl && fl.getAttribute("href") !== flUrl) fl.setAttribute("href", flUrl);
    }
  }

  function updateSecurityBadge(defaultPasswordActive) {
    var securityBadge = byId("securitybadge");
    if (!securityBadge) {
      return;
    }

    var isActive = defaultPasswordActive === 1 || defaultPasswordActive === true;
    var isInactive = defaultPasswordActive === 0 || defaultPasswordActive === false;
    securityBadge.classList.remove("security-safe", "security-risk", "security-unknown");

    if (isActive) {
      securityBadge.textContent = "Security: default password";
      securityBadge.title = "Default password is active. Change credentials in Settings.";
      securityBadge.classList.add("security-risk");
      return;
    }

    if (isInactive) {
      securityBadge.textContent = "Security: custom password";
      securityBadge.title = "Default credential check passed.";
      securityBadge.classList.add("security-safe");
      return;
    }

    securityBadge.textContent = "Security: n/a";
    securityBadge.title = "Credential security state unavailable.";
    securityBadge.classList.add("security-unknown");
  }

  function updateFirmwareVersionUi(currentVersion, updateAvailable, updateLatestVersion) {
    var chip = byId("fw_version");
    var haveCurrent = typeof currentVersion === "string" && currentVersion.length > 0 && currentVersion !== "n/a";
    var isOutdated = updateAvailable === 1 || updateAvailable === true;

    if (chip) {
      chip.textContent = haveCurrent ? currentVersion : "version n/a";
      chip.title = haveCurrent ? "Firmware version " + currentVersion : "Firmware version unavailable";
      chip.classList.toggle("fw-outdated", isOutdated);
    }

    var badge = byId("update_notifier");
    if (badge) {
      if (isOutdated) {
        var latest = typeof updateLatestVersion === "string" && updateLatestVersion.length > 0 ? updateLatestVersion : "n/a";
        var current = haveCurrent ? currentVersion : "n/a";
        badge.classList.add("is-active");
        badge.title = "New Version Available: " + latest + " (Current: " + current + ")";
        badge.onclick = function (e) {
          e.preventDefault();
          var tr = window.tc100T || function (s) { return s; };
          alert(
            tr("A newer version of the firmware is available!") + "\n\n" + tr("Latest:") + " " + latest +
            "\n" + tr("Your version:") + " " + current +
            "\n\n" + tr("Please visit the GitHub repository to download the update.")
          );
        };
      } else {
        badge.classList.remove("is-active");
        badge.onclick = null;
      }
    }
  }

  function updateStaleBanner(isStale) {
    var bannerId = "stale-data-banner";
    var existing = byId(bannerId);
    if (!isStale) {
      if (existing) existing.parentNode.removeChild(existing);
      return;
    }
    if (existing) return; // already shown
    var ageSec = sysUsageLastSuccessTs > 0 ? Math.round((Date.now() - sysUsageLastSuccessTs) / 1000) : 0;
    var ageStr = ageSec > 60 ? Math.round(ageSec / 60) + " min" : ageSec + "s";
    var banner = document.createElement("div");
    banner.id = bannerId;
    banner.setAttribute("role", "alert");
    banner.style.cssText = "position:fixed;top:0;left:0;width:100%;background:#b00020;color:#fff;text-align:center;padding:4px 8px;font-size:0.82rem;z-index:9999;";
    banner.textContent = "Device unreachable — last update " + (sysUsageLastSuccessTs > 0 ? ageStr + " ago" : "unknown") + ". Retrying...";
    var cameraState = byId("camera_state");
    var cameraDot = byId("camera_state_dot");
    if (cameraState) cameraState.textContent = "Camera unreachable";
    if (cameraDot) cameraDot.className = "camera-state-dot is-offline";
    document.body.insertBefore(banner, document.body.firstChild);
  }

  function updateMqttBadge(mqttEnabled, lastPubTs, lastPubOk) {
    var badge = byId("mqttbadge");
    if (!badge) return;
    var wrap = badge.parentElement;
    badge.classList.remove("mqtt-ok", "mqtt-fail", "mqtt-waiting", "mqtt-unknown");
    if (mqttEnabled !== 1) {
      if (wrap) wrap.style.display = "none";
      return;
    }
    if (wrap) wrap.style.display = "";
    if (!lastPubTs || lastPubTs <= 0) {
      badge.textContent = "MQTT: waiting";
      badge.title = "MQTT enabled — no publish recorded yet since boot.";
      badge.classList.add("mqtt-waiting");
      return;
    }
    var nowTs = Math.floor(Date.now() / 1000);
    var age = nowTs - lastPubTs;
    var ageStr = age < 60 ? age + "s ago" : Math.floor(age / 60) + "m ago";
    if (lastPubOk === 1) {
      badge.textContent = "MQTT: ok";
      badge.title = "Last publish OK, " + ageStr + ".";
      badge.classList.add("mqtt-ok");
    } else if (lastPubOk === 0) {
      badge.textContent = "MQTT: fail";
      badge.title = "Last publish FAILED, " + ageStr + ". Check broker connectivity.";
      badge.classList.add("mqtt-fail");
    } else {
      badge.textContent = "MQTT";
      badge.title = "MQTT publish status unavailable.";
      badge.classList.add("mqtt-unknown");
    }
  }

