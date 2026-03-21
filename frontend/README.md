## Frontend Workflow

Frontend source now lives under `frontend/src/`.

Current source-to-output mapping:

- `frontend/src/js/camcontrols.js` -> `www/scripts/camcontrols.cgi.js`, `www/scripts/camcontrols.bundle.min.js`
- `frontend/src/js/index.js` -> `www/scripts/index.bundle.min.js`
- `frontend/src/js/ptt-audio.js` -> `www/scripts/ptt-audio.bundle.min.js` (new: PTT & two-way audio)
- `frontend/src/js/scripts.js` -> `www/scripts/scripts.cgi.js`, `www/scripts/scripts.bundle.min.js`
- `frontend/src/js/status.js` -> `www/scripts/status.cgi.js`, `www/scripts/status.bundle.min.js`
- `frontend/src/js/view_records.js` -> `www/scripts/view_records.bundle.min.js`
- `frontend/src/css/ui-modern.css` -> `www/css/ui-modern.css`, `www/css/ui-modern.min.css`

Use:

```bash
npm run build:web
npm run check:web
```

## Recent Enhancements

### Complete Push-To-Talk (PTT) UI (Feature #4)
- **Audio Recording**: Hold PTT button to record voice messages (400ms - 9s limit)
- **Visual Feedback**: Status labels show recording/sending/sent/error states
- **Audio Level Meter**: Real-time display of microphone input level during recording
- **Test Speaker**: "Test" button to verify speaker audio playback with last recorded clip
- **Volume Control**: Adjustable PTT speaker output volume (0-100%)
- **Cross-Platform**: Works with touch, mouse, keyboard (Space/Enter to hold)

### Two-Way Audio (Feature #5)
- **Listen Mode**: "Listen" button streams audio from camera microphone in real-time
- **Browser Playback**: Uses HTML5 audio element for seamless listening
- **Session Management**: Auto-timeout after 30 seconds to conserve resources
- **Status Feedback**: UI shows connection status (Connecting... → Listening... → Listen)
- **Network-Friendly**: Minimal bandwidth usage with automatic client-side timeout

## Features

### PTT Controls
- **Hold to Talk**: Press and hold button to record voice message
- **Visual Meter**: See audio input levels during recording
- **Speaker Test**: Verify speaker is working before relying on two-way audio
- **Error Handling**: Clear feedback for too-short clips, no audio, connection issues
- **Mobile Friendly**: Touch, mouse, and keyboard support

### Two-Way Audio Stream
- **Real-Time Listening**: Monitor what the camera picks up remotely
- **Auto-Reconnect**: Attempts to reconnect if stream drops
- **Resource Aware**: Auto-disconnects after 30s to prevent resource exhaustion on low-memory devices
- **Security**: Streams only to authenticated browser sessions

## Notes

- This first pass is intentionally zero-dependency and offline-friendly.
- The build currently copies source bytes exactly to the shipped asset paths.
- `.bundle.min.js` and `.min.css` are legacy deploy filenames; they are not re-minified yet.
- PTT requires HTTPS or localhost for microphone access (browser security policy)
- Two-way audio streaming requires compatible audio capture binary on device (`arecord` or similar)
- Both features are optional and degradable (UI shows appropriate messages if unavailable)

