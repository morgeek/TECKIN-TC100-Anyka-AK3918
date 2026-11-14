# WIFI-STALL-01 step "counters", .11, rc43 (2026-11-14 10:00-10:09 UTC)
Read-only. `wifi-stall-watch.sh 660` on the camera (1 line/s) + Mac `ping -D -i 0.5` (3 x 330). Link: channel 3, 20 MHz,
MCS 7 short GI 72.2 Mbit/s, `iw link` signal -51 dBm (`/proc/net/wireless` level -16 a minute later), power save off,
`tx retries` / `tx failed` / `beacon loss` 0, one RTSP client (main stream ~1.5 Mbit/s). wlan0: one TX queue (`tx-0`),
`tx_queue_len 1000`, no CONFIG_NET_SCHED (default qdisc), `tx_dropped=0`, `tx_errors=0`, no debugfs.
rtl8xxxu uses mac80211 iTXQ (`.wake_tx_queue = ieee80211_handle_wake_tx_queue`), `ampdu_rx=Y`.

Mac pings: 990 sent, 1.2 / 4.2 / 0 % loss per chunk, max RTT 4.8 s. **7 stall windows of 4-5 s** (send..receive of the
replies > 800 ms): 10:03:02, 10:03:24, 10:04:43, 10:04:53, 10:05:31, 10:06:31, 10:07:46.

| counter | normal seconds (403) min / median / max | stall seconds (33) min / median / max |
|---|---|---|
| tx/s (wlan0 tx_packets) | 3 / 244 / 918 | 2 / **4** / 515 |
| rx/s | 4 / 137 / 497 | 4 / 11 / 235 |
| USB irq/s | 19 / 922 / 3915 | 19 / 38 / 2106 |
| tx_urb_free (of 64) | 64 / 64 / 64 | **64 / 64 / 64** |
| tx_urb_min | 24 (since boot) | 24 |
| txq_stops / txq_wakes | 14-16 (all before the run except +2 in a normal second) | **16, no change** |
| tx_urb_err, rx_urb_lost | 0 | 0 |
| rx_urb_alive | 32 | 32 |
| bulk_out_nak / bulk_in_nak | 0 / 0 | **0 / 0** |
| bulk_out_oldest_ms | 0 | **0** |
| tx_last_ms | -10 / 10 / 400 | 0 / 160 / 480 |
| bulk_in_oldest_ms | 0 / 10 / 90 | 0 / 30 / 140 |

Two windows second by second (STALL = Mac reply late):
```
time     tx/s rx/s irq/s urb_free txq_stops tx_last_ms bulk_in_old
10:03:01  196  115   707       64        16         40           0
10:03:02  269  143  1031       64        16          0          20  STALL
10:03:03   73   18   213       64        16        180         100  STALL
10:03:04    3    6    40       64        16        330          60  STALL
10:03:05    3    6    21       64        16        170          30  STALL
10:03:07  363  188  2079       64        16         20          30  STALL
10:03:08  523  268  1750       64        16         40          10
10:04:40    4    8    38       64        16         30          90
10:04:41    3    4    19       64        16        400          50
10:04:43    4    6    30       64        16        180          40  STALL
10:04:44    3    8    22       64        16        170           0  STALL
10:04:45    3    6    29       64        16         30          70  STALL
10:04:46    5   10    35       64        16        220          40  STALL
10:04:47    3   12    29       64        16        420          20  STALL
10:04:49  512  212  2259       64        16         10          10
```
**Reading:** during a stall the USB / TX URB path is idle, not stuck: all 64 TX URBs free, no driver queue stop, no
NAK, nothing pending on bulk OUT, a few TX completions every second (`tx_last_ms` < 0.5 s). wlan0 `tx_packets` falls to
~4/s while (2026-11-13 steps 1-3) the ICMP layer still answers ~2.5 echo requests / s and beacons keep arriving: the data
frames are held **above the driver** (qdisc / netdev queue / mac80211 iTXQ, per-TID aggregation state, ...), then
released in a burst (tx/s 363-523, irq/s ~2000-2260 in the second after). The 2026-11-13 H5 mechanism "TX URBs stuck in
the HCD" is refuted; "TX side" still holds.
