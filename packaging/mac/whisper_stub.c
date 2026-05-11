/*
 * Mach-O загрузчик для .app: Finder корректно запускает бинарь, а не bash-скрипт
 * (иначе бывает «(null)» / нет разрешения у Finder).
 * Рядом в MacOS лежит run.sh — туда передаются argv с Finder.
 */
#include <mach-o/dyld.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void stub_logf(const char *fmt, ...) {
	char path[PATH_MAX];
	const char *home = getenv("HOME");
	va_list ap;
	int fd;

	if (!home || !*home)
		home = "/tmp";
	snprintf(path, sizeof(path), "%s/Library/Logs/WhisperStub.log", home);
	fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
	if (fd < 0) {
		snprintf(path, sizeof(path), "/tmp/WhisperStub.log");
		fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
	}
	if (fd < 0)
		return;
	va_start(ap, fmt);
	vdprintf(fd, fmt, ap);
	va_end(ap);
	dprintf(fd, "\n");
	close(fd);
}

int main(int argc, char **argv) {
	char execpath[PATH_MAX];
	uint32_t sz = (uint32_t)sizeof(execpath);
	if (_NSGetExecutablePath(execpath, &sz) != 0) {
		stub_logf("WhisperClient stub: _NSGetExecutablePath failed");
		return 1;
	}
	char *slash = strrchr(execpath, '/');
	if (!slash) {
		stub_logf("WhisperClient stub: no slash in path %s", execpath);
		return 1;
	}
	strcpy(slash + 1, "run.sh");
	stub_logf("WhisperClient stub: exec bash %s", execpath);

	size_t n = (size_t)argc + 2;
	char **av = calloc(n + 1, sizeof(char *));
	if (!av) {
		stub_logf("WhisperClient stub: calloc failed");
		return 1;
	}
	av[0] = "/bin/bash";
	av[1] = execpath;
	for (int i = 1; i < argc; i++) {
		av[(size_t)i + 1] = argv[i];
	}
	av[(size_t)argc + 1] = NULL;
	execv("/bin/bash", av);
	stub_logf("WhisperClient stub: execv(/bin/bash) failed: %s", strerror(errno));
	return 1;
}
