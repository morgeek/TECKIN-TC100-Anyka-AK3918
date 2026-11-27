# `[up-fuzz]`: libFuzzer on the network parsers (plan phase 1, audit SEC-5)

Stream of the [3.2 upgrade](README.md). The audit of 2026-11-27 ([SEC-5](../audit-2026-11-27-security.md)) found no fuzzing of
the C code that reads the network. This stream adds one libFuzzer harness per input path of the six daemons, a seed corpus of
real client traffic, a CI job that runs every harness at each push, and a local entry. It is **host only** (x86, clang with
AddressSanitizer and UBSan): nothing of it is built into the camera image, and the camera sees no difference except two
small daemon changes listed under "Changes to the daemons".

| | |
|---|---|
| Switch to turn it off | none needed: CI and tests only. The CI job is `fuzz` of `.github/workflows/ci.yml` (delete the job to stop it) |
| Files | `tests/fuzz/` (harnesses `fuzz_*.c`, `fz.h`, `run.sh`, `*.dict`, `gen_seeds.py`, `corpus/<target>/`), `tests/test_fuzz_setup.py` |
| Camera test | only because two daemons changed: see the last section |

## Targets and entry points

Each harness includes the daemon's own C file (so the code that runs is the shipped code, not a copy) with its `main()` renamed,
sets up the few globals a real run would have, and feeds the fuzzer input to the same function the daemon calls on the bytes it
received. The input of every target is "byte 0 = switches (password on or off, state, where a read is cut in two) + the bytes
of the peer"; the switches are described in the header comment of each harness. Reads past the end of the input are caught
because the input is copied into a heap block of exactly its size.

