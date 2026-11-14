"""Forks removed from the once-a-minute Wi-Fi jobs (review of the background brief, docs/linux-port/frontier/
background-2026-11-11.md): the new lines must give exactly what the old ones gave, in busybox ash.

wifi-quality.sh: the gateway address without two $(echo | cut), the packet loss without printf | sed | head;
wifi-roam.sh: the uptime without $(cut), no mkdir / rm when there is nothing to do.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASH = shutil.which("busybox")

OLD_GATEWAY = r'''old_gw() { _gw=$1; printf '%d.%d.%d.%d\n' "0x${_gw#??????}" "0x$(echo "$_gw" | cut -c5-6)" "0x$(echo "$_gw" | cut -c3-4)" "0x${_gw%??????}"; }'''
OLD_LOSS = r'''old_loss() { _out=$1; _p=$(printf '%s\n' "$_out" | sed -n 's/.* \([0-9][0-9]*\)% packet loss.*/\1/p' | head -n 1)
  case "$_p" in ''|*[!0-9]*) echo null ;; *) echo "$_p" ;; esac; }'''

PINGS = [
    "PING 192.168.1.1 (192.168.1.1): 56 data bytes\n\n--- 192.168.1.1 ping statistics ---\n"
    "3 packets transmitted, 3 packets received, 0% packet loss\nround-trip min/avg/max = 1.9/3.1/4.8 ms",
    "--- 192.168.1.1 ping statistics ---\n3 packets transmitted, 2 packets received, 33% packet loss",
    "--- 192.168.1.1 ping statistics ---\n3 packets transmitted, 0 packets received, 100% packet loss",
    "3 packets transmitted, 3 received, 0% packet loss, time 2003ms",      # iputils
    "",
    "ping: sendto: Network unreachable",
    "1 2 3 packets transmitted, 7% packet loss\nother line 9% packet loss",  # two matches: the first line wins
]


def ash(code, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([ASH, "ash", "-c", code], capture_output=True, text=True, env=e, timeout=20)


def code_only(f):
    return "\n".join(l for l in f.split("\n") if not l.lstrip().startswith("#"))


def shfunc(path, name):
    s = (ROOT / path).read_text(encoding="utf-8")
    return re.search(r"^" + re.escape(name) + r"\(\)\s*\{.*?^}", s, re.M | re.S).group(0)


@unittest.skipUnless(ASH, "needs busybox")
class ForkCuts(unittest.TestCase):
    def test_gateway_is_unchanged(self):
        gw = shfunc("scripts/wifi-quality.sh", "wq_gateway")
        self.assertNotIn("| cut", code_only(gw))
        with tempfile.TemporaryDirectory() as t:
            for hexgw in ("0101A8C0", "FE01A8C0", "0100000A", "FFFFFFFF", "00000000", "0A0B0C0D"):
                route = Path(t, "route")
                route.write_text("Iface\tDestination\tGateway \tFlags\n"
                                 f"wlan0\t0001A8C0\t00000000\t0001\nwlan0\t00000000\t{hexgw}\t0003\n")
                code = (OLD_GATEWAY + "\n" + gw.replace("/proc/net/route", str(route))
                        + f'\nold_gw {hexgw}; wq_gateway')
                a, b = ash(code).stdout.split("\n")[:2]
                self.assertEqual(a, b, hexgw)

    def test_loss_is_unchanged(self):
        loss = shfunc("scripts/wifi-quality.sh", "wq_loss")
        self.assertNotIn("| sed", code_only(loss))
        with tempfile.TemporaryDirectory() as t:
            for out in PINGS:
                f = Path(t, "ping")
                f.write_text(out)
                code = OLD_LOSS + "\n" + loss + '\nold_loss "$(cat "$WQ_PING")"; wq_loss'
                a, b = ash(code, {"WQ_PING": str(f)}).stdout.split("\n")[:2]
                self.assertEqual(a, b, repr(out))

    def test_roam_uptime_and_idle_path(self):
        s = (ROOT / "scripts/wifi-roam.sh").read_text(encoding="utf-8")
        self.assertNotIn("cut -d. -f1 /proc/uptime", s)
        self.assertNotIn("$(now)", s)
        # good signal, nothing to do: the state directory exists, no weak file -> the run forks nothing
        with tempfile.TemporaryDirectory() as t:
            env = {"WRO_STATE": t, "WRO_DBM": "-50", "WRO_NOW": "1000", "WRO_WPA_CLI": "false"}
            r = subprocess.run([ASH, "ash", str(ROOT / "scripts/wifi-roam.sh"), "once"], env={**os.environ, **env},
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0)
            Path(t, "weak").write_text("1\n")
            r = subprocess.run([ASH, "ash", str(ROOT / "scripts/wifi-roam.sh"), "once"], env={**os.environ, **env},
                               capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 0)
            self.assertFalse(Path(t, "weak").exists())     # a good signal still clears the weak count
        # the uptime read gives what cut gave
        code = 'read -r t _ < /proc/uptime; t=${t%%.*}; c=$(cut -d. -f1 /proc/uptime); [ "$t" -le "$c" ] && [ $((c - t)) -le 1 ] && echo same'
        self.assertEqual(ash(code).stdout.strip(), "same")

    def test_common_functions_zero_fork_helpers(self):
        cf = ROOT / "scripts/common_functions.sh"
        kv_fn = shfunc(cf, "read_kv_config_value")
        gw_fn = shfunc(cf, "get_default_gateway")
        pl_fn = shfunc(cf, "port_listening")
        for body in (kv_fn, gw_fn, pl_fn):
            self.assertNotIn("awk", body)
            self.assertNotIn("cut", body)
            self.assertNotIn("$(printf", body)
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "test.conf"
            cfg.write_text(
                '# K=bad\nK="hello world"\r\nQ=\'single\'\nSP=  trimmed  \nK=second\n'
            )
            code = (
                f"{kv_fn}\n"
                f'f={cfg}\n'
                'out1=$(read_kv_config_value "$f" Q def)\n'
                'read_kv_config_value "$f" K def var; out2=$READ_KV_VAL\n'
                'read_kv_config_value "$f" SP def var; out3=$READ_KV_VAL\n'
                'read_kv_config_value "$f" MISSING fallback var; out4=$READ_KV_VAL\n'
                'printf "%s|%s|%s|%s\\n" "$out1" "$out2" "$out3" "$out4"\n'
            )
            r = ash(code)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "single|hello world|trimmed|fallback")

        with tempfile.TemporaryDirectory() as d:
            fake_tcp = Path(d) / "tcp"
            fake_tcp.write_text(
                "  sl  local_address rem_address   st\n"
                "   0: 00000000:1F90 00000000:0000 0A 0\n"
                "   1: 0100007F:0016 00000000:0000 01 0\n"
            )
            patched_pl = pl_fn.replace("/proc/net/tcp /proc/net/tcp6", str(fake_tcp))
            r = ash(
                f"{patched_pl}\n"
                "port_listening 8080 && echo p8080\n"
                "port_listening 22 || echo n22\n"
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip().splitlines(), ["p8080", "n22"])

        if Path("/proc/net/tcp").exists():
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", 0))
                s.listen(1)
                open_port = s.getsockname()[1]
                s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s2.bind(("127.0.0.1", 0))
                closed_port = s2.getsockname()[1]
                s2.close()
                r = ash(
                    f"{pl_fn}\n"
                    f'port_listening {open_port} && echo open\n'
                    f'port_listening {closed_port} || echo closed\n'
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip().splitlines(), ["open", "closed"])
            finally:
                s.close()

    def test_service_switch_and_health_probe_var_mode(self):
        ss = ROOT / "scripts/service-switch.sh"
        hp = ROOT / "scripts/health-probe.sh"
        probe_body = shfunc(hp, "probe_service_fast")
        self.assertIn("_pf_status", probe_body)
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "sw.conf"
            cfg.write_text("SW_A=1\nSW_B=0\n")
            code = (
                f'. "{ss}"\n'
                f'f="{cfg}"\n'
                'o1=$(svc_kv "$f" SW_A 0)\n'
                'svc_kv "$f" SW_B 1 var; o2=$_sw_v\n'
                'svc_kv "$f" SW_NONE fallback var; o3=$_sw_v\n'
                'svc_switch() { SW_FILE="$f"; SW_KEY=SW_A; SW_DEF=0; }\n'
                'svc_on x && on1=1 || on1=0\n'
                'svc_switch() { SW_FILE="$f"; SW_KEY=SW_B; SW_DEF=1; }\n'
                'svc_on x && on2=1 || on2=0\n'
                'printf "%s|%s|%s|%s|%s\\n" "$o1" "$o2" "$o3" "$on1" "$on2"\n'
            )
            r = ash(code)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "1|0|fallback|1|0")

        wanted_fn = shfunc(hp, "_pf_wanted")
        down_fn = shfunc(hp, "_pf_down")
        r = ash(
            f"{wanted_fn}\n{down_fn}\n"
            '_pf_svc=nonexistent_svc; _pf_q=var; _pf_down; v1=$_pf_status\n'
            '_pf_q=""; v2=$(_pf_down)\n'
            'svc_switch() { return 0; }; svc_on() { return 0; }\n'
            '_pf_q=var; _pf_down; v3=$_pf_status\n'
            'printf "%s|%s|%s\\n" "$v1" "$v2" "$v3"\n'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "disabled|disabled|stopped")

    def test_wq_now_matches_date_without_forking(self):
        wq = ROOT / "scripts/wifi-quality.sh"
        now_fn = shfunc(wq, "_wq_now")
        loss_fn = shfunc(wq, "wq_loss")
        self.assertIn("/proc/stat", now_fn)
        self.assertNotIn("wc -l", shfunc(wq, "wq_sample"))
        self.assertIn("var", loss_fn)
        r = ash(
            f"{now_fn}\n"
            'unset WQ_NOW\n'
            '_wq_btime=0; _wq_now; a=$_now; b=$(date +%s)\n'      # _wq_now sets _now (no subshell, no fork)
            'd=$((b - a)); [ "$d" -lt 0 ] && d=$((-d))\n'
            '[ "$d" -le 2 ] && echo ok || echo "diff=$d a=$a b=$b"\n'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "ok")

    def test_mqtt_bridge_skip_exec_and_manifest_fast_path(self):
        mb = ROOT / "scripts/mqtt-bridge.sh"
        ssri_fn = shfunc(mb, "service_script_running_int")
        pim_fn = shfunc(mb, "publish_integration_manifest")
        self.assertIn("-nt", pim_fn)
        self.assertIn("_MANIFEST_LAST_HOST", pim_fn)
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "called"
            svc = Path(d) / "ftp-server"
            svc.write_text(f"#!/bin/sh\necho 1 > '{marker}'\necho 1\n")
            svc.chmod(0o755)
            stale_pid = Path(d) / "stale.pid"
            stale_pid.write_text("999999\n")
            r = ash(
                f"{ssri_fn}\n"
                f'service_script_running_int "{svc}" "{d}/missing.pid" var; a=$_ssri_val\n'
                f'service_script_running_int "{svc}" "{stale_pid}" var; b=$_ssri_val\n'
                f'c=$(service_script_running_int "{svc}" "{d}/missing.pid")\n'
                'printf "%s|%s|%s\\n" "$a" "$b" "$c"\n'
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "0|0|0")
            self.assertFalse(marker.exists(), "should not exec status when pidfile missing/dead")

    def test_presence_isp_and_daynight_pure_shell_helpers(self):
        pm = ROOT / "scripts/presence-mode.sh"
        prf_fn = shfunc(pm, "presence_read_file")
        ppk_fn = shfunc(pm, "presence_profile_key")
        self.assertNotIn("awk", prf_fn)
        self.assertNotIn("tr", ppk_fn)
        with tempfile.TemporaryDirectory() as d:
            pf = Path(d) / "presence.conf"
            pf.write_text('# comment\nPRIVACY=0\nPRIVACY=1\n')
            r = ash(
                f"{prf_fn}\n{ppk_fn}\n"
                f'v=$(presence_read_file "{pf}" PRIVACY)\n'
                'presence_profile_key present privacy var; k1=$_pk_val\n'
                'presence_profile_key away PRIVACY var; k2=$_pk_val\n'
                'printf "%s|%s|%s\\n" "$v" "$k1" "$k2"\n'
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "1|PRESENCE_PRESENT_PRIVACY|PRESENCE_AWAY_PRIVACY")

        it = ROOT / "scripts/isp-tune.sh"
        norm_fn = shfunc(it, "isp_tune_norm")
        num_match = re.search(r'^_isp_num\(\).*$', it.read_text(), re.M)
        self.assertIsNotNone(num_match, "_isp_num helper missing")
        num_fn = num_match.group(0)
        json_fn = shfunc(it, "isp_tune_json")
        self.assertNotIn("$(isp_tune_get", json_fn)
        self.assertNotIn("$(isp_tune_enabled", json_fn)
        r = ash(
            f"{norm_fn}\n{num_fn}\n"
            'isp_tune_norm BRIGHTNESS 42 var; n1=$_it_norm\n'
            'isp_tune_norm POWER_HZ auto var; n2=$_it_norm\n'
            '_isp_num auto var; m1=$_it_num\n'
            '_isp_num 42 var; m2=$_it_num\n'
            '_isp_num bad var; m3=$_it_num\n'
            'printf "%s|%s|%s|%s|%s\\n" "$n1" "$n2" "$m1" "$m2" "$m3"\n'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '42|auto|"auto"|42|null')

        vid = (ROOT / "scripts/action.d/video.sh").read_text()
        m = re.search(r'^[ \t]*_dn_get\(\)\s*\{[^\n]*\}', vid, re.M)
        self.assertIsNotNone(m, "_dn_get helper missing")
        dn_fn = m.group(0)
        self.assertNotIn("sed", dn_fn)
        self.assertNotIn("tail", dn_fn)
        with tempfile.TemporaryDirectory() as d:
            dn_cfg = Path(d) / "daynight.conf"
            dn_cfg.write_text("# comment\nDN_MODE=auto\nDN_HYST=15\nDN_HYST=20\n")
            dn_patched = dn_fn.replace("/mnt/config/daynight.conf", str(dn_cfg))
            r = ash(
                f"{dn_patched}\n"
                'printf "%s|%s|%s\\n" "$(_dn_get DN_MODE)" "$(_dn_get DN_HYST)" "$(_dn_get MISSING)"\n'
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "auto|20|")


POSIX_SH = [ASH, "ash"] if ASH else (["/bin/dash"] if Path("/bin/dash").exists() else ["/bin/sh"])


def psh(code, env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(POSIX_SH + ["-c", code], capture_output=True, text=True, env=e, timeout=20)


class WebActionForkCuts(unittest.TestCase):
    def test_sysusageinfo_mb_to_matches_awk_without_awk(self):
        src = (ROOT / "www/cgi-bin/sysusageinfo.cgi").read_text(encoding="utf-8")
        mb_to = shfunc("www/cgi-bin/sysusageinfo.cgi", "mb_to")
        mb_fn = shfunc("www/cgi-bin/sysusageinfo.cgi", "mb")
        self.assertNotIn("awk", mb_to)
        self.assertNotIn("awk", mb_fn)
        self.assertNotIn("$(mb ", src)
        r = psh(
            f"{mb_to}\n{mb_fn}\n"
            'for v in 0 512 1024 1536 20480 ""; do mb_to out "$v"; printf "%s|%s\\n" "$out" "$(mb "$v")"; done\n'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(
            lines,
            [
                "0.0 MB|0.0 MB",
                "0.5 MB|0.5 MB",
                "1.0 MB|1.0 MB",
                "1.5 MB|1.5 MB",
                "20.0 MB|20.0 MB",
                "0.0 MB|0.0 MB",
            ],
        )

    def test_json_escape_fast_path_has_no_range_but_letters_and_digits(self):
        # a reversed range such as '~-\\ ' (from '~' to space) is read by some shells as every printable character
        f = shfunc("www/cgi-bin/func.cgi", "json_escape")
        pat = re.search(r"\*\[!([^]]*)\]\*\)", f).group(1)
        self.assertEqual(re.findall(r"(.)-(?!$)(.)", pat.replace("A-Z", "").replace("a-z", "").replace("0-9", "")), [])
        for sh in ([ASH, "ash"] if ASH else [], ["/bin/dash"], ["/bin/bash", "--posix"]):
            if not sh or not Path(sh[0]).exists() and sh[0] != ASH:
                continue
            for raw, want in (('a"b', 'a\\"b'), ("a\\b", "a\\\\b"), ("x y-z~", "x y-z~"), ("t\tu", "t\\tu"),
                              ("r\rs\nt", "r\\rs\\nt")):
                r = subprocess.run(sh + ["-c", f + '\njson_escape "$1"', "x", raw], capture_output=True, text=True)
                self.assertEqual(r.stdout, want, (sh, raw))

    def test_frigate_has_ip_is_a_literal_match(self):
        # busybox 1.37 awk no longer escapes the dots of a regex built with gsub (192x168.1.5 matched 192.168.1.5)
        src = (ROOT / "scripts/action.d/stream.sh").read_text(encoding="utf-8")
        fn = src[src.index("function has_ip(u,"):src.index("return 0 }", src.index("function has_ip(u,")) + len("return 0 }")]
        self.assertNotIn("gsub", fn)
        urls = ["rtsp://u:p@192.168.1.5:554/x", "rtsp://u@192x168.1.5/x", "rtsp://192.168.1.5/v", "rtsp://192.168.1.50/v",
                "http://h/192.168.1.5", "rtsp://a@192.168.1.55/", "rtsp://192.168.1.5"]
        awk = [ASH, "awk"] if ASH else ["awk"]
        r = subprocess.run(awk + ["-v", "ip=192.168.1.5", fn + '\n{ printf "%d", has_ip($0) } END { print "" }'],
                           input="\n".join(urls) + "\n", capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "1010101", r.stderr)

    def test_events_info_reads_once_without_ev_kv_or_grep(self):
        import json as _json
        src = (ROOT / "scripts/action.d/events.sh").read_text(encoding="utf-8")
        info = src[src.index("    events_info)"):src.index("    set_notify_config)")]
        self.assertNotIn("_ev_kv", info)
        self.assertNotIn("grep", info)
        self.assertNotIn("$(json_escape", info)
        self.assertNotIn("$(sanitize_int_range", info)
        json_escape = shfunc("www/cgi-bin/func.cgi", "json_escape")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            (cfg / "notify.conf").write_text(
                '# comment\n'
                'WEBHOOK_ENABLE=1\n'
                'WEBHOOK_URL="https://example.com/a"b"\n'
                'WEBHOOK_METHOD="PUT"\n'
                "NTFY_URL='https://ntfy.sh/a\\b'\n"
                'NTFY_AUTH="Bearer tok"\n'
                'NOTIFY_COOLDOWN_SECONDS=9999\n'
            )
            (cfg / "telegram.conf").write_text('apiToken="123:ABC"\n')
            (cfg / "tamper.conf").write_text('ENABLE=1\nTAMPER_HOLD_SEC=1\n')
            (cfg / "sound_detection.conf").write_text('ENABLE=on\nVOX_MODE=1\nMIN_LOUD_SECONDS=4\n')
            tamper = cfg / "cam_tamper"
            tamper.write_text("1\n")
            patched = (
                src.replace("/mnt/config", str(cfg))
                .replace("/tmp/cam_tamper", str(tamper))
            )
            r = psh(f"{json_escape}\nF_cmd=events_info\n{patched}")
            self.assertEqual(r.returncode, 0, r.stderr)
            j = _json.loads(r.stdout)
            self.assertEqual(j["notify"]["webhook_enable"], 1)
            self.assertEqual(j["notify"]["webhook_url"], 'https://example.com/a"b')
            self.assertEqual(j["notify"]["webhook_method"], "PUT")
            self.assertEqual(j["notify"]["ntfy_url"], r"https://ntfy.sh/a\b")
            self.assertEqual(j["notify"]["ntfy_auth_set"], 1)
            self.assertEqual(j["notify"]["telegram_ready"], 1)
            self.assertEqual(j["notify"]["cooldown"], 3600)
            self.assertEqual(j["tamper"]["active"], 1)
            self.assertEqual(j["tamper"]["hold"], 2)
            self.assertEqual(j["sound"]["enable"], 1)
            self.assertEqual(j["sound"]["min_loud"], 4)

    def test_network_action_pure_shell_paths(self):
        import json as _json
        src = (ROOT / "scripts/action.d/network.sh").read_text(encoding="utf-8")
        # 1. validate_ip_or_empty without awk
        fn_block = src[src.index("        validate_ip_or_empty()"):src.index("        dns_primary=")]
        self.assertNotIn("awk", fn_block)
        r = psh(
            f"{fn_block}\n"
            'for ip in "" 0.0.0.0 192.168.1.255 01.2.3.4 256.1.1.1 1.2.3 1.2.3.4.5 a.b.c.d; do '
            'validate_ip_or_empty "$ip" && echo ok || echo bad; done\n'
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["ok", "ok", "ok", "bad", "bad", "bad", "bad", "bad"])

        # 2. wifi_rescue_info & wifi_country_info preserve values including glob characters
        wri = src[src.index("    wifi_rescue_info)"):src.index("    wifi_country_info)")]
        wci = src[src.index("    wifi_country_info)"):src.index("    wifi_set_country)")]
        self.assertNotIn("_wr_v", wri)
        self.assertNotIn("_wc_v", wci)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "wifi-rescue.sh").write_text("#!/bin/sh\nprintf 'ap=1\\nssid=Home*5G\\npsk=pass?[1]\\n'\n")
            (p / "wifi-country.sh").write_text("#!/bin/sh\nprintf 'configured=FR\\neffective=FR\\nregdb=1\\n'\n")
            (p / "svc.sh").write_text("svc_on() { return 0; }\n")
            wri_p = (
                wri.replace("/mnt/scripts/wifi-rescue.sh", str(p / "wifi-rescue.sh"))
                .replace("/mnt/scripts/service-switch.sh", str(p / "svc.sh"))
                + "\n    esac"
            )
            r1 = psh(f'csrf_check() {{ :; }}\nF_reveal=1\ncase wifi_rescue_info in\n{wri_p}\n')
            self.assertEqual(r1.returncode, 0, r1.stderr)
            j1 = _json.loads(r1.stdout)
            self.assertEqual((j1["enabled"], j1["ap"], j1["ssid"], j1["psk"], j1["psk_set"]), (1, 1, "Home*5G", "pass?[1]", 1))

            wci_p = wci.replace("/mnt/scripts/wifi-country.sh", str(p / "wifi-country.sh")) + "\n    esac"
            r2 = psh(f'case wifi_country_info in\n{wci_p}\n')
            self.assertEqual(r2.returncode, 0, r2.stderr)
            j2 = _json.loads(r2.stdout)
            self.assertEqual((j2["country"], j2["effective"], j2["regdb"]), ("FR", "FR", 1))

        # 3. wifi_get_ssid reads wpa_supplicant.conf without awk
        wgs = src[src.index("    wifi_get_ssid)"):src.index("    wifi_set_config)")]
        self.assertNotIn("/^[ \\t]*ssid=/", wgs)
        with tempfile.TemporaryDirectory() as d:
            wpa = Path(d) / "wpa.conf"
            wpa.write_text('ctrl_interface=/var/run/wpa_supplicant\nnetwork={\n\tssid="Cafe*WiFi"\n\tpsk="secret"\n}\n')
            wgs_p = (
                wgs.replace("/mnt/config/wpa_supplicant.conf", str(wpa))
                .replace("/etc/wpa_supplicant.conf", "/nonexistent")
                + "\n    esac"
            )
            r3 = psh(f'command() {{ return 1; }}\nWIFI_CONFIG_PATH=/nonexistent\ncase wifi_get_ssid in\n{wgs_p}\n')
            self.assertEqual(r3.returncode, 0, r3.stderr)
            self.assertEqual(_json.loads(r3.stdout), {"status": "success", "ssid": "Cafe*WiFi"})

    def test_state_and_stream_and_config_exchange_fork_cuts(self):
        state = (ROOT / "www/cgi-bin/state.cgi").read_text(encoding="utf-8")
        im = state[state.index("  integrationmanifest)"):state.index("  healthsnapshot)")]
        self.assertNotIn("$(json_escape", im)
        self.assertNotIn("$(read_conf_value", im)
        fy = state[state.index("  frigateyaml)"):state.index("    ;;", state.index("  frigateyaml)"))]
        self.assertNotIn("$(read_conf_value", fy)

        stream = (ROOT / "scripts/action.d/stream.sh").read_text(encoding="utf-8")
        rsi = stream[stream.index("    rtsp_server_info)"):stream.index("    set_rtsp_server)")]
        self.assertNotIn("_rs_cfg", rsi)
        self.assertNotIn("awk", rsi)

        ce = (ROOT / "www/cgi-bin/config_exchange.cgi").read_text(encoding="utf-8")
        self.assertNotIn("$(_ce_truthy", ce)
        self.assertNotIn("| wc -w", ce)

        net = (ROOT / "www/cgi-bin/network.cgi").read_text(encoding="utf-8")
        self.assertNotIn("_autostart()", net)


if __name__ == "__main__":
    unittest.main()
