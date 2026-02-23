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

  function scheduleStatusReload(delay) {
    var reloadDelay = delay || 5000;
    if (window._srScheduled) {
      return;
    }
    window._srScheduled = true;
    setTimeout(function () {
      var content = document.getElementById("content");
      if (!content) {
        window._srScheduled = false;
        return;
      }
      fetch("cgi-bin/status.cgi", { cache: "no-store" })
        .then(function (r) {
          return r.text();
        })
        .then(function (html) {
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
      case "Day/Night auto detection":
      case "OSD Display":
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
        iconSpan.innerHTML = statusCategoryIconSvg(category);
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
      "formOSD",
      "formRecording",
      "formMotionDetection",
      "formTimelapse",
      "formaudioin",
      "formDayNight",
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
    initWebModeForm();
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
