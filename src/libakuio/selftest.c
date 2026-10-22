/* host-side check of the pool allocator: make selftest */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int akuio_test_attach(void *, unsigned, unsigned);
unsigned long akuio_alloc_pmem(int);
void akuio_free_pmem(unsigned long);
int akuio_vaddr2paddr(unsigned long);
unsigned long akuio_get_used_pmem(void);
unsigned long akuio_get_free_pmem(void);
int akuio_pmem_fini(void);

int main(void)
{
	size_t sz = 1 << 20;
	void *mem = malloc(sz);
	unsigned long a, b, c, d;

	akuio_test_attach(mem, 0x81800000, sz);
	a = akuio_alloc_pmem(100);	/* rounds to 128 */
	b = akuio_alloc_pmem(4096);
	c = akuio_alloc_pmem(1);
	assert(a && b && c && b == a + 128 && c == b + 4096);
	assert(akuio_vaddr2paddr(b + 10) == (int)(0x81800000 + 128 + 10));
	assert(akuio_get_used_pmem() == 128 + 4096 + 32);
	akuio_free_pmem(b);
	d = akuio_alloc_pmem(4000);	/* fits in the hole b left */
	assert(d == b);
	akuio_free_pmem(d); akuio_free_pmem(a); akuio_free_pmem(c);
	assert(akuio_get_used_pmem() == 0);
	assert(akuio_alloc_pmem(sz) != 0);	/* whole pool again: all merged */
	assert(akuio_alloc_pmem(32) == 0);	/* and now full */
	assert(akuio_vaddr2paddr(0x1234) == 0);
	akuio_pmem_fini();
	puts("selftest ok");
	return 0;
}
