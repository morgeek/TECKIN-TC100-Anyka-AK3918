/* util.h: pure helpers of tc100_rtsp (RTSP path -> stream, microphone level in dBFS, motion zones), kept apart so
 * that the host tests (test_util.c) build the very same code. No libc call the camera's uClibc lacks: no libm, no
 * strtol or sscanf: glibc 2.38+ headers redirect them to __isoc23_* names that uClibc does not have. */
#ifndef TC100_UTIL_H
#define TC100_UTIL_H
#include <stdint.h>
#include <string.h>
#include <strings.h>

/* ---- RTSP paths ----------------------------------------------------------------------------------------------
 * 1 when the URL names the sub-stream: any path containing "video1" (video1, video1_unicast, /x/video1/track1),
 * or whose first segment is "ch1" or "sub"; 0 (main stream) otherwise. */
static inline int url_is_sub(const char *url)
{
	const char *p = strstr(url, "://"), *q;
	size_t n;

	if (p) {			/* skip scheme and host[:port] */
		p = strchr(p + 3, '/');
		if (!p) return 0;
	} else {
		p = url;
	}
	while (*p == '/') p++;
	for (q = p; *q && *q != '?'; q++)
		if (!strncasecmp(q, "video1", 6)) return 1;
	n = strcspn(p, "/?");
	return n == 3 && (!strncasecmp(p, "ch1", 3) || !strncasecmp(p, "sub", 3));
}

/* ---- microphone level ----------------------------------------------------------------------------------------
 * RMS and peak are measured around the window's mean: without the vendor noise processing the ADC output carries a
 * DC offset (~ -1450 of 32768 on 2.x), which must not count as sound. Same numbers as libtc100fix (2.x). */
struct lvl {
	uint32_t n;
	int64_t sum;
	uint64_t sq;
	int mn, mx;
};

static inline void lvl_reset(struct lvl *l) { l->n = 0; l->sum = 0; l->sq = 0; l->mn = 32767; l->mx = -32768; }

static inline void lvl_add(struct lvl *l, int s)
{
	l->n++; l->sum += s; l->sq += (uint64_t)((int64_t)s * s);
	if (s < l->mn) l->mn = s;
	if (s > l->mx) l->mx = s;
}

static inline void lvl_merge(struct lvl *a, const struct lvl *b)
{
	a->n += b->n; a->sum += b->sum; a->sq += b->sq;
	if (b->mn < a->mn) a->mn = b->mn;
	if (b->mx > a->mx) a->mx = b->mx;
}

/* natural logarithm without libm: x = m * 2^e, m in [1,2), ln m = 2 atanh((m-1)/(m+1)) (|z| <= 1/3) */
static inline double ln_d(double x)
{
	double z, z2, t, s = 0;
	int e = 0, k;

	if (x <= 0) return -1e30;
	while (x >= 2.0) { x *= 0.5; e++; }
	while (x < 1.0) { x *= 2.0; e--; }
	z = (x - 1) / (x + 1); z2 = z * z; t = z;
	for (k = 1; k < 24; k += 2) { s += t / k; t *= z2; }
	return 2 * s + e * 0.69314718055994531;
}

static inline double log10_d(double x) { return ln_d(x) / 2.30258509299404568; }

static inline int round_i(double v) { return (int)(v < 0 ? v - 0.5 : v + 0.5); }

/* dBFS of the RMS around the mean; -96 for silence (rms <= 0.5) */
static inline int lvl_rms_db(const struct lvl *l)
{
	double mean, var;

	if (!l->n) return -96;
	mean = (double)l->sum / l->n;
	var = (double)l->sq / l->n - mean * mean;
	if (var <= 0.25) return -96;
	return round_i(10.0 * log10_d(var) - 90.308998699194354);	/* 20 log10(rms / 32768) */
}

/* dBFS of the largest excursion from the mean; -96 for silence */
static inline int lvl_peak_db(const struct lvl *l)
{
	double mean, pk;

	if (!l->n) return -96;
	mean = (double)l->sum / l->n;
	pk = l->mx - mean > mean - l->mn ? l->mx - mean : mean - l->mn;
	if (pk <= 0.5) return -96;
	return round_i(20.0 * log10_d(pk / 32768.0));
}

/* ---- motion zones ---------------------------------------------------------------------------------------------
 * config/motion_zones.conf (written by the web UI, action.d/detection.sh): up to 4 lines MDZ<k>="x1,y1,x2,y2" in
 * percent of the picture, areas the motion detection ignores. Same rules as src/tc100fix/md.c on 2.x: a grid cell is
 * ignored when its centre lies in a zone. */
#define MDZ_MAX 4

static inline const char *num_p(const char *s, int *v)	/* unsigned decimal; NULL when none */
{
	int n = 0, k = 0;

	while (*s >= '0' && *s <= '9' && k < 6) { n = n * 10 + (*s++ - '0'); k++; }
	if (!k) return NULL;
	*v = n;
	return s;
}

/* one line -> zone (x1, y1, x2, y2); 1 when valid */
static inline int mdz_parse_line(const char *ln, int z[4])
{
	int k, i;

	if (strncmp(ln, "MDZ", 3) || !(ln = num_p(ln + 3, &k)) || k < 1 || k > MDZ_MAX || *ln++ != '=') return 0;
	if (*ln == '"') ln++;
	for (i = 0; i < 4; i++) {
		if (!(ln = num_p(ln, &z[i]))) return 0;
		if (i < 3 && *ln++ != ',') return 0;
	}
	if (*ln == '"') ln++;
	while (*ln == '\r' || *ln == '\n' || *ln == ' ') ln++;
	if (*ln) return 0;
	return z[2] <= 100 && z[3] <= 100 && z[2] > z[0] && z[3] > z[1];
}

/* mask[gw*gh]: 1 = cell watched, 0 = ignored; returns the number of watched cells */
static inline int mdz_mask(unsigned char *mask, int gw, int gh, int z[][4], int nz)
{
	int x, y, i, n = 0;

	for (y = 0; y < gh; y++)
		for (x = 0; x < gw; x++) {
			int cx = (2 * x + 1) * 50 / gw, cy = (2 * y + 1) * 50 / gh, in = 0;	/* cell centre, percent */

			for (i = 0; i < nz; i++)
				if (cx >= z[i][0] && cx < z[i][2] && cy >= z[i][1] && cy < z[i][3]) in = 1;
			mask[y * gw + x] = !in;
			n += !in;
		}
	return n;
}

/* the vendor's 1..100 sensitivity: motion when more than (105 - sens) per mille of the watched cells changed */
static inline int md_triggered(int changed, int watched, int sens)
{
	if (sens < 1) sens = 1;
	if (sens > 100) sens = 100;
	return watched > 0 && changed * 1000 > watched * (5 + (100 - sens));
}

#endif
