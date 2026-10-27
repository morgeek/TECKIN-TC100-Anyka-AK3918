/* talk.c: the sound a client sends back over RTSP (the ONVIF backchannel: go2rtc, Frigate, Home Assistant) to the speaker.
 *
 * The same job as the 2.x lite server (src/tc100fix/rtsp.c), on ALSA: G.711 A-law RTP packets are decoded to S16_LE 8 kHz
 * mono and written to the standard input of `sh scripts/speaker-play.sh -`, started when the first packet arrives and
 * closed 2 s after the last one (the player finishes what it has and exits). speaker-play.sh does what the web push-to-talk
 * does: volume from /mnt/config/pttvolume.conf, the amplifier GPIO when the device tree leaves it free, and the lock
 * /tmp/speaker-play.lock (mkdir): while a push-to-talk clip plays the player exits at once (exit 3) and the packets are
 * dropped for 2 s, while a client talks the web push-to-talk is refused (upload_audio.cgi looks at the lock).
 * One talker at a time: the first client keeps the speaker until it has been silent for 3 s.
 * The packets go into a non-blocking pipe from the main loop: nothing here ever waits (a full pipe, more than 0.75 s of sound
 * not yet played, drops packets). Environment (tests): TC100_SPEAKER_SCRIPT. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "talk.h"

#define TALK_LOCK	"/tmp/speaker-play.lock"
#define TALK_SCRIPT	"/mnt/scripts/speaker-play.sh"
#define TALK_IDLE_US	2000000ULL	/* the player is closed this long after the last packet */
#define TALK_TAKE_US	3000000ULL	/* another client may take over after this much silence */
#define TALK_BACKLOG	12000		/* bytes (0.75 s) waiting in the pipe: drop what comes */
#define LOGT(...) do { char _b[200]; int _n = snprintf(_b, sizeof _b, "talk: " __VA_ARGS__); \
	_n = _n > (int)sizeof _b - 1 ? (int)sizeof _b - 1 : _n; if (_n > 0) (void)!write(2, _b, (size_t)_n); } while (0)

static pid_t pid = -1;			/* the player (a process group of its own) */
static int wfd = -1;			/* its standard input */
static int owner = -1;
static uint64_t last_us, start_us, close_us, blocked_until;
static unsigned long pkts, dropped, sessions;

static int16_t alaw_dec(unsigned char a)
{
	int t, seg;

	a ^= 0x55;
	t = (a & 0x0f) << 4;
	seg = (a & 0x70) >> 4;
	if (seg == 0) t += 8;
	else if (seg == 1) t += 0x108;
	else { t += 0x108; t <<= seg - 1; }
	return (int16_t)((a & 0x80) ? t : -t);
}

/* a process called name (/proc/<pid>/comm) exists */
static int proc_running(const char *name)
{
	DIR *d = opendir("/proc");
	struct dirent *e;
	int found = 0;

	if (!d) return 1;			/* cannot tell: assume yes, leave the lock */
	while (!found && (e = readdir(d))) {
		char p[64], c[32];
		int fd, n;

		if (e->d_name[0] < '0' || e->d_name[0] > '9') continue;
		snprintf(p, sizeof p, "/proc/%.20s/comm", e->d_name);
		if ((fd = open(p, O_RDONLY)) < 0) continue;
		n = (int)read(fd, c, sizeof c - 1);
		close(fd);
		if (n > 0) {
			c[n] = 0;
			c[strcspn(c, "\n")] = 0;
			found = !strcmp(c, name);
		}
	}
	closedir(d);
	return found;
}

void talk_init(void)
{
	/* a lock left behind by a player that was killed: nobody plays, so nobody holds it */
	if (!access(TALK_LOCK, F_OK) && !proc_running("aplay") && rmdir(TALK_LOCK) == 0)
		LOGT("removed a stale %s\n", TALK_LOCK);
}

static const char *script(void)
{
	const char *e = getenv("TC100_SPEAKER_SCRIPT");

	return e && *e ? e : TALK_SCRIPT;
}

