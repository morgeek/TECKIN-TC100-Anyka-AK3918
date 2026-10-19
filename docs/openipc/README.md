# TECKIN TC100 (Anyka AK3918EV300) — Hardware Findings & OpenIPC Diagnostic Report

Collected via Raspberry Pi Pico 2 DebugProbe (UART console @ 115200 8N1) on live hardware running the **OpenIPC Linux 4.4.302-ak3918ev300** kernel completely in-RAM.

Related OpenIPC issue: **[OpenIPC/firmware#2639](https://github.com/OpenIPC/firmware/issues/2639)**

---

## 1. Hardware Summary

* **Camera Model**: TECKIN TC100 / TECKIN Click (PCB: `YZ01-V1.0.0`)
* **SoC**: Anyka **AK3918EV300** (Chip ID: `0x20160100`, ARM926EJ-S rev 5 @ 400 MHz)
* **DRAM**: 64 MiB SIP DDR2 (24 MiB reserved for video DMA @ `0x81400000`, 35 MB available to Linux)
* **Image Sensor**: SOI **JX-F23** (Sensor ID: `0xf23`, I2C Bus 0 @ `0x40`)
* **Wi-Fi Chipset**: Realtek **RTL8188FU** / RTL8188FTV (USB VID:PID `0bda:f179`, internal USB host)
* **SPI NOR Flash**: XMC **XM25QH64A** (JEDEC `0x207017`, 8 MiB)
* **Audio**: Anyka integrated AD/DA codec (`akpcm`), built-in mic + speaker amplifier
* **Ethernet**: GMAC present on SoC, but **no PHY** on this camera board

---

## 2. Pinout & Verified GPIO Assignments

| Function | Pin / GPIO | Active Level | Verified Source | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Reset Button** | **GPIO 10** | Active LOW | Hardware test & U-Boot | `reset pin value: 1` released, `0` pressed. |
| **Factory Recovery** | **GPIO 82** | Active LOW | Stock U-Boot | Reads `0` to enter recovery boot. |
| **IR Night LEDs** | **GPIO 5** | Active HIGH | Device Tree (`/leds/ir_led/gpios`) | Controls the infrared night illuminators. |
| **Speaker Enable** | **GPIO 79** | Active HIGH | Device Tree (`/soc/adc_dac/speak-gpios`) | Power enable for on-board speaker amplifier. |
| **Sensor Reset** | **GPIO 49** | Active LOW | Device Tree (`/soc/i2c0/camera/reset-gpio`) | Hardware reset line for JX-F23 sensor. |
| **Status LEDs** | **GPIO 0, 5, 16** | TBD | Pinmux (`led_pins`, `ircut_pins`) | Dual-color status indicators. |
| **IR-Cut Filter** | **GPIO 0 / 16** | H-Bridge pulse | Pinmux (`ircut_pins`) | Mechanical day/night IR-cut switcher. |

> **Crucial Kernel Fix**: The generic Anyka DTS maps `gpiokeys` to GPIO 84. On the TC100, probing GPIO 84 causes an IRQ storm/infinite wait that freezes kernel boot. Booting with `initcall_blacklist=gpio_keys_init` (or remapping to GPIO 10) allows the kernel to reach userspace.

---

## 3. Subsystem Breakdown

### A. Video & Camera Sensor (`/dev/video0`)
* **Sensor**: SOI **JX-F23** (ID `0xf23`) responding on I2C-0 address `0x40` (8-bit `0x80`).
* **ISP Driver**: `ak_camera` (`20000000.isp`) automatically attaches to the sensor.
* **DMA Memory Pool**: 24 MiB dedicated CMA capture pool reserved at `0x81400000`.
* **Device Node**: `/dev/video0` is created and functional in userspace out of the box!

### B. USB & Wi-Fi
* **USB Host Controller**: `20200000.usb` initialized by `otg-hs.ko`.
* **Enumerated Device**:
  * Bus 001 Device 002: ID `0bda:f179`
  * Manufacturer: `Realtek`, Product: `802.11n`
* **Driver Status**:
  * The generic OpenIPC build supplies `r8188eu.ko` (which targets `0bda:8179` for RTL8188EU).
  * While `r8188eu` can bind via `new_id` and create `wlan0`, the RF synthesizer on the **RTL8188FU** cannot lock with 8188E calibration registers (resulting in 0 AP scan results).
  * **Solution for OpenIPC**: Compile the dedicated **`rtl8188fu.ko`** driver for the 4.4.302 kernel.

### C. Audio Subsystem
* ALSA driver `akpcm` (Anyka AD/DA) is registered and active:
  * `card 0 [ADDA]: akpcm - Ak AD/DA (Ak ADC DAC pcm input & output module 1)`
  * Speaker amplifier gate is on **GPIO 79**.

### D. SD / MMC Controller (`CMD18: -84`)
* MMC controller: `20100000.mmc0` (`akmci`).
* Error `-84` (`-EILSEQ` / CRC framing error) occurs on high-capacity SDXC cards at 50 MHz High-Speed mode.
* Capping the clock to 25 MHz (standard speed) or adjusting the clock phase in the driver will resolve SD card mounting.

---

## 4. Directory Contents

* **`01-system-info.txt`**: Kernel version, command line, cpuinfo, meminfo, mtd, iomem, interrupts, and modules.
* **`02-dmesg-full.log`**: Full kernel boot log from startup to login prompt.
* **`03-gpio-pinctrl.txt`**: Debug GPIO state, pinctrl pinmux mappings, and decoded hardware pins.
* **`04-i2c-sensor-video.txt`**: I2C bus scan, `/dev/video0` node, and ISP probe logs.
* **`05-usb-wifi.txt`**: USB host controller info, `lsusb`, and RTL8188FU device attributes.
* **`06-audio.txt`**: ALSA sound cards, PCM nodes, and audio codec init logs.
* **`07-mmc-storage.txt`**: MMC controller state, clock, block partitions, and driver logs.
* **`devicetree.dts`**: **Decompiled, human-readable Device Tree** (2,257 lines) extracted directly from the running kernel.
* **`devicetree.tar.gz`**: Raw extracted `/sys/firmware/devicetree/base` directory tree.
