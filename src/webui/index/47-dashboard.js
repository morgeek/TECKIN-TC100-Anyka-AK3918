  // --- Home: Dashboard and Live views, dashboard polling and graphs ---
  // dash.cgi returns raw counters (CPU ticks, bytes on the Wi-Fi
  // interface…); the rates are computed here, so the camera only reads a few
  // /proc files. Samples are kept in this page for DASH_WINDOW_MS and are
  // only taken while the dashboard is on screen.
  var DASH_POLL_MS = 5000;
  var DASH_INFO_MS = 60000;
  var DASH_SNAP_MS = 10000;
  var DASH_WINDOW_MS = 300000;
  var homeNode = null;
  var homeView = "dashboard";
  var dashActive = false;
  var dashPrev = null;
  var dashInfoTs = 0;
  var dashFetching = false;
  var dashHist = { cpu: [], mem: [], wifi: [], rx: [], tx: [] };
  var dashLast = null;

  function dashPush(name, t, v) {
    var a = dashHist[name];
    a.push([t, v]);
    var cut = t - DASH_WINDOW_MS - DASH_POLL_MS;
    while (a.length && a[0][0] < cut) a.shift();
  }

  function fmtRate(kbps) {
    if (kbps === null || isNaN(kbps)) return "–";
    if (kbps >= 1000) return (kbps / 1000).toFixed(kbps >= 10000 ? 0 : 1) + " Mbit/s";
    return Math.round(kbps) + " kbit/s";
  }

  function fmtUptime(s) {
    s = Math.max(0, s | 0);
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    return m + "m";
  }

  function fmtKb(kb) {
    if (!(kb > 0)) return "0";
    if (kb >= 1048576) return (kb / 1048576).toFixed(1) + " GB";
    if (kb >= 1024) return (kb / 1024).toFixed(kb >= 10240 ? 0 : 1) + " MB";
    return kb + " KB";
  }

  function setText(id, text) {
    var el = byId(id);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function dashSample(d) {
    var t = Date.now();
    var cpu = null, rx = null, tx = null;
    if (dashPrev && d.cpu && dashPrev.cpu) {
      var tot = 0, ptot = 0;
      for (var i = 0; i < d.cpu.length; i++) { tot += d.cpu[i]; ptot += dashPrev.cpu[i] || 0; }
      var idle = d.cpu[3] + (d.cpu[4] || 0), pidle = dashPrev.cpu[3] + (dashPrev.cpu[4] || 0);
      var dt = tot - ptot;
      if (dt > 0) cpu = Math.max(0, Math.min(100, 100 * (dt - (idle - pidle)) / dt));
      var secs = (t - dashPrev.t) / 1000;
      if (secs > 0 && d.net && dashPrev.net) {
        var drx = d.net[0] - dashPrev.net[0], dtx = d.net[1] - dashPrev.net[1];
        if (drx >= 0) rx = (drx * 8) / 1000 / secs;   // kbit/s
        if (dtx >= 0) tx = (dtx * 8) / 1000 / secs;
      }
    }
    var mem = null;
    if (d.mem && d.mem[0] > 0) mem = 100 * (d.mem[0] - d.mem[1] - d.mem[2] - d.mem[3]) / d.mem[0];
    var wifi = d.wifi && typeof d.wifi[0] === "number" ? Math.min(100, d.wifi[0]) : null;
    if (cpu !== null) dashPush("cpu", t, cpu);
    if (mem !== null) dashPush("mem", t, mem);
    if (wifi !== null) dashPush("wifi", t, wifi);
    if (rx !== null) dashPush("rx", t, rx);
    if (tx !== null) dashPush("tx", t, tx);
    dashPrev = { t: t, cpu: d.cpu, net: d.net };
    dashLast = { d: d, cpu: cpu, mem: mem, wifi: wifi, rx: rx, tx: tx };
  }

  function renderDashTiles() {
    if (!dashLast) return;
    var d = dashLast.d, now = Date.now();
    setText("dt_cpu", dashLast.cpu === null ? "…" : Math.round(dashLast.cpu) + "%");
    setText("dt_cpu_sub", "load " + (d.load || "0"));
    if (dashLast.mem !== null) {
      setText("dt_mem", Math.round(dashLast.mem) + "%");
      var used = d.mem[0] - d.mem[1] - d.mem[2] - d.mem[3];
      setText("dt_mem_sub", fmtKb(used) + " / " + fmtKb(d.mem[0]));
    }
    setText("dt_wifi", dashLast.wifi === null ? "–" : dashLast.wifi + "%");
    var lvl = d.wifi && typeof d.wifi[1] === "number" ? d.wifi[1] : null;
    setText("dt_wifi_sub", lvl === null ? (d.iface || "") : lvl < 0 ? lvl + " dBm" : "strength " + lvl + "%");
    setText("dt_net", fmtRate(dashLast.tx));
    setText("dt_net_sub", "↓ " + fmtRate(dashLast.rx));
    setText("dt_up", fmtUptime(d.up));
    setText("dt_up_sub", d.rtsp_clients + (d.rtsp_clients === 1 ? " RTSP viewer" : " RTSP viewers"));
    var o = { now: now, windowMs: DASH_WINDOW_MS, gapMs: DASH_POLL_MS * 3 };
    drawSparkline(byId("ds_cpu"), dashHist.cpu, { now: now, windowMs: DASH_WINDOW_MS, gapMs: o.gapMs, max: 100 });
    drawSparkline(byId("ds_mem"), dashHist.mem, { now: now, windowMs: DASH_WINDOW_MS, gapMs: o.gapMs, max: 100 });
    drawSparkline(byId("ds_wifi"), dashHist.wifi, { now: now, windowMs: DASH_WINDOW_MS, gapMs: o.gapMs, max: 100 });
    drawSparkline(byId("ds_net"), dashHist.tx, o);
    drawAreaChart(byId("dc_net"), [{ points: dashHist.tx }, { points: dashHist.rx }],
      { now: now, windowMs: DASH_WINDOW_MS, gapMs: o.gapMs, format: fmtRate });
    drawAreaChart(byId("dc_sys"), [{ points: dashHist.cpu }, { points: dashHist.mem }],
      { now: now, windowMs: DASH_WINDOW_MS, gapMs: o.gapMs, max: 100, format: function (v) { return Math.round(v) + "%"; } });
    var health = d.sd_health || "";
    var hb = byId("dash_sd_health");
    if (hb) {
      hb.textContent = { ok: "healthy", unused: "not used", none: "no card", errors: "errors", readonly: "read-only", failing: "failing: replace it" }[health] || "–";
      hb.className = "dash-pill" + (health === "failing" || health === "readonly" ? " is-bad" : health === "errors" ? " is-warn" : health === "ok" ? " is-ok" : "");
    }
    setText("dash_updated", new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
  }

  function dashBar(id, used, total) {
    var el = byId(id);
    if (!el) return;
    var pct = total > 0 ? Math.min(100, Math.round(100 * used / total)) : 0;
    if (used > 0 && pct === 0) pct = 1;
    el.style.width = pct + "%";
    el.parentNode.classList.toggle("is-high", pct >= 90);
  }

  function renderDashInfo(i) {
    setText("di_host", i.hostname || "–");
    setText("di_ip", i.ip || "–");
    setText("di_mac", i.mac || "–");
    setText("di_fw", i.firmware || "–");
    setText("di_kernel", i.kernel || "–");
    setText("di_soc", i.soc || "–");
    setText("di_sensor", i.sensor || "–");
    setText("di_wifi", i.wifi_chip + (i.ssid ? " · " + i.ssid : ""));
    setText("di_mode", i.storage === "flash" ? "flash (no SD card needed)" : "SD card");
    ["main", "sub"].forEach(function (k) {
      var s = i[k] || {};
      setText("ds_" + k + "_codec", (s.codec || "–").toUpperCase());
      setText("ds_" + k + "_res", s.width && s.height ? s.width + "×" + s.height : "–");
      setText("ds_" + k + "_fps", s.fps ? s.fps + " fps" : "–");
      setText("ds_" + k + "_rate", s.kbps ? s.kbps + " kbit/s" : "–");
    });
    setText("ds_port", "RTSP port " + i.rtsp_port);
    var sd = i.sd || [0, 0];
    if (sd[0] > 0) {
      var sdpct = (100 * sd[1] / sd[0]);
      var sdpctStr = sdpct > 0 && sdpct < 0.1 ? "< 0.1%" : (sdpct < 10 ? sdpct.toFixed(1) + "%" : Math.round(sdpct) + "%");
      setText("dst_sd", fmtKb(sd[1]) + " / " + fmtKb(sd[0]) + " (" + sdpctStr + ")");
      dashBar("dsb_sd", sd[1], sd[0]);
    } else {
      setText("dst_sd", "not mounted");
      dashBar("dsb_sd", 0, 0);
    }
    var fw = byId("dash_flash_wrap"), fb = byId("dsb_flash"), fl = byId("dsl_flash");
    if (fw && fb && fl && i.flash && i.flash.total_kb > 0 && Array.isArray(i.flash.parts)) {
      fw.hidden = false;
      var fpct = Math.round(100 * i.flash.used_kb / i.flash.total_kb);
      setText("dst_flash", fmtKb(i.flash.used_kb) + " / " + fmtKb(i.flash.total_kb) + " (" + fpct + "%)");
      var colors = { boot: "#6366f1", kernel: "#3b82f6", mac: "#a855f7", env: "#ec4899", initrd: "#06b6d4", stack: "#10b981", cfga: "#f59e0b", cfgb: "#d97706" };
      var segs = "", leg = "";
      i.flash.parts.forEach(function (p) {
        var c = colors[p.name] || "#64748b";
        var w = Math.max(1.5, (100 * p.size_kb / i.flash.total_kb)).toFixed(2);
        var u = p.size_kb > 0 ? Math.min(100, Math.round(100 * p.used_kb / p.size_kb)) : 100;
        var tip = p.name + ": " + fmtKb(p.used_kb) + " / " + fmtKb(p.size_kb) + " (" + u + "%)";
        segs += '<span class="dash-fseg" style="flex:' + w + ' 1 0%;--fseg-c:' + c + '" data-tip="' + tip + '"><i style="width:' + u + '%"></i></span>';
        if (p.size_kb >= 32) {
          leg += '<span><i style="background:' + c + '"></i>' + p.name + ' <small>' + fmtKb(p.used_kb) + '</small></span>';
        }
      });
      fb.innerHTML = segs;
      fl.innerHTML = leg;
    } else if (fw) {
      fw.hidden = true;
    }
  }

  function refreshDashInfo() {
    dashInfoTs = Date.now();
    fetch("cgi-bin/state.cgi?cmd=dashinfo&_=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("dashinfo " + r.status); return r.json(); })
      .then(renderDashInfo)
      .catch(function () { dashInfoTs = 0; });
  }

  function refreshDashSnapshot() {
    clearJob("dashSnap");
    if (!dashActive || document.hidden) return;
    var img = byId("dash_snap");
    var next = function () { clearJob("dashSnap"); timeoutJobs.dashSnap = setTimeout(refreshDashSnapshot, DASH_SNAP_MS); };
    if (!img) { next(); return; }
    // Wait for the picture (or its failure) before counting the delay: a slow
    // camera is not asked again while it is still sending the previous one.
    img.onload = img.onerror = next;
    img.src = liveViewSnapshotEndpoint + "?" + Date.now();
    timeoutJobs.dashSnap = setTimeout(refreshDashSnapshot, DASH_SNAP_MS * 3);   // safety net if neither event fires
  }

  function pollDashboard() {
    clearJob("dashPoll");
    if (!dashActive || document.hidden) return;
    if (Date.now() - dashInfoTs > DASH_INFO_MS) refreshDashInfo();
    if (dashFetching) return;
    dashFetching = true;
    fetch("cgi-bin/dash.cgi?_=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("dash " + r.status); return r.json(); })
      .then(function (d) {
        dashSample(d);
        renderDashTiles();
        var box = byId("view_dashboard");
        if (box) box.classList.remove("is-stale");
      })
      .catch(function () {
        var box = byId("view_dashboard");
        if (box) box.classList.add("is-stale");
      })
      .finally(function () {
        dashFetching = false;
        if (dashActive && !document.hidden) timeoutJobs.dashPoll = setTimeout(pollDashboard, DASH_POLL_MS);
      });
  }

  function startDashboard() {
    if (dashActive) return;
    dashActive = true;
    // Counters older than a poll or two give a misleading first rate.
    if (dashPrev && Date.now() - dashPrev.t > DASH_POLL_MS * 3) dashPrev = null;
    renderDashTiles();
    pollDashboard();
    refreshDashSnapshot();
  }

  function stopDashboard() {
    dashActive = false;
    clearJob("dashPoll");
    clearJob("dashSnap");
  }

  function setHomeNavActive(view) {
    Array.prototype.slice.call(document.querySelectorAll("#common_nav [data-home-view]")).forEach(function (node) {
      node.classList.toggle("is-active", view !== null && node.dataset.homeView === view);
    });
  }

  function setHash(hash) {
    try {
      if (window.location.hash !== hash) window.history.replaceState(null, "", hash || window.location.pathname);
    } catch (e) {}
  }

  // Back to the home page (Dashboard or Live) without asking the camera for
  // anything: the home node is kept aside while other pages are shown.
  function showHome(view) {
    var content = byId("content");
    if (!homeNode) homeNode = byId("home_view");
    if (!content || !homeNode) return;
    view = view === "live" ? "live" : "dashboard";
    if (homeNode.parentNode !== content) {
      if (contentLoadController) contentLoadController.abort();
      content.innerHTML = "";
      content.appendChild(homeNode);
      currentContentTarget = "";
      setActiveOnPageTarget("");
      setContentLoading(false);
    }
    homeView = view;
    var dash = byId("view_dashboard"), live = byId("view_live");
    if (dash) dash.hidden = view !== "dashboard";
    if (live) live.hidden = view !== "live";
    setHomeNavActive(view);
    setHash("#" + view);
    if (view === "dashboard") startDashboard(); else stopDashboard();
    if (view === "live" && canRefreshLiveImageNow()) scheduleRefreshLiveImage(100);
    if (view === "live") refreshCamPanel();
    window.scrollTo(0, 0);
  }

  // Called before another page replaces the content area.
  function leaveHome() {
    var content = byId("content");
    if (!homeNode) homeNode = byId("home_view");
    stopDashboard();
    liveVideoStop();   // the video element is about to leave the page: close the stream while it can still be found
    setHomeNavActive(null);
    if (content && homeNode && homeNode.parentNode === content) content.removeChild(homeNode);
  }

  document.addEventListener("visibilitychange", function () {
    if (!dashActive) return;
    if (document.hidden) { clearJob("dashPoll"); clearJob("dashSnap"); }
    else { pollDashboard(); refreshDashSnapshot(); }
  });