static int spawn(uint64_t now)
{
	int p[2];
	pid_t c;
	const char *sc = script();

	if (access(sc, R_OK)) { blocked_until = now + 5000000ULL; LOGT("%s missing\n", sc); return -1; }
	if (pipe(p)) return -1;
	c = vfork();
	if (c == 0) {
		int i = open("/dev/null", O_WRONLY);

		setpgid(0, 0);
		dup2(p[0], 0);
		if (i >= 0) { dup2(i, 1); dup2(i, 2); }
		for (i = 3; i < 256; i++) close(i);
		execl("/bin/sh", "sh", sc, "-", (char *)NULL);
		_exit(127);
	}
	close(p[0]);
	if (c < 0) { close(p[1]); return -1; }
	pid = c; wfd = p[1];
	fcntl(wfd, F_SETFL, fcntl(wfd, F_GETFL) | O_NONBLOCK);
	start_us = now;
	sessions++;
	return 0;
}

void talk_rtp(int who, const unsigned char *p, int n, uint64_t now)
{
	int off = 12, i, cnt;
	int16_t pcm[1024];

	if (n < 12 || (p[0] & 0xc0) != 0x80 || (p[1] & 0x7f) != 8) return;	/* RTP v2, PCMA */
	if (owner >= 0 && owner != who && now - last_us < TALK_TAKE_US) return;	/* someone else talks */
	off += (p[0] & 0x0f) * 4;
	if ((p[0] & 0x10) && n >= off + 4) off += 4 + ((p[off + 2] << 8 | p[off + 3]) * 4);
	if (p[0] & 0x20) n -= p[n - 1];
	if (n <= off) return;
	cnt = n - off > 1024 ? 1024 : n - off;
	if (owner != who) { owner = who; LOGT("client %d talks\n", who); }
	last_us = now;
	pkts++;
	if (wfd < 0) {
		if (pid > 0 || now < blocked_until) { dropped++; return; }	/* the last player is still finishing / was refused */
		if (spawn(now)) { dropped++; return; }
	}
	{
		int pend = 0;

		if (ioctl(wfd, FIONREAD, &pend) == 0 && pend > TALK_BACKLOG) { dropped++; return; }
	}
	for (i = 0; i < cnt; i++) pcm[i] = alaw_dec(p[off + i]);
	if (write(wfd, pcm, (size_t)cnt * 2) < 0) {
		if (errno == EAGAIN || errno == EINTR) { dropped++; return; }
		close(wfd); wfd = -1; close_us = now;		/* the player is gone */
	}
}

void talk_tick(uint64_t now)
{
	if (wfd >= 0 && now - last_us > TALK_IDLE_US) {	/* nobody talks any more: the player plays the rest and exits */
		close(wfd); wfd = -1; close_us = now; owner = -1;
		LOGT("end (%lu packets, %lu dropped)\n", pkts, dropped);
	}
	if (pid > 0) {
		int st;
		pid_t r = waitpid(pid, &st, WNOHANG);

		if (r == pid) {
			if (now - start_us < 1500000ULL && WIFEXITED(st) && WEXITSTATUS(st) != 0) {
				blocked_until = now + 2000000ULL;	/* busy (push-to-talk) or no aplay: try again later */
				LOGT("the speaker is not available (exit %d)\n", WEXITSTATUS(st));
				if (wfd >= 0) { close(wfd); wfd = -1; }
				owner = -1;
			}
			pid = -1;
		} else if (wfd < 0 && now - close_us > 10000000ULL) {	/* does not finish: stop the group */
			kill(-pid, close_us && now - close_us > 13000000ULL ? SIGKILL : SIGTERM);
		}
	}
}

void talk_release(int who)
{
	if (owner == who) owner = -1;
}

int talk_state(void) { return wfd >= 0; }

void talk_shutdown(void)
{
	if (wfd >= 0) { close(wfd); wfd = -1; }
	if (pid > 0) kill(-pid, SIGTERM);
}
