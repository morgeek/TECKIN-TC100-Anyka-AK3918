/* apb.c: the speaker played straight through the kernel's PCM ioctls, the playback twin of acap.c (plan 3 of
 * docs/linux-port/plans-2026-11-12.md: tc100_rtsp must know what it wrote and how much is still queued, to cancel the
 * echo of the speaker in the microphone).
 *
 * `aplay -D plughw:0,0 -r 8000 -c 1` of speaker-play.sh does the same through libasound's plug layer: the codec takes
 * stereo only on playback (patch 0007), so the mono samples are duplicated here. Interleaved S16_LE, 2 channels, the
 * rate asked (the driver accepts continuous rates and picks the nearest clock divider: dmesg prints the actual one);
 * period and buffer chosen by the driver (its period is a fixed 512 bytes, 128 stereo frames). No software parameters
 * are set: the stream starts with the first write and stops on an underrun (the next write prepares and starts it again).
 * Writes never block: WRITEI_FRAMES on a non-blocking descriptor takes what fits. Closing drops what is queued.
 */
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <time.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include "apb.h"
#ifdef __APPLE__
int apb_open(const char *dev, int rate) { (void)dev; (void)rate; return -1; }
int apb_write(int fd, const int16_t *mono, int n) { (void)fd; (void)mono; (void)n; return -1; }
int apb_queued(int fd) { (void)fd; return -1; }
void apb_close(int fd) { (void)fd; }
#else
#include <sound/asound.h>

static int xruns;			/* underruns of the open device */
static long last_prep = -100;		/* when the last one was recovered, monotonic seconds */

static struct snd_mask *mask(struct snd_pcm_hw_params *p, int k)
{
	return &p->masks[k - SNDRV_PCM_HW_PARAM_FIRST_MASK];
}

static struct snd_interval *iv(struct snd_pcm_hw_params *p, int k)
{
	return &p->intervals[k - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
}

static void mask_one(struct snd_mask *m, unsigned v)
{
	memset(m, 0, sizeof *m);
	m->bits[v >> 5] = 1u << (v & 31);
}

static void iv_one(struct snd_interval *i, unsigned v)
{
	memset(i, 0, sizeof *i);
	i->min = i->max = v;
	i->integer = 1;
}

int apb_open(const char *dev, int rate)
{
	struct snd_pcm_hw_params p;
	int fd = open(dev, O_WRONLY | O_NONBLOCK), k, e;

	if (fd < 0) return -1;
	xruns = 0; last_prep = -100;
	memset(&p, 0, sizeof p);
	for (k = SNDRV_PCM_HW_PARAM_FIRST_MASK; k <= SNDRV_PCM_HW_PARAM_LAST_MASK; k++)
		memset(mask(&p, k), 0xff, sizeof(struct snd_mask));
	for (k = SNDRV_PCM_HW_PARAM_FIRST_INTERVAL; k <= SNDRV_PCM_HW_PARAM_LAST_INTERVAL; k++) {
		iv(&p, k)->min = 0;
		iv(&p, k)->max = ~0u;
	}
	p.rmask = ~0u;
	p.info = ~0u;
	mask_one(mask(&p, SNDRV_PCM_HW_PARAM_ACCESS), SNDRV_PCM_ACCESS_RW_INTERLEAVED);
	mask_one(mask(&p, SNDRV_PCM_HW_PARAM_FORMAT), SNDRV_PCM_FORMAT_S16_LE);
	mask_one(mask(&p, SNDRV_PCM_HW_PARAM_SUBFORMAT), SNDRV_PCM_SUBFORMAT_STD);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_CHANNELS), 2);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_RATE), (unsigned)rate);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_SAMPLE_BITS), 16);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_FRAME_BITS), 32);
	if (ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, &p) < 0 || ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) < 0) {
		e = errno;
		close(fd);
		errno = e;
		return -1;
	}
	return fd;
}

int apb_write(int fd, const int16_t *mono, int n)
{
	int16_t st[512];
	int done = 0, tries = 0;

	while (done < n) {
		struct snd_xferi x;
		int m = n - done > 256 ? 256 : n - done, i;

		for (i = 0; i < m; i++) st[2 * i] = st[2 * i + 1] = mono[done + i];
		memset(&x, 0, sizeof x);
		x.buf = st;
		x.frames = (snd_pcm_uframes_t)m;
		if (ioctl(fd, SNDRV_PCM_IOCTL_WRITEI_FRAMES, &x) == 0 || x.result > 0) {
			done += (int)x.result;
			if ((int)x.result < m) break;		/* the buffer is full */
			continue;
		}
		if (errno == EAGAIN || errno == EINTR) break;
		if (errno == EPIPE || errno == ESTRPIPE) {	/* underrun: start again (the first write starts the stream) */
			/* PREPARE reaches the codec driver, which powers the DAC up with busy waits of tens of milliseconds
			 * (patch 0007: akpcm_playback_prepare, set_dac_samplerate, ak39_set_hp_power): at most one a second and
			 * eight in all, then -2: the caller goes back to aplay for the rest of the session */
			struct timespec ts;

			clock_gettime(CLOCK_MONOTONIC, &ts);
			xruns++;
			if (++tries > 1 || xruns > 8 || ts.tv_sec - last_prep < 1) return done ? done : -2;
			last_prep = ts.tv_sec;
			if (ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) < 0) return done ? done : -1;
			continue;
		}
		return done ? done : -1;
	}
	return done;
}

int apb_queued(int fd)
{
	snd_pcm_sframes_t d = 0;

	if (ioctl(fd, SNDRV_PCM_IOCTL_DELAY, &d) < 0) return -1;
	return d < 0 ? 0 : (int)d;
}

void apb_close(int fd)
{
	ioctl(fd, SNDRV_PCM_IOCTL_DROP);
	close(fd);
}
#endif
