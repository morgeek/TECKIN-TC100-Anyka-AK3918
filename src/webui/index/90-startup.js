  // --- Page start-up, globals for sub-pages, loadInto ---
  document.addEventListener("DOMContentLoaded", function () {
    // "Operator mode" (removed in 1.8.4) only hid menus in this browser; drop
    // its saved state so no browser stays stuck with hidden menus.
    try { localStorage.removeItem("elite_operator_mode"); } catch (e) {}
    initPttVolumeControls();
    initCamPanel();

    // The page title, the brand and the OSD name come from the first status line poll (renderReadings, applyHostName):
    // no separate state.cgi?cmd=hostname request at load.

    document.addEventListener("click", function (event) {
      var homeTarget = event.target.closest("[data-home-view]");
      if (homeTarget) {
        event.preventDefault();
        showHome(homeTarget.dataset.homeView);
        if (window.innerWidth < 1024) closeNavMenu(); else closeNavDropdowns();
        return;
      }
      var onPageTarget = event.target.closest(".onpage");
      if (onPageTarget && onPageTarget.dataset.target) {
        event.preventDefault();
        // Settings sections open straight from the menu (data-tab); the page
        // is fetched only if it is not already on screen.
        var tab = onPageTarget.dataset.tab;
        loadOnPageTarget(onPageTarget.dataset.target, tab ? function () {
          if (typeof window.tc100SettingsTab === "function") window.tc100SettingsTab(tab);
        } : null, onPageTarget.dataset.forceReload === "1");
        if (onPageTarget.id) setHash("#" + onPageTarget.id);
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
          if (/[?&]cmd=logout\b/.test(promptTarget.dataset.target)) {
            // HTTP Basic auth has no server-side logout (action.cgi has no
            // "logout" command; the button did nothing). Replace the browser's
            // cached credentials with invalid ones, then reload to get the
            // login prompt again.
            var xhr = new XMLHttpRequest();
            xhr.open("GET", "cgi-bin/state.cgi?cmd=hostname&_=" + Date.now(), true, "logout", "logout");
            xhr.onloadend = function () { window.location.replace("./"); };
            xhr.send();
            return;
          }
          // Use csrfFetch so the CSRF token is sent as a header.
          var isReboot = /[?&]cmd=reboot/.test(promptTarget.dataset.target);
          csrfFetch(promptTarget.dataset.target, { cache: "no-store" })
            .then(function () {
              showResult(isReboot ? "Restarting: the camera is back in about a minute" : "Command sent to the camera", "is-success");
            })
            .catch(function (err) {
              // csrfFetch throws an Error for an HTTP failure (403, 500: refused) and a TypeError when
              // the connection dropped. For a reboot that usually means the camera is already going down.
              if (isReboot && err instanceof TypeError) showResult("The camera stopped answering: it is probably restarting", "is-warning");
              else showResult("The camera did not accept the command", "is-danger");
            });
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

    if (navbarBurger) {
      // The burger is a link without href: make it reachable and usable from the keyboard.
      navbarBurger.setAttribute("tabindex", "0");
      navbarBurger.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navbarBurger.click(); }
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      var menu = byId("nav_menu");
      if (menu && menu.classList.contains("is-active")) { closeNavMenu(); if (navbarBurger) navbarBurger.focus(); }
      else closeNavDropdowns();
    });

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

    initDiagnosticsPanel();

    initLiveViewVisibilityObserver();

    var liveview = byId("liveview");
    if (liveview) {
      // Instead of relying on a blind setInterval, we wait for the
      // previous image to finish loading before scheduling the next one.
      liveview.onload = function () {
        if (canRefreshLiveImageNow()) {
          scheduleRefreshLiveImage(liveViewVisibleIntervalMs);
        }
      };
      liveview.addEventListener("error", function () {
        if (!canRefreshLiveImageNow()) {
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
        if (canRefreshLiveImageNow()) {
          scheduleRefreshLiveImage(100);
        } else {
          clearJob("refreshLiveImage");
        }
        liveVideoSync();
      });
    }
    setLiveToggleButtonState();
    initLiveModeSwitch();

    statusRefreshButton = byId("status_refresh");
    statusUpdatedLabel = byId("status_updated");
    if (statusRefreshButton) {
      statusRefreshButton.addEventListener("click", function () {
        updateStatusRefreshUi("loading");
        refreshSysUsage();
      });
    }

    document.addEventListener("visibilitychange", function () {
      if (canRefreshLiveImageNow()) {
        scheduleRefreshLiveImage(150);
      } else {
        clearJob("refreshLiveImage");
      }
      liveVideoSync(); // video: closed while hidden (the camera stops encoding), opened again when shown
      if (document.hidden) {
        clearJob("refreshSysUsage");
        updateStatusRefreshUi("paused");
      } else {
        updateStatusRefreshUi("loading");
        scheduleRefreshSysUsage(0);
      }
    });

    // PTT and two-way audio is handled by ptt-audio.js module loaded separately

    fixMenuPadding();
    initNavDropdownToggles();
    refreshSysUsage();

    // #dashboard (default), #live, or the id of a menu entry (#status,
    // #nav_video, #logs…) to come back to the same page after a reload.
    var hash = document.location.hash;
    if (hash === "#nav_audio") hash = "#nav_video";   // the Audio section is now part of Streams & audio
    var hashTarget = null;
    if (hash && hash !== "#dashboard" && hash !== "#live" && /^#[A-Za-z][\w-]*$/.test(hash)) {
      hashTarget = document.querySelector(hash);
    }
    if (hashTarget && hashTarget.classList.contains("onpage")) {
      hashTarget.click();
    } else {
      showHome(hash === "#live" ? "live" : "dashboard");
    }
  });

  window.addEventListener("resize", fixMenuPadding);
  window.addEventListener("beforeunload", function () {
    liveVideoStop();
    if (liveViewVisibilityObserver) {
      liveViewVisibilityObserver.disconnect();
      liveViewVisibilityObserver = null;
    }
  });

  window.refreshLiveImage = refreshLiveImage;
  window.scheduleRefreshLiveImage = scheduleRefreshLiveImage;
  window.refreshSysUsage = refreshSysUsage;
  window.scheduleRefreshSysUsage = scheduleRefreshSysUsage;
  window.refreshPerformanceProfile = refreshPerformanceProfile;
  // Expose the live CSRF token to SPA sub-pages (backup.html, configeditor.html)
  // whose inline getCsrfToken() otherwise read the IIFE-local `csrfToken`, which
  // is out of their scope — so their X-CSRF-Token header was always empty and
  // config import / backup restore failed once CSRF is enforced.
  window.getCsrfToken = function () { return csrfToken; };
  window.ensureCsrfToken = ensureCsrfToken;
  window.showResult = showResult;
  window.fixMenuPadding = fixMenuPadding;
  window.setCookie = setCookie;
  window.getCookie = getCookie;

  // Global utility for sub-page scripts to check if they are still 'mounted'
  window.isHostStillActive = function (node) {
    return !!(node && node.parentNode && document.body.contains(node));
  };

  // Load a page fragment (CGI or .html) into an element and run its scripts,
  // like the main content area does (Settings → Network / Backup, Diagnostics).
  function loadInto(el, url) {
    if (!el || !url) return Promise.resolve();
    el.classList.add("content-loading");
    return fetch(cacheBustedUrl(url), { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error(url + " (" + r.status + ")");
        return r.text();
      })
      .then(function (html) {
        el.innerHTML = html;
        executeEmbeddedScripts(el);
      })
      .catch(function (e) {
        el.innerHTML = "<article class='message is-danger'><div class='message-body'>The camera did not return this part of the page.</div></article>";
        el.removeAttribute("data-loaded");
        console.log(e);
      })
      .finally(function () { el.classList.remove("content-loading"); });
  }

