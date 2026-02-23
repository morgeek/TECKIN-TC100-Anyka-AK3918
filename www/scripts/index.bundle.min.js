(function () {
  var timeoutJobs = {};
  var contentLoadController = null;
  var liveFeedEnabled = true;
  var currentContentTarget = "";

  var LIVEVIEW_INTERVAL_VISIBLE_DEFAULT_MS = 2500;
  var LIVEVIEW_INTERVAL_HIDDEN_DEFAULT_MS = 12000;
  var SYSUSAGE_INTERVAL_VISIBLE_DEFAULT_MS = 15000;
  var SYSUSAGE_INTERVAL_HIDDEN_DEFAULT_MS = 60000;
  var AUTONIGHT_INTERVAL_VISIBLE_DEFAULT_MS = 8000;
  var AUTONIGHT_INTERVAL_HIDDEN_DEFAULT_MS = 20000;

  var LIVEVIEW_INTERVAL_VISIBLE_MS = LIVEVIEW_INTERVAL_VISIBLE_DEFAULT_MS;
  var LIVEVIEW_INTERVAL_HIDDEN_MS = LIVEVIEW_INTERVAL_HIDDEN_DEFAULT_MS;
  var SYSUSAGE_INTERVAL_VISIBLE_MS = SYSUSAGE_INTERVAL_VISIBLE_DEFAULT_MS;
  var SYSUSAGE_INTERVAL_HIDDEN_MS = SYSUSAGE_INTERVAL_HIDDEN_DEFAULT_MS;
  var AUTONIGHT_INTERVAL_VISIBLE_MS = AUTONIGHT_INTERVAL_VISIBLE_DEFAULT_MS;
  var AUTONIGHT_INTERVAL_HIDDEN_MS = AUTONIGHT_INTERVAL_HIDDEN_DEFAULT_MS;

  var liveViewVisibleIntervalMs = LIVEVIEW_INTERVAL_VISIBLE_MS;
  var liveViewSnapshotEndpoint = "cgi-bin/currentpic.cgi";
  var currentPerfProfileToken = "balanced";
  var dynamicSysUsageIntervalMs = 0;
  var dynamicAutoNightIntervalMs = 0;
  var uiUltraLiteMode = false;
  var lastLumValue = "";
  var lastAwbValue = "";
  var settingsStylesInjected = false;
  var settingsStyleHrefs = [
    "css/bulma-divider.min.css",
    "css/bulma-switch.1.0.1.min.css",
    "css/bulma-badge.1.0.1.min.css",
    "css/bulma-quickview.1.0.1.min.css",
  ];

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

    if (changed && liveFeedEnabled && !document.hidden) {
      scheduleRefreshLiveImage(liveViewVisibleIntervalMs);
    }
  }

  function applyAdaptivePollingPressure(cpuPercent, ramPercent) {
    var cpu = typeof cpuPercent === "number" && !isNaN(cpuPercent) ? cpuPercent : 0;
    var ram = typeof ramPercent === "number" && !isNaN(ramPercent) ? ramPercent : 0;
    var pressure = Math.max(cpu, ram);

    dynamicSysUsageIntervalMs = 0;
    dynamicAutoNightIntervalMs = 0;
    if (pressure > 80) {
      dynamicSysUsageIntervalMs = 12000;
      dynamicAutoNightIntervalMs = 8000;
    } else if (pressure >= 50) {
      dynamicSysUsageIntervalMs = 6000;
      dynamicAutoNightIntervalMs = 4000;
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

  function hasStylesheet(href) {
    return Array.prototype.some.call(document.querySelectorAll("link[rel='stylesheet']"), function (node) {
      var nodeHref = node.getAttribute("href") || "";
      return nodeHref === href || nodeHref.indexOf(href) !== -1;
    });
  }

  function injectStylesheet(href) {
    if (!href || hasStylesheet(href)) {
      return;
    }
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.setAttribute("data-lazy-css", "1");
    document.head.appendChild(link);
  }

  function ensureSettingsStylesLoaded() {
    if (settingsStylesInjected) {
      return;
    }
    settingsStylesInjected = true;
    settingsStyleHrefs.forEach(function (href) {
      injectStylesheet(href);
    });
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

  function updateSysUsageBadges(sysusageText, cpuPercentHint, ramPercentHint) {
    var cpuBadge = byId("cpuusage");
    var ramBadge = byId("ramusage");
    if (!cpuBadge || !ramBadge) {
      return null;
    }

    var cpu = cpuPercentHint;
    if (typeof cpu !== "number" || isNaN(cpu)) {
      cpu = parseCpuPercent(sysusageText);
    }
    var ramPercent = ramPercentHint;
    if (typeof ramPercent !== "number" || isNaN(ramPercent)) {
      var ram = parseRamUsage(sysusageText);
      ramPercent = ram ? ram.percent : null;
    }

    if (typeof cpu === "number" && !isNaN(cpu)) {
      if (cpu < 0) {
        cpu = 0;
      } else if (cpu > 100) {
        cpu = 100;
      }
      cpuBadge.textContent = "CPU: " + cpu + "%";
      applyUsageClass(cpuBadge, cpu);
      setAdaptiveLivePreviewProfile(cpu, ramPercent);
    } else {
      cpuBadge.textContent = "CPU: ...";
      cpuBadge.classList.remove("usage-low", "usage-mid", "usage-high");
      cpuBadge.classList.add("usage-low");
    }

    if (typeof ramPercent === "number" && !isNaN(ramPercent)) {
      if (ramPercent < 0) {
        ramPercent = 0;
      } else if (ramPercent > 100) {
        ramPercent = 100;
      }
      ramBadge.textContent = "RAM: " + ramPercent + "%";
      applyUsageClass(ramBadge, ramPercent);
    } else {
      ramBadge.textContent = "RAM: ...";
      ramBadge.classList.remove("usage-low", "usage-mid", "usage-high");
      ramBadge.classList.add("usage-low");
    }

    applyAdaptivePollingPressure(cpu, ramPercent);
    return cpu;
  }

  function updateChipTempBadge(chipTempC, chipTempText) {
    var tempBadge = byId("chiptemp");
    if (!tempBadge) {
      return;
    }

    var tempValue = null;
    if (typeof chipTempC === "number" && !isNaN(chipTempC)) {
      tempValue = Math.round(chipTempC);
    } else if (typeof chipTempText === "string") {
      var match = /^([0-9]{1,3})\s*C$/i.exec(chipTempText.trim());
      if (match) {
        tempValue = parseInt(match[1], 10);
      }
    }

    if (typeof tempValue === "number" && !isNaN(tempValue) && tempValue >= 0 && tempValue <= 150) {
      tempBadge.textContent = "TEMP: " + tempValue + "C";
      tempBadge.classList.remove("temp-unknown");
      tempBadge.classList.remove("usage-low", "usage-mid", "usage-high");
      if (tempValue > 80) {
        tempBadge.classList.add("usage-high");
      } else if (tempValue >= 65) {
        tempBadge.classList.add("usage-mid");
      } else {
        tempBadge.classList.add("usage-low");
      }
      return;
    }

    tempBadge.textContent = "TEMP: n/a";
    tempBadge.classList.remove("temp-unknown");
    tempBadge.classList.remove("usage-low", "usage-mid", "usage-high");
    tempBadge.classList.add("temp-unknown");
  }

  function formatTenths(valueTenths) {
    var whole = Math.floor(valueTenths / 10);
    var frac = Math.abs(valueTenths % 10);
    return whole + "." + frac;
  }

  function updatePowerBadge(powerEstimatedMw, powerVoltageMv, powerEstimateEnabled, powerEstimatedCurrentMa, powerSensorPath) {
    var powerBadge = byId("powerdraw");
    if (!powerBadge) {
      return;
    }

    powerBadge.classList.remove("usage-low", "usage-mid", "usage-high", "temp-unknown");

    var hasEstimated = typeof powerEstimatedMw === "number" && !isNaN(powerEstimatedMw) && powerEstimatedMw >= 0;
    var hasVoltage = typeof powerVoltageMv === "number" && !isNaN(powerVoltageMv) && powerVoltageMv > 0;
    var hasCurrent = typeof powerEstimatedCurrentMa === "number" && !isNaN(powerEstimatedCurrentMa) && powerEstimatedCurrentMa >= 0;
    var source = typeof powerSensorPath === "string" && powerSensorPath ? powerSensorPath : "n/a";

    if (hasEstimated) {
      var tenthsW = Math.round(powerEstimatedMw / 100);
      var suffix = powerEstimateEnabled ? "*" : "";
      powerBadge.textContent = "PWR: " + formatTenths(tenthsW) + "W" + suffix;

      if (powerEstimatedMw > 2800) {
        powerBadge.classList.add("usage-high");
      } else if (powerEstimatedMw >= 1800) {
        powerBadge.classList.add("usage-mid");
      } else {
        powerBadge.classList.add("usage-low");
      }

      var tooltip = "Estimated power draw. * means estimated model is enabled.";
      if (hasVoltage) {
        tooltip += " Voltage: " + (powerVoltageMv / 1000).toFixed(2) + "V.";
      }
      if (hasCurrent) {
        tooltip += " Estimated current: " + Math.round(powerEstimatedCurrentMa) + "mA.";
      }
      tooltip += " Source: " + source + ".";
      powerBadge.title = tooltip;
      return;
    }

    if (hasVoltage) {
      var vin = (powerVoltageMv / 1000).toFixed(2);
      powerBadge.textContent = "VIN: " + vin + "V";
      powerBadge.classList.add("usage-low");
      powerBadge.title = "Input voltage from sensor path: " + source + ".";
      return;
    }

    powerBadge.textContent = "PWR: n/a";
    powerBadge.classList.add("temp-unknown");
    powerBadge.title = "Power telemetry unavailable.";
  }

  function pad2(value) {
    return value < 10 ? "0" + value : "" + value;
  }

  function updateLastRebootBadge(rebootEpoch) {
    var rebootBadge = byId("lastreboot");
    if (!rebootBadge) {
      return;
    }

    var epoch = typeof rebootEpoch === "number" && !isNaN(rebootEpoch) ? Math.floor(rebootEpoch) : 0;
    if (epoch > 0) {
      var dt = new Date(epoch * 1000);
      if (!isNaN(dt.getTime())) {
        var shortLabel = pad2(dt.getMonth() + 1) + "-" + pad2(dt.getDate()) + " " + pad2(dt.getHours()) + ":" + pad2(dt.getMinutes());
        rebootBadge.textContent = "Reboot: " + shortLabel;
        rebootBadge.title = "Last reboot: " + dt.toLocaleString() + " (epoch " + epoch + ")";
        return;
      }
    }

    rebootBadge.textContent = "Reboot: n/a";
    rebootBadge.title = "Last reboot: unavailable";
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

  function parseJsonArray(data) {
    try {
      var parsed = JSON.parse(data);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function clearJob(name) {
    if (timeoutJobs[name] !== undefined) {
      clearTimeout(timeoutJobs[name]);
      delete timeoutJobs[name];
    }
  }

  function executeEmbeddedScripts(root) {
    var scripts = Array.prototype.slice.call(root.querySelectorAll("script"));
    scripts.forEach(function (oldScript) {
      var newScript = document.createElement("script");
      Array.prototype.slice.call(oldScript.attributes).forEach(function (attr) {
        newScript.setAttribute(attr.name, attr.value);
      });
      if (oldScript.src) {
        newScript.async = false;
        newScript.src = oldScript.src;
      } else {
        newScript.text = oldScript.textContent;
      }
      oldScript.parentNode.replaceChild(newScript, oldScript);
    });
  }

  function setContentLoading(isLoading) {
    var content = byId("content");
    if (!content) {
      return;
    }
    content.classList.toggle("content-loading", !!isLoading);
  }

  function cacheBustedUrl(target) {
    var cachebuster = "_=" + Date.now();
    return target.indexOf("?") >= 0 ? target + "&" + cachebuster : target + "?" + cachebuster;
  }

  function normalizeTarget(target) {
    return (target || "").replace(/[?#].*$/, "");
  }

  function setActiveOnPageTarget(target) {
    var normalized = normalizeTarget(target);
    Array.prototype.slice.call(document.querySelectorAll(".onpage[data-target]")).forEach(function (node) {
      node.classList.toggle("is-active", normalizeTarget(node.dataset.target) === normalized);
    });
  }

  function closeNavMenu() {
    var burger = byId("navbar_burger");
    var menu = byId("nav_menu");
    if (burger) {
      burger.classList.remove("is-active");
      burger.setAttribute("aria-expanded", "false");
    }
    if (menu) {
      menu.classList.remove("is-active");
    }
    closeNavDropdowns();
  }

  function getDropdownToggle(dropdown) {
    if (!dropdown) {
      return null;
    }
    return dropdown.querySelector(".navbar-link");
  }

  function closeNavDropdowns(exceptNode) {
    Array.prototype.slice.call(document.querySelectorAll("#nav_menu .navbar-item.has-dropdown")).forEach(function (node) {
      if (exceptNode && node === exceptNode) {
        return;
      }
      node.classList.remove("is-active");
      var toggle = getDropdownToggle(node);
      if (toggle) {
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  function initNavDropdownToggles() {
    Array.prototype.slice.call(document.querySelectorAll("#nav_menu .navbar-item.has-dropdown > .navbar-link")).forEach(function (toggle) {
      if (toggle.dataset.dropdownBound === "1") {
        return;
      }
      toggle.dataset.dropdownBound = "1";
      toggle.setAttribute("aria-haspopup", "true");
      toggle.setAttribute("aria-expanded", "false");
      toggle.addEventListener("click", function (event) {
        if (window.innerWidth >= 1024) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        var dropdown = toggle.closest(".navbar-item.has-dropdown");
        if (!dropdown) {
          return;
        }
        var willOpen = !dropdown.classList.contains("is-active");
        closeNavDropdowns(dropdown);
        dropdown.classList.toggle("is-active", willOpen);
        toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
      });
    });
  }

  function loadOnPageTarget(target, onLoaded, forceReload) {
    var content = byId("content");
    if (!content || !target) {
      return;
    }
    var normalizedTarget = normalizeTarget(target);
    if (normalizedTarget === "cgi-bin/status.cgi") {
      ensureSettingsStylesLoaded();
    }
    if (!forceReload && normalizedTarget && normalizedTarget === currentContentTarget) {
      if (typeof onLoaded === "function") {
        onLoaded();
      }
      closeNavMenu();
      return;
    }

    if (contentLoadController) {
      contentLoadController.abort();
    }

    contentLoadController = new AbortController();
    setContentLoading(true);

    fetch(cacheBustedUrl(target), {
      cache: "no-store",
      signal: contentLoadController.signal,
    })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("Failed to load " + target + " (" + r.status + ")");
        }
        return r.text();
      })
      .then(function (html) {
        content.innerHTML = html;
        executeEmbeddedScripts(content);
        currentContentTarget = normalizedTarget;
        setActiveOnPageTarget(target);
        if (typeof onLoaded === "function") {
          onLoaded();
        }
      })
      .catch(function (e) {
        if (e && e.name === "AbortError") {
          return;
        }
        console.log(e);
        content.innerHTML = "<article class='message is-danger'><div class='message-header'><p>Load error</p></div><div class='message-body'>Unable to load page content.</div></article>";
      })
      .finally(function () {
        setContentLoading(false);
      });
  }

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

  function refreshLiveImage() {
    var liveview = byId("liveview");
    if (!liveview || !liveFeedEnabled) {
      clearJob("refreshLiveImage");
      return;
    }
    if (document.hidden) {
      scheduleRefreshLiveImage(LIVEVIEW_INTERVAL_HIDDEN_MS);
      return;
    }
    // We only change the src here. The onload/onerror handlers
    // will schedule the NEXT refresh once this one finishes.
    liveview.src = liveViewSnapshotEndpoint + "?" + Date.now();
  }

  function scheduleRefreshLiveImage(interval) {
    clearJob("refreshLiveImage");
    timeoutJobs.refreshLiveImage = setTimeout(refreshLiveImage, interval);
  }

  function refreshPerformanceProfile() {
    fetch("cgi-bin/state.cgi?cmd=perfprofile&uid=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (profile) {
        setPerformanceProfileBadge(profile);
      })
      .catch(function () { });
  }

  function refreshSysUsageLegacy(nextInterval) {
    fetch("cgi-bin/state.cgi?cmd=sysusage&uid=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (sysusage) {
        updateSysUsageBadges(sysusage, null, null);
        updateChipTempBadge(null, "n/a");
        updatePowerBadge(null, null, null, null, null);
        updateLastRebootBadge(null);
        updateSecurityBadge(null);
        refreshPerformanceProfile();
      })
      .finally(function () {
        scheduleRefreshSysUsage(nextInterval);
      });
  }

  function refreshSysUsage() {
    var baseInterval = document.hidden ? SYSUSAGE_INTERVAL_HIDDEN_MS : SYSUSAGE_INTERVAL_VISIBLE_MS;
    var nextInterval = baseInterval + dynamicSysUsageIntervalMs;
    fetch("cgi-bin/state.cgi?cmd=statusline&uid=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (statuslinePayload) {
        var statusline = null;
        try {
          statusline = JSON.parse(statuslinePayload);
        } catch (e) {
          statusline = null;
        }

        if (statusline && typeof statusline.sysusage === "string") {
          var cpuPercent = typeof statusline.cpu === "number" ? statusline.cpu : null;
          var ramPercent = typeof statusline.ram_percent === "number" ? statusline.ram_percent : null;
          updateSysUsageBadges(statusline.sysusage, cpuPercent, ramPercent);
          if (typeof statusline.perfprofile === "string") {
            setPerformanceProfileBadge(statusline.perfprofile);
          }
          if (typeof statusline.ui_ultralite_mode === "number") {
            applyUiUltraLiteMode(statusline.ui_ultralite_mode > 0);
          }
          updateChipTempBadge(
            typeof statusline.chip_temp_c === "number" ? statusline.chip_temp_c : null,
            typeof statusline.chip_temp_text === "string" ? statusline.chip_temp_text : "n/a"
          );
          updatePowerBadge(
            typeof statusline.power_estimated_mw === "number" ? statusline.power_estimated_mw : null,
            typeof statusline.power_voltage_mv === "number" ? statusline.power_voltage_mv : null,
            typeof statusline.power_estimate_enabled === "number" ? statusline.power_estimate_enabled > 0 : false,
            typeof statusline.power_estimated_current_ma === "number" ? statusline.power_estimated_current_ma : null,
            typeof statusline.power_sensor_path === "string" ? statusline.power_sensor_path : "n/a"
          );
          updateLastRebootBadge(typeof statusline.reboot_epoch === "number" ? statusline.reboot_epoch : null);
          updateSecurityBadge(typeof statusline.default_password_active === "number" ? statusline.default_password_active : null);
          updateLumAwbLabels(typeof statusline.lum === "string" ? statusline.lum : "", typeof statusline.awb === "string" ? statusline.awb : "");
          scheduleRefreshSysUsage(nextInterval);
          return;
        }

        refreshSysUsageLegacy(nextInterval);
      })
      .catch(function () {
        refreshSysUsageLegacy(nextInterval);
      });
  }

  function scheduleRefreshSysUsage(interval) {
    clearJob("refreshSysUsage");
    timeoutJobs.refreshSysUsage = setTimeout(refreshSysUsage, interval);
  }

  function showResult(txt) {
    var qv = byId("quickviewDefault");
    var v = byId("quicViewContent");
    if (!qv || !v) {
      return;
    }
    if (qv.classList.contains("is-active")) {
      qv.classList.remove("is-active");
    }
    v.innerHTML = txt;
    qv.classList.add("is-active");
    setTimeout(function () {
      var close = byId("quickViewClose");
      if (close) {
        close.click();
      }
    }, 2500);
  }

  function fixMenuPadding() {
    var navMenu = byId("nav_menu");
    if (!navMenu) {
      return;
    }
    if (window.innerWidth < 1023) {
      navMenu.style.paddingBottom = "6rem";
    } else {
      navMenu.style.paddingBottom = "";
    }
  }

  function setCookie(name, value) {
    document.cookie = encodeURIComponent(name) + "=" + encodeURIComponent(value) + "; path=/";
  }

  function getCookie(name) {
    var nameEQ = encodeURIComponent(name) + "=";
    var ca = document.cookie.split(";");
    for (var i = 0; i < ca.length; i++) {
      var c = ca[i];
      while (c.charAt(0) === " ") {
        c = c.substring(1, c.length);
      }
      if (c.indexOf(nameEQ) === 0) {
        return decodeURIComponent(c.substring(nameEQ.length, c.length));
      }
    }
    return null;
  }

  function setTheme(c) {
    if (!c) {
      return;
    }

    Array.prototype.slice.call(document.querySelectorAll(".theme_choice")).forEach(function (choice) {
      choice.classList.remove("is-active");
    });

    var theme = byId("theme_choice_" + c);
    var cssHref = "";
    if (theme) {
      theme.classList.add("is-active");
      cssHref = theme.dataset.css || "";
    } else if (c === "0") {
      cssHref = "css/bulma.0.6.2.min.css";
    } else if (c === "1") {
      cssHref = "css/bulmaswatch.min.css";
    }

    if (!cssHref) {
      return;
    }

    Array.prototype.slice.call(document.querySelectorAll("link.custom_theme")).forEach(function (node) {
      node.parentNode.removeChild(node);
    });

    var css = document.createElement("link");
    css.className = "custom_theme";
    css.rel = "stylesheet";
    css.href = cssHref;
    document.head.appendChild(css);

    var customCss = byId("custom_css");
    if (customCss) {
      var clone = customCss.cloneNode(true);
      customCss.remove();
      document.head.appendChild(clone);
    }

    setCookie("theme", c);
  }

  function getThemeChoice() {
    return getCookie("theme");
  }

  document.addEventListener("DOMContentLoaded", function () {
    setTheme(getThemeChoice());

    fetch("cgi-bin/state.cgi?cmd=hostname", { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (title) {
        document.title = title;
        var titleNode = byId("title");
        if (titleNode) {
          titleNode.title = title;
        }
      });

    document.addEventListener("click", function (event) {
      var onPageTarget = event.target.closest(".onpage");
      if (onPageTarget && onPageTarget.dataset.target) {
        event.preventDefault();
        loadOnPageTarget(onPageTarget.dataset.target, null, onPageTarget.dataset.forceReload === "1");
        if (window.innerWidth < 1024) {
          closeNavMenu();
        } else {
          closeNavDropdowns();
        }
        return;
      }

      var promptTarget = event.target.closest(".prompt");
      if (promptTarget && promptTarget.dataset.target) {
        if (confirm(promptTarget.dataset.message)) {
          window.location.href = promptTarget.dataset.target;
        }
        return;
      }

      if (window.innerWidth < 1024) {
        var menu = byId("nav_menu");
        if (menu && menu.classList.contains("is-active") && !event.target.closest("#nav_menu") && !event.target.closest("#navbar_burger")) {
          closeNavMenu();
        }
      } else if (!event.target.closest("#nav_menu")) {
        closeNavDropdowns();
      }
    });

    var navbarBurger = byId("navbar_burger");
    if (navbarBurger) {
      navbarBurger.addEventListener("click", function () {
        var willOpen = !navbarBurger.classList.contains("is-active");
        navbarBurger.classList.toggle("is-active", willOpen);
        navbarBurger.setAttribute("aria-expanded", willOpen ? "true" : "false");
        var menu = byId(navbarBurger.dataset.target);
        if (menu) {
          menu.classList.toggle("is-active", willOpen);
        }
        if (!willOpen) {
          closeNavDropdowns();
        }
      });
    }

    var navMenu = byId("nav_menu");
    if (navMenu) {
      navMenu.addEventListener("click", function (event) {
        if (window.innerWidth >= 1024) {
          return;
        }
        var clickedItem = event.target.closest(".navbar-item");
        if (!clickedItem || clickedItem.classList.contains("has-dropdown")) {
          return;
        }
        closeNavMenu();
      });
    }

    var quickViewClose = byId("quickViewClose");
    if (quickViewClose) {
      quickViewClose.addEventListener("click", function () {
        var quickView = byId("quickviewDefault");
        if (quickView) {
          quickView.classList.remove("is-active");
        }
      });
    }

    if (document.location.hash !== "") {
      var hashTarget = document.querySelector(document.location.hash);
      if (hashTarget) {
        hashTarget.click();
      }
    }

    var liveview = byId("liveview");
    if (liveview) {
      // Instead of relying on a blind setInterval, we wait for the 
      // previous image to finish loading before scheduling the next one.
      liveview.onload = function () {
        if (liveFeedEnabled) {
          scheduleRefreshLiveImage(liveViewVisibleIntervalMs);
        }
      };
      liveview.addEventListener("error", function () {
        if (!liveFeedEnabled) {
          return;
        }
        // If image fails to load, wait a short bit then try again
        scheduleRefreshLiveImage(800);
      });
    }

    var liveToggle = byId("live_toggle");
    if (liveToggle) {
      liveToggle.addEventListener("click", function () {
        liveFeedEnabled = !liveFeedEnabled;
        setLiveToggleButtonState();
        if (liveFeedEnabled) {
          scheduleRefreshLiveImage(100);
        } else {
          clearJob("refreshLiveImage");
        }
      });
    }
    setLiveToggleButtonState();

    document.addEventListener("visibilitychange", function () {
      scheduleRefreshLiveImage(document.hidden ? LIVEVIEW_INTERVAL_HIDDEN_MS : liveViewVisibleIntervalMs);
      scheduleRefreshSysUsage(document.hidden ? SYSUSAGE_INTERVAL_HIDDEN_MS : SYSUSAGE_INTERVAL_VISIBLE_MS);
    });

    // Push-to-Talk (Walkie-Talkie) feature
    (function () {
      var pttBtn = byId("ptt_btn");
      if (!pttBtn) { return; }

      // Inject icon + label span structure so the mic icon always stays visible
      pttBtn.innerHTML = '<i class="icon-microphone"></i> <span class="ptt-label">Hold to Talk</span>';

      if (!navigator.mediaDevices || !window.MediaRecorder) {
        var lbl = pttBtn.querySelector(".ptt-label");
        if (lbl) { lbl.textContent = "PTT (unsupported)"; }
        pttBtn.disabled = true;
        return;
      }

      if (!window.isSecureContext) {
        var lbl = pttBtn.querySelector(".ptt-label");
        if (lbl) { lbl.textContent = "PTT (needs HTTPS/localhost)"; }
        pttBtn.disabled = true;
        pttBtn.title = "Microphone access requires a Secure Context (HTTPS or localhost).";
        return;
      }

      var mediaRecorder = null;
      var audioStream = null;
      var audioChunks = [];
      var pttActive = false;
      var pttStartTime = 0;
      var PTT_MIN_DURATION_MS = 400;
      var pttResetTimer = null;

      function setPttLabel(text) {
        var lbl = pttBtn.querySelector(".ptt-label");
        if (lbl) { lbl.textContent = text; }
      }

      function resetPttBtn() {
        if (pttResetTimer) {
          clearTimeout(pttResetTimer);
          pttResetTimer = null;
        }
        pttBtn.classList.remove("is-loading", "ptt-recording", "ptt-sent", "ptt-error");
        pttBtn.disabled = false;
        setPttLabel("Hold to Talk");
      }

      function flashAndReset(label, cssClass, delayMs) {
        pttBtn.classList.remove("ptt-recording");
        pttBtn.classList.add(cssClass);
        setPttLabel(label);
        pttResetTimer = setTimeout(resetPttBtn, delayMs);
      }

      function releaseStream() {
        if (audioStream) {
          audioStream.getTracks().forEach(function (t) { t.stop(); });
          audioStream = null;
        }
      }

      function startRecording() {
        if (pttActive) { return; }
        setPttLabel("Requesting Mic\u2026");
        navigator.mediaDevices.getUserMedia({ audio: true, video: false })
          .then(function (stream) {
            pttActive = true;
            pttStartTime = Date.now();
            audioStream = stream;
            audioChunks = [];
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.addEventListener("dataavailable", function (e) {
              if (e.data && e.data.size > 0) {
                audioChunks.push(e.data);
              }
            });
            mediaRecorder.start();
            pttBtn.classList.add("ptt-recording");
            setPttLabel("Recording\u2026");
          })
          .catch(function (err) {
            console.log("PTT mic error: " + err.name + " - " + err.message);
            flashAndReset("Mic denied", "ptt-error", 2000);
          });
      }

      function stopRecording() {
        if (!pttActive || !mediaRecorder) { return; }
        pttActive = false;

        var elapsed = Date.now() - pttStartTime;
        if (elapsed < PTT_MIN_DURATION_MS) {
          // Too short — discard, don't send
          mediaRecorder.stop();
          releaseStream();
          mediaRecorder = null;
          audioChunks = [];
          flashAndReset("Too short", "ptt-error", 1200);
          return;
        }

        setPttLabel("Sending\u2026");
        pttBtn.classList.remove("ptt-recording");
        pttBtn.classList.add("is-loading");
        pttBtn.disabled = true;

        mediaRecorder.addEventListener("stop", function () {
          var blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
          mediaRecorder = null;
          audioChunks = [];
          fetch("cgi-bin/upload_audio.cgi", {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: blob,
          })
            .then(function (r) { return r.text(); })
            .then(function (result) {
              var ok = result.trim() === "OK";
              pttBtn.classList.remove("is-loading");
              flashAndReset(ok ? "Sent!" : "Error", ok ? "ptt-sent" : "ptt-error", 1400);
            })
            .catch(function () {
              pttBtn.classList.remove("is-loading");
              flashAndReset("Error", "ptt-error", 1400);
            });
        });

        mediaRecorder.stop();
        releaseStream();
      }

      pttBtn.addEventListener("mousedown", startRecording);
      pttBtn.addEventListener("touchstart", function (e) { e.preventDefault(); startRecording(); }, { passive: false });
      pttBtn.addEventListener("mouseup", stopRecording);
      pttBtn.addEventListener("mouseleave", stopRecording);
      pttBtn.addEventListener("touchend", stopRecording);
      pttBtn.addEventListener("touchcancel", stopRecording);
    })();

    fixMenuPadding();
    initNavDropdownToggles();
    refreshSysUsage();
  });

  window.addEventListener("resize", fixMenuPadding);

  window.refreshLiveImage = refreshLiveImage;
  window.scheduleRefreshLiveImage = scheduleRefreshLiveImage;
  window.refreshSysUsage = refreshSysUsage;
  window.scheduleRefreshSysUsage = scheduleRefreshSysUsage;
  window.refreshPerformanceProfile = refreshPerformanceProfile;
  window.showResult = showResult;
  window.fixMenuPadding = fixMenuPadding;
  window.setCookie = setCookie;
  window.getCookie = getCookie;
  window.setTheme = setTheme;
  window.getThemeChoice = getThemeChoice;

  // Global utility for sub-page scripts to check if they are still 'mounted'
  window.isHostStillActive = function (node) {
    return !!(node && node.parentNode && document.body.contains(node));
  };
})();
