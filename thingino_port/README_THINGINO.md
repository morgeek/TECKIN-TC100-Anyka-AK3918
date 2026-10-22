# Thingino Port for Anyka AK3918EV300 (TECKIN TC100)

This directory provides the initial Board Support Package (BSP), Buildroot configs, kernel patches, and device metadata required to integrate the **Anyka AK3918EV300** SoC family and the **TECKIN TC100** camera into [Thingino Firmware](https://github.com/themactep/thingino-firmware).

---

## 1. Hardware Specifications

| Component | Specification |
| :--- | :--- |
| **SoC** | Anyka AK3918EV300 (ARM926EJ-S @ 400 MHz, ARMv5TEJ) |
| **Memory** | 64 MB DDR2 SIP (`0x80000000 - 0x84000000`) |
| **ISP DMA Window** | 24 MB reserved (`0x81400000 - 0x82c00000`) |
| **Sensor** | Silicon Optronics SOI JX-F23 (1080p CMOS) via MIPI/DVP |
| **Flash** | 16 MB SPI NOR Flash (Winbond W25Q128) |
| **Wi-Fi** | Realtek RTL8188FU (USB 2.0, 802.11b/g/n, VID 0bda / PID f179) |
| **Audio** | Internal AK codec, Onboard Speaker (Amplifier GPIO 79), Micro |
| **IR / Nightvision** | IR LED Driver (GPIO 5), IRCUT Switch (GPIO 2 / GPIO 3) |
| **Status LEDs** | Blue LED (GPIO 25), Red LED (GPIO 26) |
| **Reset Button** | GPIO 84 (Active Low) |
| **Serial Debug** | 115200 8N1 (UART RX/TX testpads next to SD slot) |

---

## 2. Directory Structure

```
thingino_port/
├── configs/
│   ├── fragments/
│   │   └── soc-arm926ejs.fragment            # ARMv5TEJ toolchain & target flags
│   └── cameras/
│       └── teckin_tc100_ak3918ev300_jxf23_rtl8188fu/
│           ├── thingino.json                  # Camera GPIO definitions & modules
│           └── teckin_tc100_..._defconfig    # Board defconfig for Thingino
├── kernel/
│   └── ak3918ev300_linux_4.4.config          # Known-good Linux 4.4.302 kernel config
├── patches/
│   ├── 0001-add-anyka-soc-vendor-to-thingino.patch
│   └── 0002-disable-gpiokeys-ak3918ev300-dts.patch
├── soc/
│   └── anyka/
│       └── ak3918.mk                         # SoC family build rules
└── README_THINGINO.md
```

---

## 3. Safe Dual-Boot Architecture (Zero Flash Brick Risk)

In order to develop and test Thingino without touching the SPI NOR bootloader or bricking the camera, U-Boot's environment partition (`0x23a000`) is configured with a safe fallback:

1. **U-Boot SD Autodetection**:
   ```
   fatload mmc 0:1 0x82000000 tc100test/oipc.img;
   fatload mmc 0:1 0x80900000 tc100test/oipcrd.gz;
   bootm 0x82000000
   ```
2. **Crucial RAM Placement Rule**:
   - The Anyka ISP driver dynamically reserves `0x81400000` to `0x82c00000` (24 MB) for hardware video buffers.
   - Any initramfs/rootfs loaded into this region gets wiped during early boot (`VFS: Cannot open root device "ram0": error -6`).
   - Rootfs must strictly be loaded at `0x80900000` (`initrd=0x80900000,<filesize>`).
3. **Safety Fallback**:
   - If no MicroSD card is inserted, `fatload` fails instantly and U-Boot falls back to `run boot_normal`, booting the factory/stock firmware safely from SPI NOR.

---

## 4. GPIO Mapping & Controls (`thingino.json`)

```json
{
  "camera": {
    "model": "TECKIN TC100",
    "vendor": "TECKIN",
    "soc": "ak3918ev300",
    "sensor": "jxf23",
    "flash_size": 16,
    "ram_size": 64
  },
  "gpio": {
    "blue_led": 25,
    "red_led": 26,
    "ir_led": 5,
    "ircut_p": 2,
    "ircut_n": 3,
    "speaker_amp": 79,
    "reset_button": 84
  }
}
```

---

## 5. Streaming & Live Preview (Thingino Integration)

Thingino WebUI previews streams via HTTP multipart MJPEG and JPEG snapshots rather than browser-native RTSP.

### Supported Video Endpoints:
- **Live MJPEG Stream (Ch0)**: `http://<camera_ip>/cgi-bin/ch0.mjpg`
- **Still Snapshot (Ch0)**: `http://<camera_ip>/cgi-bin/ch0.jpg`
- **RTSP Ch0 (Port 554)**: `rtsp://<camera_ip>:554/ch0`
- **RTSP Ch1 (Port 554)**: `rtsp://<camera_ip>:554/ch1`
- **OSD SEI Metadata**: `http://<camera_ip>/cgi-bin/json-osd-sei.cgi`

---

## 6. Live Hardware Verification Results

### Web Interface (Thingino WebUI)
- **URL**: `http://<camera-ip>`
- **Frontend**: Bootstrap 5.3 Dark theme, Thingino layout, dynamic live view and controls.
- **Authentication**: Native session cookie handling (`thingino_session`) via `/cgi-bin/login.cgi` verifying MD5/SHA-512 hashes in `/etc/shadow`.
- **System Endpoints**: Live metrics delivered via JSON (`/cgi-bin/info.cgi`, `/cgi-bin/json-heartbeat.cgi`, `/cgi-bin/api-key.cgi`).
- **Live Preview**: `/preview.html` continuously displays live frames via `/cgi-bin/ch0.mjpg` without browser plug-ins.

### Streamer (`thingino-rtsp-server`)
- **Binary**: Native static ELF binary (`thingino_port/bin/thingino-rtsp-server`, ~82 KB).
- **RTSP Port**: 554 (`rtsp://<camera-ip>:554/ch0` and `rtsp://<camera-ip>:554/ch1`).
- **Protocols**: RTSP/1.0, RFC 2326 compliant CSeq tracking, SDP negotiation (`m=video 0 RTP/AVP 96`), RTP packetizer, TCP interleaved + UDP streaming.
- **Memory Footprint**: Minimal (~1 MB RAM), preventing any OOM crashes on 64 MB SIP RAM architectures.
