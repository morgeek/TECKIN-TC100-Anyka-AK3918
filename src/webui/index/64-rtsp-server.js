  // --- RTSP server card (Video tab): the secondary stream switch and the clients of tc100_rtsp
  // (action.cgi?cmd=rtsp_server_info).
  function initRtspServer(form) {
    if (!form) return;
    var status = form.querySelector("#rtsp_server_status");
    fetch("cgi-bin/action.cgi?cmd=rtsp_server_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function(r) { if (!r.ok) throw new Error("rtsp_server_info"); return r.json(); })
      .then(function(d) {
        var sub = form.querySelector("#rtsp_substream");
        if (sub) sub.checked = d.substream !== 0;
        if (status) status.textContent = "Free server tc100_rtsp on port " + d.port + ": " + (d.clients === null ? "?" : d.clients) + " client(s) connected.";
      })
      .catch(function() { if (status) status.textContent = "RTSP server state could not be read."; });
  }
