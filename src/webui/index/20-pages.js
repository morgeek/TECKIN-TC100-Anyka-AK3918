  // --- Single-page navigation: loading Settings / Tools pages into the content area ---
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
        leaveHome();
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
        leaveHome();
        content.innerHTML = "<article class='message is-danger'><div class='message-header'><p>Page unavailable</p></div><div class='message-body'>The camera did not return this page. <button id='page_retry' class='button is-small' type='button'>Retry</button> <button id='page_logs' class='button is-small' type='button'>Open logs</button></div></article>";
        var retryButton = byId("page_retry");
        if (retryButton) retryButton.addEventListener("click", function () { loadOnPageTarget(target, onLoaded, true); });
        var logsButton = byId("page_logs");
        if (logsButton) logsButton.addEventListener("click", function () { loadOnPageTarget("logs.html", null, true); });
      })
      .finally(function () {
        setContentLoading(false);
      });
  }

