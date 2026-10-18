  // --- Privacy masks (Image tab): draw up to 4 rectangles on a snapshot ---
  // Stored as MASK1..MASK4 = "x1,y1,x2,y2" in percent of the picture
  // (scripts/isp-tune.sh); the tuning thread in the video server turns them
  // into hardware masks (src/tc100fix/isp_tune.c).
  var MASK_MAX = 4;

  function parseMask(v) {
    var m = /^(\d{1,3}),(\d{1,3}),(\d{1,3}),(\d{1,3})$/.exec(v || "");
    if (!m) return null;
    var a = m.slice(1).map(function(n) { return Math.min(100, parseInt(n, 10)); });
    return a[2] > a[0] && a[3] > a[1] ? a : null;
  }

  function initPrivacyMasks(form, conf) {
    var editor = form.querySelector("#mask_editor");
    if (!editor) return;
    var img = editor.querySelector("#mask_preview");
    var layer = editor.querySelector("#mask_layer");
    var count = form.querySelector("#mask_count");
    var masks = [];
    for (var i = 1; i <= MASK_MAX; i++) {
      var m = parseMask(conf["MASK" + i]);
      if (m) masks.push(m);
    }
    var color = form.querySelector("#isp_mask_color");
    if (color) color.value = conf.MASK_COLOR || "black";

    function sync() {
      for (var k = 1; k <= MASK_MAX; k++) {
        var input = form.querySelector('[name="isp_mask' + k + '"]');
        if (input) input.value = masks[k - 1] ? masks[k - 1].join(",") : "";
      }
      if (count) count.textContent = masks.length + " / " + MASK_MAX;
    }

    function render(draft) {
      layer.textContent = "";
      masks.concat(draft ? [draft] : []).forEach(function(m, idx) {
        var box = document.createElement("div");
        box.className = "mask-box" + (m === draft ? " is-draft" : "");
        box.style.left = m[0] + "%"; box.style.top = m[1] + "%";
        box.style.width = (m[2] - m[0]) + "%"; box.style.height = (m[3] - m[1]) + "%";
        if (m !== draft) {
          var del = document.createElement("button");
          del.type = "button"; del.className = "mask-del"; del.textContent = "×";
          del.setAttribute("aria-label", "Remove this mask");
          del.addEventListener("pointerdown", function(e) { e.stopPropagation(); });
          del.addEventListener("click", function(e) {
            e.stopPropagation(); masks.splice(idx, 1); sync(); render();
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
        editor._sync(); editor._render();
      });
      var clear = form.querySelector("#mask_clear");
      if (clear) clear.addEventListener("click", function() { editor._masks.length = 0; editor._sync(); editor._render(); });
      var reload = form.querySelector("#mask_reload");
      if (reload) reload.addEventListener("click", function() { img.src = "cgi-bin/currentpic.cgi?_=" + Date.now(); });
    }
    // The handlers bound once above read the current list through the editor.
    editor._masks = masks; editor._sync = sync; editor._render = render;
    img.src = "cgi-bin/currentpic.cgi?_=" + Date.now();
    sync(); render();
  }