| Target | Entry point (file:line) | What it covers |
|---|---|---|
| `rtsp_req` | `cli_read()` `src/tc100rtsp/tc100_rtsp.c:3251` (with `handle()` :3049) | the byte stream of an RTSP client over a socket: request line, headers (`hdr()`), CSeq, Content-Length and body, DESCRIBE with `Require: ...backchannel`, SETUP and its Transport (TCP `interleaved=`, UDP `client_port=`, tracks 1 to 3), PLAY, TEARDOWN, blank lines between requests, interleaved `$` frames (RTCP, talk RTP on the backchannel channel), partial reads (three cuts), the password check on or off |
| `rtsp_auth` | `auth_ok()` :2087 (`field()`, `url_path()`, `uri_covers()`, `b64dec`, MD5) | the Authorization header, Basic and Digest, with a nonce held or not; fast (about 2 M runs a minute) |
| `rtsp_talk` | `talk_rtp()` `src/tc100rtsp/talk.c:238` | one RTP packet of the client's backchannel (G.711 A-law): CSRC list, header extension, padding, ownership of the speaker; the player is a script of ours that discards the sound |
| `httpfront` | `serve()` `src/httpfront/httpfront.c:448` (`hdr_bad()` :228, `auth_count()`, `login_ok()` :301, `pl_route()` `poll.h:40`, `b64dec`/`md5crypt`) | what the front does with the first 4095 bytes of a connection: request line, `GET /` and `/metrics` redirects, header canonicalisation (400, 431), the Authorization header, the query string of the native routes, the Basic login against four `/etc/httpd.conf` variants (MD5 crypt, plain, none, broken), lockout and native status on or off |
| `onvif_soap` | `handle_soap()` `src/onvifd/onvifd.c:1574` (`body_action()`, `find_elem()`, `get_text()`, `check_auth()` :842, every `op_*`) | a SOAP envelope for each of the five services, with a password set: WS-Security UsernameToken (PasswordText and PasswordDigest, nonce, Created, replay table), the arguments of every operation (GetStreamUri, CreatePullPointSubscription, Renew, PullMessages, ...) |
| `onvif_http` | `conn_read()` :1715 (`process()`, `hdr_val()`) | the HTTP framing of an ONVIF client over a socket: request line, Content-Length, 413, service and subscription id from the path, partial reads |
| `onvif_wsd` | `udp_in()` :1835 | a WS-Discovery datagram on UDP 3702: Probe, Resolve, Types filter, MessageID, the answer rate limit; the answer goes to a socket of ours |
| `mqttd` | `parse_in()` `src/mqttd/mqttd.c:800` (`on_packet()` :751) | the packets a broker sends, in the states "waiting for CONNACK" and "up": fixed header, remaining length, CONNACK, PUBLISH (QoS, retain, topic length, a command payload with NUL, CR, LF), SUBACK, PINGRESP; two reads |
| `whep_stun` | `stun_parse()` `src/whep/whep_proto.h:46`, `stun_check_integrity()`, `stun_binding_response()` | a STUN message on the gateway's UDP port before any session exists (attributes, FINGERPRINT, MESSAGE-INTEGRITY) |
| `whep_sdp` | `sdp_parse_offer()` :201, `sdp_pick_h264()`, `sdp_pick_pcma()`, `sdp_answer()` | the body of `POST /whep`: the SDP offer of a browser, then the answer built from it exactly as `whep_post()` does, into a buffer of the daemon's size |
| `whep_hello` | `wh_chello_feed()` :388 | the first DTLS datagrams: a ClientHello in several fragments (Chrome's post-quantum key share), reassembled |
| `whep_misc` | `wh_b64()`, `wh_nets_parse()`, `wh_nets_ok()` | the `sprop-parameter-sets` base64 and the `TC100_NET_ALLOW` list |
| `mdns` | `mdns_answer()` `src/mdnsd/mdns_pkt.h:101`, `mdns_sd_answer_lazy()` :311, the rate limiter | an mDNS query: name compression, up to 16 questions, A / AAAA / ANY / PTR / SRV / TXT, legacy unicast; answers written into exact-size buffers |

`whep_*` includes `whep_proto.h` only. It never includes `tc100_whep.c` (Mbed TLS, being ported to 3.6 by `[up-base]`), so the
harness does not move when the TLS code does.

## Running it

```sh
sh tests/docker/local-ci.sh fuzz            # Docker (Git Bash on Windows too): clang 18 on ubuntu:24.04 as the CI runner, 60 s per target
FUZZ_SECONDS=600 sh tests/docker/local-ci.sh fuzz   # a longer run; crash inputs and logs in tests/fuzz/out/<target>/
```

On a Linux host with clang (libFuzzer and the sanitizers come with the `clang` package of Ubuntu 24.04 and Debian):

```sh
sh tests/fuzz/run.sh                        # build all 13, run each 60 s, 4 at a time (what the CI job does)
sh tests/fuzz/run.sh -t 600 -j 13 mdns httpfront     # chosen targets, longer
sh tests/fuzz/run.sh -b                     # build only (does a harness still compile?)
sh tests/fuzz/run.sh -t 600 -k -o tests/fuzz/out     # go on from the inputs an earlier run found
```

`run.sh` copies the seeds of `tests/fuzz/corpus/<target>/` to its work directory first, so a run never changes what is in
git. A crash leaves `crash-<hash>` (also `timeout-`, `oom-`, `leak-`) next to the log in `OUTDIR/<target>/`, and the script
ends with status 1. To replay or minimise one:

```sh
tests/fuzz/out/bin/rtsp_req tests/fuzz/out/rtsp_req/crash-...                  # replays it (FZ_VERBOSE=1 shows the daemon's log lines)
tests/fuzz/out/bin/rtsp_req -minimize_crash=1 -runs=100000 tests/fuzz/out/rtsp_req/crash-...
```

From the Docker entry only the logs and the crash inputs come back to `tests/fuzz/out/<target>/` (the binaries stay in the
container); to replay one there:

```sh
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W 2>/dev/null || pwd):/src:ro" ubuntu:24.04 sh -c '
  apt-get update -qq && apt-get install -y -qq clang >/dev/null && cp -r /src /w && cd /w &&
  sh tests/fuzz/run.sh -b -o /tmp/o onvif_soap && FZ_VERBOSE=1 /tmp/o/bin/onvif_soap tests/fuzz/out/onvif_soap/crash-...'
```

A minimised input that is worth keeping goes to `tests/fuzz/corpus/<target>/regress-<what>` (that name is not written by the
generator and is kept by `tests/test_fuzz_setup.py`).

Seeds: `python3 tests/fuzz/gen_seeds.py` rebuilds every seed that is not a `regress-*` file. They are what real clients send
(VLC, ffmpeg and go2rtc RTSP requests with Basic and a computed Digest response; a Chrome browser's HTTP requests with
cookies and Basic logins; ONVIF Device Manager style SOAP with WS-Security digests that verify; mosquitto's CONNACK, SUBACK,
PINGRESP and PUBLISH; Chrome's STUN binding request with its integrity and fingerprint, and its SDP offer; a DTLS
ClientHello in three fragments; Avahi/macOS style mDNS queries) and a few that are hostile on purpose (two Authorization
headers, continuation lines, a pointer loop, a varint of five bytes). `.gitattributes` marks the corpus `binary`: CRLF and NUL
bytes must reach the fuzzer untouched. `rtsp.dict`, `onvif.dict`, `http.dict`, `mqttd.dict` and `whep_sdp.dict` are the
dictionaries.

The harness code shares `tests/fuzz/fz.h`: a fake clock (every read moves it 100 ms, so the per-address lockouts of the
daemons, 20 wrong logins a minute or 20 answers a second, do not shut a parser off after a few hundred inputs; the
fake `time()` stays inside a 200 s window so that a WS-Security `Created` of a seed keeps verifying), and a filter that keeps the
daemons' log lines on fd 2 out of the fuzzer's output.

## CI

Job `fuzz` of `.github/workflows/ci.yml` (on every push to `main` and `upgrade-3.2`, and on pull requests): installs clang
with apt, builds the 13 harnesses (4 at a time: 26 s on 4 CPUs) and runs each for 60 s (4 at a time: four batches), about 6
minutes in all (measured in Docker limited to 4 CPUs: 404 s with the apt install and a second build); the limit is 25 minutes. A crash, a timeout, an out-of-memory or a leak ends the job with a failure and uploads the inputs and the logs as the
artifact `fuzz-findings` (14 days). The job uses the same pinned actions as the others (`tests/test_ci_pinning.py` checks the
commit SHAs); apt packages are signed by the distribution, as for the other jobs. 60 s per push finds what a seed corpus
reaches quickly; the plan's "a longer one nightly" is a scheduled run of the same script with `-t 1800` and has not been
added (no nightly trigger exists in this CI yet).

`tests/test_fuzz_setup.py` (in the normal test run) checks that every target has a harness, seeds and its dictionary, that the
seeds in git are what `gen_seeds.py` writes, that the CI job and the local entry exist, and that the harness of the
gateway never includes the TLS code.

## Changes to the daemons

1. `src/httpfront/httpfront.c`: two `#ifdef TC100_FUZZ_HOST` / `#ifndef TC100_FUZZ_HOST` pairs. The file is freestanding ARM code
   (raw `svc 0` system calls and a `naked` `_start`), which cannot be built for x86; with the macro defined (only by
   `tests/fuzz/run.sh`) `sc()` is only declared (the harness gives a stand-in that serves the request from the input and
   answers the file reads from memory) and `_start` is left out. Without the macro the preprocessed file is the same as
   before; the ARM build of CI (`httpfront` with `-Wall`, hardening checks, qemu tests) is unchanged.
2. `src/onvifd/onvifd.c` `dur_s()` (:1417): the fix of the finding below.

No other daemon was touched; everything else is reached through the existing functions.

## Findings

Runs done while writing this stream, on a 12-core host, clang 18, ASan + UBSan, `-fno-sanitize-recover=undefined`:
a first round of 90 s (everything clean), then two rounds of 10 minutes per target, all 13 at once, the second one going on
from the inputs the first had found (`-k`); then 8 more minutes of `rtsp_req` after the talk seeds were added. Executions and
coverage (libFuzzer edges "cov") at the end of each 10-minute round:

| Target | Round 1: runs | Round 2: runs | cov | Result |
|---|---:|---:|---:|---|
| `rtsp_req` | 2 284 453 | 313 244 (+ 504 414 in the 8 min run) | 349 / 346 / 370 | clean |
| `rtsp_auth` | 34 109 527 | 17 312 478 | 106 | clean |
| `rtsp_talk` | 34 113 900 | 6 775 509 | 51 | clean |
| `httpfront` | 1 008 672 | 333 815 | 764 / 767 | clean |
| `onvif_soap` | 4 630 153 (stopped at the finding, 6 min) | 907 776 | 583 / 596 | **F1**, fixed, then clean |
| `onvif_http` | 3 771 590 | 1 070 340 | 650 / 664 | clean |
| `onvif_wsd` | 4 795 175 | 1 753 046 | 164 | clean |
| `mqttd` | 14 765 424 | 9 504 266 | 153 | clean |
| `whep_stun` | 80 641 590 | 97 025 783 | 73 | clean |
| `whep_sdp` | 14 156 389 | 1 640 132 | 181 | clean |
| `whep_hello` | 6 691 327 | 1 876 837 | 36 | clean |
| `whep_misc` | 44 976 826 | 16 268 360 | 69 | clean |
| `mdns` | 6 093 397 | 7 347 424 | 244 | clean |

(The second round is slower per target because the corpus was kept on a Windows bind mount.) The coverage is what the harness
reaches, not a percentage of the daemon: the parsers are small and the counts stop growing after a few minutes, which is
the sign that a 60 s CI run per push re-finds anything the seeds and dictionaries lead to, and that the part left is the one
listed under "What the harnesses do not reach".

### F1. `dur_s()` of tc100-onvifd: signed integer overflow on an ISO 8601 duration (fixed)

- **Input**: any SOAP request with a duration such as `<tev:InitialTerminationTime>PT999999H</tev:InitialTerminationTime>`
  (CreatePullPointSubscription), `<wsnt:TerminationTime>PT999999H</wsnt:TerminationTime>` (Renew) or `<tev:Timeout>PT999999H`
  (PullMessages). Found by `onvif_soap` after about 4.6 million runs; the input is kept as
  `tests/fuzz/corpus/onvif_soap/regress-dur-overflow-found` (485 bytes) and `regress-dur-overflow` (the clean version).
- **Cause**: `src/onvifd/onvifd.c` `dur_s()`: the digits accumulate in `n` up to 999999, and `tot += n * 3600` is an `int`
  multiplication: 999999 x 3600 does not fit 32 bits. The clamp `if (tot > 1000000)` came after the multiplication, so it did
  not prevent the overflow (undefined behaviour; with the usual wrap-around the result is a negative number).
- **Effect**: no memory corruption. The wrapped value is negative for every `n` above 596 523, so a Renew or subscription of
  "PT999999H" got the 5 s minimum instead of the 3600 s ceiling, and PullMessages did not wait. The caller clamps on both sides,
  which is why nothing worse happens. A UBSan report all the same, and the result depended on the compiler.
- **Fix** (minimal, behaviour unchanged for every duration that did not overflow): the product is computed in `long long`
  and the sum is clamped to 1 000 000 before it is stored.
- **Test**: `tests/test_onvifd.py` `test_duration_overflow_is_clamped` (a Renew with `PT999999H`, `PT999999H999999H`,
  `PT99999999999H` ends 3500 s or more ahead; `PT1H30M15S` still gets the ceiling), and the two regression inputs above.

### Open

No other crash, hang, leak or sanitizer report in the runs above, and nothing that needs a design decision. Two things
looked at while reading and found safe, noted so that nobody has to look again:

- `reply()` of `tc100_rtsp.c` (:2978) builds its answer with `n += snprintf(b + n, sizeof b - n, ...)` into `char b[2048]`: if
  `n` ever went past 2048 the next size argument would wrap. The worst case today is about 1.9 KB (a 272-byte Content-Base
  from the 255-character URL the client sent, a 1535-byte SDP buffer, about 120 bytes of headers), and the SDP is made of the
  server's own parameters, so no client input can reach the limit; a future longer header would have to keep that in mind.
- `num()` of `tc100_rtsp.c` and `num_at()` of `onvifd.c` already stop at 9 digits; `dur_s()` was the one place where a
  decoded number was multiplied.

## What the harnesses do not reach

- **tc100_rtsp**: RTCP and RTP received over UDP are not read by the server (only the backchannel's RTP, which `rtsp_talk`
  covers through `talk_rtp()`); the small matching loop of the UDP backchannel in `main()` (source address and port against the
  SETUP) is not run. The video, audio and recording paths (RTP packetisation, GOP cache, encoder, AAC, MP4) read no network input.
  The Digest *success* path is reached by `rtsp_auth` (computed seed) but a socket run with a held random nonce cannot
  match it.
- **httpfront**: only the first 4095 bytes of a connection are looked at. Everything after them (the method beyond
  `GET /`, the body, Content-Length, cookies, the CGI environment) is parsed by busybox `httpd`, which is not our code and is not
  fuzzed here. The state files read by `status.h`, `dash.h` and `poll.h` (`/proc`, `/tmp`) are local, not network input, and the
  harness answers `ENOENT` for them; `locked()` / `lock_note()` read the failure records of the children; `run()` (arguments,
  environment, accept loop, fork) is not run.
- **onvifd**: the multicast Hello and Bye, the interface and netmask ioctls, `load_config()` (local files), the deferred
  PullMessages answer (timers) and the 2 s configuration poll. The password is a fixed string, so the PasswordDigest
  *failure* paths are covered but a wrong-user path is reached only by mutation of the seeds.
- **mqttd**: the socket read loop (`conn_start`, `broker_addr`, the DNS lookup of the broker), the TCP stream cut into
  arbitrary pieces beyond two reads, `parse_records()` (what the worker script writes, not the network), the FIFO and the child
  processes. There is no TLS to the broker in this daemon.
- **whep**: `tc100_whep.c` itself: `http_handle()` (HTTP request line by `sscanf`, Content-Length, the 12 000 byte offer
  limit), `whep_post()`'s glue, `on_udp()`'s dispatch, `rtsp_resp()` (the answer of the local RTSP source), the DTLS handshake
  and the SRTP/SRTCP code (Mbed TLS and `srtp.h` keys). They are the part the `[up-base]` port to Mbed TLS 3.6 changes; a
  harness for `http_handle()` and the dispatch is the next step once that port is merged (the function takes a socket and
  reads with `recv`, so it needs the same socketpair as `onvif_http`).
- **mdnsd**: `run()` (the socket loop, the interface address and the hostname files).

None of the six daemons has a TLS or an HTTP/2 stack of its own; the web UI and its CGIs (shell, busybox) are outside the
scope of a libFuzzer harness.

## Camera test (owner, SD-booted system)

Only because `tc100-onvifd` (the `dur_s()` fix) and `httpfront` (compiled the same) changed. From the SD card in RAM
(`pack66/boot66b.sh`), nothing written to the flash:

1. ONVIF Device Manager (or the NVR / Home Assistant ONVIF integration the owner uses): discovery finds the camera
   (WS-Discovery), the profiles and the live stream open, a motion event subscription (CreatePullPointSubscription, PullMessages,
   Renew) works for a few minutes. Pass: as on 3.0.2.
2. The web UI opens at `http://<camera>/` (the redirect to `/index.html`, the login, the status line refreshing). Pass: as before.

No change to RTSP, MQTT, WebRTC or mDNS.
