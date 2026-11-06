/* Host test of sndq.h, the frame queue between the capture loop and the sender thread of tc100_rtsp (RTSP_SENDER_THREAD).
 * tests/test_tc100rtsp.py runs it and wants "all OK". Checks: order preserved, the producer is never blocked by a slow
 * consumer, the drop policy (oldest non-IDR first, IDR kept, gap marks), byte limit, stop with a sleeping consumer. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "sndq.h"

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)

static struct sjob *mk(unsigned long seq, int idr, int si, unsigned len)
{
	unsigned char *buf = malloc(len ? len : 1);
	struct sjob *j;

	memset(buf, (int)(seq & 255), len);
	j = sjob_new(buf, len, NULL, 0);
	free(buf);
	j->seq = seq; j->idr = idr; j->si = si;
	return j;
}

/* drop policy, single thread */
static void test_policy(void)
{
	struct sndq q;
	struct sjob *j;
	int dmax, dep;
	unsigned long dr;

	sndq_init(&q, 4, 1 << 20);
	/* queue: IDR1 P2 P3 P4 (full), then P5 arrives: P2 (oldest non-IDR) goes, P3 carries the gap */
	sndq_put(&q, mk(1, 1, 0, 100));
	sndq_put(&q, mk(2, 0, 0, 100));
	sndq_put(&q, mk(3, 0, 0, 100));
	sndq_put(&q, mk(4, 0, 0, 100));
	CHECK(sndq_put(&q, mk(5, 0, 0, 100)) == 1);
	j = sndq_get(&q); CHECK(j && j->seq == 1 && !j->gap); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 3 && j->gap == 1u && j->gapseq == 2); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 4 && !j->gap); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 5 && !j->gap); free(j);
	sndq_stats(&q, &dmax, &dr, &dep);
	CHECK(dmax == 4 && dr == 1 && dep == 0);
	sndq_stats(&q, &dmax, &dr, &dep);
	CHECK(dmax == 0 && dr == 0);

	/* only IDR frames: the oldest goes; the dropped one is the last-but-none: the new job carries the gap */
	sndq_put(&q, mk(10, 1, 1, 100));
	sndq_put(&q, mk(11, 1, 1, 100));
	sndq_put(&q, mk(12, 1, 1, 100));
	sndq_put(&q, mk(13, 1, 1, 100));
	CHECK(sndq_put(&q, mk(14, 1, 1, 100)) == 1);
	j = sndq_get(&q); CHECK(j && j->seq == 11 && j->gap == 2u && j->gapseq == 10); free(j);
	while ((j = sndq_get(&q)), q.n > 0) free(j);
	free(j);

	/* two drops in a row: the gap travels on to the next survivor with the highest dropped number */
	sndq_put(&q, mk(20, 1, 0, 100));
	sndq_put(&q, mk(21, 0, 0, 100));
	sndq_put(&q, mk(22, 0, 0, 100));
	sndq_put(&q, mk(23, 1, 0, 100));
	sndq_put(&q, mk(24, 0, 0, 100));		/* drops 21 */
	sndq_put(&q, mk(25, 0, 0, 100));		/* drops 22, the gap of 21 is on 23 already */
	j = sndq_get(&q); CHECK(j && j->seq == 20); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 23 && j->gap == 1u && j->gapseq == 22); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 24 && !j->gap); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 25); free(j);

	/* the dropped frame was the last one queued: the gap goes to the job being queued */
	sndq_init(&q, 1, 1 << 20);
	sndq_put(&q, mk(30, 0, 0, 10));
	CHECK(sndq_put(&q, mk(31, 1, 0, 10)) == 1);
	j = sndq_get(&q); CHECK(j && j->seq == 31 && j->gap == 1u && j->gapseq == 30); free(j);

	/* byte limit */
	sndq_init(&q, 100, 1000);
	sndq_put(&q, mk(40, 1, 0, 400));
	sndq_put(&q, mk(41, 0, 0, 400));
	CHECK(sndq_put(&q, mk(42, 0, 0, 400)) == 1);	/* 1200 > 1000: P41 goes */
	CHECK(q.bytes == 800 && q.n == 2);
	j = sndq_get(&q); CHECK(j && j->seq == 40); free(j);
	j = sndq_get(&q); CHECK(j && j->seq == 42 && j->gap == 1u); free(j);
	CHECK(q.bytes == 0 && q.n == 0 && !q.head && !q.tail);
}

