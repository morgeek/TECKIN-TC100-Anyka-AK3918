/* httpfront: tiny front for busybox httpd on the Linux 6.6 system.
 *
 * The busybox httpd of the base image answers 404 for any directory URL, "/" included, so a browser
 * pointed at http://camera/ shows nothing. This listener accepts the connection, peeks (MSG_PEEK) at the
 * request line without consuming it, answers "GET /" with a redirect to /index.html, and hands every other
 * connection to `httpd -i` (inetd mode) as stdin/stdout.
 *
 * usage: httpfront [-p PORT] [-h HOME] [-r TARGET]    (defaults 80, /tmp/www, /index.html)
 */
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	int port = 80, ls, on = 1, o;
	const char *home = "/tmp/www", *target = "/index.html";
	struct sockaddr_in a = { .sin_family = AF_INET };

	while ((o = getopt(argc, argv, "p:h:r:")) != -1) {
		if (o == 'p') port = atoi(optarg);
		else if (o == 'h') home = optarg;
		else if (o == 'r') target = optarg;
		else return 2;
	}
	signal(SIGCHLD, SIG_IGN);
	signal(SIGPIPE, SIG_IGN);
	ls = socket(AF_INET, SOCK_STREAM, 0);
	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
	a.sin_port = htons(port);
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	if (bind(ls, (struct sockaddr *)&a, sizeof a) || listen(ls, 16)) { perror("httpfront"); return 1; }
	for (;;) {
		int c = accept(ls, NULL, NULL);

		if (c < 0) { if (errno != EINTR) usleep(100000); continue; }
		if (fork() == 0) {
			char b[64], r[256];
			ssize_t n;
			int tries = 0;

			close(ls);
			/* wait (max ~5 s) until the request line is complete */
			for (;;) {
				n = recv(c, b, sizeof b - 1, MSG_PEEK);
				if (n <= 0) _exit(0);
				b[n] = 0;
				if (strchr(b, '\n') || n >= (ssize_t)sizeof b - 1 || ++tries > 50) break;
				usleep(100000);
			}
			if (!strncmp(b, "GET / ", 6) || !strncmp(b, "GET /?", 6) || !strncmp(b, "HEAD / ", 7)) {
				int l = snprintf(r, sizeof r, "HTTP/1.0 302 Found\r\nLocation: %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", target);

				(void)!write(c, r, l);
				_exit(0);
			}
			dup2(c, 0); dup2(c, 1);
			if (c > 2) close(c);
			execl("/usr/sbin/httpd", "httpd", "-i", "-h", home, (char *)NULL);
			_exit(1);
		}
		close(c);
	}
}
