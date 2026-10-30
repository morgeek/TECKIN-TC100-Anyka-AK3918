  // --- RTSP server card (Video tab): the secondary stream and two-way audio switches, and the clients of
  // tc100_rtsp (action.cgi?cmd=rtsp_server_info).
  function initRtspServer(form) {
    if (!form) return;
    var status = form.querySelector("#rtsp_server_status");
    fetch("cgi-bin/action.cgi?cmd=rtsp_server_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function(r) { if (!r.ok) throw new Error("rtsp_server_info"); return r.json(); })
      .then(function(d) {
        var sub = form.querySelector("#rtsp_substream");
        if (sub) sub.checked = d.substream !== 0;
        var talk = form.querySelector("#rtsp_talk");
        if (talk) talk.checked = d.talk !== 0;
        var idle = form.querySelector("#rtsp_idle_fps"), after = form.querySelector("#rtsp_idle_after"), warn = form.querySelector("#rtsp_idle_warn");
        if (idle) idle.value = String(d.idle_fps || 0);
        if (after) after.value = String(d.idle_after || 10);
        if (warn) warn.classList.toggle("is-hidden", !(d.idle_fps > 0 && d.motion_detection === 0));
        if (status) status.textContent = "Free server tc100_rtsp on port " + d.port + ": " + (d.clients === null ? "?" : d.clients) + " client(s) connected.";
      })
      .catch(function() { if (status) status.textContent = "RTSP server state could not be read."; });
  }
