#!/usr/bin/env bats

setup() {
  rm -f /tmp/func_exploit_marker
  unset F_bad F_good
}

@test "do not execute backticks from query string" {
  # malicious attempt: `%60touch /tmp/func_exploit_marker%60` -> `touch /tmp/func_exploit_marker`
  QUERY_STRING='bad=%60touch%20/tmp/func_exploit_marker%60&good=ok'
  # Ensure we don't run dd (simulate GET-style parsing)
  unset REQUEST_METHOD
  . ./www/cgi-bin/func.cgi

  # Exploit should NOT have been executed
  [ ! -f /tmp/func_exploit_marker ]
  # Value should be the literal backticked string
  [ "${F_bad}" = "`touch /tmp/func_exploit_marker`" ]
  [ "${F_good}" = "ok" ]
}
