  // --- Rectangles drawn on a snapshot: privacy masks (Image tab) and motion
  // zones (Detection tab), up to 4 each, "x1,y1,x2,y2" in percent.
  //   masks: MASK1..MASK4 (scripts/isp-tune.sh), hardware masks painted by
  //          the video server (src/tc100fix/isp_tune.c)
  //   zones: MDZ1..MDZ4 (/mnt/config/motion_zones.conf), areas the camera's
  //          motion detection ignores (src/tc100fix/md.c)
  var MASK_MAX = 4;

  function parseMask(v) {
    var m = /^(\d{1,3}),(\d{1,3}),(\d{1,3}),(\d{1,3})$/.exec(v || "");
    if (!m) return null;
    var a = m.slice(1).map(function(n) { return Math.min(100, parseInt(n, 10)); });
    return a[2] > a[0] && a[3] > a[1] ? a : null;
  }

  // o: { id: element id prefix ("mask" -> #mask_editor, #mask_preview,
  //      #mask_layer, #mask_count, #mask_clear, #mask_reload), field: hidden
  //      input name prefix ("isp_mask" -> isp_mask1..4), rects: initial
  //      values, boxClass: extra class of the drawn boxes, label: delete
  //      button label }
  function initRectEditor(form, o) {
    var editor = form.querySelector("#" + o.id + "_editor");
    if (!editor) return;
    var img = editor.querySelector("#" + o.id + "_preview");
    var layer = editor.querySelector("#" + o.id + "_layer");
    var count = form.querySelector("#" + o.id + "_count");
    var rects = [];
    (o.rects || []).forEach(function(v) { var m = parseMask(v); if (m && rects.length < MASK_MAX) rects.push(m); });

    // user: the change comes from the editor, so tell the form (unsaved-changes tracking)
    function sync(user) {
      var first = null;
      for (var k = 1; k <= MASK_MAX; k++) {
        var input = form.querySelector('[name="' + o.field + k + '"]');
        if (input) input.value = rects[k - 1] ? rects[k - 1].join(",") : "";
        if (!first) first = input;
      }
      if (user === true && first) first.dispatchEvent(new Event("input"));
      if (count) count.textContent = rects.length + " / " + MASK_MAX;
    }

    function render(draft) {
      layer.textContent = "";
      rects.concat(draft ? [draft] : []).forEach(function(m, idx) {
        var box = document.createElement("div");
        box.className = "mask-box" + (o.boxClass ? " " + o.boxClass : "") + (m === draft ? " is-draft" : "");
        box.style.left = m[0] + "%"; box.style.top = m[1] + "%";
        box.style.width = (m[2] - m[0]) + "%"; box.style.height = (m[3] - m[1]) + "%";
        if (m !== draft) {
          var del = document.createElement("button");
          del.type = "button"; del.className = "mask-del"; del.textContent = "×";
          del.setAttribute("aria-label", o.label || "Remove this mask");
          del.addEventListener("pointerdown", function(e) { e.stopPropagation(); });
          del.addEventListener("click", function(e) {
            e.stopPropagation(); rects.splice(idx, 1); sync(true); render();
          });
          box.appendChild(del);
        }
        layer.appendChild(box);
      });
    }

    function pct(e) {
      var r = layer.getBoundingClientRect();
      return [Math.max(0, Math.min(100, Math.round((e.clientX - r.left) * 100 / r.width))),
              Math.max(0, Math.min(100, Math.round((e.clientY - r.top) * 100 / r.height)))];
    }

    if (!editor.dataset.maskBound) {
      editor.dataset.maskBound = "1";
      var start = null;
      layer.addEventListener("pointerdown", function(e) {
        if (editor._masks.length >= MASK_MAX) return;
        start = pct(e); layer.setPointerCapture(e.pointerId); e.preventDefault();
      });
      layer.addEventListener("pointermove", function(e) {
        if (!start) return;
        var p = pct(e);
        editor._render([Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])]);
      });
      layer.addEventListener("pointerup", function(e) {
        if (!start) return;
        var p = pct(e), m = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
        start = null;
        if (m[2] - m[0] >= 2 && m[3] - m[1] >= 2) editor._masks.push(m);
        editor._sync(true); editor._render();
      });
      layer.addEventListener("pointercancel", function() { start = null; editor._render(); });
      var clear = form.querySelector("#" + o.id + "_clear");
      if (clear) clear.addEventListener("click", function() { editor._masks.length = 0; editor._sync(true); editor._render(); });
      var reload = form.querySelector("#" + o.id + "_reload");
      if (reload) reload.addEventListener("click", function() { img.src = "cgi-bin/currentpic.cgi?_=" + Date.now(); });
    }
    // The handlers bound once above read the current list through the editor.
    editor._masks = rects; editor._sync = sync; editor._render = render;
    img.src = "cgi-bin/currentpic.cgi?_=" + Date.now();
    sync(); render();
  }

  function initPrivacyMasks(form, conf) {
    var color = form.querySelector("#isp_mask_color");
    if (color) color.value = conf.MASK_COLOR || "black";
    initRectEditor(form, { id: "mask", field: "isp_mask",
      rects: [conf.MASK1, conf.MASK2, conf.MASK3, conf.MASK4] });
  }

  // Motion zones: read from action.cgi?cmd=md_zones_info, saved with the
  // detection form (conf_motiondetect).
  function initMotionZones(form) {
    if (!form || !form.querySelector("#mdz_editor")) return;
    var status = form.querySelector("#mdz_status");
    fetch("cgi-bin/action.cgi?cmd=md_zones_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function(r) { if (!r.ok) throw new Error("md_zones_info"); return r.json(); })
      .then(function(d) {
        initRectEditor(form, { id: "mdz", field: "md_zone", rects: d.zones || [], boxClass: "is-zone",
          label: "Remove this zone" });
        if (status) {
          var s = d.detector || {};
          if (!d.enabled) status.textContent = "The camera's motion detection is off (Services): zones apply when it is on.";
          else if (s.grid) status.textContent = "Applied: " + (s.ignored || 0) + " of the " + s.grid.replace("x", " × ") + " detection cells ignored.";
          else status.textContent = "";
        }
      })
      .catch(function() {
        initRectEditor(form, { id: "mdz", field: "md_zone", rects: [], boxClass: "is-zone", label: "Remove this zone" });
        if (status) status.textContent = "Motion zones could not be read.";
      });
  }
