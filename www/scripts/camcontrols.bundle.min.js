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

  fetch("cgi-bin/camcontrols.cgi", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "cmd=setsettings&controls=" + encodeURIComponent(enabled.join(" ")),
  })
    .then(function () {
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
    })
    .finally(function () {
      if (submit) {
        submit.classList.remove("is-loading");
        submit.disabled = false;
      }
    });
}
