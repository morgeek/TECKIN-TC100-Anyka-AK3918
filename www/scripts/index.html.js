(function () {
  var timeoutJobs = {};
  var contentLoadController = null;
  var liveFeedEnabled = true;
  var currentContentTarget = "";

  var LIVEVIEW_INTERVAL_VISIBLE_MS = 2000;
  var LIVEVIEW_INTERVAL_HIDDEN_MS = 10000;
  var SYSUSAGE_INTERVAL_VISIBLE_MS = 15000;
  var SYSUSAGE_INTERVAL_HIDDEN_MS = 60000;
  var AUTONIGHT_INTERVAL_VISIBLE_MS = 8000;
  var AUTONIGHT_INTERVAL_HIDDEN_MS = 20000;

  function byId(id) {
    return document.getElementById(id);
  }

  function byClass(cls) {
    return Array.prototype.slice.call(document.getElementsByClassName(cls));
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

  function closeNavDropdowns(exceptNode) {
    Array.prototype.slice.call(document.querySelectorAll("#nav_menu .navbar-item.has-dropdown")).forEach(function (node) {
      if (exceptNode && node === exceptNode) {
        return;
      }
      node.classList.remove("is-active");
    });
  }

  function initNavDropdownToggles() {
    Array.prototype.slice.call(document.querySelectorAll("#nav_menu .navbar-item.has-dropdown > .navbar-link")).forEach(function (toggle) {
      if (toggle.dataset.dropdownBound === "1") {
        return;
      }
      toggle.dataset.dropdownBound = "1";
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
        if (willOpen && dropdown.id === "camcontrol_link") {
          syncSwitchesTimeout(300);
        }
      });
    });
  }

  function loadOnPageTarget(target, onLoaded, forceReload) {
    var content = byId("content");
    if (!content || !target) {
      return;
    }
    var normalizedTarget = normalizeTarget(target);
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
    liveview.src = "cgi-bin/currentpic.cgi?" + Date.now();
  }

  function scheduleRefreshLiveImage(interval) {
    clearJob("refreshLiveImage");
    timeoutJobs.refreshLiveImage = setTimeout(refreshLiveImage, interval);
  }

  function refreshSysUsage() {
    var nextInterval = document.hidden ? SYSUSAGE_INTERVAL_HIDDEN_MS : SYSUSAGE_INTERVAL_VISIBLE_MS;
    fetch("cgi-bin/state.cgi?cmd=sysusage&uid=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (sysusage) {
        var usage = byId("sysusage");
        if (usage) {
          usage.textContent = sysusage;
          usage.classList.remove("usage-low", "usage-mid", "usage-high");
          var match = /CPU:\s*([0-9]{1,3})%/i.exec(sysusage);
          if (match) {
            var cpu = parseInt(match[1], 10);
            if (cpu > 80) {
              usage.classList.add("usage-high");
            } else if (cpu >= 50) {
              usage.classList.add("usage-mid");
            } else {
              usage.classList.add("usage-low");
            }
          }
        }
        scheduleRefreshSysUsage(nextInterval);
      })
      .catch(function () {
        scheduleRefreshSysUsage(nextInterval);
      });
  }

  function scheduleRefreshSysUsage(interval) {
    clearJob("refreshSysUsage");
    timeoutJobs.refreshSysUsage = setTimeout(refreshSysUsage, interval);
  }

  function refreshAutoNightLumAwb() {
    var nextInterval = document.hidden ? AUTONIGHT_INTERVAL_HIDDEN_MS : AUTONIGHT_INTERVAL_VISIBLE_MS;
    fetch("cgi-bin/state.cgi?cmd=lumawb&uid=" + Date.now(), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (data) {
        var lumAwb = data.split("\n");
        byClass("labelLum").forEach(function (node) {
          node.textContent = "Current: " + (lumAwb[0] || "");
        });
        byClass("labelAWB").forEach(function (node) {
          node.textContent = "Current: " + (lumAwb[1] || "");
        });
        scheduleRefreshAutoNightLumAwb(nextInterval);
      })
      .catch(function () {
        scheduleRefreshAutoNightLumAwb(nextInterval);
      });
  }

  function scheduleRefreshAutoNightLumAwb(interval) {
    clearJob("refreshAutoNightLumAwb");
    if (interval > 0) {
      timeoutJobs.refreshAutoNightLumAwb = setTimeout(refreshAutoNightLumAwb, interval);
    }
  }

  function syncSwitchesTimeout(millis) {
    clearJob("syncSwitches");
    timeoutJobs.syncSwitches = setTimeout(syncSwitches, millis);
  }

  function syncSwitches() {
    fetch("cgi-bin/camcontrols.cgi?cmd=getallstate", { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (data) {
        var switchesStateArray = parseJsonArray(data);
        switchesStateArray.forEach(function (switchState) {
          var e = byId(switchState.id);
          if (e) {
            e.checked = switchState.status && switchState.status.trim().toLowerCase() === "on";
          }
        });
      });
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

  function cameraControlClick(control) {
    var e = control;
    if (!e) {
      return;
    }
    e.disabled = true;
    var id = e.getAttribute("id");

    fetch("cgi-bin/camcontrols.cgi?cmd=getstate&control=" + encodeURIComponent(id), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (status) {
        var url = status.trim().toLowerCase() === "on" ? e.dataset.unchecked : e.dataset.checked;
        return fetch(url, { cache: "no-store" }).then(function () {
          e.checked = status.trim().toLowerCase() !== "on";
        });
      })
      .finally(function () {
        e.disabled = false;
        syncSwitchesTimeout(5000);
      });
  }

  function updateCameraControls() {
    fetch("cgi-bin/camcontrols.cgi?cmd=getcontrols", { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (data) {
        var camControlsArray = parseJsonArray(data);
        var container = byId("camcontrol_items");
        if (!container) {
          return;
        }

        container.innerHTML = "";
        camControlsArray.forEach(function (camControl) {
          var item = document.createElement("span");
          item.className = "navbar-item";

          var input = document.createElement("input");
          input.id = camControl.id;
          input.type = "checkbox";
          input.name = camControl.id;
          input.className = "switch";
          input.dataset.checked = "cgi-bin/camcontrols.cgi?cmd=on&control=" + encodeURIComponent(camControl.id);
          input.dataset.unchecked = "cgi-bin/camcontrols.cgi?cmd=off&control=" + encodeURIComponent(camControl.id);
          input.onclick = function () {
            cameraControlClick(this);
          };

          var label = document.createElement("label");
          label.setAttribute("for", camControl.id);
          label.textContent = camControl.name;

          item.appendChild(input);
          item.appendChild(document.createTextNode(" "));
          item.appendChild(label);
          container.appendChild(item);
        });

        syncSwitches();
      });
  }

  function pushToTalk(action) {
    var btn = byId("btn-ptt");
    if (!btn) {
      return;
    }

    var span = btn.querySelector("span");
    if (action === "on") {
      if (span) {
        span.style.color = "red";
        span.removeAttribute("onpointerdown");
      }
      btn.setAttribute("onpointerup", "pushToTalk('off')");
      if (window.startRecording) {
        window.startRecording();
      }
    } else {
      if (window.stopRecording) {
        window.stopRecording();
      }
      if (span) {
        span.style.color = "";
        span.removeAttribute("onpointerup");
      }
      btn.setAttribute("onpointerdown", "pushToTalk('on')");
    }
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

    updateCameraControls();

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

      var directTarget = event.target.closest(".direct");
      if (directTarget && directTarget.dataset.target) {
        window.location.href = directTarget.dataset.target;
        return;
      }

      var promptTarget = event.target.closest(".prompt");
      if (promptTarget && promptTarget.dataset.target) {
        if (confirm(promptTarget.dataset.message)) {
          window.location.href = promptTarget.dataset.target;
        }
      }
    });

    var camControlLink = byId("camcontrol_link");
    if (camControlLink) {
      camControlLink.addEventListener("mouseenter", function () {
        camControlLink.classList.add("is-active");
        syncSwitchesTimeout(500);
      });
      camControlLink.addEventListener("mouseleave", function () {
        camControlLink.classList.remove("is-active");
      });
    }

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
        if (willOpen) {
          syncSwitchesTimeout(500);
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

    Array.prototype.slice.call(document.querySelectorAll(".navbar-item")).forEach(function (node) {
      node.addEventListener("click", function () {
        var id = node.getAttribute("id");
        if (id && !node.classList.contains("has-dropdown")) {
          scheduleRefreshAutoNightLumAwb(id === "status" ? AUTONIGHT_INTERVAL_VISIBLE_MS : 0);
        }
      });
    });

    var liveview = byId("liveview");
    if (liveview) {
      liveview.onload = function () {
        if (liveFeedEnabled) {
          scheduleRefreshLiveImage(LIVEVIEW_INTERVAL_VISIBLE_MS);
        }
      };
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
      scheduleRefreshLiveImage(document.hidden ? LIVEVIEW_INTERVAL_HIDDEN_MS : LIVEVIEW_INTERVAL_VISIBLE_MS);
      scheduleRefreshSysUsage(document.hidden ? SYSUSAGE_INTERVAL_HIDDEN_MS : SYSUSAGE_INTERVAL_VISIBLE_MS);
    });

    fixMenuPadding();
    initNavDropdownToggles();
    refreshSysUsage();
  });

  window.addEventListener("resize", fixMenuPadding);

  window.refreshLiveImage = refreshLiveImage;
  window.scheduleRefreshLiveImage = scheduleRefreshLiveImage;
  window.refreshSysUsage = refreshSysUsage;
  window.scheduleRefreshSysUsage = scheduleRefreshSysUsage;
  window.refreshAutoNightLumAwb = refreshAutoNightLumAwb;
  window.scheduleRefreshAutoNightLumAwb = scheduleRefreshAutoNightLumAwb;
  window.syncSwitchesTimeout = syncSwitchesTimeout;
  window.syncSwitches = syncSwitches;
  window.showResult = showResult;
  window.fixMenuPadding = fixMenuPadding;
  window.setCookie = setCookie;
  window.getCookie = getCookie;
  window.setTheme = setTheme;
  window.getThemeChoice = getThemeChoice;
  window.cameraControlClick = cameraControlClick;
  window.updateCameraControls = updateCameraControls;
  window.pushToTalk = pushToTalk;
})();
