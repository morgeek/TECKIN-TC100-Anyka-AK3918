#!/bin/sh
# check-libc-data-imports.sh: after the ARM build, no program linked against the stand-in libc of its Makefile imports
# a libc VARIABLE (rc27 tester R3). The stand-in declares every import as a function, so a variable (stderr, optarg,
# environ, timezone...) reads the PLT stub instead of the data: tc100-onvifd crashed at start on the camera. Each
# Makefile writes imports.txt (nm -u of the object, macros expanded); this reads them all. The source-level test is
# tests/test_audit_fixes.py NoLibcDataImports; this one also sees a variable reached through a macro.
#   tests/check-libc-data-imports.sh [DIR...]     (default: src/tc100rtsp src/netacl)
DATA='stdin stdout stderr optarg optind opterr optopt environ __environ timezone daylight tzname h_errno _res
__progname program_invocation_name program_invocation_short_name signgam __ctype_b __ctype_tolower __ctype_toupper'
[ $# -gt 0 ] || set -- src/tc100rtsp src/netacl src/libakuio	# the stand-in libc programs (the others are musl ones since 2026-11-07)
# names the glibc headers produce that the camera's uClibc 0.9.33 does not export (the loader stops the program the first
# time one is called: tc100-logfwd died at its first log line from rc28 to rc31 on __isoc99_sscanf; libnetacl.so had
# __isoc23_strtol): ISO C redirections, ctype tables reached through functions, _FORTIFY_SOURCE checks, 64-bit file calls
GLIBC_ONLY='^(__isoc99_|__isoc23_|__ctype_(b|tolower|toupper)_loc$|__[a-z_]+_chk$|__(x|fx|lx)stat|__libc_single_threaded)'
rc=0
for d in "$@"; do
  f=$d/imports.txt
  [ -f "$f" ] || { echo "check-libc-data-imports: $f missing (build $d first)"; rc=1; continue; }
  if grep -Eq "$GLIBC_ONLY" "$f"; then
    echo "check-libc-data-imports: $d imports a name the camera's uClibc does not have: $(grep -E "$GLIBC_ONLY" "$f" | tr '\n' ' ')"; rc=1
  fi
  for v in $DATA; do
    if grep -qx "$v" "$f"; then echo "check-libc-data-imports: $d imports the libc variable $v"; rc=1; fi
  done
done
[ $rc = 0 ] && echo "check-libc-data-imports: ok ($*)"
exit $rc
