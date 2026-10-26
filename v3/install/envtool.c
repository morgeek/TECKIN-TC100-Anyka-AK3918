/* envtool: read and change the U-Boot environment of the TECKIN TC100 from Linux (stock 3.4 or 6.6).
 *
 *   envtool show DEV                     print the variables (DEV: the MTD character device of the "ENV" partition)
 *   envtool set DEV BACKUP NAME=VALUE...  set (or, with an empty VALUE, remove) variables
 *
 * The environment is one CRC32 word followed by NAME=VALUE strings, each ended by a zero byte, and a final zero
 * byte. Its size is not known here (U-Boot's CONFIG_ENV_SIZE): the sizes that fit the partition are tried, and the
 * one whose CRC matches is used. When none matches (empty or damaged environment, U-Boot then runs on its built-in
 * one) nothing is written.
 *
 * "set" is careful: the whole partition is first saved to BACKUP (written, synced, read back and compared), then
 * erased and written, then read back and compared with what was meant; on any difference the original bytes are
 * written back (three tries). The U-Boot code itself is never touched: only DEV is opened for writing.
 * Exit: 0 done, 1 usage, 2 read / CRC problem (nothing written), 3 backup failed (nothing written), 4 write failed
 * and the original was restored, 5 write failed and the restore failed too (U-Boot then uses its built-in
 * environment: the camera still starts the stock firmware).
 *
 * Built static (CI: arm-linux-gnueabi-gcc -static) so that it runs under the stock firmware as well.
 */
#include <errno.h>
#include <fcntl.h>
#include <mtd/mtd-user.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAXPART (64 * 1024)

static uint32_t crc32(const unsigned char *p, size_t n)
{
	uint32_t c = 0xffffffffu;

	while (n--) {
		c ^= *p++;
		for (int k = 0; k < 8; k++)
			c = (c >> 1) ^ (0xedb88320u & -(c & 1));
	}
	return ~c;
}

static unsigned char part[MAXPART], want[MAXPART], back[MAXPART];
static size_t psize, esize;		/* partition size, environment size */
static unsigned eblock;			/* erase block size */
static int testmode;			/* ENVTOOL_TEST=1: DEV is a plain file (host tests) */

static int read_all(const char *dev, unsigned char *buf)
{
	int fd = open(dev, O_RDONLY);
	size_t got = 0;

	if (fd < 0) { fprintf(stderr, "envtool: %s: %s\n", dev, strerror(errno)); return -1; }
	while (got < psize) {
		ssize_t n = read(fd, buf + got, psize - got);

		if (n <= 0) { fprintf(stderr, "envtool: read %s: %s\n", dev, n ? strerror(errno) : "short"); close(fd); return -1; }
		got += n;
	}
	close(fd);
	return 0;
}

static int open_env(const char *dev)
{
	struct mtd_info_user mi;
	int fd = open(dev, O_RDONLY);
	static const size_t sizes[] = { 0x1000, 0x2000, 0x4000, 0x8000, 0x10000 };

	if (getenv("ENVTOOL_TEST")) {
		struct stat st;

		if (fd < 0 || fstat(fd, &st)) { fprintf(stderr, "envtool: %s: %s\n", dev, strerror(errno)); return -1; }
		memset(&mi, 0, sizeof mi);
		mi.size = st.st_size; mi.erasesize = 4096; mi.flags = MTD_WRITEABLE; testmode = 1;
	} else if (fd < 0 || ioctl(fd, MEMGETINFO, &mi) < 0) {
		fprintf(stderr, "envtool: %s is not an MTD device (%s)\n", dev, strerror(errno));
		if (fd >= 0) close(fd);
		return -1;
	}
	close(fd);
	if (mi.size == 0 || mi.size > MAXPART || mi.erasesize == 0 || mi.size % mi.erasesize) {
		fprintf(stderr, "envtool: unexpected partition (size %u, erase %u)\n", mi.size, mi.erasesize);
		return -1;
	}
	psize = mi.size; eblock = mi.erasesize;
	if (read_all(dev, part)) return -1;
	for (unsigned i = 0; i < sizeof sizes / sizeof sizes[0] && sizes[i] <= psize; i++) {
		uint32_t stored = part[0] | part[1] << 8 | part[2] << 16 | (uint32_t)part[3] << 24;

		if (crc32(part + 4, sizes[i] - 4) == stored) { esize = sizes[i]; break; }
	}
	if (!esize) { fprintf(stderr, "envtool: no valid environment in %s (CRC does not match any size)\n", dev); return -1; }
	if (!(mi.flags & MTD_WRITEABLE)) fprintf(stderr, "envtool: note: %s is read-only\n", dev);
	return 0;
}

/* variables: pointers into a copy of the data area */
static char *var[1024];
static int nvar;

