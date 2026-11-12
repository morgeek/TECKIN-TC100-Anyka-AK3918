/* host simulation of rc.h (tests/test_h265cmdlist.py RateControl): picture size = complexity * 2^((32 - qp) / 6),
 * an IDR 4x a P picture; prints the mean bit rate per second and the QP range.
 *   rctest [kbps [pictures [complexity [vbr [floor]]]]]
 * With a vbr argument (0 or 1) a second line gives the QP range of the P pictures 30..n/4 (floor, when given, set from
 * picture 0 to n/4 and released then) and of n/4+30..n/2 (floor released); complexity should be a still scene. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "rc.h"

int main(int argc, char **argv)
{
	int kbps = argc > 1 ? atoi(argv[1]) : 1600, n = argc > 2 ? atoi(argv[2]) : 500, gop = 50, k, qlo = 99, qhi = 0, jump = 0, prev = -1;
	double cplx = argc > 3 ? atof(argv[3]) : 20000, sum = 0, sec = 0, worst = 0;
	struct rc r;
	int vbr = argc > 4 ? atoi(argv[4]) : 0, floor = argc > 5 ? atoi(argv[5]) : 0, a_lo = 99, a_hi = 0, b_lo = 99, b_hi = 0;

	rc_init(&r, kbps, 25, 22, 50, 32);
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
		if (k % 25 == 24) {
			double kb = sec * 8 / 1000;
			if (k >= 75 && k < n / 2 - 25 && fabs(kb / kbps - 1) > worst) worst = fabs(kb / kbps - 1);
			if (k >= n / 2 + 75 && fabs(kb / kbps - 1) > worst) worst = fabs(kb / kbps - 1);
			sec = 0;
		}
	}
	printf("mean %.0f kbit/s, qp %d..%d, max step %d, worst 1 s window off by %.0f %%\n", sum * 8 / 1000 / (n / 25.0), qlo, qhi, jump, worst * 100);
	if (argc > 4) printf("vbr %d floor %d: qp %d..%d then %d..%d\n", vbr, floor, a_lo, a_hi, b_lo, b_hi);
	return 0;
}
