/* Entry point for a program that the uClibc loader runs: uClibc's __uClibc_main() instead of glibc's
 * __libc_start_main(). Args: main, argc, argv, init, fini, rtld_fini, stack_end (last three on the stack). */
	.text
	.global _start
	.type _start, %function
_start:
	mov	fp, #0
	mov	lr, #0
	mov	r5, r0			/* rtld_fini from the loader */
	ldr	r1, [sp], #4		/* argc */
	mov	r2, sp			/* argv */
	mov	r6, sp			/* stack_end */
	bic	sp, sp, #7
	ldr	r0, =main
	mov	r3, #0			/* init: none */
	mov	r4, #0			/* fini: none */
	mov	r7, #0
	stmfd	sp!, {r4, r5, r6, r7}
	bl	__uClibc_main
	bl	abort
	.ltorg
