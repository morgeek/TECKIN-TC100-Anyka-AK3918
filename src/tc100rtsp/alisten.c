/* alisten.c: lets other programs listen to the microphone capture of tc100_rtsp.
 *
 * ALSA allows one capture reader and tc100_rtsp's arecord is it, so the web UI's "Listen" (www/cgi-bin/audio_stream.cgi)
 * gets the sound from here: the CGI makes a FIFO <dir>/<pid>.fifo and reads it (cat); tc100_rtsp finds it (lis_scan, twice
 * a second), opens it O_RDWR|O_NONBLOCK (so the CGI's blocking open of the read end always succeeds) and writes the raw
 * PCM (S16_LE, mono, 8 kHz) to it from the capture loop.
 *
 * The capture loop never blocks: writes are non-blocking and dropped when the FIFO is full. Because tc100_rtsp holds the
 * read end too it gets no EPIPE when the reader is gone; a listener whose FIFO keeps more than LIS_BACKLOG bytes (1.5 s)
 * unread, whose FIFO file was removed, or who has listened for LIS_SECONDS (60) is closed and its FIFO removed: the CGI's
 * cat then reads end of file and the browser's audio stops. At most LIS_MAX listeners; an extra FIFO is opened and closed at
 * once (the reader sees end of file).
 * Environment (tests): TC100_LISTEN_DIR, TC100_LISTEN_SECONDS. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "alisten.h"

#define LIS_MAX		3
#define LIS_BACKLOG	24000
#define LIS_DIR		"/tmp/tc100_listen"

static struct lis { int fd; char path[128]; uint64_t since; } L[LIS_MAX];
static const char *dir = LIS_DIR;
static unsigned lis_seconds = 60;
static int ready;
static uint64_t last_scan;

static void lis_drop(struct lis *l, const char *why)
{
	(void)why;
	if (l->fd >= 0) close(l->fd);
	unlink(l->path);
	l->fd = -1; l->path[0] = 0;
}

void lis_init(void)
{
	const char *e;
	int i;

	if ((e = getenv("TC100_LISTEN_DIR")) && *e) dir = e;
	if ((e = getenv("TC100_LISTEN_SECONDS")) && *e) { lis_seconds = 0; while (*e >= '0' && *e <= '9') lis_seconds = lis_seconds * 10 + (unsigned)(*e++ - '0'); }
	for (i = 0; i < LIS_MAX; i++) L[i].fd = -1;
	if (mkdir(dir, 0755) != 0 && errno != EEXIST) return;
	{	/* FIFOs left by CGIs of an earlier run: their readers are gone (or end at once) */
		DIR *dp = opendir(dir);
		struct dirent *de;

		while (dp && (de = readdir(dp))) {
			size_t n = strlen(de->d_name);
			char path[128];

			if (n < 6 || n > 40 || strcmp(de->d_name + n - 5, ".fifo")) continue;
			snprintf(path, sizeof path, "%.80s/%.40s", dir, de->d_name);
			unlink(path);
		}
		if (dp) closedir(dp);
	}
	ready = 1;
}

int lis_count(void)
{
	int i, n = 0;

	for (i = 0; i < LIS_MAX; i++) if (L[i].fd >= 0) n++;
	return n;
}

static int known(const char *path)
{
	for (int i = 0; i < LIS_MAX; i++) if (L[i].fd >= 0 && !strcmp(L[i].path, path)) return 1;
	return 0;
}

void lis_scan(uint64_t now_ms)
{
	DIR *dp;
	struct dirent *e;
	int i;

	if (!ready || now_ms - last_scan < 400) return;
	last_scan = now_ms;
	for (i = 0; i < LIS_MAX; i++) {
		struct lis *l = &L[i];
		int pend = 0;

		if (l->fd < 0) continue;
		if (access(l->path, F_OK) != 0) lis_drop(l, "gone");
		else if (now_ms - l->since >= (uint64_t)lis_seconds * 1000) lis_drop(l, "time limit");
		else if (ioctl(l->fd, FIONREAD, &pend) == 0 && pend > LIS_BACKLOG) lis_drop(l, "not read");
	}
	if (!(dp = opendir(dir))) return;
	while ((e = readdir(dp))) {
		size_t n = strlen(e->d_name);
		char path[128];
		struct stat sb;
		int fd;

		if (n < 6 || n > 40 || strcmp(e->d_name + n - 5, ".fifo")) continue;
		snprintf(path, sizeof path, "%.80s/%.40s", dir, e->d_name);
		if (known(path)) continue;
		if (lstat(path, &sb) != 0 || !S_ISFIFO(sb.st_mode)) continue;
		fd = open(path, O_RDWR | O_NONBLOCK);
		if (fd < 0) continue;
		for (i = 0; i < LIS_MAX && L[i].fd >= 0; i++) ;
		if (i == LIS_MAX) { close(fd); unlink(path); continue; }	/* full: the reader sees end of file */
		L[i].fd = fd; L[i].since = now_ms;
		snprintf(L[i].path, sizeof L[i].path, "%s", path);
	}
	closedir(dp);
}

void lis_write(const unsigned char *pcm, int n)
{
	for (int i = 0; i < LIS_MAX; i++) {
		if (L[i].fd < 0) continue;
		/* up to PIPE_BUF bytes are written whole or not at all: a full FIFO drops this block */
		if (write(L[i].fd, pcm, (size_t)n) < 0 && errno != EAGAIN && errno != EINTR) lis_drop(&L[i], "write");
	}
}

void lis_close_all(void)
{
	for (int i = 0; i < LIS_MAX; i++) if (L[i].fd >= 0) lis_drop(&L[i], "exit");
}