/* aux table and frame bytes survive the copy */
static void test_copy(void)
{
	unsigned char d[300], aux[40];
	struct sjob *j;

	for (unsigned i = 0; i < sizeof d; i++) d[i] = (unsigned char)(i * 7);
	for (unsigned i = 0; i < sizeof aux; i++) aux[i] = (unsigned char)(i + 1);
	j = sjob_new(d, sizeof d, aux, sizeof aux);
	CHECK(j && j->len == sizeof d && j->aux_len == sizeof aux);
	CHECK(j && !memcmp(j->d, d, sizeof d) && !memcmp(j->aux, aux, sizeof aux) && !((uintptr_t)j->aux & 7));
	free(j);
	j = sjob_new(d, 5, NULL, 0);
	CHECK(j && !j->aux && !memcmp(j->d, d, 5));
	free(j);
}

/* producer much faster than the consumer: never blocks, order kept among survivors, IDR frames not lost while room is left */
static struct sndq tq;
static unsigned long got_n, got_bad, got_last, got_idr;

static void *slow_consumer(void *a)
{
	struct sjob *j;

	(void)a;
	while ((j = sndq_get(&tq))) {
		if (j->seq <= got_last) got_bad++;	/* order */
		got_last = j->seq;
		if (j->idr) got_idr++;
		got_n++;
		if (got_n % 8 == 0) usleep(2000);	/* about 4000 frames/s at best, the producer makes far more */
		free(j);
	}
	return NULL;
}

static void test_threads(void)
{
	pthread_t th;
	struct timespec a, b;
	const unsigned long N = 20000;
	unsigned long idr_sent = 0;
	long us;

	sndq_init(&tq, 16, 1 << 20);
	pthread_create(&th, NULL, slow_consumer, NULL);
	clock_gettime(CLOCK_MONOTONIC, &a);
	for (unsigned long i = 1; i <= N; i++) {
		int idr = i % 25 == 1;

		idr_sent += idr;
		sndq_put(&tq, mk(i, idr, 0, 200));
	}
	clock_gettime(CLOCK_MONOTONIC, &b);
	us = (b.tv_sec - a.tv_sec) * 1000000L + (b.tv_nsec - a.tv_nsec) / 1000;
	CHECK(us < 5000000);			/* never waited for the consumer (it needs seconds for 20000 frames) */
	sndq_stop(&tq);
	pthread_join(th, NULL);			/* no deadlock: the consumer drains what is left and ends */
	CHECK(got_bad == 0);
	CHECK(got_last == N);			/* the newest frame always arrives */
	CHECK(got_n + tq.total_drops == N);	/* every frame is either delivered or counted as dropped */
	CHECK(tq.total_drops > 0);
	CHECK(got_idr > 0 && got_idr <= idr_sent);
	printf("producer %lu frames in %ld us, delivered %lu, dropped %lu, deepest queue %d, IDR delivered %lu of %lu\n",
	       N, us, got_n, tq.total_drops, tq.depth_max, got_idr, idr_sent);
}

/* sndq_stop wakes a consumer sleeping on an empty queue */
static void *waiter(void *a)
{
	struct sjob *j = sndq_get((struct sndq *)a);

	return j;
}

static void test_stop(void)
{
	static struct sndq q;
	pthread_t th;
	void *r;

	sndq_init(&q, 4, 1000);
	pthread_create(&th, NULL, waiter, &q);
	usleep(50000);
	sndq_stop(&q);
	pthread_join(th, &r);
	CHECK(r == NULL);
	CHECK(sndq_get(&q) == NULL);
}

int main(void)
{
	test_policy();
	test_copy();
	test_threads();
	test_stop();
	if (fails) { printf("%d FAILED\n", fails); return 1; }
	printf("all OK\n");
	return 0;
}
