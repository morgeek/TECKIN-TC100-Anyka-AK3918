/* writes h265_work_table() on stdout (tests/test_h265cmdlist.py WorkTable) */
#include <stdio.h>
#include "worktab.h"
int main(void) { static uint8_t b[WORKTAB_SIZE]; h265_work_table(b); fwrite(b, 1, sizeof b, stdout); return 0; }
