(function () {
  var recordsMap = new Map();
  var autoPlayEnabled = false;

  function byId(id) {
    return document.getElementById(id);
  }

  function safeParseArray(data) {
    try {
      var parsed = JSON.parse(data);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function setActionsEnabled(enabled) {
    var downloadBtn = byId("dwbtn");
    var removeBtn = byId("rmbtn");
    if (downloadBtn) {
      downloadBtn.disabled = !enabled;
    }
    if (removeBtn) {
      removeBtn.disabled = !enabled;
    }
  }

  function selectedDate() {
    var dateSelect = byId("dateselect");
    return dateSelect ? dateSelect.value : "";
  }

  function selectedRecord() {
    var recordSelect = byId("recordselect");
    return recordSelect ? recordSelect.value : "";
  }

  function buildRecordFile(date, record) {
    return date + "_" + record + ".mkv";
  }

  function buildRecordUrl(date, record) {
    return "/DCIM/" + buildRecordFile(date, record);
  }

  function autoPlayCheck(checkbox) {
    var player = byId("rpl");
    if (!player || !checkbox) {
      return;
    }
    autoPlayEnabled = !!checkbox.checked;
    if (autoPlayEnabled) {
      player.setAttribute("autoplay", "");
    } else {
      player.removeAttribute("autoplay");
    }
  }

  function onRecordChanged() {
    var date = selectedDate();
    var record = selectedRecord();
    var hasSelection = !!(date && record);
    setActionsEnabled(hasSelection);
    if (!hasSelection) {
      return;
    }

    var player = byId("rpl");
    if (!player) {
      return;
    }

    var source = document.createElement("source");
    source.src = buildRecordUrl(date, record);
    player.innerHTML = "";
    player.appendChild(source);
    try {
      player.load();
    } catch (e) {
      console.error(e);
    }
  }

  function setDateRecords(records) {
    var recordSelect = byId("recordselect");
    var recordSelectDiv = byId("recordselectdiv");
    if (!recordSelect) {
      return;
    }

    while (recordSelect.firstChild) {
      recordSelect.removeChild(recordSelect.firstChild);
    }

    records.forEach(function (record) {
      var opt = document.createElement("option");
      opt.value = record;
      opt.textContent = record;
      recordSelect.appendChild(opt);
    });

    if (recordSelectDiv) {
      recordSelectDiv.classList.remove("is-loading");
    }

    if (recordSelect.options.length > 0) {
      recordSelect.options[0].selected = true;
      onRecordChanged();
    } else {
      setActionsEnabled(false);
    }
  }

  function onDateChanged() {
    var date = selectedDate();
    var recordSelectDiv = byId("recordselectdiv");
    if (!date) {
      setActionsEnabled(false);
      return;
    }
    loadMotionTimeline(date);

    if (recordSelectDiv) {
      recordSelectDiv.classList.add("is-loading");
    }
    setActionsEnabled(false);

    var cached = recordsMap.get(date);
    if (cached && cached.size > 0) {
      setDateRecords(Array.prototype.slice.call(cached));
      return;
    }

    fetch("cgi-bin/viewrecords.cgi?cmd=list_records&date=" + encodeURIComponent(date), { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (data) {
        var allRecords = safeParseArray(data);
        var recordSet = new Set();
        allRecords.forEach(function (item) {
          if (item && item.record) {
            recordSet.add(item.record);
          }
        });
        recordsMap.set(date, recordSet);
        setDateRecords(Array.prototype.slice.call(recordSet));
      })
      .catch(function (e) {
        if (recordSelectDiv) {
          recordSelectDiv.classList.remove("is-loading");
        }
        console.error(e);
      });
  }

  function downloadRecord() {
    var date = selectedDate();
    var record = selectedRecord();
    if (!(date && record)) {
      return;
    }
    window.open(buildRecordUrl(date, record), "_blank");
  }

  function showRecordError(msg) {
    var note = byId("videonote");
    if (note) {
      note.textContent = msg;
      note.style.display = "";
    }
  }

  function clearRecordError() {
    var note = byId("videonote");
    if (note) {
      note.textContent = "";
      note.style.display = "none";
    }
  }

  function renderDiskUsage(data) {
    var wrap = byId("disk_usage_wrap");
    var bar = byId("disk_usage_bar");
    var label = byId("disk_usage_label");
    if (!wrap || !bar || !label) { return; }
    var pct = parseInt(data.percent, 10) || 0;
    var availMb = Math.round((data.avail_kb || 0) / 1024);
    var totalMb = Math.round((data.total_kb || 0) / 1024);
    bar.value = pct;
    bar.className = "progress " + (pct >= 90 ? "is-danger" : pct >= 70 ? "is-warning" : "is-info");
    label.textContent = availMb + " MB free of " + totalMb + " MB (" + pct + "% used)";
    wrap.style.display = "";
  }

  function loadDiskUsage() {
    fetch("cgi-bin/viewrecords.cgi?cmd=disk_usage", { cache: "no-store" })
      .then(function (r) { return r.text(); })
      .then(function (t) {
        try { renderDiskUsage(JSON.parse(t)); } catch (e) { /* ignore */ }
      })
      .catch(function () { /* non-critical */ });
  }

  function removeRecord() {
    var date = selectedDate();
    var record = selectedRecord();
    if (!(date && record)) {
      return;
    }

    var file = buildRecordFile(date, record);
    if (!confirm("Delete '" + file + "'? This cannot be undone.")) {
      return;
    }

    clearRecordError();
    var removeBtn = byId("rmbtn");
    if (removeBtn) {
      removeBtn.disabled = true;
    }

    fetch("cgi-bin/viewrecords.cgi?cmd=remove_record&record=" + encodeURIComponent(file), { cache: "no-store" })
      .then(function (r) { return r.text(); })
      .then(function (t) {
        var result = {};
        try { result = JSON.parse(t); } catch (e) { result = { ok: false, error: "Unexpected response" }; }
        if (result.ok === false) {
          showRecordError("Delete failed: " + (result.error || "unknown error"));
          return;
        }
        var dateSet = recordsMap.get(date);
        if (dateSet) {
          dateSet.delete(record);
        }
        loadDiskUsage();
        if (!dateSet || dateSet.size === 0) {
          recordsMap.delete(date);
          var dateSelect = byId("dateselect");
          if (dateSelect) {
            Array.prototype.slice.call(dateSelect.options).forEach(function (opt) {
              if (opt.value === date) {
                opt.parentNode.removeChild(opt);
              }
            });
          }
          onDateChanged();
        } else {
          setDateRecords(Array.prototype.slice.call(dateSet));
        }
      })
      .catch(function (e) {
        showRecordError("Delete request failed: " + e);
        console.error(e);
      })
      .finally(function () {
        if (removeBtn) {
          removeBtn.disabled = false;
        }
      });
  }

  function populateDates(dates) {
    var dateSelect = byId("dateselect");
    var dateSelectDiv = byId("dateselectdiv");
    if (!dateSelect) {
      return;
    }

    while (dateSelect.firstChild) {
      dateSelect.removeChild(dateSelect.firstChild);
    }

    dates.forEach(function (item) {
      if (!item || !item.date) {
        return;
      }
      var date = item.date;
      recordsMap.set(date, new Set());
      var opt = document.createElement("option");
      opt.value = date;
      opt.textContent = date;
      dateSelect.appendChild(opt);
    });

    if (dateSelectDiv) {
      dateSelectDiv.classList.remove("is-loading");
    }

    if (dateSelect.options.length > 0) {
      dateSelect.selectedIndex = dateSelect.options.length - 1;
      onDateChanged();
      return;
    }

    setActionsEnabled(false);
    var recordSelect = byId("recordselect");
    var autoplay = byId("autoplay");
    if (dateSelect) {
      dateSelect.disabled = true;
    }
    if (recordSelect) {
      recordSelect.disabled = true;
    }
    if (autoplay) {
      autoplay.disabled = true;
    }

    var player = byId("rpl");
    if (player) {
      var empty = document.createElement("div");
      empty.className = "notification is-info";
      empty.innerHTML = "No video records found.<br>Enable <strong>'Recording'</strong> service in settings to store video on MicroSD-card.";
      player.parentNode.replaceChild(empty, player);
    }
  }

  function initNote() {
    var note = byId("videonote");
    if (!note) {
      return;
    }
    var ua = navigator.userAgent || "";
    var isChromeFamily = /Chrome/.test(ua) && !/Edge|OPR/.test(ua);
    if (!isChromeFamily) {
      note.textContent = "Playback is most reliable in Chrome-family browsers.";
    }
  }

  function initAutoPlayAdvance() {
    var player = byId("rpl");
    if (!player) {
      return;
    }
    player.addEventListener("ended", function () {
      if (!autoPlayEnabled) {
        return;
      }
      var recordSelect = byId("recordselect");
      if (!recordSelect || recordSelect.selectedIndex < 0) {
        return;
      }
      var nextIndex = recordSelect.selectedIndex + 1;
      if (nextIndex < recordSelect.options.length) {
        recordSelect.selectedIndex = nextIndex;
        onRecordChanged();
      }
    });
  }

  var motionTimelineCollapsed = false;

  function toggleMotionTimeline() {
    var body = byId("motion_timeline_body");
    var icon = byId("motion_timeline_toggle_icon");
    if (!body) { return; }
    motionTimelineCollapsed = !motionTimelineCollapsed;
    body.style.display = motionTimelineCollapsed ? "none" : "";
    if (icon) { icon.innerHTML = motionTimelineCollapsed ? "&#9650;" : "&#9660;"; }
  }

  function buildDatePrefix(epochSec) {
    // Returns "YYYYMMDD" from a Unix timestamp — used to correlate events with record dates
    var d = new Date(epochSec * 1000);
    var y = d.getFullYear();
    var mo = ("0" + (d.getMonth() + 1)).slice(-2);
    var day = ("0" + d.getDate()).slice(-2);
    return "" + y + mo + day;
  }

  function formatEventTime(item) {
    if (item.time_utc) { return item.time_utc; }
    if (item.ts) {
      var d = new Date(item.ts * 1000);
      return d.toLocaleString();
    }
    return "";
  }

  function loadMotionTimeline(activeDate) {
    var list = byId("motion_timeline_list");
    if (!list) { return; }

    fetch("cgi-bin/motionevents.cgi?limit=80", { cache: "no-store" })
      .then(function (r) { return r.text(); })
      .then(function (t) {
        var data;
        try { data = JSON.parse(t); } catch (e) { data = { items: [] }; }
        var items = (data.items || []).slice().reverse(); // newest first

        while (list.firstChild) { list.removeChild(list.firstChild); }

        if (!items.length) {
          var empty = document.createElement("li");
          empty.style.cssText = "padding:0.5rem;color:#999;font-size:0.85em;";
          empty.textContent = "No motion events recorded.";
          list.appendChild(empty);
          return;
        }

        items.forEach(function (item) {
          if (item.type !== "motion_on" && item.type !== "motion_off") { return; }
          var li = document.createElement("li");
          li.className = "motion-timeline-item";
          var itemDate = item.ts ? buildDatePrefix(item.ts) : "";
          if (activeDate && itemDate === activeDate) { li.classList.add("is-selected"); }

          // Thumbnail
          if (item.snapshot) {
            var img = document.createElement("img");
            img.className = "motion-timeline-thumb";
            img.alt = "snapshot";
            img.src = item.snapshot;
            img.onerror = function () { this.style.display = "none"; };
            li.appendChild(img);
          }

          var info = document.createElement("div");
          info.className = "motion-timeline-info";

          var typeSpan = document.createElement("span");
          typeSpan.className = item.type === "motion_on" ? "motion-timeline-type-on" : "motion-timeline-type-off";
          typeSpan.textContent = item.type === "motion_on" ? "Motion ON" : "Motion OFF";
          info.appendChild(typeSpan);

          var timeDiv = document.createElement("div");
          timeDiv.className = "motion-timeline-time";
          timeDiv.textContent = formatEventTime(item);
          info.appendChild(timeDiv);

          li.appendChild(info);

          // Clicking navigates date selector to matching date
          if (itemDate) {
            li.addEventListener("click", function () {
              var dateSelect = byId("dateselect");
              if (!dateSelect) { return; }
              Array.prototype.slice.call(dateSelect.options).forEach(function (opt) {
                if (opt.value === itemDate) {
                  dateSelect.value = itemDate;
                  onDateChanged();
                }
              });
            });
          }

          list.appendChild(li);
        });
      })
      .catch(function () { /* non-critical */ });
  }

  function init() {
    initNote();
    loadDiskUsage();
    loadMotionTimeline("");

    var autoplay = byId("autoplay");
    if (autoplay) {
      autoplay.addEventListener("change", function () {
        autoPlayCheck(this);
      });
    }

    initAutoPlayAdvance();

    fetch("cgi-bin/viewrecords.cgi?cmd=list_dates", { cache: "no-store" })
      .then(function (r) {
        return r.text();
      })
      .then(function (data) {
        populateDates(safeParseArray(data));
      })
      .catch(function (e) {
        console.error(e);
      });
  }

  window.downloadRecord = downloadRecord;
  window.removeRecord = removeRecord;
  window.onDateChanged = onDateChanged;
  window.onRecordChanged = onRecordChanged;
  window.autoPlayCheck = autoPlayCheck;
  window.toggleMotionTimeline = toggleMotionTimeline;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
