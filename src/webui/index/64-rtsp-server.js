  // --- RTSP server card (Video tab): original or lite server, secondary
  // stream, two-way audio; status of the lite server (action.cgi?cmd=rtsp_server_info).
  function initRtspServer(form) {
    if (!form) return;
    var status = form.querySelector("#rtsp_server_status");
    fetch("cgi-bin/action.cgi?cmd=rtsp_server_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function(r) { if (!r.ok) throw new Error("rtsp_server_info"); return r.json(); })
      .then(function(d) {
        var sel = form.querySelector("#rtsp_server");
        if (sel) sel.value = d.server === "lite" ? "lite" : "vendor";
        var sub = form.querySelector("#rtsp_substream");
        if (sub) sub.checked = d.substream !== 0;
        var talk = form.querySelector("#rtsp_talk");
        if (talk) talk.checked = d.talk !== 0;
        if (!status) return;
        if (d.server !== "lite") { status.textContent = "The original server is in use."; return; }
        if (d.fallback) { status.textContent = "The lite server did not start: the original server has the port until the next reboot."; return; }
        if (d.clients === null || d.status_age === null || d.status_age > 30) { status.textContent = "Lite server: no status yet."; return; }
        status.textContent = "Lite server on port " + d.port + ": " + d.clients + " client(s), " + d.drops + " frame(s) skipped" +
          (d.audio && d.audio !== "none" ? ", sound " + d.audio.toUpperCase() : ", no sound") +
          (d.talk_state === "playing" ? ", someone is talking" : "") + ".";
      })
      .catch(function() { if (status) status.textContent = "RTSP server state could not be read."; });
  }
