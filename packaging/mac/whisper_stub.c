/*
 * Mach-O загрузчик для .app: Finder корректно запускает бинарь, а не bash-скрипт
 * (иначе бывает «(null)» / нет разрешения у Finder).
 * Рядом в MacOS лежит run.sh — туда передаются argv с Finder.
 */
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
	char execpath[PATH_MAX];
	uint32_t sz = (uint32_t)sizeof(execpath);
	if (_NSGetExecutablePath(execpath, &sz) != 0) {
		return 1;
	}
	char *slash = strrchr(execpath, '/');
	if (!slash) {
		return 1;
	}
	strcpy(slash + 1, "run.sh");

	size_t n = (size_t)argc + 2;
	char **av = calloc(n + 1, sizeof(char *));
	if (!av) {
		return 1;
	}
	av[0] = "/bin/bash";
	av[1] = execpath;
	for (int i = 1; i < argc; i++) {
		av[(size_t)i + 1] = argv[i];
	}
	av[(size_t)argc + 1] = NULL;
	execv("/bin/bash", av);
	return 1;
}
