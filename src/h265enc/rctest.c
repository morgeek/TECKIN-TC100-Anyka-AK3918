/* host simulation of rc.h (tests/test_h265cmdlist.py RateControl): picture size = complexity * 2^((32 - qp) / 6),
 * an IDR 4x a P picture; prints the mean bit rate per second and the QP range */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "rc.h"

int main(int argc, char **argv)
{
	int kbps = argc > 1 ? atoi(argv[1]) : 1600, n = argc > 2 ? atoi(argv[2]) : 500, gop = 50, k, qlo = 99, qhi = 0, jump = 0, prev = -1;
	double cplx = argc > 3 ? atof(argv[3]) : 20000, sum = 0, sec = 0, worst = 0;
	struct rc r;

	rc_init(&r, kbps, 25, 22, 50, 32);
	for (k = 0; k < n; k++) {
		int idr = k % gop == 0, qp = rc_qp(&r, idr);
		double c = cplx * (k >= n / 2 ? 2.5 : 1.0) * (1 + 0.1 * sin(k));	/* busier scene in the second half */
		long bytes = (long)(c * (idr ? 4 : 1) * pow(2, (32 - qp) / 6.0));

		rc_done(&r, idr, qp, bytes);
		sum += bytes; sec += bytes;
		if (k >= 75 && !idr) { if (qp < qlo) qlo = qp; if (qp > qhi) qhi = qp; }
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
	return 0;
}