static int parse(void)
{
	static char data[MAXPART];
	size_t i = 0, end = esize - 4;

	memcpy(data, part + 4, end);
	nvar = 0;
	while (i < end && data[i]) {
		size_t l = strnlen(data + i, end - i);

		if (i + l >= end || !strchr(data + i, '=') || nvar == (int)(sizeof var / sizeof var[0])) {
			fprintf(stderr, "envtool: environment does not parse\n");
			return -1;
		}
		var[nvar++] = data + i;
		i += l + 1;
	}
	return 0;
}

static int write_part(const char *dev, const unsigned char *buf)
{
	int fd = open(dev, O_RDWR);
	size_t done = 0;

	if (fd < 0) { fprintf(stderr, "envtool: open %s for writing: %s\n", dev, strerror(errno)); return -1; }
	for (size_t o = 0; o < psize; o += eblock) {
		struct erase_info_user ei = { .start = o, .length = eblock };

		if (!testmode && ioctl(fd, MEMERASE, &ei) < 0) { fprintf(stderr, "envtool: erase: %s\n", strerror(errno)); close(fd); return -1; }
	}
	if (lseek(fd, 0, SEEK_SET) < 0) { close(fd); return -1; }
	while (done < psize) {
		ssize_t n = write(fd, buf + done, psize - done);

		if (n <= 0) { fprintf(stderr, "envtool: write: %s\n", strerror(errno)); close(fd); return -1; }
		done += n;
	}
	close(fd);
	return 0;
}

static int write_checked(const char *dev, const unsigned char *buf)
{
	return write_part(dev, buf) || read_all(dev, back) || memcmp(back, buf, psize) ? -1 : 0;
}

int main(int argc, char **argv)
{
	if (argc < 3 || (strcmp(argv[1], "show") && strcmp(argv[1], "set")) || (!strcmp(argv[1], "set") && argc < 5)) {
		fprintf(stderr, "usage: envtool show DEV | envtool set DEV BACKUP NAME=VALUE...\n");
		return 1;
	}
	const char *dev = argv[2];

	if (open_env(dev) || parse()) return 2;
	if (!strcmp(argv[1], "show")) {
		printf("# %s: environment %zu bytes in a %zu-byte partition\n", dev, esize, psize);
		for (int i = 0; i < nvar; i++) puts(var[i]);
		return 0;
	}

	/* new variable list */
	static char *nv[1024];
	static int used[256];
	int n = 0;

	if (argc - 4 > (int)(sizeof used / sizeof used[0])) { fprintf(stderr, "envtool: too many arguments\n"); return 1; }
	for (int a = 4; a < argc; a++) {
		const char *eq = strchr(argv[a], '=');

		if (!eq || eq == argv[a]) { fprintf(stderr, "envtool: bad argument %s\n", argv[a]); return 1; }
	}
	for (int i = 0; i < nvar; i++) {	/* a variable that changes keeps its place */
		char *keep = var[i];

		for (int a = 4; a < argc; a++)
			if (!strncmp(var[i], argv[a], strchr(argv[a], '=') - argv[a] + 1)) {
				keep = strchr(argv[a], '=')[1] ? argv[a] : NULL;
				used[a - 4] = 1;
			}
		if (keep) nv[n++] = keep;
	}
	for (int a = 4; a < argc; a++)
		if (!used[a - 4] && strchr(argv[a], '=')[1] && n < (int)(sizeof nv / sizeof nv[0])) nv[n++] = argv[a];

	memset(want, 0xff, psize);
	memset(want, 0, esize);
	size_t o = 4;

	for (int i = 0; i < n; i++) {
		size_t l = strlen(nv[i]) + 1;

		if (o + l + 1 > esize) { fprintf(stderr, "envtool: the environment would not fit %zu bytes\n", esize); return 2; }
		memcpy(want + o, nv[i], l);
		o += l;
	}
	uint32_t c = crc32(want + 4, esize - 4);

	want[0] = c; want[1] = c >> 8; want[2] = c >> 16; want[3] = c >> 24;
	if (!memcmp(want, part, psize)) { printf("envtool: nothing to change\n"); return 0; }

	/* backup first */
	FILE *b = fopen(argv[3], "wb");

	if (!b || fwrite(part, 1, psize, b) != psize || fflush(b) || fsync(fileno(b)) || fclose(b)) {
		fprintf(stderr, "envtool: cannot write the backup %s\n", argv[3]);
		return 3;
	}
	b = fopen(argv[3], "rb");
	if (!b || fread(back, 1, psize, b) != psize || memcmp(back, part, psize)) {
		fprintf(stderr, "envtool: the backup %s does not read back\n", argv[3]);
		if (b) fclose(b);
		return 3;
	}
	fclose(b);

	if (!write_checked(dev, want)) { printf("envtool: environment written and verified (%zu bytes)\n", esize); return 0; }
	for (int t = 0; t < 3; t++)
		if (!write_checked(dev, part)) { fprintf(stderr, "envtool: write failed, original restored\n"); return 4; }
	fprintf(stderr, "envtool: write failed and the original could not be restored; backup in %s\n", argv[3]);
	return 5;
}
