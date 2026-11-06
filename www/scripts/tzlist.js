/* Common time zones as POSIX TZ strings (what /mnt/config/timezone.conf holds), shared by the setup wizard and
 * Settings -> Time zone and clock. [IANA name, POSIX rule]: the camera has no zoneinfo, so the daylight saving rules are
 * written out (Mm.w.d = month, week 1-5 with 5 = last, day 0 = Sunday; /h = local hour of the change).
 * TC100_TZ.browser() -> the entry of the browser's zone (Intl) or "UTC"; fill(select, posix, custom) builds the list. */
(function () {
  "use strict";
  var EU_W = "WET0WEST,M3.5.0/1,M10.5.0", CET = "CET-1CEST,M3.5.0,M10.5.0/3", EET = "EET-2EEST,M3.5.0/3,M10.5.0/4";
  var US_E = "EST5EDT,M3.2.0,M11.1.0", US_C = "CST6CDT,M3.2.0,M11.1.0", US_M = "MST7MDT,M3.2.0,M11.1.0", US_P = "PST8PDT,M3.2.0,M11.1.0";
  var AU_E = "AEST-10AEDT,M10.1.0,M4.1.0/3", AU_C = "ACST-9:30ACDT,M10.1.0,M4.1.0/3";
  var GROUPS = [	// [group, group in French, zones]
    ["UTC", "UTC", [["UTC", "UTC0"]]],
    ["Europe", "Europe", [["Europe/London", "GMT0BST,M3.5.0/1,M10.5.0"], ["Europe/Dublin", "GMT0IST,M3.5.0/1,M10.5.0"], ["Europe/Lisbon", EU_W],
      ["Atlantic/Reykjavik", "GMT0"], ["Europe/Paris", CET], ["Europe/Brussels", CET], ["Europe/Amsterdam", CET], ["Europe/Luxembourg", CET],
      ["Europe/Berlin", CET], ["Europe/Zurich", CET], ["Europe/Vienna", CET], ["Europe/Rome", CET], ["Europe/Madrid", CET],
      ["Europe/Stockholm", CET], ["Europe/Oslo", CET], ["Europe/Copenhagen", CET], ["Europe/Prague", CET], ["Europe/Warsaw", CET],
      ["Europe/Budapest", CET], ["Europe/Belgrade", CET], ["Europe/Zagreb", CET], ["Europe/Athens", EET], ["Europe/Helsinki", EET],
      ["Europe/Kyiv", EET], ["Europe/Bucharest", EET], ["Europe/Sofia", EET], ["Europe/Riga", EET], ["Europe/Tallinn", EET],
      ["Europe/Vilnius", EET], ["Europe/Istanbul", "<+03>-3"], ["Europe/Moscow", "MSK-3"], ["Europe/Minsk", "<+03>-3"]]],
    ["America", "Amérique", [["America/New_York", US_E], ["America/Toronto", US_E], ["America/Detroit", US_E], ["America/Chicago", US_C],
      ["America/Winnipeg", US_C], ["America/Mexico_City", "CST6"], ["America/Denver", US_M], ["America/Edmonton", US_M],
      ["America/Phoenix", "MST7"], ["America/Los_Angeles", US_P], ["America/Vancouver", US_P], ["America/Anchorage", "AKST9AKDT,M3.2.0,M11.1.0"],
      ["Pacific/Honolulu", "HST10"], ["America/Halifax", "AST4ADT,M3.2.0,M11.1.0"], ["America/St_Johns", "NST3:30NDT,M3.2.0,M11.1.0"],
      ["America/Puerto_Rico", "AST4"], ["America/Panama", "EST5"], ["America/Guatemala", "CST6"], ["America/Bogota", "<-05>5"],
      ["America/Lima", "<-05>5"], ["America/Caracas", "<-04>4"], ["America/Santiago", "<-04>4<-03>,M9.1.6/24,M4.1.6/24"],
      ["America/Sao_Paulo", "<-03>3"], ["America/Argentina/Buenos_Aires", "<-03>3"], ["America/Montevideo", "<-03>3"]]],
    ["Asia", "Asie", [["Asia/Jerusalem", "IST-2IDT,M3.4.4/26,M10.5.0"], ["Asia/Beirut", "EET-2EEST,M3.5.0/0,M10.5.0/0"], ["Asia/Baghdad", "<+03>-3"],
      ["Asia/Riyadh", "<+03>-3"], ["Asia/Tehran", "<+0330>-3:30"], ["Asia/Dubai", "<+04>-4"], ["Asia/Karachi", "PKT-5"],
      ["Asia/Tashkent", "<+05>-5"], ["Asia/Almaty", "<+05>-5"], ["Asia/Kolkata", "IST-5:30"], ["Asia/Colombo", "<+0530>-5:30"],
      ["Asia/Kathmandu", "<+0545>-5:45"], ["Asia/Dhaka", "<+06>-6"], ["Asia/Yangon", "<+0630>-6:30"], ["Asia/Bangkok", "<+07>-7"],
      ["Asia/Ho_Chi_Minh", "<+07>-7"], ["Asia/Jakarta", "WIB-7"], ["Asia/Shanghai", "CST-8"], ["Asia/Hong_Kong", "HKT-8"],
      ["Asia/Taipei", "CST-8"], ["Asia/Singapore", "<+08>-8"], ["Asia/Kuala_Lumpur", "<+08>-8"], ["Asia/Manila", "PST-8"],
      ["Asia/Seoul", "KST-9"], ["Asia/Tokyo", "JST-9"]]],
    ["Australia and Pacific", "Australie et Pacifique", [["Australia/Perth", "AWST-8"], ["Australia/Darwin", "ACST-9:30"], ["Australia/Adelaide", AU_C],
      ["Australia/Brisbane", "AEST-10"], ["Australia/Sydney", AU_E], ["Australia/Melbourne", AU_E], ["Australia/Hobart", AU_E],
      ["Pacific/Auckland", "NZST-12NZDT,M9.5.0,M4.1.0/3"], ["Pacific/Fiji", "<+12>-12"]]],
    ["Africa", "Afrique", [["Africa/Casablanca", "<+01>-1"], ["Africa/Algiers", "CET-1"], ["Africa/Tunis", "CET-1"], ["Africa/Lagos", "WAT-1"],
      ["Africa/Accra", "GMT0"], ["Africa/Cairo", "EET-2EEST,M4.5.5/0,M10.5.4/24"], ["Africa/Johannesburg", "SAST-2"], ["Africa/Nairobi", "EAT-3"]]]
  ];
  // names a browser may report for a zone listed above under another name
  var ALIAS = { "Europe/Kiev": "Europe/Kyiv", "Asia/Calcutta": "Asia/Kolkata", "Asia/Saigon": "Asia/Ho_Chi_Minh", "Asia/Rangoon": "Asia/Yangon",
    "Asia/Katmandu": "Asia/Kathmandu", "Etc/UTC": "UTC", "Etc/GMT": "UTC", "GMT": "UTC", "Atlantic/Faroe": "Europe/Lisbon",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires", "Australia/Canberra": "Australia/Sydney", "Europe/Bratislava": "Europe/Prague",
    "Europe/Ljubljana": "Europe/Zagreb", "Europe/Sarajevo": "Europe/Zagreb", "Europe/Skopje": "Europe/Zagreb", "Europe/Podgorica": "Europe/Belgrade",
    "Europe/Monaco": "Europe/Paris", "Europe/Malta": "Europe/Rome", "Europe/Vatican": "Europe/Rome", "Europe/San_Marino": "Europe/Rome",
    "Europe/Andorra": "Europe/Madrid", "Europe/Vaduz": "Europe/Zurich", "Asia/Kuwait": "Asia/Riyadh",
    "Asia/Qatar": "Asia/Riyadh", "Asia/Muscat": "Asia/Dubai", "Asia/Tbilisi": "Asia/Dubai", "Asia/Yerevan": "Asia/Dubai", "Asia/Baku": "Asia/Dubai",
    "Asia/Macau": "Asia/Hong_Kong", "Asia/Brunei": "Asia/Singapore", "Asia/Pyongyang": "Asia/Seoul", "America/Montreal": "America/Toronto",
    "America/Indiana/Indianapolis": "America/New_York", "America/Kentucky/Louisville": "America/New_York", "America/Boise": "America/Denver",
    "America/Costa_Rica": "America/Guatemala", "America/El_Salvador": "America/Guatemala", "America/Jamaica": "America/Panama",
    "America/Guayaquil": "America/Bogota", "America/La_Paz": "America/Caracas", "America/Asuncion": "America/Sao_Paulo",
    "Africa/Abidjan": "Africa/Accra", "Africa/Dakar": "Africa/Accra", "Africa/Addis_Ababa": "Africa/Nairobi", "Africa/Dar_es_Salaam": "Africa/Nairobi" };
  var flat = [];
  GROUPS.forEach(function (g) { g[2].forEach(function (z) { flat.push(z); }); });

  function find(id) {
    var i;
    id = ALIAS[id] || id;
    for (i = 0; i < flat.length; i++) if (flat[i][0] === id) return flat[i];
    return null;
  }
  function byPosix(p) {
    var i;
    for (i = 0; i < flat.length; i++) if (flat[i][1] === p) return flat[i];
    return null;
  }
  // the browser's zone from Intl, "UTC" when it has none, throws, or reports a zone this list lacks
  function browser() {
    var id = "";
    try { id = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { id = ""; }
    return find(id) || flat[0];
  }
  // fill a <select>: one option per zone (value = the IANA name) in groups; custom = an extra "other" option (value "")
  // when the current posix string is not in the list; returns the value selected
  function fill(sel, posix, custom) {
    var html = "", cur = byPosix(posix);
    var fr = window.tc100Lang === "fr";	// set by scripts/i18n.js: the group names are not in its text dictionary
    GROUPS.forEach(function (g) {
      html += '<optgroup label="' + (fr ? g[1] : g[0]) + '">';
      g[2].forEach(function (z) { html += '<option value="' + z[0] + '">' + z[0].replace(/_/g, " ") + "</option>"; });
      html += "</optgroup>";
    });
    if (custom) html = '<option value="">' + custom + "</option>" + html;
    sel.innerHTML = html;
    sel.value = cur ? cur[0] : "";
    return sel.value;
  }
  window.TC100_TZ = { zones: flat, find: find, byPosix: byPosix, browser: browser, fill: fill };
})();
