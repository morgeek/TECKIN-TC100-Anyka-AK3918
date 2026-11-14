# WIFI-STALL-01: where are the frames held? (read-only analysis, 2026-11-14)

Sources read: `/home/claude/scratch/linux-src` (v6.6 + patches 0004/0018/0019/0020). "V" = verified in the code,
"I" = inferred. Nothing was built or run.

## Verdict

- The counters do **not** prove "held above the driver". `tx_packets` is not a "left mac80211" counter (see below), and
  `tx_last_ms` never exceeds 480 ms in 33 stall samples: something is handed to the chip at least twice a second,
  which is the cadence of the echo replies. Most likely the frames **do reach the chip and the air**.
- Best fit (I): a TX BlockAck session is operational on TID 0, the chip silently drops one MPDU, nobody sends a
  BlockAck Request, and the **AP's reorder buffer** holds every later TID 0 frame until its own flush. TCP then
  collapses to a few frames per second, so the 64-frame window no longer advances by itself.
- Second: the mac80211 ADDBA handshake (TID queue stopped 1 s per unanswered request, 4 requests in a row = 4 s).
  The arithmetic fits, the ping pattern and `tx_last_ms` do not.
- AQL, airtime fairness and queue stop reasons are ruled out by the code.
- One free test splits the candidates (a second ping on another TID); the fix candidate is a runtime `ampdu_tx` switch.

## Ranked mechanisms

**0. What the existing counters mean (V).** `tx_packets` is incremented in `ieee80211_xmit_fast_finish()`
(`tx.c:3544`), which for an iTXQ driver runs at **dequeue** (`tx.c:3895-3904`), and in the slow path at **enqueue**
(`tx.c:4314`). A frame takes the slow path whenever a `tid_tx` exists and is not OPERATIONAL (`tx.c:3759-3761`). So
3-4/s during a stall is compatible with both "held in the iTXQ" and "passed to the driver". `tx retries`/`tx failed`
= 0 is meaningless: `rtl8xxxu_tx_complete()` sets `IEEE80211_TX_STAT_ACK` whenever the URB succeeded
(`rtl8xxxu_core.c:5296-5307`).

**1. AP-side reorder hole, no BAR (I, built on V facts).**
- V: the driver opens a TX BA session on every TID at the first QoS data frame
  (`rtl8xxxu_core.c:5667-5670`, timeout 0), returns `IEEE80211_AMPDU_TX_START_IMMEDIATE` (`:6962`), sets
  `tid_tx_operational` on TX_OPERATIONAL (`:6975`), and then sends with `TXDESC40_AGG_ENABLE` (`:5453`).
- V: mac80211 sends a BAR only if the driver reports `IEEE80211_TX_STAT_AMPDU_NO_BACK` (`status.c:963-973`); rtl8xxxu
  never does. The TX descriptor is zeroed (`:5624`) and no BAR retry field is set.
- V: the 8188F has a 256 ms packet lifetime programmed (`rtl8xxxu_8188f.c:1756`, `rtl8xxxu_core.c:4399-4401`) and a
  retry limit of 0x30 (`:4343`): a frame the chip cannot deliver is dropped, with no trace on the host.
- I: after such a drop the AP waits for the missing sequence number. At 244 frames/s the window passes it in 0.26 s
  (invisible); once TCP has backed off to ~4 frames/s it does not, and the AP releases everything at its own timeout.
  This gives delayed-not-lost replies in 0.5 s steps, a burst, an idle driver, live RX, and "only the camera whose
  frames get dropped".
- Weak point: the 4-5 s is the AP's flush time, which I cannot read anywhere.

**2. mac80211 ADDBA handshake holding the TID queue (V mechanism, poor fit).**
- V: at session start the work sets `IEEE80211_TXQ_STOP` on the TID's txq (`ht.c:395-402`);
  `ieee80211_tx_dequeue()` then returns nothing for it (`tx.c:3828`). It is cleared only by
  `ieee80211_agg_start_txq()` (`agg-tx.c:211-235`) on ADDBA response (`:795`), on stop (`:956`) or on driver
  refusal (`:554`).
- V: `ADDBA_RESP_INTERVAL` = 1 s (`sta_info.h:111`, `agg-tx.c:467`). On timeout the session stops, the driver clears
  `tx_aggr_started` (`:6969`), and the next frame starts a new one. After more than `HT_AGG_BURST_RETRIES` = 3
  requests further ones are refused for 15 s (`agg-tx.c:695-697`): 4 x 1 s, then a pause. Other TIDs and management
  frames keep flowing.
- Against: the queue drains between attempts (so ping RTT would saw-tooth at <= 1 s, not reach 4.8 s), completions
  would be ~1 s apart, and after 16 failures it stops for good (`agg-tx.c:685`), whereas the stalls go on.
- Needs a trigger too: the AP tearing the session down (DELBA) and then not answering.

**3. Chip not transmitting (CCA busy / receiver saturation, old H7) (I).** Frames would wait in the chip FIFO
(0xf7 pages, `rtl8xxxu.h:38`) without NAK at 4 frames/s. The 256 ms lifetime argues for loss rather than a 4.8 s delay,
if the chip enforces it.

