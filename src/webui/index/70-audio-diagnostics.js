  // --- Talk volume and Diagnostics panel (stability chart, Frigate YAML) ---
  function initPttVolumeControls() {
    var vol = byId("ptt_vol");
    var lbl = byId("ptt_vol_label");
    if (!vol || !lbl) {
      return;
    }

    fetch("cgi-bin/action.cgi?cmd=get_ptt_vol", { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (t) {
        var v = parseInt(String(t || "").trim(), 10);
        if (!isNaN(v) && v >= 0 && v <= 100) {
          vol.value = v;
          lbl.textContent = v + "%";
        }
      })
      .catch(function () {});

    vol.addEventListener("input", function () {
      lbl.textContent = vol.value + "%";
    });
    vol.addEventListener("change", function () {
      csrfFetch("cgi-bin/action.cgi?cmd=conf_ptt&audiooutVol=" + encodeURIComponent(vol.value))
        .catch(function () {});
    });
  }

  function drawStabilityChart(csv, memTotal) {
    var canvas = byId("stability_chart");
    var legend = byId("stability_legend");
    if (!canvas || !canvas.getContext) return;
    var rows = String(csv || "").trim().split(/\r?\n/).slice(1).map(function (line) {
      var c = line.split(",");
      return { load: parseFloat(c[2]) || 0, mem: parseInt(c[3], 10) || 0, bad: parseInt(c[4], 10) || 0 };
    });
    if (!rows.length) { if (legend) legend.textContent = "The first sample appears after five minutes."; return; }
    var ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height, pad = 18;
    ctx.clearRect(0, 0, w, h);
    function plot(color, value) {
      ctx.beginPath();
      rows.forEach(function (row, i) {
        var x = pad + (rows.length === 1 ? 0 : i * (w - pad * 2) / (rows.length - 1));
        var y = h - pad - Math.max(0, Math.min(1, value(row))) * (h - pad * 2);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.stroke();
    }
    plot("#3b9ef5", function (r) { return Math.min(r.load / 2, 1); });
    plot("#25a66a", function (r) { return memTotal > 0 ? r.mem / memTotal : 0; });
    rows.forEach(function (row, i) {
      if (!row.bad) return;
      var x = pad + (rows.length === 1 ? 0 : i * (w - pad * 2) / (rows.length - 1));
      ctx.fillStyle = "#d64545"; ctx.fillRect(x - 2, 4, 4, h - 8);
    });
    if (legend) legend.textContent = rows.length + " samples · blue: load · green: available memory · red: incident";
  }

  function initDiagnosticsPanel() {
    var toggle = byId("diagnostics_toggle");
    var panel = byId("diagnostics_panel");
    if (!toggle || !panel) return;
    var loaded = false;
    toggle.addEventListener("click", function () {
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
      if (panel.hidden || loaded) return;
      loaded = true;
      Promise.all([
        fetch("cgi-bin/health.cgi", {cache:"no-store"}).then(function(r){return r.json();}),
        fetch("cgi-bin/stability.cgi", {cache:"no-store"}).then(function(r){return r.text();}),
        fetch("cgi-bin/state.cgi?cmd=frigateyaml&redact=1", {cache:"no-store"}).then(function(r){return r.text();})
      ]).then(function(data) {
        var health = data[0] || {}, services = health.services || {}, bad = 0;
        Object.keys(services).forEach(function(k){ if (services[k] === "unhealthy" || services[k] === "error") bad++; });
        var summary = byId("diagnostics_summary");
        if (summary) summary.textContent = bad ? bad + " service issue(s)" : "Core services healthy";
        var preview = byId("frigate_preview");
        if (preview) preview.textContent = data[2];
        drawStabilityChart(data[1], health.system ? health.system.mem_total_kb : 0);
      }).catch(function() {
        var summary = byId("diagnostics_summary");
        if (summary) summary.textContent = "Diagnostics unavailable";
        loaded = false;
      });
    });
    var copy = byId("copy_frigate");
    if (copy) copy.addEventListener("click", function () {
      var text = byId("frigate_preview") ? byId("frigate_preview").textContent : "";
      if (navigator.clipboard && text) navigator.clipboard.writeText(text).then(function(){ copy.textContent = "Copied"; setTimeout(function(){copy.textContent="Copy Frigate YAML";},1200); });
    });
  }

