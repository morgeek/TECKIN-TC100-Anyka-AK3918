  // --- Polling: performance profile, system usage, shared status line request ---
  function refreshPerformanceProfile() {
    if (perfProfileFetchController) {
      perfProfileFetchController.abort();
    }
    var controller = new AbortController();
    perfProfileFetchController = controller;

    fetch("cgi-bin/state.cgi?cmd=perfprofile&uid=" + Date.now(), { cache: "no-store", signal: controller.signal })
      .then(function (r) {
        return r.text();
      })
      .then(function (profile) {
        setPerformanceProfileBadge(profile);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") {
          return;
        }
      })
      .finally(function () {
        if (perfProfileFetchController === controller) {
          perfProfileFetchController = null;
        }
      });
  }

  function refreshSysUsageLegacy(nextInterval) {
    if (legacySysUsageFetchController) {
      legacySysUsageFetchController.abort();
    }
    var controller = new AbortController();
    legacySysUsageFetchController = controller;

    fetch("cgi-bin/state.cgi?cmd=sysusage&uid=" + Date.now(), { cache: "no-store", signal: controller.signal })
      .then(function (r) {
        return r.text();
      })
      .then(function (sysusage) {
        sysUsageConsecErrors = 0;
        sysUsageLastSuccessTs = Date.now();
        updateStaleBanner(false);
        updateStatusRefreshUi("fresh");
        updateSystemLoadState(sysusage, null, null);
        updateSecurityBadge(null);
        refreshPerformanceProfile();
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") {
          return;
        }
        updateStatusRefreshUi("error");
      })
      .finally(function () {
        if (legacySysUsageFetchController === controller) {
          legacySysUsageFetchController = null;
          scheduleRefreshSysUsage(nextInterval);
        }
      });
  }

  function refreshSysUsage() {
    if (document.hidden) {
      clearJob("refreshSysUsage");
      updateStatusRefreshUi("paused");
      return;
    }
    var baseInterval = document.hidden ? SYSUSAGE_INTERVAL_HIDDEN_MS : SYSUSAGE_INTERVAL_VISIBLE_MS;
    var nextInterval = baseInterval + dynamicSysUsageIntervalMs;
    if (sysUsageFetchController) {
      sysUsageFetchController.abort();
    }
    var controller = new AbortController();
    sysUsageFetchController = controller;

    fetch("cgi-bin/statusline.cgi?uid=" + Date.now(), { cache: "no-store", signal: controller.signal })
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
          updateSystemLoadState(statusline.sysusage, cpuPercent, ramPercent);
          if (typeof statusline.perfprofile === "string") {
            setPerformanceProfileBadge(statusline.perfprofile);
          }
          if (typeof statusline.ui_ultralite_mode === "number") {
            applyUiUltraLiteMode(statusline.ui_ultralite_mode > 0);
          }
          updateSecurityBadge(typeof statusline.default_password_active === "number" ? statusline.default_password_active : null);
          updateMqttBadge(
            typeof statusline.mqtt_enabled === "number" ? statusline.mqtt_enabled : -1,
            typeof statusline.mqtt_last_pub_ts === "number" ? statusline.mqtt_last_pub_ts : 0,
            typeof statusline.mqtt_last_pub_ok === "number" ? statusline.mqtt_last_pub_ok : -1,
            typeof statusline.mqtt_refused === "number" ? statusline.mqtt_refused : 0
          );
          updateLumAwbLabels(typeof statusline.lum === "string" ? statusline.lum : "", typeof statusline.awb === "string" ? statusline.awb : "");
          if (typeof statusline.csrf_token === "string" && statusline.csrf_token.length > 0) {
            csrfToken = statusline.csrf_token;
          }
          updateFirmwareVersionUi(
            typeof statusline.current_version === "string" ? statusline.current_version : null,
            typeof statusline.update_available === "number" ? statusline.update_available : null,
            typeof statusline.update_latest_version === "string" ? statusline.update_latest_version : null
          );
          lastStatusline = statusline;
          lastStatuslineTs = Date.now();
          if (dashboardStatusRenderer) dashboardStatusRenderer(statusline);
          renderReadings(statusline);
          sysUsageConsecErrors = 0;
          sysUsageLastSuccessTs = Date.now();
          updateStaleBanner(false);
          updateStatusRefreshUi("fresh");
          scheduleRefreshSysUsage(nextInterval);
          return;
        }

        sysUsageConsecErrors++;
        updateStaleBanner(true);
        var backoffInterval = Math.min(nextInterval * Math.pow(2, sysUsageConsecErrors), nextInterval * 8);
        refreshSysUsageLegacy(backoffInterval);
      })
      .catch(function (err) {
        if (err && err.name === "AbortError") {
          return;
        }
        sysUsageConsecErrors++;
        updateStaleBanner(true);
        var backoffInterval = Math.min(nextInterval * Math.pow(2, sysUsageConsecErrors), nextInterval * 8);
        refreshSysUsageLegacy(backoffInterval);
      })
      .finally(function () {
        if (sysUsageFetchController === controller) {
          sysUsageFetchController = null;
        }
      });
  }

  function scheduleRefreshSysUsage(interval) {
    clearJob("refreshSysUsage");
    if (document.hidden) return;
    timeoutJobs.refreshSysUsage = setTimeout(refreshSysUsage, interval);
  }

  function getStatusline(maxAgeMs) {
    var maxAge = typeof maxAgeMs === "number" ? maxAgeMs : 10000;
    if (lastStatusline && Date.now() - lastStatuslineTs <= maxAge) return Promise.resolve(lastStatusline);
    if (sharedStatuslineRequest) return sharedStatuslineRequest;
    sharedStatuslineRequest = fetch("cgi-bin/statusline.cgi", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("Status HTTP " + r.status); return r.json(); })
      .then(function (data) {
        lastStatusline = data;
        lastStatuslineTs = Date.now();
        if (data && data.csrf_token) csrfToken = data.csrf_token;
        return data;
      })
      .finally(function () { sharedStatuslineRequest = null; });
    return sharedStatuslineRequest;
  }

  function updateStatusRefreshUi(state) {
    if (!statusUpdatedLabel) statusUpdatedLabel = byId("status_updated");
    if (!statusRefreshButton) statusRefreshButton = byId("status_refresh");
    if (statusRefreshButton) {
      statusRefreshButton.classList.toggle("is-loading", state === "loading");
      statusRefreshButton.disabled = state === "loading";
    }
    if (!statusUpdatedLabel) return;
    if (state === "paused") statusUpdatedLabel.textContent = "Monitoring paused in background";
    else if (state === "loading") statusUpdatedLabel.textContent = "Updating…";
    else if (state === "fresh") statusUpdatedLabel.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    else if (state === "error") statusUpdatedLabel.textContent = "Status unavailable, retrying";
  }

