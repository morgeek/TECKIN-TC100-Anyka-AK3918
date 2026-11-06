/* sndq.h: the bounded frame queue between the capture/encode loop and the sender thread of tc100_rtsp
 * (RTSP_SENDER_THREAD=1, R16 / H1). Kept apart, with no knowledge of clients or RTP, so that the host test
 * (test_sndq.c) builds the very same code.
 *
 * One producer (the capture loop: sndq_put never waits for anything but a lock held for a few instructions),
 * one consumer (the sender thread: sndq_get sleeps while the queue is empty).
 *
 * Drop policy: when the queue is over its frame count or byte limit, the OLDEST NON-IDR frame goes (an old IDR is worth more
 * than an old P frame: a client that lost frames resumes at the next IDR anyway). If only IDR frames are queued, the oldest
 * goes. A dropped frame leaves a gap: the job after it (or the job being queued when the dropped one was the last) gets
 * the stream bit in `gap` and the dropped sequence number in `gapseq`; the sender then makes every client of that stream
 * wait for the next IDR and counts it in its `dropped`, exactly like the congested-client case of bcast().
 *
 * Only pthread_mutex_* / pthread_cond_* calls (initialised at run time, never with the static initialisers: the camera runs
 * under uClibc with glibc headers, only the sizes of the objects are shared). */
#ifndef TC100_SNDQ_H
#define TC100_SNDQ_H
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

struct sjob {
	struct sjob *next;
	int si, idr;			/* stream (0 main, 1 sub), IDR frame */
	unsigned len, aux_len;
	uint32_t ts;
	unsigned long seq;		/* 1, 2, 3 ... in queueing order, 0 = not numbered */
	unsigned long gapseq;		/* highest seq of a frame dropped just before this one */
	unsigned gap;			/* bit si set: a frame of stream si was dropped just before this one */
	unsigned char *aux;		/* copy of the caller's side table (NAL table), or NULL */
	unsigned char *d;		/* the frame */
};

struct sndq {
	pthread_mutex_t mu;
	pthread_cond_t cv;
	struct sjob *head, *tail;
	int n, maxn, stop;
	size_t bytes, maxb;
	int depth_max;			/* deepest the queue got since the last sndq_stats */
	unsigned long drops;		/* frames dropped since the last sndq_stats */
	unsigned long total_drops;
};

static inline int sndq_init(struct sndq *q, int maxn, size_t maxb)
{
	memset(q, 0, sizeof *q);
	q->maxn = maxn; q->maxb = maxb;
	if (pthread_mutex_init(&q->mu, NULL)) return -1;
	if (pthread_cond_init(&q->cv, NULL)) return -1;
	return 0;
}

/* one malloc: job, aux copy, frame copy; NULL when out of memory */
static inline struct sjob *sjob_new(const void *d, unsigned len, const void *aux, unsigned aux_len)
{
	size_t h = (sizeof(struct sjob) + 7) & ~(size_t)7, a = ((size_t)aux_len + 7) & ~(size_t)7;
	struct sjob *j = (struct sjob *)malloc(h + a + len);

	if (!j) return NULL;
	memset(j, 0, sizeof *j);
	j->len = len; j->aux_len = aux_len;
	j->aux = aux_len ? (unsigned char *)j + h : NULL;
	j->d = (unsigned char *)j + h + a;
	if (aux_len) memcpy(j->aux, aux, aux_len);
	memcpy(j->d, d, len);
	return j;
}

/* queue the job (the queue owns it from here); never blocks; returns how many frames it had to drop */
static inline int sndq_put(struct sndq *q, struct sjob *job)
{
	int dropped = 0;

	pthread_mutex_lock(&q->mu);
	while (q->n > 0 && (q->n >= q->maxn || q->bytes + job->len > q->maxb)) {
		struct sjob *x = q->head, *px = NULL, *s;

		for (struct sjob *p = q->head, *pp = NULL; p; pp = p, p = p->next)
			if (!p->idr) { x = p; px = pp; break; }
		if (px) px->next = x->next; else q->head = x->next;
		if (q->tail == x) q->tail = px;
		q->n--; q->bytes -= x->len;
		s = x->next ? x->next : job;			/* the frame the gap is in front of */
		s->gap |= x->gap | (1u << x->si);
		if (x->gapseq > s->gapseq) s->gapseq = x->gapseq;
		if (x->seq > s->gapseq) s->gapseq = x->seq;
		free(x);
		dropped++; q->drops++; q->total_drops++;
	}
	job->next = NULL;
	if (q->tail) q->tail->next = job; else q->head = job;
	q->tail = job;
	q->n++; q->bytes += job->len;
	if (q->n > q->depth_max) q->depth_max = q->n;
	pthread_cond_signal(&q->cv);
	pthread_mutex_unlock(&q->mu);
	return dropped;
}

/* the oldest job; sleeps while there is none; NULL once sndq_stop was called and the queue is empty */
static inline struct sjob *sndq_get(struct sndq *q)
{
	struct sjob *j;

	pthread_mutex_lock(&q->mu);
	while (!q->head && !q->stop) pthread_cond_wait(&q->cv, &q->mu);
	j = q->head;
	if (j) {
		q->head = j->next;
		if (!q->head) q->tail = NULL;
		q->n--; q->bytes -= j->len;
	}
	pthread_mutex_unlock(&q->mu);
	return j;
}

static inline void sndq_stop(struct sndq *q)
{
	pthread_mutex_lock(&q->mu);
	q->stop = 1;
	pthread_cond_broadcast(&q->cv);
	pthread_mutex_unlock(&q->mu);
}

/* depth max and drops since the previous call (both reset), current depth */
static inline void sndq_stats(struct sndq *q, int *depth_max, unsigned long *drops, int *depth)
{
	pthread_mutex_lock(&q->mu);
	*depth_max = q->depth_max; *drops = q->drops; *depth = q->n;
	q->depth_max = q->n; q->drops = 0;
	pthread_mutex_unlock(&q->mu);
}
#endif
