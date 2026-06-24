#!/bin/sh
# wizard.cgi — First-boot configuration wizard
# GET ?check  → JSON {"first_boot":true|false}
# GET         → wizard HTML page
# POST        → apply choices, write boot.conf, mark done

FIRST_BOOT_FLAG="/tmp/.first_boot"
WIZARD_DONE_FILE="/mnt/config/.wizard_done"
BOOT_CONF="/mnt/config/boot.conf"

# Rewrite KEY=value in a shell config file; appends if key absent.
# Uses a sibling temp file (same FS) for atomic replacement.
set_conf() {
    _sc_file="$1" _sc_key="$2" _sc_val="$3"
    [ -f "$_sc_file" ] || return 1
    _sc_tmp="${_sc_file}.wztmp.$$"
    awk -v k="$_sc_key" -v v="$_sc_val" '
        BEGIN { FS="="; found=0 }
        $1 == k { print k "=" v; found=1; next }
        { print $0 }
        END { if (!found) print k "=" v }
    ' "$_sc_file" > "$_sc_tmp" && mv "$_sc_tmp" "$_sc_file"
}

# ── router ────────────────────────────────────────────────────────────────────

METHOD="${REQUEST_METHOD:-GET}"
QUERY="${QUERY_STRING:-}"

# ?check — status probe called by index.html on every page load
case "$QUERY" in
    *check*)
        echo "Content-Type: application/json"
        echo ""
        if [ -f "$FIRST_BOOT_FLAG" ]; then
            echo '{"first_boot":true}'
        else
            echo '{"first_boot":false}'
        fi
        exit 0
        ;;
esac

# POST — apply wizard answers
if [ "$METHOD" = "POST" ]; then
    _cl="${CONTENT_LENGTH:-0}"
    case "$_cl" in ''|*[!0-9]*) _cl=0 ;; esac
    [ "$_cl" -gt 4096 ] && _cl=4096
    _body="$(head -c "$_cl" 2>/dev/null)"

    _profile="$(printf '%s' "$_body" | tr '&' '\n' | grep '^profile=' | head -1 | cut -d= -f2-)"
    _security="$(printf '%s' "$_body" | tr '&' '\n' | grep '^security=' | head -1 | cut -d= -f2-)"

    echo "Content-Type: application/json"
    echo ""

    if [ -z "$_profile" ] || [ -z "$_security" ]; then
        echo '{"ok":false,"error":"missing_params"}'
        exit 0
    fi

    # Validate inputs — allowlist only
    case "$_profile" in
        standalone|frigate_ha|nvr) ;;
        *) echo '{"ok":false,"error":"invalid_profile"}'; exit 0 ;;
    esac
    case "$_security" in
        https_strict|https_mixed|http_lite) ;;
        *) echo '{"ok":false,"error":"invalid_security"}'; exit 0 ;;
    esac

    # Apply profile
    case "$_profile" in
        frigate_ha)
            set_conf "$BOOT_CONF" INTEGRATION_PROFILE frigate_ha
            set_conf "$BOOT_CONF" MQTT_ENABLE 1
            ;;
        *)
            set_conf "$BOOT_CONF" INTEGRATION_PROFILE default
            set_conf "$BOOT_CONF" MQTT_ENABLE 0
            ;;
    esac

    # Apply security / web mode
    case "$_security" in
        https_strict)
            set_conf "$BOOT_CONF" WEB_MODE full
            set_conf "$BOOT_CONF" SECURITY_HARDENING_MODE 1
            ;;
        http_lite)
            set_conf "$BOOT_CONF" WEB_MODE ultra-lite
            set_conf "$BOOT_CONF" SECURITY_HARDENING_MODE 0
            ;;
        *)
            set_conf "$BOOT_CONF" WEB_MODE full
            set_conf "$BOOT_CONF" SECURITY_HARDENING_MODE 0
            ;;
    esac

    touch "$WIZARD_DONE_FILE" 2>/dev/null || true
    rm -f "$FIRST_BOOT_FLAG" 2>/dev/null || true

    echo '{"ok":true}'
    exit 0
