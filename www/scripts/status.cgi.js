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

  function loadEmbeddedPanel(hostSelector, url) {
    var host = qs(hostSelector);
    if (!host) {
      return Promise.resolve();
    }
    return fetch(url, { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (html) {
        host.innerHTML = html;
        executeEmbeddedScripts(host);
        setupStatusDensityControls();
      })
      .catch(function (e) {
        console.error(e);
        host.innerHTML = "<p>Failed to load panel.</p>";
      });
  }

  function initEmbeddedSettingsPanels() {
    loadEmbeddedPanel("#embeddedServices", "cgi-bin/scripts.cgi");
    loadEmbeddedPanel("#embeddedCamControls", "cgi-bin/camcontrols.cgi?cmd=getsettings");
    loadEmbeddedPanel("#embeddedSysUsageInfo", "cgi-bin/sysusageinfo.cgi");
    loadEmbeddedPanel("#embeddedDeviceInfo", "cgi-bin/devinfo.cgi");
    loadEmbeddedPanel("#embeddedNetworkInfo", "cgi-bin/network.cgi");
    loadEmbeddedPanel("#embeddedDiskInfo", "cgi-bin/disk.cgi");
    loadEmbeddedPanel("#embeddedLogs", "logs.html");
  }

  function statusCardTitle(card) {
    var titleNode = card.querySelector(".card-header-title");
    return titleNode ? titleNode.textContent.trim() : "";
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
      "HTTP/RTSP/Telnet Password": true,
      "Video Settings": true,
      "RTSP stream address": true,
    };

    cards.forEach(function (card) {
      var title = statusCardTitle(card);
      var isBasic = !!basicTitles[title];
      var header = card.querySelector(".card-header");
      card.dataset.statusGroup = isBasic ? "basic" : "advanced";
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
    if (!firstCard || qs("#statusViewMode")) {
      return;
    }

    var controls = document.createElement("div");
    controls.id = "statusViewMode";
    controls.className = "status-view-mode";
    controls.innerHTML =
      "<span class='status-view-mode-label'>Settings view</span>" +
      "<button id='statusViewBasic' class='button is-small is-link is-outlined' type='button'>Basic</button>" +
      "<button id='statusViewAll' class='button is-small is-link is-outlined' type='button'>All</button>";
    firstCard.parentNode.insertBefore(controls, firstCard);

    function setMode(mode) {
      var showAll = mode === "all";
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

    setMode("basic");
  }

  function initStatusPage() {
    var forms = [
      "formResolution",
      "formRtspPreset",
      "formStreamTopology",
      "formOnvifPolicy",
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
      "formAudio",
      "formDayNight",
      "formPtt",
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
