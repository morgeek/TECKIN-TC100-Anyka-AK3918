/* acap.c: the microphone read straight from the ALSA kernel interface, item 11 of the implementer list.
 *
 * tc100_rtsp used to start `arecord -D hw:0,0 -f S16_LE -r 8000 -c 1 -t raw` on a pipe: one more process (~660 KB PSS)
 * and every period copied twice through a pipe. The same thing with the kernel's PCM ioctls (sound/asound.h, a stable
 * kernel ABI): hardware parameters (interleaved, S16_LE, 1 channel, 8000 Hz; period and buffer chosen by the driver,
 * whose period is a fixed 512 bytes: forcing one gave I/O errors with arecord -F/-B), prepare, start, then
 * READI_FRAMES on a non-blocking descriptor that select() watches. An overrun (-EPIPE) is prepared and started again.
 * Closing the descriptor stops the capture (the driver's 300 ms delayed start is cancelled there, patch 0007).
 * RTSP_ALSA_DIRECT=1 turns it on (tc100_rtsp falls back to arecord when the device does not open).
 */
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include "acap.h"
#ifdef __APPLE__
int acap_open(const char *dev) { (void)dev; return -1; }
int acap_read(int fd, void *buf, int bytes) { (void)fd; (void)buf; (void)bytes; return -1; }
int acap_delay_bytes(int fd) { (void)fd; return 0; }
#else
#include <sound/asound.h>

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

int acap_open(const char *dev)
{
	struct snd_pcm_hw_params p;
	int fd = open(dev, O_RDONLY | O_NONBLOCK), k, e;

	if (fd < 0) return -1;
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
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_CHANNELS), 1);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_RATE), 8000);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_SAMPLE_BITS), 16);
	iv_one(iv(&p, SNDRV_PCM_HW_PARAM_FRAME_BITS), 16);
	/* the kernel refines what is left (period, buffer) and chooses */
	if (ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, &p) < 0 || ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) < 0 ||
	    ioctl(fd, SNDRV_PCM_IOCTL_START) < 0) {
		e = errno;
		close(fd);
		errno = e;
		return -1;
	}
	return fd;
}

int acap_read(int fd, void *buf, int bytes)
{
	struct snd_xferi x;

	memset(&x, 0, sizeof x);
	x.buf = buf;
	x.frames = (snd_pcm_uframes_t)(bytes / 2);
	if (ioctl(fd, SNDRV_PCM_IOCTL_READI_FRAMES, &x) == 0) return (int)x.result * 2;
	if (errno == EAGAIN || errno == EINTR) return 0;
	if ((errno == EPIPE || errno == ESTRPIPE) && ioctl(fd, SNDRV_PCM_IOCTL_PREPARE) == 0 &&
	    ioctl(fd, SNDRV_PCM_IOCTL_START) == 0)
		return 0;	/* overrun: some sound lost, going on */
	return -1;
}

int acap_delay_bytes(int fd)
{
	snd_pcm_sframes_t d = 0;

	if (ioctl(fd, SNDRV_PCM_IOCTL_DELAY, &d) < 0 || d < 0) return 0;
	return (int)d * 2;
}
#endif
