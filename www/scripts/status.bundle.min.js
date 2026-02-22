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
        button.textContent = statusCategoryLabel(category);
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
      "formClientProfilePreset",
      "formStreamTopology",
      "formOnvifPolicy",
      "formAdvancedTuning",
      "formMqttConfig",
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
