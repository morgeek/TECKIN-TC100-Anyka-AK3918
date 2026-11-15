/* host simulation of rc.h (tests/test_h265cmdlist.py RateControl): picture size = complexity * 2^((32 - qp) / 6),
 * an IDR 4x a P picture; prints the mean bit rate per second and the QP range.
 *   rctest [kbps [pictures [complexity [vbr [floor]]]]]
 * With a vbr argument (0 or 1) a second line gives the QP range of the P pictures 30..n/4 (floor, when given, set from
 * picture 0 to n/4 and released then) and of n/4+30..n/2 (floor released); complexity should be a still scene.
 * A 6th argument is the capture rate in use (rc_set_rate; the encoder was opened for 25 fps): the windows are then 1 s of
 * that rate and the GOP 2 s of it.
 *   rctest check   ENC-02 (2026-11-15): prints the values of rc_set_rate, rc_set_idr_cap, rc_set_idr_offset and rc_over
 *                  that tests/test_h265cmdlist.py RateControlEnc02 checks */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rc.h"

int main(int argc, char **argv)
{
	int kbps = argc > 1 ? atoi(argv[1]) : 1600, n = argc > 2 ? atoi(argv[2]) : 500, gop = 50, k, qlo = 99, qhi = 0, jump = 0, prev = -1;
	double cplx = argc > 3 ? atof(argv[3]) : 20000, sum = 0, sec = 0, worst = 0;
	struct rc r;
	int fps = argc > 6 ? atoi(argv[6]) : 25;
	int vbr = argc > 4 ? atoi(argv[4]) : 0, floor = argc > 5 ? atoi(argv[5]) : 0, a_lo = 99, a_hi = 0, b_lo = 99, b_hi = 0;

	if (argc > 1 && !strcmp(argv[1], "check")) {
		int q, tries;
		long size;

		rc_init(&r, 1600, 25, 25, 48, 32);
		printf("budget25 %ld spread %d credit %d\n", (long)r.budget, r.spread, r.credit);
		rc_set_rate(&r, 0, 10);
		printf("budget10 %ld spread %d credit %d\n", (long)r.budget, r.spread, r.credit);
		rc_set_rate(&r, 800, 0);
		printf("budget10at800 %ld\n", (long)r.budget);
		rc_set_rate(&r, 1600, 25);
		printf("back %ld spread %d credit %d\n", (long)r.budget, r.spread, r.credit);
		/* the IDR size limit: a 160 KB IDR at QP 30, limit 80 KB: the next one at QP 36 or more; a 20 KB one: free again */
		rc_set_vbr(&r, 1); rc_set_vbr_qp(&r, 32);
		rc_set_idr_cap(&r, 80000);
		q = rc_qp(&r, 1); printf("idr_first %d\n", q);
		rc_done(&r, 1, q, 160000); r.qp = 25;
		q = rc_qp(&r, 1); printf("idr_after_160k %d\n", q);
		rc_done(&r, 1, q, 80000); r.qp = 25;
		q = rc_qp(&r, 1); printf("idr_after_80k %d\n", q);
		rc_done(&r, 1, q, 20000); r.qp = 25;
		q = rc_qp(&r, 1); printf("idr_after_20k %d\n", q);
		/* the offset of a still scene: 4 below the P QP instead of 2 */
		rc_set_idr_cap(&r, 0);
		printf("offset2 %d", rc_qp(&r, 0) - rc_qp(&r, 1));
		rc_set_idr_offset(&r, 4); printf(" offset4 %d", rc_qp(&r, 0) - rc_qp(&r, 1));
		rc_set_idr_offset(&r, RC_IDR_OFFSET); printf(" back %d\n", rc_qp(&r, 0) - rc_qp(&r, 1));
		/* an IDR of 1.5 MB at QP 30 into a 500 KB buffer: each try 6 QP higher until it fits */
		for (tries = 0; tries < 20; tries++) {
			q = rc_qp(&r, 1);
			size = (long)(1500000 * pow(2, (30 - q) / 6.0));
			printf("over try %d qp %d size %ld\n", tries, q, size);
			if (size <= 500000) { rc_done(&r, 1, q, size); break; }
			rc_over(&r, 1, q, 500000);
		}
		printf("over fits_after %d buffer_positive %d\n", tries, r.buffer > 0);
		return 0;
	}
	rc_init(&r, kbps, 25, 22, 50, 32);
	if (fps != 25) { rc_set_rate(&r, 0, fps); gop = 2 * fps; }
	if (argc > 4) rc_set_vbr(&r, vbr);
	if (floor) rc_set_floor(&r, floor);
	for (k = 0; k < n; k++) {
		int idr, qp;

		if (floor && k == n / 4) rc_set_floor(&r, 0);
		idr = k % gop == 0; qp = rc_qp(&r, idr);
		double c = cplx * (k >= n / 2 ? 2.5 : 1.0) * (1 + 0.1 * sin(k));	/* busier scene in the second half */
		long bytes = (long)(c * (idr ? 4 : 1) * pow(2, (32 - qp) / 6.0));

		rc_done(&r, idr, qp, bytes);
		sum += bytes; sec += bytes;
		if (k >= 75 && !idr) { if (qp < qlo) qlo = qp; if (qp > qhi) qhi = qp; }
		if (!idr && k >= 30 && k < n / 4) { if (qp < a_lo) a_lo = qp; if (qp > a_hi) a_hi = qp; }
		if (!idr && k >= n / 4 + 30 && k < n / 2) { if (qp < b_lo) b_lo = qp; if (qp > b_hi) b_hi = qp; }
		if (prev >= 0 && !idr && abs(qp - prev) > jump && k % gop != 1) jump = abs(qp - prev);
		if (!idr) prev = qp;
		if (k % fps == fps - 1) {
			double kb = sec * 8 / 1000;
			if (k >= 75 && k < n / 2 - 25 && fabs(kb / kbps - 1) > worst) worst = fabs(kb / kbps - 1);
			if (k >= n / 2 + 75 && fabs(kb / kbps - 1) > worst) worst = fabs(kb / kbps - 1);
			sec = 0;
		}
	}
	printf("mean %.0f kbit/s, qp %d..%d, max step %d, worst 1 s window off by %.0f %%\n", sum * 8 / 1000 / (n / (double)fps), qlo, qhi, jump, worst * 100);
	if (argc > 4) printf("vbr %d floor %d: qp %d..%d then %d..%d\n", vbr, floor, a_lo, a_hi, b_lo, b_hi);
	return 0;
}
