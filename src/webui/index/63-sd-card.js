  // --- SD card question (flash mode): index.html #sd_modal ---
  // state.cgi's status line carries sd_prompt (the card's id) while a card
  // put in has not been answered for; action.cgi sd_card_* does the work
  // (scripts/sd-card.sh). Texts live in the HTML so the dictionary
  // translates them; this only toggles them.
  var sdPromptSeen = {};
  function sdFreeWord() { var w = byId("sd_free_word"); return w ? w.textContent : "free"; }


  function sdModalEls() {
    var m = byId("sd_modal");
    if (!m) return null;
    return { m: m, size: byId("sd_modal_size"), prog: byId("sd_modal_progress"), err: byId("sd_modal_err"),
             rec: byId("sd_modal_rec"), fmt: byId("sd_modal_format"), later: byId("sd_modal_later") };
  }

  function sdShowFormatState(e, state, msg) {
    e.prog.hidden = !state;
    Array.prototype.forEach.call(e.prog.querySelectorAll("[data-fmt]"), function (s) {
      s.hidden = s.getAttribute("data-fmt") !== state;
    });
    e.err.textContent = state === "error" ? (msg || "") : "";
  }

  function sdFillModal(e, d) {
    e.m.setAttribute("data-kind", d.kind || "blank");
    e.m.dataset.cardId = d.id || "";
    var gb = function (mb) { return (mb / 1024).toFixed(mb >= 10240 ? 0 : 1) + " GB"; };
    e.size.textContent = d.size_mb ? gb(d.size_mb) + (d.free_mb !== null && d.mounted ? " · " + gb(d.free_mb) + " " + sdFreeWord() : "") : "";
    e.rec.hidden = !(d.kind === "data" || d.kind === "empty");
    e.fmt.hidden = d.kind === "errors" || d.format_state === "running";
  }

  function sdAck(e) {
    var id = e.m.dataset.cardId;
    if (!id) return Promise.resolve();
    return csrfFetch("cgi-bin/action.cgi?cmd=sd_card_ack&format=json&id=" + encodeURIComponent(id), { method: "POST" })
      .catch(function () {});
  }

  function sdCloseModal(e) { e.m.hidden = true; }

  function sdPollFormat(e) {
    fetch("cgi-bin/action.cgi?cmd=sd_card_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.format_state === "running") { setTimeout(function () { sdPollFormat(e); }, 3000); return; }
        sdFillModal(e, d);
        sdShowFormatState(e, d.format_state === "done" ? "done" : "error", d.format_msg);
        if (d.format_state === "done") sdAck(e);
      })
      .catch(function () { setTimeout(function () { sdPollFormat(e); }, 5000); });
  }

  function sdBind(e) {
    if (e.m.dataset.bound) return;
    e.m.dataset.bound = "1";
    e.later.addEventListener("click", function () { sdAck(e).then(function () { sdCloseModal(e); }); });
    e.rec.addEventListener("click", function () {
      sdAck(e).then(function () {
        sdCloseModal(e);
        loadOnPageTarget("settings.html", function () {
          if (typeof window.tc100SettingsTab === "function") window.tc100SettingsTab("tab-record");
        });
      });
    });
    e.fmt.addEventListener("click", function () {
      var q = byId("sd_confirm_text");
      if (!window.confirm(q ? q.textContent : "Format?")) return;
      e.fmt.hidden = true; e.rec.hidden = true;
      sdShowFormatState(e, "running");
      csrfFetch("cgi-bin/action.cgi?cmd=sd_card_format&format=json", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) { setTimeout(function () { sdPollFormat(e); }, 3000); return; }
          sdShowFormatState(e, "error", (d && (d.message || d.error)) || "");
          e.fmt.hidden = false;
        })
        .catch(function () { sdShowFormatState(e, "error", ""); e.fmt.hidden = false; });
    });
  }

  function openSdModal(d) {
    var e = sdModalEls();
    if (!e || !d || !d.present) return;
    sdBind(e);
    sdFillModal(e, d);
    sdShowFormatState(e, d.format_state === "running" ? "running" : "");
    e.m.hidden = false;
  }

  // From the status line poll (40-polling.js).
  function sdCardPrompt(st) {
    if (!st || st.storage !== "flash" || !st.sd_prompt || sdPromptSeen[st.sd_prompt]) return;
    sdPromptSeen[st.sd_prompt] = 1;
    fetch("cgi-bin/action.cgi?cmd=sd_card_info&format=json&_=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(openSdModal)
      .catch(function () { delete sdPromptSeen[st.sd_prompt]; });
  }
  // For Settings → Recording (settings.html is loaded into this page).
  if (typeof window !== "undefined") {
    window.tc100SdFreeWord = sdFreeWord;
    window.tc100OpenSdModal = function () {
      fetch("cgi-bin/action.cgi?cmd=sd_card_info&format=json&_=" + Date.now(), { cache: "no-store" })
        .then(function (r) { return r.json(); }).then(openSdModal).catch(function () {});
    };
  }
