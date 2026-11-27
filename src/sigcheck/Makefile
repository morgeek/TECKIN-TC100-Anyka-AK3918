# tc100-sigcheck: Ed25519 verifier of the update packages, a program of the 3.0 system built against musl (src/musl.mk).
# Monocypher 4.0.2 (monocypher*.c/h, LICENCE-monocypher.md: unchanged from the release tarball, see sign.md for its SHA-256).
all: tc100-sigcheck
include ../musl.mk

SRCS = sigcheck.c monocypher.c monocypher-ed25519.c

tc100-sigcheck.dbg: $(SRCS) Makefile ../musl.mk | $(MUSL)/bin/musl-gcc
	$(MUSL_CC) $(MUSL_CFLAGS) $(MUSL_LDFLAGS) $(SRCS) -o $@

tc100-sigcheck: tc100-sigcheck.dbg
	$(CROSS)strip --strip-unneeded -R .comment -o $@ $<

# host build with keygen and sign (the owner's tool, scripts/sign_update.py; tests/test_update_sig.py)
host: $(SRCS)
	$(CC) -O2 -Wall -Wextra -std=gnu11 -DSIGCHECK_HOST -o tc100-sigcheck-host $(SRCS)

clean:
	rm -f tc100-sigcheck tc100-sigcheck.dbg tc100-sigcheck-host *.o
