  // Settings page (settings.html calls EliteUI.initDashboard on every visit).
  function initDashboard() {
    var dash = byId('settings_container');
    if (!dash) return;

    function setVal(id, val) {
        var el = byId(id);
        if (!el) return;
        if (el.type === 'checkbox') {
            el.checked = !!(val === 1 || val === true || val === '1' || val === 'true');
        } else {
            el.value = (val !== undefined && val !== null) ? val : '';
        }
    }

    dash.querySelectorAll('form').forEach(function(form) {
        form.onsubmit = function(event) { event.preventDefault(); return false; };
        form.querySelectorAll('button[type="submit"]').forEach(function(button) { button.disabled = true; });
    });

    // Fetch full config to populate all tabs at once
    fetch('cgi-bin/state.cgi?cmd=fullconfig&_=' + Date.now())
        .then(function(r) {
            if (!r.ok) throw new Error('API Response Error');
            return r.text(); // Get raw text first to handle potential parsing issues
        })
        .then(function(text) {
            try {
                return JSON.parse(text);
            } catch (e) {
                console.error('Malformed configuration JSON:', e, text);
                showResult('Configuration parsing error. Check device logs.', 'is-danger');
                throw e;
            }
        })
        .then(function(res) {
            if (!window.isHostStillActive(dash)) return;
            if (!res || !res.video || !res.audio) throw new Error("Incomplete configuration response");

            // 1. Dashboard Block
            var sys = res.system || {};
            var vid = res.video || {};
            var aud = res.audio || {};
            var isp = res.isp || {};
            var osd = res.osd || {};
            var mqtt = res.mqtt || {};
            var rec = res.recording || {};
            var svc = res.services || {};
            var tel = res.telegram || {};
            var sysl = res.syslog || {};
            var periph = res.peripherals || {};

            if (byId('dash_ip')) byId('dash_ip').textContent = window.location.hostname;
            if (byId('dash_gw')) byId('dash_gw').textContent = sys.gateway || 'n/a';
            if (byId('dash_rtsp_link_0')) {
                byId('dash_rtsp_link_0').href = 'rtsp://' + window.location.hostname + ':' + (vid.rtsp_port || 554) + '/video0_unicast';
            }

            // 2. Video & Audio
            // vid/sys/aud/isp/osd/mqtt/rec/svc/tel/sysl/periph are all
            // guaranteed objects (defaulted with || {} above), so plain
            // dot access is safe here — no optional chaining needed.
            var vmain = vid.main || {};
            var vsub = vid.sub || {};
            var rsch = sys.reboot_schedule || {};
            var mguard = sys.mem_guard || {};
            var bootCfg = res.boot || {};

            setVal('video_size0', (vmain.width || 1920) + 'x' + (vmain.height || 1080));
            setVal('video_codec0', vmain.codec);
            setVal('fps0', vmain.fps);
            setVal('brbitrate0', vmain.bitrate);
            setVal('goplen0', vmain.gop);
            setVal('video_format0', vmain.format);
            setVal('minqp0', vmain.minqp);
            setVal('maxqp0', vmain.maxqp);
            setVal('smartmode0', vmain.smartmode);

            setVal('video_size1', (vsub.width || 640) + 'x' + (vsub.height || 360));
            setVal('fps1', vsub.fps);
            setVal('brbitrate1', vsub.bitrate);
            setVal('video_codec1', vsub.codec);
            setVal('goplen1', vsub.gop);
            setVal('video_format1', vsub.format);
            setVal('minqp1', vsub.minqp);
            setVal('maxqp1', vsub.maxqp);
            setVal('smartmode1', vsub.smartmode);


            setVal('audio_vol', aud.volume);

            // 3. ISP & OSD
            setVal('daynightlum', isp.daynight_lum);
            setVal('nightdaylum', isp.nightday_lum);

            setVal('osdenabled', osd.enabled);
            setVal('osdtext', osd.text);
            setVal('frontcolor', osd.frontcolor);
            setVal('backcolor', osd.backcolor);
            setVal('osdalpha', osd.alpha);
            setVal('osdfontsize0', osd.fontsize0);
            setVal('osdx0', osd.x0);
            setVal('osdy0', osd.y0);
            setVal('imageflip', vid.flip);

            // 3b. Live image tuning (separate endpoint; values applied by libtc100fix)
            loadIspTune(dash);

            // 4. Automation
            setVal('mqtt_enabled', mqtt.enabled);
            setVal('mqtt_host', mqtt.host);
            setVal('mqtt_port', mqtt.port);
            setVal('mqtt_user', mqtt.user);
            setVal('mqtt_topic_root', mqtt.topic_root);
            setVal('mqtt_discovery', mqtt.discovery);
            if (window.tc100HaSync) window.tc100HaSync();

            setVal('mdsens', svc.motion_sens);
            setVal('sound_det_threshold', svc.sound_det_threshold);
            setVal('sound_det_enable', svc.sound_det_enable);
            setVal('motion_led', svc.motion_led);
            initMotionZones(document.getElementById('formDetect'));
            initRtspServer(document.getElementById('formRtspServer'));

            setVal('motion_activated', rec.motion_activated);
            setVal('postrec', rec.postrec);
            setVal('maxduration', rec.maxduration);
            setVal('reserved_mb', rec.reserved_mb);

            // 5. Network
            setVal('hostname', sys.hostname);
            setVal('rtsp_port', vid.rtsp_port);
            setVal('telnet_port', svc.telnet_port);
            setVal('timezone', sys.timezone);
            setVal('ntp_server', sys.ntp_server);

            // 6. System & Tuning
            setVal('lightweight_mode', bootCfg.lightweight_mode);
            setVal('security_hardening', bootCfg.security_hardening);
            setVal('mem_guard_enable', mguard.enable);
            setVal('mem_guard_warn_kb', mguard.warn_kb);
            setVal('mem_guard_crit_kb', mguard.crit_kb);
            setVal('mem_guard_interval', mguard.interval);

            setVal('reboot_enable', rsch.enable);
            setVal('reboot_schedule_hour', rsch.hour);
            setVal('reboot_schedule_min', rsch.min);
            setVal('reboot_schedule_dow', rsch.dow);


            // 8. Telegram & Syslog
            setVal('telegram_enable', tel.enabled);
            setVal('telegram_token', tel.token);
            setVal('telegram_chat_id', tel.chat_id);
            setVal('syslog_enable', sysl.enabled);
            setVal('syslog_host', sysl.host);
            setVal('syslog_port', sysl.port);
            var frig = res.frigate || {};
            setVal('frigate_url', frig.url);
            setVal('frigate_camera', frig.camera);

            // 9. Peripherals
            setVal('led_front', periph.led_front);
            setVal('led_red', periph.led_red);

            if (!window.isHostStillActive(dash)) return;
            byId('settings_load_status').textContent = 'Current settings loaded. Changes are saved only when you choose Save or Apply.';
            dash.querySelectorAll('button[type="submit"]').forEach(function(button) { button.disabled = false; });

            // Form dirty state tracking and validation
            var dirtyForms = [];
            var settingsSaveInProgress = false;
            activeDirtyForms = dirtyForms;

            function markFormDirty(form) {
                if (dirtyForms.indexOf(form) === -1) { dirtyForms.push(form); }
                updateFormSubmitButton(form);
            }

            function markFormClean(form) {
                var i = dirtyForms.indexOf(form);
                if (i !== -1) { dirtyForms.splice(i, 1); }
                updateFormSubmitButton(form);
            }

            function updateFormSubmitButton(form) {
                var submitBtn = form.querySelector('button[type="submit"]');
                if (!submitBtn) return;
                var isDirty = dirtyForms.indexOf(form) !== -1;
                submitBtn.classList.toggle('is-loading', form.getAttribute('aria-busy') === 'true');
                if (isDirty) {
                    submitBtn.classList.add('has-background-warning-light');
                    submitBtn.title = 'Click to save changes';
                } else {
                    submitBtn.classList.remove('has-background-warning-light');
                    submitBtn.title = 'No changes to save';
                }
            }

            function validateFormField(input) {
                if (!input.type || !input.name) return true;
                var val = input.value.trim();

                // Port validation: 1-65535
                if (input.name.toLowerCase().indexOf('port') !== -1) {
                    var port = parseInt(val, 10);
                    if (val && (isNaN(port) || port < 1 || port > 65535)) {
                        input.classList.add('is-danger');
                        input.title = 'Port must be 1-65535';
                        return false;
                    }
                }

                // Hostname validation (basic: alphanumeric, dots, hyphens)
                if (input.name.toLowerCase().indexOf('hostname') !== -1) {
                    if (val && !/^[a-zA-Z0-9.-]*$/.test(val)) {
                        input.classList.add('is-danger');
                        input.title = 'Invalid hostname characters';
                        return false;
                    }
                }

                // Host fields (mqtt_host, syslog_host, ...) must accept a
                // HOSTNAME as well as an IP — otherwise mqtt_host cannot be
                // set to e.g. "homeassistant.local", which blocked the
                // documented Home Assistant quick-start. Checked before the
                // stricter IP rule below.
                if (input.name.toLowerCase().indexOf('host') !== -1) {
                    if (val && !/^[a-zA-Z0-9.-]+$/.test(val)) {
                        input.classList.add('is-danger');
                        input.title = 'Invalid hostname or IP address';
                        return false;
                    }
                } else if (/(^|_)(ip|dns\d?|gateway|netmask)(_|$)/i.test(input.name)) {
                    // Pure IP fields (dns, static ip, gateway): dotted quad or localhost.
                    if (val && !/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(val) && val !== 'localhost') {
                        input.classList.add('is-danger');
                        input.title = 'Invalid IP address format';
                        return false;
                    }
                }

                // Number fields: non-negative
                if (input.type === 'number') {
                    if (val) {
                        var num = parseInt(val, 10);
                        var allowNeg = input.min !== '' && parseInt(input.min, 10) < 0;
                        if (isNaN(num) || (num < 0 && !allowNeg)) {
                            input.classList.add('is-danger');
                            input.title = 'Must be a positive number';
                            return false;
                        }
                    }
                }

                input.classList.remove('is-danger');
                input.title = '';
                return true;
            }

            // Set up generic form submission listeners for all dashboard forms
            dash.querySelectorAll('form').forEach(function(f) {
                f.noValidate = true; // Validate and reveal collapsed fields in the submit handler.
                // Track changes on all inputs
                var inputs = f.querySelectorAll('input, select, textarea');
                inputs.forEach(function(input) {
                    input.addEventListener('change', function() {
                        if (!validateFormField(this)) return false;
                        markFormDirty(f);
                    });
                    input.addEventListener('input', function() {
                        validateFormField(this);
                        markFormDirty(f);
                    });
                });

                // Disable submit button initially (no changes yet)
                updateFormSubmitButton(f);

                f.onsubmit = function(ev) {
                    ev.preventDefault();
                    if (settingsSaveInProgress) {
                        settingsSaveStatus(f, 'Please wait for the current save to finish.', 'pending');
                        return false;
                    }

                    // Validate all fields
                    var isValid = true;
                    this.querySelectorAll('input, select, textarea').forEach(function(input) {
                        if (!validateFormField(input) || (input.checkValidity && !input.checkValidity())) {
                            isValid = false;
                            var details = input.closest('details');
                            while (details) { details.open = true; details = details.parentElement.closest('details'); }
                            input.classList.add('is-danger');
                        }
                    });

                    if (!isValid) {
                        settingsSaveStatus(f, 'Please check the highlighted fields before saving.', 'error');
                        var invalidInput = f.querySelector('.is-danger');
                        if (invalidInput) invalidInput.focus();
                        return false;
                    }

                    var params = new URLSearchParams(new FormData(this));
                    settingsSaveInProgress = true;
                    setSettingsFormBusy(f, true);
                    saveSettingsRequest(this.action, params, function(message, kind) {
                        settingsSaveStatus(f, message, kind);
                    }).then(function(result) {
                        if (result.ok !== true || result.unconfirmed) {
                            markFormDirty(f);
                            settingsSaveStatus(f, result.message, 'warning');
                            return;
                        }
                        markFormClean(f);
                        if (result.settingsConfig) {
                            refreshSettingsVideoForms(dash, result.settingsConfig, dirtyForms);
                            result.message += ' Current video values refreshed; any other unsaved edits are kept.';
                        }
                        settingsSaveStatus(f, result.message || 'The camera confirmed the request.', 'success');
                        // Keep the draft until the asynchronous save actually succeeds.
                        try { localStorage.removeItem('dashboard_form_' + (f.id || f.action)); } catch (e) {}
                    }).catch(function(err) {
                        markFormDirty(f);
                        settingsSaveStatus(f, err.message || 'Saving failed. Your edits are kept.', 'error');
                    }).finally(function() {
                        settingsSaveInProgress = false;
                        setSettingsFormBusy(f, false);
                        updateFormSubmitButton(f);
                    });
                    return false;
                };
            });

            // Warn if user tries to leave with unsaved changes. Registered
            // ONCE (guarded) to avoid leaking a listener per Settings visit;
            // it reads activeDirtyForms so it always reflects the current
            // visit. Note: dirtyForms is an Array — the old code checked
            // `.size` (undefined on arrays) so the warning never fired.
            if (!settingsUnloadBound) {
                settingsUnloadBound = true;
                window.addEventListener('beforeunload', function(e) {
                    if (activeDirtyForms && activeDirtyForms.length > 0) {
                        e.preventDefault();
                        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
                        return e.returnValue;
                    }
                });
            }

            // PHASE 2: Password Visibility Toggle
            dash.querySelectorAll('input[type="password"]').forEach(function(pwdInput) {
                // Wrap the field itself: restyling its parent (as this
                // used to) turned a whole card into one flex row.
                var wrap = document.createElement('span');
                wrap.className = 'v2-secret';
                wrap.style.cssText = 'position:relative;display:block;';
                pwdInput.parentNode.insertBefore(wrap, pwdInput);
                wrap.appendChild(pwdInput);
                var toggleBtn = document.createElement('button');
                toggleBtn.type = 'button';
                toggleBtn.className = 'button is-small is-light v2-secret-toggle';
                toggleBtn.style.cssText = 'position:absolute;right:4px;top:50%;transform:translateY(-50%);z-index:2;';
                toggleBtn.textContent = 'Show';
                toggleBtn.title = 'Show password';
                toggleBtn.setAttribute('aria-label', 'Show password');
                toggleBtn.onclick = function(e) {
                    e.preventDefault();
                    var isPassword = pwdInput.type === 'password';
                    pwdInput.type = isPassword ? 'text' : 'password';
                    toggleBtn.textContent = isPassword ? 'Hide' : 'Show';
                    toggleBtn.title = isPassword ? 'Hide password' : 'Show password';
                    toggleBtn.setAttribute('aria-label', toggleBtn.title);
                };
                wrap.appendChild(toggleBtn);
                pwdInput.style.paddingRight = '4.2rem';
            });

            // PHASE 2: Copy-to-Clipboard Utilities
            function copyToClipboard(text, label) {
                if (!navigator.clipboard) {
                    alert('Copy text: ' + text);
                    return;
                }
                navigator.clipboard.writeText(text).then(function() {
                    showResult('Copied: ' + label, 'is-success');
                }).catch(function() {
                    showResult('Failed to copy', 'is-danger');
                });
            }

            var ipDisplay = byId('dash_ip');
            if (ipDisplay) {
                var ipBtn = document.createElement('button');
                ipBtn.type = 'button';
                ipBtn.className = 'button is-small is-light ml-2';
                ipBtn.textContent = '📋 Copy';
                ipBtn.onclick = function(e) {
                    e.preventDefault();
                    copyToClipboard(ipDisplay.textContent, 'Device IP');
                };
                ipDisplay.parentElement.appendChild(ipBtn);
            }

            var rtspLink = byId('dash_rtsp_link_0');
            if (rtspLink) {
                var rtspBtn = document.createElement('button');
                rtspBtn.type = 'button';
                rtspBtn.className = 'button is-small is-light ml-2';
                rtspBtn.textContent = '📋 Copy URL';
                rtspBtn.onclick = function(e) {
                    e.preventDefault();
                    copyToClipboard(rtspLink.href, 'RTSP URL');
                };
                rtspLink.parentElement.appendChild(rtspBtn);
            }

            var mqttClientId = byId('mqtt_client_id');
            if (mqttClientId) {
                var mqttBtn = document.createElement('button');
                mqttBtn.type = 'button';
                mqttBtn.className = 'button is-small is-light';
                mqttBtn.textContent = '📋';
                mqttBtn.title = 'Copy MQTT Client ID';
                mqttBtn.style.marginLeft = '4px';
                mqttBtn.onclick = function(e) {
                    e.preventDefault();
                    copyToClipboard(mqttClientId.value, 'MQTT Client ID');
                };
                mqttClientId.parentElement.appendChild(mqttBtn);
            }

            // PHASE 2: Client-Side Form Caching
            var CACHE_KEY_PREFIX = 'dashboard_form_';
            var CACHE_TTL_MINUTES = 60;

            function cacheFormState(form) {
                var formId = form.id || form.action;
                var cacheData = {
                    timestamp: Date.now(),
                    values: {}
                };
                form.querySelectorAll('input, select, textarea').forEach(function(field) {
                    // Never keep passwords (Wi-Fi, MQTT, web) in the browser's storage.
                    if (field.name && field.name.indexOf('_') !== 0 && field.type !== 'password') {
                        if (field.type === 'checkbox' || field.type === 'radio') {
                            cacheData.values[field.name] = field.checked;
                        } else {
                            cacheData.values[field.name] = field.value;
                        }
                    }
                });
                try {
                    localStorage.setItem(CACHE_KEY_PREFIX + formId, JSON.stringify(cacheData));
                } catch (e) {
                    // localStorage quota exceeded or disabled, silently fail
                }
            }

            function restoreFormState(form) {
                var formId = form.id || form.action;
                try {
                    var cached = localStorage.getItem(CACHE_KEY_PREFIX + formId);
                    if (!cached) return;
                    var cacheData = JSON.parse(cached);
                    var ageMinutes = (Date.now() - cacheData.timestamp) / (1000 * 60);
                    if (ageMinutes > CACHE_TTL_MINUTES) return; // Cache expired

                    var restoredChanged = false;
                    form.querySelectorAll('input, select, textarea').forEach(function(field) {
                        if (field.name && field.type !== 'password' && cacheData.values.hasOwnProperty(field.name)) {
                            var val = cacheData.values[field.name];
                            if (field.type === 'checkbox' || field.type === 'radio') {
                                if (field.checked !== val) { restoredChanged = true; }
                                field.checked = val;
                            } else {
                                if (field.value !== val) { restoredChanged = true; }
                                field.value = val;
                            }
                        }
                    });
                    // The cached values (up to 60 min old) have just overwritten
                    // the fresh device config read into these fields. If that
                    // actually changed anything, mark the form dirty so the user
                    // SEES these are unsaved local values — otherwise stale cache
                    // was silently presented as current device state and a later
                    // save would re-POST it, reverting changes made elsewhere.
                    if (restoredChanged && typeof markFormDirty === 'function') {
                        markFormDirty(form);
                    }
                } catch (e) {
                    // JSON parse error or localStorage issue, silently fail
                }
            }

            dash.querySelectorAll('form').forEach(function(f) {
                // Restore cached state on page load
                restoreFormState(f);

                // Cache form state on every change
                f.querySelectorAll('input, select, textarea').forEach(function(field) {
                    field.addEventListener('change', function() {
                        cacheFormState(f);
                    });
                });


            });

            // Set up individual buttons
            var btnReboot = byId('btnReboot');
            if (btnReboot) {
                btnReboot.onclick = function() {
                    if (!confirm('Reboot camera?')) return;
                    csrfFetch('cgi-bin/action.cgi?cmd=reboot', { method: 'POST' }).then(function() {
                        showResult('Rebooting... please wait 60s', 'is-info');
                    });
                };
            }
            var btnFreeRam = byId('btnFreeRam');
            if (btnFreeRam) {
                btnFreeRam.onclick = function() {
                    csrfFetch('cgi-bin/action.cgi?cmd=clear_mem', { method: 'POST' }).then(function() {
                        showResult('Memory cache cleared', 'is-success');
                    });
                };
            }
        })
        .catch(function(e) {
            console.error('Dashboard init failed', e);
            if (window.isHostStillActive(dash)) byId('settings_load_status').textContent = 'Settings could not be loaded. Reopen Settings to retry; saving is disabled.';
        });

    // The main statusline loop feeds these gauges too. Do not create a
    // second poller each time the Settings view is mounted.
    dashboardStatusRenderer = function(res) {
        if (!window.isHostStillActive(dash)) {
            dashboardStatusRenderer = null;
            return;
        }
        if (!res) return;
        var cpuText = byId('dash_cpu_val');
        var cpuBar = byId('dash_cpu_bar');
        if (cpuText) cpuText.textContent = res.cpu + '%';
        if (cpuBar) { cpuBar.style.width = res.cpu + '%'; cpuBar.className = 'ui-progress-bar ' + (res.cpu > 80 ? 'is-danger' : (res.cpu > 50 ? 'is-warning' : 'is-success')); }

        var memText = byId('dash_mem_val');
        var memBar = byId('dash_mem_bar');
        if (memText) memText.textContent = res.ram_percent + '%';
        if (memBar) { memBar.style.width = res.ram_percent + '%'; memBar.className = 'ui-progress-bar ' + (res.ram_percent > 90 ? 'is-danger' : (res.ram_percent > 70 ? 'is-warning' : 'is-success')); }

        var wifiText = byId('dash_wifi_val');
        var wifiBar = byId('dash_wifi_bar');
        if (wifiText) {
            var qual = (typeof res.wifi_qual === "number") ? res.wifi_qual : null;
            wifiText.textContent = qual === null ? '—' : qual + '%';
            if (wifiBar) { wifiBar.style.width = (qual === null ? 0 : qual) + '%'; wifiBar.className = 'ui-progress-bar ' + (qual < 40 ? 'is-danger' : (qual < 70 ? 'is-warning' : 'is-success')); }
        }

        if (byId('sd_readonly_warning')) byId('sd_readonly_warning').style.display = res.sd_readonly ? 'block' : 'none';
        if (byId('security_warning')) byId('security_warning').style.display = (res.default_password_active || res.setup_wizard_done === 0) ? 'block' : 'none';
    };
    if (lastStatusline) dashboardStatusRenderer(lastStatusline);
  }

  // Settings → Update & backup: named configuration presets.
  function initPresets() {
    var presetsContainer = byId('tab-backup');
    if (!presetsContainer) return;

    var presetDropdown = byId('preset_dropdown');
    var presetNameInput = byId('preset_name_input');
    var btnLoadPreset = byId('btn_load_preset');
    var btnSavePreset = byId('btn_save_preset');
    var btnRefreshPresets = byId('btn_refresh_presets');
    var btnExportConfig = byId('btn_export_config');
    var btnImportConfig = byId('btn_import_config');
    var importFileInput = byId('import_file_input');
    var presetsTable = byId('presets_table');
    var presetsTbody = byId('presets_tbody');
    var presetsEmpty = byId('presets_empty');

    var currentConfig = null;

    function refreshPresetList() {
        fetch('cgi-bin/state.cgi?cmd=list_presets&format=json&_=' + Date.now())
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (!res || !res.presets) return;

                presetDropdown.innerHTML = '<option value="">-- Select a preset --</option>';
                presetsTbody.innerHTML = '';

                if (res.presets.length === 0) {
                    presetsTable.style.display = 'none';
                    presetsEmpty.style.display = 'block';
                } else {
                    presetsTable.style.display = 'table';
                    presetsEmpty.style.display = 'none';

                    res.presets.forEach(function(p) {
                        var opt = document.createElement('option');
                        opt.value = p.name;
                        opt.textContent = p.name;
                        presetDropdown.appendChild(opt);

                        var tr = document.createElement('tr');
                        var nameCell = document.createElement('td');
                        nameCell.textContent = p.name;
                        var actionsCell = document.createElement('td');
                        var deleteBtn = document.createElement('button');
                        deleteBtn.type = 'button';
                        deleteBtn.className = 'button is-danger is-small';
                        deleteBtn.textContent = 'Delete';
                        deleteBtn.onclick = function(e) {
                            e.preventDefault();
                            if (!confirm('Delete preset "' + p.name + '"?')) return;
                            csrfFetch('cgi-bin/action.cgi?cmd=delete_preset&name=' + encodeURIComponent(p.name), { method: 'POST' })
                                .then(function() {
                                    showResult('Preset deleted', 'is-success');
                                    refreshPresetList();
                                })
                                .catch(function(e) { showResult('Error deleting preset', 'is-danger'); });
                        };
                        actionsCell.appendChild(deleteBtn);
                        tr.appendChild(nameCell);
                        tr.appendChild(actionsCell);
                        presetsTbody.appendChild(tr);
                    });
                }
            })
            .catch(function(e) { console.error('Failed to refresh preset list', e); });
    }

    function captureCurrentConfig() {
        var forms = document.querySelectorAll('#settings_container form');
        var config = {};

        forms.forEach(function(form) {
            var inputs = form.querySelectorAll('input, select, textarea');
            inputs.forEach(function(inp) {
                if (inp.name) {
                    if (inp.type === 'checkbox') {
                        config[inp.name] = inp.checked ? 1 : 0;
                    } else {
                        config[inp.name] = inp.value;
                    }
                }
            });
        });

        return config;
    }

    function applyConfig(config) {
        if (!config) return Promise.reject('No config');

        var forms = document.querySelectorAll('#settings_container form');
        var promise = Promise.resolve();

        forms.forEach(function(form) {
            var formData = new FormData();
            var inputs = form.querySelectorAll('input, select, textarea');
            var hasChanges = false;

            inputs.forEach(function(inp) {
                if (inp.name && config[inp.name] !== undefined) {
                    var newVal = config[inp.name];
                    if (inp.type === 'checkbox') {
                        inp.checked = newVal === 1 || newVal === '1' || newVal === true;
                    } else {
                        inp.value = newVal;
                    }
                    formData.append(inp.name, newVal);
                    hasChanges = true;
                }
            });

            if (hasChanges) {
                var action = form.getAttribute('action');
                if (action) {
                    promise = promise.then(function() {
                        return csrfFetch(action, { method: 'POST', body: formData });
                    });
                }
            }
        });

        return promise;
    }

    if (btnLoadPreset) {
        btnLoadPreset.onclick = function(e) {
            e.preventDefault();
            var presetName = presetDropdown.value;
            if (!presetName) {
                showResult('Select a preset first', 'is-warning');
                return;
            }

            if (!confirm('Load preset "' + presetName + '"? Current unsaved changes will be lost.')) return;

            fetch('cgi-bin/state.cgi?cmd=load_preset&format=json&name=' + encodeURIComponent(presetName) + '&_=' + Date.now())
                .then(function(r) { return r.json(); })
                .then(function(res) {
                    if (!res || !res.preset) throw new Error('Invalid preset');
                    return applyConfig(res.preset.settings || res.preset);
                })
                .then(function() {
                    showResult('Preset "' + presetName + '" loaded', 'is-success');
                })
                .catch(function(e) {
                    console.error('Failed to load preset', e);
                    showResult('Error loading preset', 'is-danger');
                });
        };
    }

    if (btnSavePreset) {
        btnSavePreset.onclick = function(e) {
            e.preventDefault();
            var presetName = presetNameInput.value.trim();
            if (!presetName) {
                showResult('Enter a preset name', 'is-warning');
                return;
            }

            var config = captureCurrentConfig();
            var presetData = JSON.stringify({ name: presetName, settings: config, timestamp: Math.floor(Date.now() / 1000) });

            csrfFetch('cgi-bin/action.cgi?cmd=save_preset&name=' + encodeURIComponent(presetName), {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'data=' + encodeURIComponent(presetData)
            })
                .then(function() {
                    showResult('Preset "' + presetName + '" saved', 'is-success');
                    presetNameInput.value = '';
                    refreshPresetList();
                })
                .catch(function(e) {
                    console.error('Failed to save preset', e);
                    showResult('Error saving preset', 'is-danger');
                });
        };
    }

    if (btnRefreshPresets) {
        btnRefreshPresets.onclick = function(e) {
            e.preventDefault();
            refreshPresetList();
        };
    }

    if (btnExportConfig) {
        btnExportConfig.onclick = function(e) {
            e.preventDefault();
            var config = captureCurrentConfig();
            var blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'config-' + new Date().toISOString().split('T')[0] + '.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        };
    }

    if (btnImportConfig) {
        btnImportConfig.onclick = function(e) {
            e.preventDefault();
            importFileInput.click();
        };
    }

    if (importFileInput) {
        importFileInput.onchange = function(e) {
            var file = e.target.files[0];
            if (!file) return;

            var reader = new FileReader();
            reader.onload = function(evt) {
                try {
                    var config = JSON.parse(evt.target.result);
                    applyConfig(config)
                        .then(function() {
                            showResult('Configuration imported and applied', 'is-success');
                        })
                        .catch(function(err) {
                            showResult('Error applying imported config', 'is-danger');
                        });
                } catch (err) {
                    showResult('Invalid JSON file', 'is-danger');
                }
            };
            reader.readAsText(file);
            importFileInput.value = '';
        };
    }

    // Initialize preset list on load
    refreshPresetList();
  }
