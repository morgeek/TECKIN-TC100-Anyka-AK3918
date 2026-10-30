  // --- Helpers: result messages, menu padding, cookies, CSRF token and fetch ---
  var resultToastTimer = 0;
  function showResult(txt, cls) {
    var toast = byId("result_toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "result_toast";
      toast.style.position = "fixed";
      toast.style.right = "1rem";
      toast.style.bottom = "1rem";
      toast.style.maxWidth = "80vw";
      toast.style.zIndex = "1200";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      toast.style.padding = "0.55rem 0.8rem";
      toast.style.borderRadius = "10px";
      toast.style.color = "#fff";
      toast.style.fontSize = "0.9rem";
      toast.style.boxShadow = "0 10px 24px rgba(0,0,0,0.28)";
      document.body.appendChild(toast);
    }
    var bg = "rgba(21, 31, 43, 0.92)";
    if (cls === "is-success") bg = "rgba(24, 110, 60, 0.95)";
    else if (cls === "is-danger") bg = "rgba(160, 30, 40, 0.95)";
    else if (cls === "is-warning") bg = "rgba(150, 100, 10, 0.95)";
    toast.style.background = bg;
    toast.textContent = String(txt || "");
    toast.style.display = "block";
    // A newer message restarts the delay: the old timer used to hide it early.
    if (resultToastTimer) clearTimeout(resultToastTimer);
    resultToastTimer = setTimeout(function () { resultToastTimer = 0; if (toast) toast.style.display = "none"; }, 2500);
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


  // Attach the current CSRF token as a header on state-changing requests to action.cgi.
  var csrfTokenRequest = null;
  function ensureCsrfToken() {
    if (csrfToken) return Promise.resolve(csrfToken);
    if (!csrfTokenRequest) {
      csrfTokenRequest = getStatusline(15000)
        .then(function(data) {
          if (!data || !data.csrf_token) throw new Error("Missing CSRF token");
          csrfToken = data.csrf_token;
          return csrfToken;
        }).finally(function() { csrfTokenRequest = null; });
    }
    return csrfTokenRequest;
  }

  function csrfFetch(url, opts) {
    opts = Object.assign({}, opts || {});
    opts.method = opts.method || "POST";
    return ensureCsrfToken().then(function(token) {
      var headers = new Headers(opts.headers || {});
      headers.set("X-CSRF-Token", token);
      opts.headers = headers;
      return fetch(url, opts);
    }).then(function(response) {
      if (!response.ok) throw new Error("Request failed (HTTP " + response.status + ")");
      return response;
    });
  }

  // Settings save contract: HTTP success alone never confirms application success.
