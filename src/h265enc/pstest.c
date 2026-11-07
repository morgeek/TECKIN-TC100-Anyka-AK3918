/* writes the parameter sets of paramsets.h for W x H at FPS on stdout (tests/test_h265cmdlist.py ParamSets) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "paramsets.h"

int main(int argc, char **argv)
{
	uint8_t b[512];
	int n = h265_param_sets(b, sizeof b, argc > 1 ? (uint32_t)atoi(argv[1]) : 1920, argc > 2 ? (uint32_t)atoi(argv[2]) : 1080,
				argc > 3 ? (uint32_t)atoi(argv[3]) : 25);

	if (n < 0) return 1;
	fwrite(b, 1, (size_t)n, stdout);
	return 0;
}
