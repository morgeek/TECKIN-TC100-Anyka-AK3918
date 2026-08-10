function saveCamControls() {
  var prefix = "camcontrol_";
  var enabled = [];
  Array.prototype.slice.call(document.querySelectorAll("input[type=checkbox]")).forEach(function (cb) {
    if (cb.id && cb.id.indexOf(prefix) === 0 && cb.checked) {
      enabled.push(cb.id.slice(prefix.length));
    }
  });

  var submit = document.getElementById("saveCamControlsBtn");
  if (submit) {
    submit.classList.add("is-loading");
    submit.disabled = true;
  }

  // Use csrfFetch so the X-CSRF-Token header is attached — camcontrols.cgi
  // enforces CSRF on `setsettings`, so a plain fetch was rejected with 403.
  var doFetch = (window.EliteUI && window.EliteUI.csrfFetch) ? window.EliteUI.csrfFetch : fetch;
  doFetch("cgi-bin/camcontrols.cgi", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "cmd=setsettings&controls=" + encodeURIComponent(enabled.join(" ")),
  })
    .then(function (r) {
      // Check r.ok — previously any HTTP error (403/500) still fell through to
      // updateCameraControls and the UI silently reported success.
      if (!r || !r.ok) {
        if (window.showResult) {
          window.showResult("Failed to save camera controls" + (r ? " (" + r.status + ")" : ""), "is-danger");
        }
        return;
      }
      if (window.showResult) { window.showResult("Camera controls saved", "is-success"); }
      if (window.updateCameraControls) {
        try {
          window.updateCameraControls();
        } catch (e) {
          console.log(e);
        }
      }
    })
    .catch(function (e) {
      console.error(e);
      if (window.showResult) { window.showResult("Error saving camera controls", "is-danger"); }
    })
    .finally(function () {
      if (submit) {
        submit.classList.remove("is-loading");
        submit.disabled = false;
      }
    });
}
