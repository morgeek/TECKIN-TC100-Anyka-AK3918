#!/bin/sh
# check-libc-data-imports.sh: after the ARM build, no program linked against the stand-in libc of its Makefile imports
# a libc VARIABLE (rc27 tester R3). The stand-in declares every import as a function, so a variable (stderr, optarg,
# environ, timezone...) reads the PLT stub instead of the data: tc100-onvifd crashed at start on the camera. Each
# Makefile writes imports.txt (nm -u of the object, macros expanded); this reads them all. The source-level test is
# tests/test_audit_fixes.py NoLibcDataImports; this one also sees a variable reached through a macro.
#   tests/check-libc-data-imports.sh [DIR...]     (default: src/tc100rtsp src/mqttd src/onvifd src/supervisord src/logfwd src/netacl)
DATA='stdin stdout stderr optarg optind opterr optopt environ __environ timezone daylight tzname h_errno _res
__progname program_invocation_name program_invocation_short_name signgam __ctype_b __ctype_tolower __ctype_toupper'
[ $# -gt 0 ] || set -- src/tc100rtsp src/mqttd src/onvifd src/supervisord src/rwconf src/logfwd src/netacl
rc=0
for d in "$@"; do
  f=$d/imports.txt
  [ -f "$f" ] || { echo "check-libc-data-imports: $f missing (build $d first)"; rc=1; continue; }
  for v in $DATA; do
    if grep -qx "$v" "$f"; then echo "check-libc-data-imports: $d imports the libc variable $v"; rc=1; fi
  done
done
[ $rc = 0 ] && echo "check-libc-data-imports: ok ($*)"
exit $rc
