// Web UI main script, part 1/12 — shared state and poll intervals.
// Source of www/scripts/index.bundle.min.js: edit these files, then run
// src/webui/build-index.sh (the tests check that the bundle matches).
(function () {
  var timeoutJobs = {};
  var contentLoadController = null;
  var liveFeedEnabled = false;
  var currentContentTarget = "";

  var LIVEVIEW_INTERVAL_VISIBLE_DEFAULT_MS = 4000;
  var LIVEVIEW_INTERVAL_HIDDEN_DEFAULT_MS = 20000;
  var SYSUSAGE_INTERVAL_VISIBLE_DEFAULT_MS = 20000;
  var SYSUSAGE_INTERVAL_HIDDEN_DEFAULT_MS = 90000;
  var AUTONIGHT_INTERVAL_VISIBLE_DEFAULT_MS = 12000;
  var AUTONIGHT_INTERVAL_HIDDEN_DEFAULT_MS = 30000;

  var LIVEVIEW_INTERVAL_VISIBLE_MS = LIVEVIEW_INTERVAL_VISIBLE_DEFAULT_MS;
  var LIVEVIEW_INTERVAL_HIDDEN_MS = LIVEVIEW_INTERVAL_HIDDEN_DEFAULT_MS;
  var SYSUSAGE_INTERVAL_VISIBLE_MS = SYSUSAGE_INTERVAL_VISIBLE_DEFAULT_MS;
  var SYSUSAGE_INTERVAL_HIDDEN_MS = SYSUSAGE_INTERVAL_HIDDEN_DEFAULT_MS;
  var AUTONIGHT_INTERVAL_VISIBLE_MS = AUTONIGHT_INTERVAL_VISIBLE_DEFAULT_MS;
  var AUTONIGHT_INTERVAL_HIDDEN_MS = AUTONIGHT_INTERVAL_HIDDEN_DEFAULT_MS;

  var liveViewVisibleIntervalMs = LIVEVIEW_INTERVAL_VISIBLE_MS;
  var liveViewSnapshotEndpoint = "cgi-bin/currentpic.cgi";
  var liveViewInViewport = true;
  var liveViewVisibilityObserver = null;
  var currentPerfProfileToken = "balanced";
  var dynamicSysUsageIntervalMs = 0;
  var uiUltraLiteMode = false;
  var perfProfileFetchController = null;
  var sysUsageFetchController = null;
  var legacySysUsageFetchController = null;
  var sysUsageConsecErrors = 0;
  var sysUsageLastSuccessTs = 0;
  var lastLumValue = "";
  var lastAwbValue = "";
  var csrfToken = "";
  var lastStatusline = null;
  var lastStatuslineTs = 0;
  var sharedStatuslineRequest = null;
  var dashboardStatusRenderer = null;
  var statusRefreshButton = null;
  var statusUpdatedLabel = null;
  // Stable anchors for Settings dirty-form tracking. initDashboard runs on every
  // Settings visit; keeping these at IIFE scope lets a SINGLE beforeunload
  // listener always see the current visit's dirty set instead of leaking one
  // stale listener (bound to a stale array) per visit.
  var activeDirtyForms = null;
  var settingsUnloadBound = false;

