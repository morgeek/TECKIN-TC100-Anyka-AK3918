  // --- Small charts for the dashboard: inline SVG, no library ---
  // A series is a list of [t, value] pairs (t in ms). Gaps longer than
  // `gapMs` break the line, so time without samples (page closed, camera
  // busy) shows as a hole instead of a straight line across it.

  function chartPaths(points, t0, t1, vmax, w, h, gapMs) {
    var line = "";
    var area = "";
    var seg = [];
    var span = Math.max(1, t1 - t0);
    function flush() {
      if (!seg.length) return;
      var d = "M" + seg.join("L");
      line += d;
      area += d + "L" + seg[seg.length - 1].split(",")[0] + "," + h + "L" + seg[0].split(",")[0] + "," + h + "Z";
      seg = [];
    }
    var prevT = null;
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p[0] < t0 || p[1] === null || isNaN(p[1])) continue;
      if (prevT !== null && p[0] - prevT > gapMs) flush();
      var x = ((p[0] - t0) / span) * w;
      var y = h - (Math.min(p[1], vmax) / vmax) * h;
      seg.push(x.toFixed(1) + "," + y.toFixed(1));
      prevT = p[0];
    }
    flush();
    return { line: line, area: area };
  }

  function niceMax(v) {
    if (!(v > 0)) return 1;
    var e = Math.pow(10, Math.floor(Math.log(v) / Math.LN10));
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      if (v <= steps[i] * e) return steps[i] * e;
    }
    return 10 * e;
  }

  // Sparkline for a stat tile: one series, filled, no axes.
  function drawSparkline(el, points, opts) {
    if (!el) return;
    opts = opts || {};
    var w = 120, h = 32;
    var now = opts.now || Date.now();
    var t0 = now - (opts.windowMs || 300000);
    var vmax = opts.max;
    if (!vmax) {
      vmax = 0;
      for (var i = 0; i < points.length; i++) if (points[i][0] >= t0 && points[i][1] > vmax) vmax = points[i][1];
      vmax = niceMax(vmax * 1.15);
    }
    var d = chartPaths(points, t0, now, vmax, w, h - 2, opts.gapMs || 20000);
    el.innerHTML = '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<path class="spark-area" d="' + d.area + '"/><path class="spark-line" d="' + d.line + '"/></svg>';
  }

  // Area chart for a dashboard card: several series, horizontal grid,
  // the top value on the left and the time span under the chart.
  function drawAreaChart(el, series, opts) {
    if (!el) return;
    opts = opts || {};
    var w = 600, h = 150;
    var now = opts.now || Date.now();
    var windowMs = opts.windowMs || 300000;
    var t0 = now - windowMs;
    var vmax = opts.max;
    if (!vmax) {
      vmax = 0;
      series.forEach(function (s) {
        s.points.forEach(function (p) { if (p[0] >= t0 && p[1] > vmax) vmax = p[1]; });
      });
      vmax = niceMax(vmax * 1.1);
    }
    var fmt = opts.format || function (v) { return String(Math.round(v)); };
    var svg = '<svg viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" aria-hidden="true">';
    for (var g = 1; g <= 3; g++) {
      var gy = (h * g / 4).toFixed(1);
      svg += '<line class="chart-grid" x1="0" x2="' + w + '" y1="' + gy + '" y2="' + gy + '"/>';
    }
    series.forEach(function (s, i) {
      var d = chartPaths(s.points, t0, now, vmax, w, h, opts.gapMs || 20000);
      svg += '<path class="chart-area s' + i + '" d="' + d.area + '"/><path class="chart-line s' + i + '" d="' + d.line + '"/>';
    });
    svg += "</svg>";
    el.innerHTML = '<div class="chart-plot">' + svg +
      '<span class="chart-ymax">' + fmt(vmax) + '</span><span class="chart-ymid">' + fmt(vmax / 2) + "</span></div>" +
      '<div class="chart-x"><span>-' + Math.round(windowMs / 60000) + " min</span><span>now</span></div>";
  }

