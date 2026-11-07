/* writes h265_work_table(), or h264_work_table() with an argument "264", on stdout (tests/test_h265cmdlist.py WorkTable) */
#include <stdio.h>
#include <string.h>
#include "worktab.h"
int main(int argc, char **argv)
{
	static uint8_t b[WORKTAB_SIZE];

	if (argc > 1 && !strcmp(argv[1], "264")) h264_work_table(b); else h265_work_table(b);
	fwrite(b, 1, sizeof b, stdout);
	return 0;
}
