# TECKIN TC100 "Elite Edition" Anyka AK3918 Camera Hacks
**Version 1.2.0** — *Definitive Elite Dashboard Release*

This is a high-performance, modernized firmware extension for the **Teckin TC100 / Teckin Click** (CPU Anyka AK3918 v300). This version is 100% cloud-free, MicroSD-based, and performance-optimized.

## 🚀 "Elite Edition" Highlights
The camera has been fully modernized with a premium, tabbed dashboard built on Bulma 1.0.2:

- **Elite Dashboard**: A single-page, tabbed management interface (Dashboard, Video, ISP, Automation, Network, System).
- **High-Performance Icons**: 100% custom SVG iconography for instant, reliable rendering on any device.
- **Elite Optimization Presets**: 1-click tuning for `Frigate Balanced`, `Universal H264`, and `Maximum Performance`.
- **Safety Snapshot Management**: Save and restore "Known-Good" configuration points to recover from aggressive tuning experiments.
- **Privacy Shield**: One-click "Stealth Mode" that instantly severs all cloud, external, and outbound polling paths.
- **Full Legacy Parity**: 100% of the features from the original hack are preserved and enhanced, including LED controls, Telegram bot, and Syslog forwarding.

## 🛠 Features
- **Massive Optimization**: Extreme focus on zero-memory leaks and low CPU footprint for the AK3918 hardware.
- **Two-Way Audio + PTT**: Listen in real-time or hold-to-talk to speak through the camera speaker.
- **Elite Timelapse Studio**: Integrated management for automated timelapse capture.
- **Home Assistant & Frigate Native**: Auto-pairing with compatibility presets, MQTT discovery, and live integration manifests.
- **Advanced Security**: Security hardening mode, HTTPS support, and Privacy Shield isolation.

## 📦 Installation
1. Format MicroSD as FAT32 (32K allocation size recommended).
2. Copy repository contents to the card.
3. Create `wpa_supplicant.conf` from `wpa_supplicant.conf.dist` and set Wi-Fi SSID/PSK.
4. Insert card into camera and reboot.
5. Open `https://CAMERA-IP` (default user: `root` / pass: `pass`).

## 🏠 Home Assistant / Frigate Integration
- **One-Click Pairing**: Use the UI to pair with Home Assistant using the `Frigate Balanced` or `Frigate Low-Bandwidth` presets.
- **Integration Pack**: Fetch the live manifest via `cgi-bin/state.cgi?cmd=integrationmanifest` for instant Frigate YAML snippets.
- **MQTT Telemetry**: Structured results for all commands, network health monitoring, and recovery metadata.
- **Self-Healing**: Automatic "Integration Repair" and post-change stream health checks with auto-rollback.

## 🎛 Peripherals & Mastery
- **LED Control**: Granular toggles for Front Activity LED and Infrared status lights.
- **Notification Suite**: Native Telegram Bot support and remote Syslog forwarding for expert monitoring.
- **Smart Memory Guard**: OOM prevention daemon with customizable warn/critical/emergency thresholds.

## 📜 Development Workflow
- **Frontend**: Source lives in `frontend/src/` using a zero-dependency Bulma 1.0.2 baseline.
- **CGI API**: State is served via JSON-atomic `state.cgi` and persisted via `action.cgi`.
- **Build**: Use `npm run build:web` to sync `frontend/src/` to the served assets, and `npm run check:web` to detect drift (CI gate). Details in `frontend/README.md`. Always edit `frontend/src/`, never `www/scripts/` or `www/css/ui-modern.min.css` directly.

---
*This project is local-LAN focused and does not require cloud services. Your privacy is prioritized by default.*
