(function () {
  function qs(selector) {
    return document.querySelector(selector);
  }

  function qsa(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector));
  }

  function executeEmbeddedScripts(root) {
    if (!root) {
      return;
    }
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

  function toFormBody(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function ensureSubmitControl(form) {
    var button = form.querySelector("input[type=submit],button[type=submit],.is-primary");
    if (!button) {
      button = document.createElement("input");
      button.type = "submit";
      button.style.display = "none";
      form.appendChild(button);
    }
    return button;
  }

  function setLoading(button, loading) {
    if (!button) {
      return;
    }
    button.classList.toggle("is-loading", !!loading);
    button.disabled = !!loading;
  }

  function showResult(text) {
    if (window.showResult) {
      try {
        window.showResult(text);
      } catch (e) {
        console.log(e);
      }
    } else {
      console.log(text);
    }
  }

  function setTextValue(selector, text) {
    var field = qs(selector);
    if (!field) {
      return;
    }
    field.value = text;
  }

  function yamlQuote(value) {
    return JSON.stringify(value == null ? "" : String(value));
  }

  function fallbackCopyText(text) {
    var probe = document.createElement("textarea");
    probe.value = text;
    probe.setAttribute("readonly", "readonly");
    probe.style.position = "fixed";
    probe.style.top = "-1000px";
    probe.style.left = "-1000px";
    document.body.appendChild(probe);
    probe.focus();
    probe.select();
    try {
      if (!document.execCommand("copy")) {
        throw new Error("copy failed");
      }
    } finally {
      document.body.removeChild(probe);
    }
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext !== false) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        fallbackCopyText(text);
        resolve();
      } catch (error) {
        reject(error);
      }
    });
  }

  function buildIntegrationSummary(manifest) {
    var web = manifest.web || {};
    var rtsp = manifest.rtsp || {};
    var mqtt = manifest.mqtt || {};
    var onvif = manifest.onvif || {};
    var lines = [];

    lines.push("Camera: " + (manifest.hostname || "TC100 Camera") + " (" + (manifest.primary_ip || "CAMERA-IP") + ")");
    lines.push("Generated: " + (manifest.generated_at_utc || "n/a"));
    lines.push("Web base: " + (web.base_url || "disabled"));
    if (web.snapshot_url) {
      lines.push("Snapshot: " + web.snapshot_url);
    }
    if (web.healthsnapshot_url) {
      lines.push("Health JSON: " + web.healthsnapshot_url);
    }
    if (rtsp.main && rtsp.main.url) {
      lines.push("RTSP main: " + rtsp.main.url);
    }
    if (rtsp.substream_enabled && rtsp.sub && rtsp.sub.url) {
      lines.push("RTSP sub: " + rtsp.sub.url);
    } else {
      lines.push("RTSP sub: disabled");
    }
    if (onvif.device_service_url) {
      lines.push("ONVIF: " + onvif.device_service_url);
    }
    if (mqtt.enabled) {
      lines.push("MQTT broker: " + (mqtt.broker_host || "127.0.0.1") + ":" + (mqtt.broker_port || 1883));
      lines.push("MQTT health topic: " + (mqtt.health_topic || ""));
      lines.push("MQTT motion topic: " + (mqtt.motion_state_topic || ""));
      lines.push("MQTT command topic: " + (mqtt.command_topic || ""));
    } else {
      lines.push("MQTT: disabled");
    }

    return lines.join("\n");
  }

  function buildFrigateSnippet(manifest) {
    var rtsp = manifest.rtsp || {};
    var mqtt = manifest.mqtt || {};
    var frigate = rtsp.frigate || {};
    var cameraSlug = manifest.camera_slug || "tc100_camera";
    var lines = [];
    var recordUrl = frigate.record_url || (rtsp.main && rtsp.main.url) || "";
    var detectUrl = frigate.detect_url || recordUrl;

    if (rtsp.auth_warning) {
      lines.push("# " + rtsp.auth_warning);
      lines.push("# Replace USERNAME/PASSWORD placeholders if needed.");
      lines.push("");
    }

    if (mqtt.enabled) {
      lines.push("mqtt:");
      lines.push("  host: " + yamlQuote(mqtt.broker_host || "127.0.0.1"));
      lines.push("  port: " + (mqtt.broker_port || 1883));
      if (mqtt.username) {
        lines.push("  user: " + yamlQuote(mqtt.username));
      }
      if (mqtt.password) {
        lines.push("  password: " + yamlQuote(mqtt.password));
      }
      if (mqtt.topic_root) {
        lines.push("  topic_prefix: " + yamlQuote(mqtt.topic_root));
      }
      lines.push("");
    }

    lines.push("cameras:");
    lines.push("  " + cameraSlug + ":");
    lines.push("    ffmpeg:");
    lines.push("      inputs:");
    lines.push("        - path: " + yamlQuote(recordUrl));
    lines.push("          roles:");
    lines.push("            - record");
    if (detectUrl === recordUrl) {
      lines.push("            - detect");
    } else {
      lines.push("        - path: " + yamlQuote(detectUrl));
      lines.push("          roles:");
      lines.push("            - detect");
    }

    return lines.join("\n");
  }

  function buildHomeAssistantNotes(manifest) {
    var web = manifest.web || {};
    var rtsp = manifest.rtsp || {};
    var mqtt = manifest.mqtt || {};
    var onvif = manifest.onvif || {};
    var lines = [];

    lines.push("ONVIF integration");
    lines.push("host: " + (manifest.primary_ip || "CAMERA-IP"));
    lines.push("port: " + (onvif.port || 8081));
    lines.push("username: " + (rtsp.username || "root"));
    lines.push("password: " + (rtsp.password || ""));
    lines.push("stream policy: " + (onvif.stream_policy || "main-primary"));

    if (mqtt.enabled) {
      lines.push("");
      lines.push("MQTT discovery");
      lines.push("broker: " + (mqtt.broker_host || "127.0.0.1") + ":" + (mqtt.broker_port || 1883));
      lines.push("discovery enabled: " + (mqtt.discovery_enabled ? "yes" : "no"));
      lines.push("discovery prefix: " + (mqtt.discovery_prefix || "homeassistant"));
      lines.push("topic root: " + (mqtt.topic_root || ""));
      lines.push("command topic: " + (mqtt.command_topic || ""));
      lines.push("availability topic: " + (mqtt.availability_topic || ""));
      lines.push("health topic: " + (mqtt.health_topic || ""));
      lines.push("motion state topic: " + (mqtt.motion_state_topic || ""));
      lines.push("event topic: " + (mqtt.event_topic || ""));
    } else {
      lines.push("");
      lines.push("MQTT discovery");
      lines.push("disabled");
    }

    if (web.base_url) {
      lines.push("");
      lines.push("Useful local URLs");
      lines.push("snapshot: " + (web.snapshot_url || ""));
      lines.push("health JSON: " + (web.healthsnapshot_url || ""));
      lines.push("motion events JSON: " + (web.motion_events_url || ""));
      lines.push("latest motion thumbnail: " + (web.motion_thumbnail_url || ""));
      lines.push("integration manifest: " + (web.integration_manifest_url || ""));
    }

    if (rtsp.auth_warning) {
      lines.push("");
      lines.push("Note");
      lines.push(rtsp.auth_warning);
    }

    return lines.join("\n");
  }

  function initCopyTargets() {
    qsa("[data-copy-target]").forEach(function (button) {
      if (button.dataset.copyBound === "1") {
        return;
      }
      button.dataset.copyBound = "1";
      button.addEventListener("click", function () {
        var targetId = button.getAttribute("data-copy-target");
        var target = targetId ? document.getElementById(targetId) : null;
        var text = target ? target.value || target.textContent || "" : "";
        copyText(text)
          .then(function () {
            showResult("Copied.");
          })
          .catch(function (error) {
            console.error(error);
            showResult("Copy failed.");
          });
      });
    });
  }

  function initIntegrationPack() {
    if (!qs("#integrationSummarySnippet")) {
      return;
    }

    fetch("cgi-bin/state.cgi?cmd=integrationmanifest&uid=" + Date.now(), { cache: "no-store" })
      .then(function (response) {
        return response.text();
      })
      .then(function (text) {
        var manifest = JSON.parse(text);
        setTextValue("#integrationSummarySnippet", buildIntegrationSummary(manifest));
        setTextValue("#frigateConfigSnippet", buildFrigateSnippet(manifest));
        setTextValue("#homeAssistantIntegrationNotes", buildHomeAssistantNotes(manifest));
      })
      .catch(function (error) {
        var fallback = "Failed to load integration manifest.";
        console.error(error);
        setTextValue("#integrationSummarySnippet", fallback);
        setTextValue("#frigateConfigSnippet", fallback);
        setTextValue("#homeAssistantIntegrationNotes", fallback);
      });
  }

  function buildIntegrationSelfTestSummary(result) {
    var tests = result.tests || {};
    var lines = [];

    function renderTestLine(label, key) {
      var test = tests[key] || {};
      var status = String(test.status || "unknown").toUpperCase();
      var detail = test.detail ? " - " + test.detail : "";
      return label + ": " + status + detail;
    }

    lines.push("Overall: " + String(result.overall_status || "unknown").toUpperCase());
    lines.push("Camera: " + (result.hostname || "TC100 Camera") + " (" + (result.primary_ip || "CAMERA-IP") + ")");
    lines.push("Timestamp: " + (result.timestamp_utc || "n/a"));
    lines.push("");
    lines.push(renderTestLine("RTSP main", "rtsp_main"));
    lines.push(renderTestLine("RTSP sub", "rtsp_sub"));
    lines.push(renderTestLine("ONVIF", "onvif"));
    lines.push(renderTestLine("MQTT publish", "mqtt_publish"));
    lines.push(renderTestLine("Snapshot", "snapshot"));

    return lines.join("\n");
  }

  function initIntegrationSelfTest() {
    var runButton = qs("#integrationSelfTestRun");
    var output = qs("#integrationSelfTestResult");
    if (!runButton || !output || runButton.dataset.bound === "1") {
      return;
    }

    runButton.dataset.bound = "1";
    runButton.addEventListener("click", function () {
      setLoading(runButton, true);
      output.value = "Running integration self-test...";
      fetch("cgi-bin/state.cgi?cmd=integrationtest&uid=" + Date.now(), { cache: "no-store" })
        .then(function (response) {
          return response.text();
        })
        .then(function (text) {
          var result = JSON.parse(text);
          output.value = buildIntegrationSelfTestSummary(result);
        })
        .catch(function (error) {
          console.error(error);
          output.value = "Integration self-test failed to run.";
          showResult("Self-test failed.");
        })
        .finally(function () {
          setLoading(runButton, false);
        });
    });
  }

  function scheduleStatusReload(delay) {
    var reloadDelay = delay || 5000;
    if (window._srScheduled) {
      return;
    }

    var content = document.getElementById("content");
    // If we've navigated away from the page that owns this script, stop polling
    if (window.isHostStillActive && !window.isHostStillActive(content)) {
      return;
    }

    window._srScheduled = true;
    setTimeout(function () {
      if (!content || (window.isHostStillActive && !window.isHostStillActive(content))) {
        window._srScheduled = false;
        return;
      }
      fetch("cgi-bin/status.cgi", { cache: "no-store" })
        .then(function (r) {
          return r.text();
        })
        .then(function (html) {
          // Final check before mutation: did the user navigate away while we were fetching?
          if (window.isHostStillActive && !window.isHostStillActive(content)) {
            return;
          }
          content.innerHTML = html;
          executeEmbeddedScripts(content);
        })
        .catch(function (e) {
          console.error(e);
        })
        .finally(function () {
          window._srScheduled = false;
        });
    }, reloadDelay);
  }

  function bindAjaxForm(form, triggerReload) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var submitControl = ensureSubmitControl(form);
      setLoading(submitControl, true);
      fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: toFormBody(form),
      })
        .then(function (r) {
          return r.text();
        })
        .then(function (text) {
          showResult(text);
          if (form.id === "formPerformanceProfile" && window.refreshPerformanceProfile) {
            setTimeout(function () {
              window.refreshPerformanceProfile();
            }, 700);
          }
          if (triggerReload !== false) {
            scheduleStatusReload(5000);
          }
        })
        .catch(function (e) {
          console.error(e);
        })
        .finally(function () {
          setLoading(submitControl, false);
        });
    });
  }

  function initServiceTrimToggle() {
    var serviceTrim = qs("#serviceTrim");
    if (!serviceTrim) {
      return;
    }

    serviceTrim.addEventListener("change", function () {
      var url = serviceTrim.checked ? "cgi-bin/action.cgi?cmd=service_trim_on" : "cgi-bin/action.cgi?cmd=service_trim_off";
      fetch(url, { cache: "no-store" })
        .then(function (r) {
          return r.text();
        })
        .then(function (text) {
          showResult(text);
          if (window.refreshPerformanceProfile) {
            setTimeout(function () {
              window.refreshPerformanceProfile();
            }, 700);
          }
          scheduleStatusReload(5000);
        })
        .catch(function (e) {
          console.error(e);
        });
    });
  }

  function initImageFlipToggle() {
    var imageFlip = qs("#imageFlip");
    if (!imageFlip) {
      return;
    }

    imageFlip.addEventListener("change", function () {
      fetch("cgi-bin/action.cgi?cmd=image-flip", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: "flipValue=" + encodeURIComponent(imageFlip.value),
      }).catch(function (e) {
        console.error(e);
      });
    });
  }

  function initRtspLogToggle() {
    var rtspLog = qs("#enable_rtsp_log");
    if (!rtspLog) {
      return;
    }

    rtspLog.addEventListener("change", function () {
      var url = rtspLog.checked ? "cgi-bin/action.cgi?cmd=rtsp-log-on" : "cgi-bin/action.cgi?cmd=rtsp-log-off";
      fetch(url, { cache: "no-store" }).catch(function (e) {
        console.error(e);
      });
    });
  }

  function initThemePicker() {
    var themeChoices = qsa(".theme_choice[data-theme]");
    if (!themeChoices.length) {
      return;
    }

    themeChoices.forEach(function (choice) {
      if (choice.dataset.themeBound === "1") {
        return;
      }
      choice.dataset.themeBound = "1";
      choice.addEventListener("click", function (event) {
        event.preventDefault();
        if (window.setTheme) {
          window.setTheme(choice.dataset.theme);
        }
      });
    });

    if (window.getThemeChoice && window.setTheme) {
      window.setTheme(window.getThemeChoice() || "0");
    }
  }

  function initMemoryPurge() {
    var btn = qs("#btnFreeRam");
    if (!btn) {
      return;
    }

    btn.addEventListener("click", function (event) {
      event.preventDefault();
      setLoading(btn, true);
      fetch("cgi-bin/action.cgi?cmd=clear_mem", { cache: "no-store" })
        .then(function (r) {
          return r.text();
        })
        .then(function (text) {
          showResult(text);
          if (window.scheduleStatusReload) {
            window.scheduleStatusReload(1000);
          }
        })
        .catch(function (e) {
          console.error(e);
        })
        .finally(function () {
          setLoading(btn, false);
        });
    });
  }

  function initWebModeForm() {
    var mode = qs("#web_mode");
    var port = qs("#ultralite_http_port");
    var portField = port ? port.closest(".web-port-field") : null;

    if (!mode || !port || !portField) {
      return;
    }

    function syncPortVisibility() {
      var show = mode.value === "ultra-lite";
      portField.classList.toggle("is-hidden", !show);
      port.disabled = !show;
    }

    if (mode.dataset.bound !== "1") {
      mode.dataset.bound = "1";
      mode.addEventListener("change", syncPortVisibility);
    }
    syncPortVisibility();
  }

  var embeddedPanelConfig = [];

  function loadEmbeddedPanelHost(host) {
    if (!host) {
      return Promise.resolve();
    }
    if (host.dataset.panelLoaded === "1" || host.dataset.panelLoading === "1") {
      return Promise.resolve();
    }

    var url = host.dataset.panelUrl;
    if (!url) {
      return Promise.resolve();
    }

    host.dataset.panelLoading = "1";
    return fetch(url, { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (html) {
        host.innerHTML = html;
        executeEmbeddedScripts(host);
        host.dataset.panelLoaded = "1";
      })
      .catch(function (e) {
        console.error(e);
        host.innerHTML = "<p>Failed to load panel.</p>";
      })
      .finally(function () {
        host.dataset.panelLoading = "0";
      });
  }

  function loadVisibleEmbeddedPanels() {
    qsa("[data-panel-url]").forEach(function (host) {
      var parentCard = host.closest(".status_card");
      if (parentCard && (parentCard.classList.contains("status-collapsed") || parentCard.classList.contains("is-hidden"))) {
        return;
      }
      loadEmbeddedPanelHost(host);
    });
  }

  function initEmbeddedSettingsPanels() {
    embeddedPanelConfig.forEach(function (entry) {
      var host = qs(entry[0]);
      if (!host) {
        return;
      }
      host.dataset.panelUrl = entry[1];
      host.dataset.panelLoaded = "0";
      host.dataset.panelLoading = "0";
    });
    loadVisibleEmbeddedPanels();
  }

  function statusCardTitle(card) {
    var titleNode = card.querySelector(".card-header-title");
    return titleNode ? titleNode.textContent.trim() : "";
  }

  function slugifyStatusTitle(title) {
    return String(title || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function categorizeStatusCard(title) {
    switch (title) {
      case "System":
      case "Advanced Tuning":
      case "Scheduled Reboot":
      case "MQTT Bridge":
      case "Motion Event API":
        return "system";
      case "HTTP/RTSP/Telnet Password":
      case "HTTP Password":
      case "Telnet Server":
      case "FTP Server":
        return "access";
      case "Video Settings":
      case "RTSP/Misc":
      case "RTSP stream address":
        return "video";
      case "Audio Settings":
        return "audio";
      case "Recording":
      case "Timelapse":
        return "recording";
      case "ISP Pro Mode & OSD":
      case "Sound Detection (Beta)":
      case "Motion Detection":
        return "imaging";
      case "Tests":
        return "tools";
      default:
        return "other";
    }
  }

  function statusCategoryLabel(category) {
    switch (category) {
      case "system":
        return "System";
      case "access":
        return "Access";
      case "video":
        return "Video";
      case "audio":
        return "Audio";
      case "recording":
        return "Recording";
      case "imaging":
        return "Image/OSD";
      case "tools":
        return "Tools";
      default:
        return "Other";
    }
  }

  function statusCategoryIconSvg(category) {
    switch (category) {
      case "system":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M10.5 6h9M4.5 6h2M8.5 6a1 1 0 1 0-2 0a1 1 0 0 0 2 0zM19.5 12h-2M4.5 12h9M17.5 12a1 1 0 1 0 2 0a1 1 0 0 0-2 0zM10.5 18h9M4.5 18h2M8.5 18a1 1 0 1 0-2 0a1 1 0 0 0 2 0z'/></svg>";
      case "access":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3a5 5 0 0 1 5 5v2h1a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h1V8a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v2h6V8a3 3 0 0 0-3-3zm0 8a2 2 0 0 0-1 3.73V18h2v-1.27A2 2 0 0 0 12 13z'/></svg>";
      case "video":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v2.2l3.2-2a1 1 0 0 1 1.5.85v7.9a1 1 0 0 1-1.5.85L17 14.8V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7z'/></svg>";
      case "audio":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 10h4l5-4v12l-5-4H4v-4zm12.5-2.5a5 5 0 0 1 0 9M18.5 5a8 8 0 0 1 0 14'/></svg>";
      case "recording":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 20a8 8 0 1 1 0-16a8 8 0 0 1 0 16zm0-11a3 3 0 1 0 0 6a3 3 0 0 0 0-6z'/></svg>";
      case "imaging":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M5 7h4l2-2h2l2 2h4a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zm7 3a4 4 0 1 0 0 8a4 4 0 0 0 0-8z'/></svg>";
      case "tools":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M14.7 6.3a3.5 3.5 0 0 0-4.95 4.95l-5.2 5.2a1.5 1.5 0 1 0 2.12 2.12l5.2-5.2a3.5 3.5 0 0 0 4.95-4.95l-2.1 2.1l-2.12-2.12l2.1-2.1z'/></svg>";
      default:
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 8h.01M11 12h1v4h1M12 22a10 10 0 1 1 0-20a10 10 0 0 1 0 20z'/></svg>";
    }
  }

  function statusTitleIconSvg(title, category) {
    switch (title) {
      case "Setup Wizard":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 20l5-5M10 3l2 2M3 10l2 2M8 7l2 2M14 4l6 6M12 12l2 2M16 12l2-2M14 14l-2 2'/></svg>";
      case "System":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M10.5 6h9M4.5 6h2M7.5 6h0M19.5 12h-2M4.5 12h9M18.5 12h0M10.5 18h9M4.5 18h2M7.5 18h0'/></svg>";
      case "Advanced Tuning":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M10.3 4.3l.6 1.7a6.4 6.4 0 0 1 2.2 0l.6-1.7l2 1.1l-.4 1.7c.6.4 1.1 1 1.6 1.6l1.7-.4l1.1 2l-1.7.6a6.4 6.4 0 0 1 0 2.2l1.7.6l-1.1 2l-1.7-.4c-.4.6-1 1.1-1.6 1.6l.4 1.7l-2 1.1l-.6-1.7a6.4 6.4 0 0 1-2.2 0l-.6 1.7l-2-1.1l.4-1.7a6.4 6.4 0 0 1-1.6-1.6l-1.7.4l-1.1-2l1.7-.6a6.4 6.4 0 0 1 0-2.2l-1.7-.6l1.1-2l1.7.4c.4-.6 1-1.1 1.6-1.6l-.4-1.7l2-1.1zM12 9a3 3 0 1 0 0 6a3 3 0 0 0 0-6z'/></svg>";
      case "Scheduled Reboot":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 8v5l3 2M21 12a9 9 0 1 1-2.64-6.36M21 4v6h-6'/></svg>";
      case "MQTT Bridge":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M5 12h4M15 12h4M9 8l3-3l3 3M9 16l3 3l3-3M12 5v14'/></svg>";
      case "Motion Event API":
        return "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='M4 12a8 8 0 0 1 16 0M8 12a4 4 0 0 1 8 0M12 12h.01'/></svg>";
      default:
        return statusCategoryIconSvg(category);
    }
  }

  function setCardCollapsed(card, collapsed) {
    card.classList.toggle("status-collapsed", !!collapsed);
    var header = card.querySelector(".card-header");
    if (header) {
      header.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
  }

  function setupStatusDensityControls() {
    var cards = qsa(".status_card");
    if (!cards.length) {
      return;
    }

    var basicTitles = {
      System: true,
      "Advanced Tuning": true,
      "HTTP/RTSP/Telnet Password": true,
      "Video Settings": true,
      "RTSP stream address": true,
    };

    var assignedIds = {};
    cards.forEach(function (card) {
      var title = statusCardTitle(card);
      var isBasic = !!basicTitles[title];
      var header = card.querySelector(".card-header");
      var category = categorizeStatusCard(title);
      var titleNode = card.querySelector(".card-header-title");
      var slugBase = slugifyStatusTitle(title) || "section";
      var slugIndex = assignedIds[slugBase] || 0;
      assignedIds[slugBase] = slugIndex + 1;
      var cardId = slugIndex === 0 ? "status-card-" + slugBase : "status-card-" + slugBase + "-" + slugIndex;
      card.id = card.id || cardId;
      card.dataset.statusGroup = isBasic ? "basic" : "advanced";
      card.dataset.statusCategory = category;
      card.dataset.statusTitle = title;
      card.classList.add("status-collapsible");
      if (!isBasic) {
        setCardCollapsed(card, true);
      } else {
        setCardCollapsed(card, false);
      }

      if (titleNode && !titleNode.querySelector(".status-card-category-icon")) {
        var iconSpan = document.createElement("span");
        iconSpan.className = "status-card-category-icon";
        iconSpan.setAttribute("aria-hidden", "true");
        iconSpan.innerHTML = statusTitleIconSvg(title, category);
        titleNode.insertBefore(iconSpan, titleNode.firstChild);
      }

      if (!header || header.dataset.toggleBound === "1") {
        return;
      }
      header.dataset.toggleBound = "1";
      header.classList.add("status-card-header-toggle");
      header.setAttribute("role", "button");
      header.setAttribute("tabindex", "0");

      function toggleCard() {
        setCardCollapsed(card, !card.classList.contains("status-collapsed"));
        loadVisibleEmbeddedPanels();
      }

      header.addEventListener("click", function (event) {
        if (event.target.closest("a,button,input,select,textarea,label")) {
          return;
        }
        toggleCard();
      });

      header.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleCard();
        }
      });
    });

    var firstCard = cards[0];
    if (!firstCard) {
      return;
    }
    var organizer = qs("#statusOrganizer");
    if (!organizer) {
      organizer = document.createElement("div");
      organizer.id = "statusOrganizer";
      organizer.className = "status-organizer";
      organizer.innerHTML =
        "<div id='statusViewMode' class='status-view-mode'>" +
        "<span class='status-view-mode-label'>Settings view</span>" +
        "<button id='statusViewBasic' class='button is-small is-link is-outlined' type='button'>Basic</button>" +
        "<button id='statusViewAll' class='button is-small is-link is-outlined' type='button'>All</button>" +
        "</div>" +
        "<div class='status-filter-wrap'>" +
        "<input id='statusFilterInput' class='input is-small status-filter-input' type='search' placeholder='Filter settings...'>" +
        "</div>" +
        "<div id='statusQuickNav' class='status-quicknav'></div>" +
        "<p id='statusFilterInfo' class='status-filter-info'></p>";
      firstCard.parentNode.insertBefore(organizer, firstCard);
    }

    var currentMode = "basic";
    function setMode(mode) {
      var showAll = mode === "all";
      currentMode = showAll ? "all" : "basic";
      cards.forEach(function (card) {
        var advanced = card.dataset.statusGroup === "advanced";
        setCardCollapsed(card, !showAll && advanced);
      });

      var basicBtn = qs("#statusViewBasic");
      var allBtn = qs("#statusViewAll");
      if (basicBtn) {
        basicBtn.classList.toggle("is-active", !showAll);
      }
      if (allBtn) {
        allBtn.classList.toggle("is-active", showAll);
      }
      applyFilter();
    }

    function focusCard(card) {
      if (!card) {
        return;
      }
      if (card.dataset.statusGroup === "advanced" && currentMode !== "all") {
        setMode("all");
      }
      setCardCollapsed(card, false);
      card.classList.remove("is-hidden");
      loadVisibleEmbeddedPanels();
      card.scrollIntoView({ block: "start" });
    }

    function applyFilter() {
      var input = qs("#statusFilterInput");
      var info = qs("#statusFilterInfo");
      var term = input ? String(input.value || "").toLowerCase().trim() : "";
      var visibleCount = 0;

      cards.forEach(function (card) {
        var byMode = currentMode === "all" || card.dataset.statusGroup !== "advanced";
        var byTerm = true;
        if (term) {
          var haystack = (card.dataset.statusTitle + " " + statusCategoryLabel(card.dataset.statusCategory)).toLowerCase();
          byTerm = haystack.indexOf(term) !== -1;
        }
        var visible = byMode && byTerm;
        card.classList.toggle("is-hidden", !visible);
        if (!visible) {
          setCardCollapsed(card, true);
        }
        if (visible) {
          visibleCount += 1;
        }
      });

      if (info) {
        info.textContent = term ? visibleCount + " section(s) match" : "";
      }
      loadVisibleEmbeddedPanels();
    }

    function buildQuickNav() {
      var quickNav = qs("#statusQuickNav");
      if (!quickNav) {
        return;
      }
      quickNav.innerHTML = "";
      var firstCardByCategory = {};
      cards.forEach(function (card) {
        var category = card.dataset.statusCategory || "other";
        if (!firstCardByCategory[category]) {
          firstCardByCategory[category] = card;
        }
      });

      Object.keys(firstCardByCategory).forEach(function (category) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "button is-small is-light status-quicknav-btn";
        button.innerHTML =
          "<span class='status-quicknav-icon' aria-hidden='true'>" + statusCategoryIconSvg(category) + "</span>" +
          "<span class='status-quicknav-label'>" + statusCategoryLabel(category) + "</span>";
        button.addEventListener("click", function () {
          focusCard(firstCardByCategory[category]);
        });
        quickNav.appendChild(button);
      });
    }

    var basicButton = qs("#statusViewBasic");
    var allButton = qs("#statusViewAll");
    if (basicButton) {
      basicButton.addEventListener("click", function () {
        setMode("basic");
      });
    }
    if (allButton) {
      allButton.addEventListener("click", function () {
        setMode("all");
      });
    }

    var filterInput = qs("#statusFilterInput");
    if (filterInput && filterInput.dataset.bound !== "1") {
      filterInput.dataset.bound = "1";
      filterInput.addEventListener("input", applyFilter);
      filterInput.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          filterInput.value = "";
          applyFilter();
        }
      });
    }

    buildQuickNav();
    setMode("basic");
  }

  function initStatusPage() {
    var forms = [
      "formPerformanceProfile",
      "formWebMode",
      "formResolution",
      "formRtspPreset",
      "formRtspQualityProfile",
      "formClientProfilePreset",
      "formKnownGoodSave",
      "formKnownGoodRestore",
      "formStreamTopology",
      "formOnvifPolicy",
      "formSetupWizard",
      "formAdvancedTuning",
      "formRebootSchedule",
      "formMqttConfig",
      "formHomeAssistantPair",
      "tzForm",
      "passwordForm",
      "allPasswordForm",
      "telnetForm",
      "ftpForm",
      "formISPPro",
      "formSoundDetection",
      "formRecording",
      "formMotionDetection",
      "formTimelapse",
      "formaudioin",
    ];

    forms.forEach(function (id) {
      var form = qs("#" + id);
      if (form) {
        bindAjaxForm(form, true);
      }
    });

    initServiceTrimToggle();
    initImageFlipToggle();
    initRtspLogToggle();
    initThemePicker();
    initMemoryPurge();
    initWebModeForm();
    initCopyTargets();
    initIntegrationPack();
    initIntegrationSelfTest();
    initEmbeddedSettingsPanels();
    setupStatusDensityControls();

    window.scheduleStatusReload = scheduleStatusReload;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initStatusPage);
  } else {
    initStatusPage();
  }
})();