**4. Crystal-cap CFO tracking (V code, I effect).** The 2 s watchdog moves the crystal cap one step per run while
|CFO| > 20 kHz until < 10 kHz (`rtl8xxxu_core.c:7163-7230`, `:7260`, `rtl8xxxu.h:1761-1763`). A wrong CFO reading
would detune TX for a few watchdog periods. Would give loss, not delay.

**Ruled out (V).** AQL and airtime fairness: every check is gated on `NL80211_EXT_FEATURE_AQL` /
airtime fairness (`tx.c:3962`, `:4129`, `:4163`), and rtl8xxxu sets only `CQM_RSSI_LIST` (`rtl8xxxu_core.c:7748`).
Driver queue stops: counted, unchanged. TX BA session idle timer: timeout 0 from the driver; an AP-supplied timeout
is refreshed by every frame (`tx.c:3763`). IQ calibration / `REG_TXPAUSE`: only at init and stop (`:4467-4469`).

## Decisive observations

1. **No kernel change, do first.** Run two Mac pings at once: the normal one, and one with a TOS that maps to another
   TID (`ping -z 0xb8 -i 0.5 <camera>`; the echo reply copies the TOS, so it leaves on TID 5).
   - TOS ping on time while the normal one stalls: per-TID hold, so mechanism 1 or 2.
   - Both stall: chip or air, mechanism 3 or 4.
2. **Counters (0444, same macro as 0020), all in `rtl8xxxu_core.c`:**
   - `ba_tx_start`, `ba_tx_oper`, `ba_tx_stop`: in `rtl8xxxu_ampdu_action()` at `:6953`, `:6973`, `:6963`.
     Flat during a stall with `ba_tx_oper` >= 1 points to mechanism 1; `ba_tx_start` +3/+4 and `ba_tx_stop` moving in
     the stall seconds is mechanism 2.
   - `tx_qos_data` and `tx_other`: in `rtl8xxxu_tx()` next to `:5655` (QoS data with `sta`) and its else case.
     `tx_qos_data` rising 2-4/s during a stall proves the replies reach the driver (refutes 2).
   - `xtal_cap`: mirror of `cfo->crystal_cap`, written at the end of `rtl8188f_set_crystal_cap()`
     (`rtl8xxxu_8188f.c:1660`). A change in the stall seconds supports 4.
3. Optional: the macOS sniffer on channel 3 would show the camera's frames ACKed during a stall with a
   sequence-number gap (mechanism 1).

## Proposed fix/switch

Runtime switch, default unchanged (`Y`), mirroring `ampdu_rx` (patch 0018). Gate the **call site**, not TX_START:
refusing TX_START makes mac80211 stop and restart the txq with a `synchronize_net()` on every frame, because
`addba_req_num` is only incremented when a request is sent (`agg-tx.c:473`).

```diff
+static bool rtl8xxxu_ampdu_tx = true;
+module_param_named(ampdu_tx, rtl8xxxu_ampdu_tx, bool, 0644);
+MODULE_PARM_DESC(ampdu_tx, "Open TX A-MPDU (BlockAck) sessions (default Y)");
@@ rtl8xxxu_tx()
-			if (!test_bit(tid, priv->tx_aggr_started) &&
+			if (rtl8xxxu_ampdu_tx &&
+			    !test_bit(tid, priv->tx_aggr_started) &&
 			    !(skb->protocol == cpu_to_be16(ETH_P_PAE)))
```

- Use: `echo 0 > /sys/module/rtl8xxxu/parameters/ampdu_tx && wpa_cli -i wlan0 reassociate`. An existing session
  stays until the reassociation; a few lines calling `ieee80211_stop_tx_ba_session()` when the bit is set and the
  switch is off would make it live, at the cost of more code.
- Effect: no BA agreement, so the AP has no reorder buffer for the camera and every MPDU is ACKed singly. This
  removes mechanisms 1 and 2 together.
- Risk: lower peak throughput (single MPDUs at MCS 7, still far above the 1.5 Mbit/s stream) and more airtime.
  `ampdu_enable` stays true, so frames keep hardware RTS and `AGG_BREAK`, exactly as before a session exists today.
- Clearing `IEEE80211_HW_AMPDU_AGGREGATION` is not suitable: it also removes RX aggregation and is not runtime.
- If test 1 says "both stall", this switch will not help: try `tx_atten` (0019) or distance for 3, and a `cfo_track`
  bool skipping `rtl8xxxu_track_cfo()` at `:7260` for 4.

## What I did not check

- Whether the 8188F firmware sends a BAR by itself or enforces the 256 ms lifetime (no firmware source); the AP's
  reorder flush time; the AP model.
- Whether a TX BA session is actually operational on this camera (nothing exposes it without the counters).
- Whether the RTSP client used TCP or UDP in this run, and whether the Mac `ping -z` value reaches the camera
  unchanged through the AP.
- `ieee80211_next_txq()` / fq internals beyond the gates listed, and patch 0021's code beyond its parameter
  descriptions.
- Why the second camera is spared: I assume fewer dropped MPDUs, not verified.