fi

# GET — serve wizard HTML
echo "Content-Type: text/html; charset=utf-8"
echo ""
cat << 'HTMLEOF'
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TC100 — Configuration initiale</title>
<link rel="stylesheet" href="/css/bulma.1.0.2.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; }

body {
    background: #0d0f1a;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1.25rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #e2e8f0;
}

.wz-shell {
    background: #131624;
    border: 1px solid #1e2235;
    border-radius: 20px;
    padding: 2.25rem 2rem 2rem;
    width: 100%;
    max-width: 660px;
    box-shadow: 0 32px 80px rgba(0,0,0,0.6);
}

/* ── Header ─────────────────────────────────────── */
.wz-header {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    margin-bottom: 2rem;
}
.wz-logo-ring {
    width: 34px; height: 34px;
    background: linear-gradient(135deg, #6d58f5 0%, #9b6dff 100%);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.wz-title { font-size: 1rem; font-weight: 700; letter-spacing: .06em; color: #e2e8f0; }
.wz-subtitle { margin-left: auto; font-size: 0.72rem; color: #4b5563; letter-spacing: .04em; text-transform: uppercase; }

/* ── Step bar ────────────────────────────────────── */
.wz-steps {
    display: flex;
    align-items: center;
    margin-bottom: 2rem;
}
.wz-dot {
    width: 30px; height: 30px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.72rem; font-weight: 700;
    flex-shrink: 0;
    transition: background .25s, color .25s;
}
.wz-dot.active  { background: #6d58f5; color: #fff; }
.wz-dot.done    { background: #16a34a; color: #fff; }
.wz-dot.pending { background: #1e2235; color: #4b5563; }
.wz-line {
    flex: 1; height: 2px;
    background: #1e2235;
    transition: background .35s;
}
.wz-line.done { background: #16a34a; }

/* ── Step panels ─────────────────────────────────── */
.wz-panel { display: none; }
.wz-panel.active { display: block; }

.wz-step-title {
    font-size: 1.2rem; font-weight: 700; color: #f1f5f9;
    margin-bottom: .3rem;
}
.wz-step-hint {
    font-size: 0.82rem; color: #6b7280;
    margin-bottom: 1.4rem;
}

/* ── Choice cards ────────────────────────────────── */
.wz-card {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem 1.125rem;
    background: #191c2e;
    border: 2px solid #1e2235;
    border-radius: 12px;
    cursor: pointer;
    margin-bottom: 0.625rem;
    transition: border-color .18s, background .18s, box-shadow .18s;
    user-select: none;
}
.wz-card:hover {
    border-color: #4b3fd4;
    background: #1c1f35;
}
.wz-card.selected {
    border-color: #6d58f5;
    background: #1a1730;
    box-shadow: 0 0 0 1px #6d58f5, 0 4px 24px rgba(109,88,245,.18);
}
.wz-icon {
    width: 42px; height: 42px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.wz-card-body { flex: 1; min-width: 0; }
.wz-card-title { font-size: .92rem; font-weight: 600; color: #e2e8f0; margin-bottom: .15rem; display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.wz-card-desc  { font-size: .78rem; color: #6b7280; line-height: 1.4; }
.wz-check {
    width: 20px; height: 20px;
    border-radius: 50%;
    border: 2px solid #2d3456;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: background .18s, border-color .18s;
}
.wz-card.selected .wz-check { background: #6d58f5; border-color: #6d58f5; }

/* ── Badges ──────────────────────────────────────── */
.badge {
    display: inline-block;
    padding: .15rem .5rem;
    border-radius: 5px;
    font-size: .68rem;
    font-weight: 700;
    line-height: 1.5;
}
.badge-green  { background: rgba(22,163,74,.18);  color: #4ade80; }
.badge-purple { background: rgba(109,88,245,.18); color: #a78bfa; }
.badge-amber  { background: rgba(217,119,6,.18);  color: #fbbf24; }
.badge-slate  { background: rgba(71,85,105,.2);   color: #94a3b8; }

/* ── Nav ─────────────────────────────────────────── */
.wz-nav {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 1.625rem;
}
.btn-primary {
    background: #6d58f5;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: .6rem 1.375rem;
    font-size: .875rem;
    font-weight: 600;
    cursor: pointer;
    transition: background .15s, opacity .15s;
    display: inline-flex; align-items: center; gap: .45rem;
}
.btn-primary:hover:not(:disabled) { background: #5b47e0; }
.btn-primary:disabled { opacity: .45; cursor: not-allowed; }
.btn-ghost {
    background: transparent; color: #6b7280;
    border: none; font-size: .82rem;
    cursor: pointer; padding: .5rem .25rem;
    transition: color .15s;
}
.btn-ghost:hover { color: #e2e8f0; }

/* ── Summary ─────────────────────────────────────── */
.wz-summary {
    background: #0d0f1a;
    border: 1px solid #1e2235;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 1.5rem;
}
.wz-summary-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: .75rem 1rem;
    font-size: .83rem;
    border-bottom: 1px solid #1a1d2e;
}
.wz-summary-row:last-child { border-bottom: none; }
.wz-summary-key { color: #6b7280; }

/* ── Success ─────────────────────────────────────── */
.wz-success { display: none; text-align: center; padding: 1.5rem 0 1rem; }
.wz-success-ring {
    width: 68px; height: 68px; border-radius: 50%;
    background: rgba(22,163,74,.12);
    border: 2px solid rgba(22,163,74,.25);
    display: flex; align-items: center; justify-content: center;
    margin: 0 auto 1.25rem;
}
.wz-success-title { font-size: 1.05rem; font-weight: 700; color: #f1f5f9; margin-bottom: .35rem; }
.wz-success-sub   { font-size: .83rem; color: #6b7280; }

/* ── Spinner ─────────────────────────────────────── */
@keyframes wz-spin { to { transform: rotate(360deg); } }
.wz-spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: wz-spin .65s linear infinite;
    display: inline-block;
}
</style>
</head>

<body>
<div class="wz-shell">

  <!-- Header -->
  <div class="wz-header">
    <div class="wz-logo-ring">
      <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
        <circle cx="10" cy="10" r="9" stroke="rgba(255,255,255,.25)" stroke-width="1.5"/>
        <circle cx="10" cy="10" r="4.5" fill="white" opacity=".9"/>
        <circle cx="10" cy="10" r="2" fill="#6d58f5"/>
      </svg>
    </div>
    <span class="wz-title">TC100 ELITE</span>
    <span class="wz-subtitle">Configuration initiale</span>
  </div>

  <!-- Step bar -->
  <div class="wz-steps" id="wzSteps">
    <div class="wz-dot active"  id="wdot1">1</div>
    <div class="wz-line"        id="wline1"></div>
    <div class="wz-dot pending" id="wdot2">2</div>
    <div class="wz-line"        id="wline2"></div>
    <div class="wz-dot pending" id="wdot3">3</div>
  </div>

  <!-- ── Step 1 : Profile ─────────────────────── -->
  <div class="wz-panel active" id="wpanel1">
    <div class="wz-step-title">Profil d'intégration</div>
    <div class="wz-step-hint">Comment cette caméra sera-t-elle utilisée ?</div>

    <div class="wz-card" data-val="standalone" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(109,88,245,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
          <polyline points="9 22 9 12 15 12 15 22"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">Autonome</div>
        <div class="wz-card-desc">Caméra locale indépendante — dashboard complet, toutes les fonctionnalités</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-card" data-val="frigate_ha" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(22,163,74,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
          <line x1="8" y1="21" x2="16" y2="21"/>
          <line x1="12" y1="17" x2="12" y2="21"/>
          <polyline points="7.5,10 10.5,13 16.5,7" stroke-width="2.2"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">Frigate + Home Assistant <span class="badge badge-green">Recommandé</span></div>
        <div class="wz-card-desc">Délègue détection, enregistrement et alertes à Frigate — footprint minimal</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-card" data-val="nvr" data-group="profile" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(217,119,6,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="6" width="20" height="12" rx="2" ry="2"/>
          <circle cx="7" cy="12" r="1.5" fill="#fbbf24" stroke="none"/>
          <path d="M15 9.5l5 2.5-5 2.5V9.5z" fill="#fbbf24" stroke="none"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">NVR tiers</div>
        <div class="wz-card-desc">Blue Iris, Synology Surveillance, iSpy — flux RTSP direct sans MQTT</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-nav">
      <span></span>
      <button class="btn-primary" id="wbtn1" disabled onclick="goStep(2)">
        Suivant
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><polyline points="3,7 11,7 8,4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><polyline points="8,10 11,7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>

  <!-- ── Step 2 : Security ─────────────────────── -->
  <div class="wz-panel" id="wpanel2">
    <div class="wz-step-title">Accès et sécurité</div>
    <div class="wz-step-hint">Comment accéder à l'interface web ?</div>

    <div class="wz-card" data-val="https_strict" data-group="security" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(22,163,74,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">HTTPS uniquement <span class="badge badge-green">Recommandé</span></div>
        <div class="wz-card-desc">Chiffrement TLS, HTTP redirigé automatiquement, certificat auto-signé</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-card" data-val="https_mixed" data-group="security" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(109,88,245,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">HTTPS + HTTP</div>
        <div class="wz-card-desc">Les deux protocoles acceptés — pratique pour intégrations locales mixtes</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-card" data-val="http_lite" data-group="security" onclick="pick(this)">
      <div class="wz-icon" style="background:rgba(217,119,6,.12)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
      </div>
      <div class="wz-card-body">
        <div class="wz-card-title">HTTP ultra-léger</div>
        <div class="wz-card-desc">Busybox httpd — RAM minimal, idéal si dashboard inutilisé (Frigate headless)</div>
      </div>
      <div class="wz-check"><svg width="9" height="9" viewBox="0 0 9 9" fill="none"><polyline points="1.5,4.5 3.5,6.5 7.5,2" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
    </div>

    <div class="wz-nav">
      <button class="btn-ghost" onclick="goStep(1)">← Retour</button>
      <button class="btn-primary" id="wbtn2" disabled onclick="goStep(3)">
        Résumé
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><polyline points="3,7 11,7 8,4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><polyline points="8,10 11,7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>

  <!-- ── Step 3 : Summary ──────────────────────── -->
  <div class="wz-panel" id="wpanel3">
    <div class="wz-step-title">Résumé</div>
    <div class="wz-step-hint">Vérifiez avant d'appliquer — tout est modifiable ensuite depuis le dashboard</div>

    <div class="wz-summary" id="wzSummary"></div>

    <div class="wz-nav">
      <button class="btn-ghost" onclick="goStep(2)">← Retour</button>
      <button class="btn-primary" id="wbtnApply" onclick="applyConfig()">
        Appliquer et lancer
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><polyline points="3,7 11,7 8,4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><polyline points="8,10 11,7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>

  <!-- ── Success ───────────────────────────────── -->
  <div class="wz-success" id="wzSuccess">
    <div class="wz-success-ring">
      <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
        <polyline points="5,14 11,20 23,8" stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="wz-success-title">Configuration appliquée</div>
    <div class="wz-success-sub">Redirection dans <span id="wzCountdown">3</span> s…</div>
  </div>

</div><!-- .wz-shell -->

<script>
var wz = { profile: null, security: null };

var PROFILE_LABEL = {
    standalone: 'Autonome',
    frigate_ha: 'Frigate + Home Assistant',
    nvr:        'NVR tiers'
};
var PROFILE_BADGE = {
    standalone: 'badge-purple',
    frigate_ha: 'badge-green',
    nvr:        'badge-amber'
};
var SECURITY_LABEL = {
    https_strict: 'HTTPS uniquement',
    https_mixed:  'HTTPS + HTTP',
    http_lite:    'HTTP ultra-léger'
};
var SECURITY_BADGE = {
    https_strict: 'badge-green',
    https_mixed:  'badge-purple',
    http_lite:    'badge-amber'
};

function pick(el) {
    var group = el.getAttribute('data-group');
    var val   = el.getAttribute('data-val');
    var cards = document.querySelectorAll('.wz-card[data-group="' + group + '"]');
    var i;
    for (i = 0; i < cards.length; i++) { cards[i].classList.remove('selected'); }
    el.classList.add('selected');
    wz[group] = val;
    if (group === 'profile')   { document.getElementById('wbtn1').disabled = false; }
    if (group === 'security')  { document.getElementById('wbtn2').disabled = false; }
}

function goStep(n) {
    var i;
    for (i = 1; i <= 3; i++) {
        document.getElementById('wpanel' + i).classList.remove('active');
        var dot = document.getElementById('wdot' + i);
        dot.className = 'wz-dot ' + (i < n ? 'done' : i === n ? 'active' : 'pending');
    }
    for (i = 1; i <= 2; i++) {
        document.getElementById('wline' + i).className = 'wz-line' + (i < n ? ' done' : '');
    }
    document.getElementById('wpanel' + n).classList.add('active');
    if (n === 3) { renderSummary(); }
}

function badge(cls, text) {
    return '<span class="badge ' + cls + '">' + text + '</span>';
}

function renderSummary() {
    var mqttOn = wz.profile === 'frigate_ha';
    var rows = [
        ['Profil',       badge(PROFILE_BADGE[wz.profile]   || 'badge-slate', PROFILE_LABEL[wz.profile]   || wz.profile)],
        ['Accès web',    badge(SECURITY_BADGE[wz.security] || 'badge-slate', SECURITY_LABEL[wz.security] || wz.security)],
        ['MQTT',         mqttOn ? badge('badge-green','Activé') : badge('badge-slate','Désactivé')]
    ];
    var html = '';
    var r;
    for (r = 0; r < rows.length; r++) {
        html += '<div class="wz-summary-row">' +
                '<span class="wz-summary-key">' + rows[r][0] + '</span>' +
                '<span>' + rows[r][1] + '</span>' +
                '</div>';
    }
    document.getElementById('wzSummary').innerHTML = html;
}

function applyConfig() {
    var btn = document.getElementById('wbtnApply');
    btn.disabled = true;
    btn.innerHTML = '<span class="wz-spinner"></span> Application…';

    var body = 'profile=' + encodeURIComponent(wz.profile) +
               '&security=' + encodeURIComponent(wz.security);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/cgi-bin/wizard.cgi', true);
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.onreadystatechange = function() {
        if (xhr.readyState !== 4) { return; }
        if (xhr.status === 200) {
            showSuccess();
        } else {
            btn.disabled = false;
            btn.innerHTML = 'Réessayer';
        }
    };
    xhr.send(body);
}

function showSuccess() {
    var i;
    for (i = 1; i <= 3; i++) { document.getElementById('wpanel' + i).classList.remove('active'); }
    document.getElementById('wzSteps').style.display = 'none';
    document.getElementById('wzSuccess').style.display = 'block';

    var n = 3;
    var el = document.getElementById('wzCountdown');
    var timer = setInterval(function() {
        n -= 1;
        el.textContent = n;
        if (n <= 0) {
            clearInterval(timer);
            window.location.replace('/');
        }
    }, 1000);
}
</script>
</body>
</html>
HTMLEOF
