# shellcheck shell=sh
# action.cgi commands: Logs.
# Sourced by www/cgi-bin/action.cgi after its checks (rate limit, CSRF,
# audit log) and helpers; F_* are the request fields. Only the file of the
# requested command is read, so a request parses this file, not all of them.

  # the video server log (tc100_rtsp)
  _vlog=/tmp/logs/tc100_rtsp.log
  case "$F_cmd" in
    showlog)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "showlog command does not support JSON format"
      else
        echo "<pre>"
        case "${F_logname}" in
          "" | 1)
            emit_log_tail_dir "/var/log" "Summary of /var/log (tail -n ${LOG_SUMMARY_TAIL_LINES})" "$LOG_SUMMARY_TAIL_LINES"
            emit_log_tail_dir "/mnt/log" "=== /mnt/log (tail -n ${LOG_SUMMARY_TAIL_LINES}) ===" "$LOG_SUMMARY_TAIL_LINES"
            emit_log_tail_dir "/tmp/logs" "=== /tmp/logs (tail -n ${LOG_SUMMARY_TAIL_LINES}) ===" "$LOG_SUMMARY_TAIL_LINES"
            emit_log_tail_dir "/tmp/log" "=== /tmp/log (tail -n ${LOG_SUMMARY_TAIL_LINES}) ===" "$LOG_SUMMARY_TAIL_LINES"
            ;;

          2)
            echo "Content of dmesg (tail -n ${LOG_DMESG_TAIL_LINES})<br/>"
            /bin/dmesg 2>/dev/null | tail -n "$LOG_DMESG_TAIL_LINES"
            ;;

          3)
            echo "Content of ${_vlog##*/} (tail -n ${LOG_VIDEO_TAIL_LINES})<br/>"
            if [ -f $_vlog ]; then
              tail -n "$LOG_VIDEO_TAIL_LINES" $_vlog
            else
              echo "Log file not found: $_vlog"
            fi
            ;;

        esac
        echo "</pre>"
      fi
    ;;
    clearlog)
      if wants_json_response; then
        json_body_err "FORMAT_NOT_SUPPORTED" "clearlog command does not support JSON format"
      else
        echo "<pre>"
        case "${F_logname}" in
          "" | 1)
            cleared_var="$(clear_log_dir_files /var/log)"
            cleared_mnt="$(clear_log_dir_files /mnt/log)"
            echo "Summary logs cleared<br/>"
            echo "/var/log files cleared: $cleared_var<br/>"
            echo "/mnt/log files cleared: $cleared_mnt<br/>"
            ;;
          2)
            echo "Content of dmesg cleared<br/>"
            /bin/dmesg -c > /dev/null
            ;;
          3)
            echo "Content of ${_vlog##*/} cleared<br/>"
            : > $_vlog 2>/dev/null || true
            ;;
        esac
        echo "</pre>"
      fi
    ;;
  esac
