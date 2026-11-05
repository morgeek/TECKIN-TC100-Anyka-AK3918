/* rwconf: read or write keys of an INI-like file. Free replacement (item 53) of the prebuilt 2.x bin/rwconf, which is
 * ReadWriteConfig.cpp + ConfigFile.cpp of anyka-v4l2rtspserver (Unlicense, public domain); this is the same behaviour
 * in C, byte for byte on what the scripts of this repository use:
 *
 *   rwconf FILE r SECTION KEY [SECTION KEY ...]   prints the values separated by one space, then a newline
 *   rwconf FILE w SECTION KEY VALUE [...]         sets the values, rewrites the file
 *
 * Behaviour of the original that is kept on purpose:
 *  - SECTION " " (or "") is the top level; names and values are trimmed (space \t \n \v \f \r) on both sides.
 *  - a line is "[section]" (after trimming, longer than 2 characters, '[' first and ']' last) or "key=value" (first
 *    '=' splits; empty key ignored); a trimmed line of 2 characters or less is ignored, so "a=" is lost and "a=1" is
 *    not; any other line (comments without '=') is ignored, "#x=1" is the key "#x". The last duplicate wins.
 *  - missing file, section or key reads as an empty string (still one field and the newline); exit status always 0.
 *  - a write keeps nothing of the old layout: top level keys first, then each "[section]" with its keys, sections and
 *    keys sorted by byte value, written as "key=value\n"; comments and blank lines are dropped, CRLF becomes LF.
 *  - the file is written (truncated in place) only when a value changed and there is at least one entry; a file that
 *    cannot be opened for writing is silently left alone. Writing an empty value to a key that does not exist is
 *    not a change (but the empty key is written if another value changes).
 *  - fewer than 5 arguments or a mode not starting with r/w: the help text on stdout, status 0. Incomplete trailing
 *    groups of arguments are ignored.
 * Not kept: a NUL byte inside the file ends its line (the original keeps it inside the string).
 * No libc variable (stdout...) is used: the ARM build links against a stand-in libc (src/mqttd/Makefile). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct ent { char *sec, *key, *val; };
static struct ent *E;
static size_t nE, capE;
static int changed;

static char *dup_trim(const char *s, size_t n)
{
	while (n && strchr(" \t\n\v\f\r", s[0])) { s++; n--; }
	while (n && strchr(" \t\n\v\f\r", s[n - 1])) n--;
	char *r = malloc(n + 1);
	if (!r) exit(1);
	memcpy(r, s, n);
	r[n] = 0;
	return r;
}

static struct ent *find(const char *sec, const char *key)
{
	for (size_t i = 0; i < nE; i++)
		if (!strcmp(E[i].sec, sec) && !strcmp(E[i].key, key)) return &E[i];
	return NULL;
}

/* takes ownership of the three strings; returns the entry */
static struct ent *put(char *sec, char *key, char *val)
{
	struct ent *e = find(sec, key);
	if (e) {
		free(sec); free(key);
		if (strcmp(e->val, val)) changed = 1;
		free(e->val);
		e->val = val;
		return e;
	}
	if (nE == capE) {
		capE = capE ? capE * 2 : 16;
		E = realloc(E, capE * sizeof *E);
		if (!E) exit(1);
	}
	e = &E[nE++];
	e->sec = sec; e->key = key; e->val = val;
	if (*val) changed = 1;	/* a new entry starts as "" in the original */
	return e;
}

static void load(const char *path)
{
	FILE *f = fopen(path, "rb");
	if (!f) return;
	size_t n = 0, cap = 4096, r;
	char *buf = malloc(cap + 1);
	if (!buf) exit(1);
	while ((r = fread(buf + n, 1, cap - n, f)) > 0) {
		n += r;
		if (n == cap) { cap *= 2; buf = realloc(buf, cap + 1); if (!buf) exit(1); }
	}
	fclose(f);
	buf[n] = 0;
	/* the file opened: the original clears the config, and reading only adds */
	char *sec = dup_trim("", 0);
	for (char *p = buf; ; ) {
		char *nl = strchr(p, '\n');
		size_t len = nl ? (size_t)(nl - p) : strlen(p);
		char *next = nl ? nl + 1 : p + len;
		char *t = dup_trim(p, len);
		size_t tl = strlen(t);
		if (tl > 2) {
			if (t[0] == '[' && t[tl - 1] == ']') {
				free(sec);
				sec = dup_trim(t + 1, tl - 2);
			} else {
				char *eq = strchr(t, '=');
				if (eq) {
					char *key = dup_trim(t, (size_t)(eq - t));
					if (*key) {
						struct ent *e = find(sec, key);
						char *val = dup_trim(eq + 1, strlen(eq + 1));
						if (e) { free(e->val); e->val = val; free(key); }
						else {
							int c = changed;
							put(strdup(sec), key, val);
							changed = c;	/* reading is not a change */
						}
					} else free(key);
				}
			}
		}
		free(t);
		if (!nl) break;
		p = next;
	}
	free(sec);
	free(buf);
}

static int cmp(const void *a, const void *b)
{
	const struct ent *x = a, *y = b;
	int c = strcmp(x->sec, y->sec);
	return c ? c : strcmp(x->key, y->key);
}

static void save(const char *path)
{
	if (!nE || !changed) return;
	FILE *f = fopen(path, "wb");
	if (!f) return;
	qsort(E, nE, sizeof *E, cmp);
	const char *cur = "";
	for (size_t i = 0; i < nE; i++) {
		if (strcmp(E[i].sec, cur)) {
			cur = E[i].sec;
			fprintf(f, "[%s]\n", cur);
		}
		fprintf(f, "%s=%s\n", E[i].key, E[i].val);
	}
	fclose(f);
}

static void help(void)
{
	printf("Read/Write ini-file utility\n"
	       "Params:\n"
	       "   <ini file path>\n"
	       "   r/w   - read or write param\n"
	       "   <section name>\n"
	       "   <key name>\n"
	       "   <value>\n\n"
	       "rwconf \"myconf.ini\" r main mykey\n"
	       "rwconf \"myconf.ini\" r main mykey main mykey2 main mykey3\n"
	       "rwconf \"myconf.ini\" w main mykey mynewvalue\n"
	       "rwconf \"myconf.ini\" w main mykey mynewvalue main mykey2 mynewvalue2\n");
}

int main(int argc, char **argv)
{
	if (argc > 4 && (argv[2][0] == 'r' || argv[2][0] == 'w')) {
		load(argv[1]);
		if (argv[2][0] == 'r') {
			for (int i = 3; i <= argc - 2; i += 2) {
				char *s = dup_trim(argv[i], strlen(argv[i])), *k = dup_trim(argv[i + 1], strlen(argv[i + 1]));
				struct ent *e = find(s, k);
				printf(i == 3 ? "%s" : " %s", e ? e->val : "");
				free(s); free(k);
			}
			printf("\n");
		} else {
			for (int i = 3; i <= argc - 3; i += 3)
				put(dup_trim(argv[i], strlen(argv[i])), dup_trim(argv[i + 1], strlen(argv[i + 1])),
				    dup_trim(argv[i + 2], strlen(argv[i + 2])));
			save(argv[1]);
		}
	} else help();
	return 0;
}
