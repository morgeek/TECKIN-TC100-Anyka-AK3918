# Two-way audio: talk through the camera from Home Assistant, Frigate or go2rtc

With *Two-way audio* on (Settings → Video → RTSP server, on by default) and a camera password set, the RTSP server of the camera (`tc100_rtsp`) accepts sound sent back over the RTSP connection. This is the ONVIF "backchannel" that go2rtc uses, and it is played on the camera's speaker.

Anything that goes through go2rtc can use it: go2rtc's own page, Frigate's live view, and Home Assistant's WebRTC card.

How it works:
1. go2rtc connects to the camera as usual, and asks for the backchannel.
2. The camera answers with an extra audio track that it receives (G.711 A-law, 8 kHz), over TCP or UDP.
3. When you press the microphone button, your browser sends your voice to go2rtc over WebRTC. go2rtc passes it to the camera on that track.
4. The camera decodes it and plays it on the speaker. The volume is the push-to-talk volume (Live view → push-to-talk volume, `/mnt/config/pttvolume.conf`).

Only one person can talk at a time. A second one is ignored until the first has been silent for 2 s.

## 1. The go2rtc stream

The stream must point **directly at the camera's RTSP address**. An `ffmpeg:` source has no backchannel.

```yaml
go2rtc:
  streams:
    camera1: rtsp://USER:PASSWORD@CAMERA-IP:554/video0_unicast
```

This is the stream that the Frigate configuration from the camera already uses (Live view → More tools → Diagnostics). go2rtc asks for the backchannel on its own; there is nothing to add.

**Check it.** On go2rtc's page (`http://GO2RTC-HOST:1984/`, or Frigate → System → go2rtc if it is exposed), open the stream's info. The producer should list three media:

```
video, recvonly, H265
audio, recvonly, PCMA/8000
audio, sendonly, PCMA/8000                <- the backchannel
```

If the third line is missing:
- two-way audio is off, or the camera has no password: see Settings → Video → RTSP server and Settings → System;
- or the stream is not a plain `rtsp://` source.

## 2. Talk from go2rtc's page

Open:

```
https://GO2RTC-HOST:1984/webrtc.html?src=camera1&media=video+audio+microphone
```

Allow the microphone, then speak.

Browsers only give the microphone to pages served over **HTTPS** (or from `localhost`). Over plain `http://` from another computer, the button does nothing.

## 3. Talk from Frigate

Recent versions of Frigate (0.14 and later) show a microphone button in the live view of a camera whose go2rtc stream has a backchannel. It needs:
- **HTTPS**, for the same browser reason;
- the camera's live view going through the go2rtc stream above. The `live` → `stream_name` of the camera in Frigate's configuration should be that stream.

## 4. Talk from Home Assistant

Use the **WebRTC Camera** card (HACS: "WebRTC Camera" by AlexxIT), pointed at the same go2rtc stream:

```yaml
type: custom:webrtc-camera
url: camera1                 # the go2rtc stream name
server: http://GO2RTC-HOST:1984/
media: video,audio,microphone
```

Home Assistant itself must be opened over HTTPS (Nabu Casa, a reverse proxy, or HTTPS in Home Assistant) for the browser to allow the microphone. The Home Assistant app on a phone works the same way.

## 5. Send a sound file (automations)

go2rtc can play a file or a URL to a camera through its API. For example, a chime when the doorbell rings:

```
curl -X POST "http://GO2RTC-HOST:1984/api/streams?dst=camera1&src=ffmpeg:/config/chime.wav%23audio=pcma%23input=file"
```

In Home Assistant this fits in a `rest_command`. go2rtc converts the file to G.711 with ffmpeg.

## Troubleshooting

- `/tmp/logs/tc100_rtsp.log` on the camera (System → Logs) logs `talk: client N talks` when sound comes in and `talk: end (... packets, ... dropped)` 2 s after it stops.
- **Nothing heard**: check the push-to-talk volume, which is shared; then that the browser page is HTTPS and that the microphone permission was granted.
- The web page's own push-to-talk answers "busy" while someone talks through the stream, and the other way round.
- Two-way audio needs the RTSP password: no client can use the speaker without it. It can be turned off in the same card.
