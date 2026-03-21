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

  function removeRecord() {
    var date = selectedDate();
    var record = selectedRecord();
    if (!(date && record)) {
      return;
    }

    var file = buildRecordFile(date, record);
    if (!confirm("Want to delete file '" + file + "'?")) {
      return;
    }

    var removeBtn = byId("rmbtn");
    if (removeBtn) {
      removeBtn.disabled = true;
    }

    fetch("cgi-bin/viewrecords.cgi?cmd=remove_record&record=" + encodeURIComponent(file), { cache: "no-store" })
      .then(function () {
        var dateSet = recordsMap.get(date);
        if (dateSet) {
          dateSet.delete(record);
        }

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

  function init() {
    initNote();

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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
