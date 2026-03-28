/*
 * whisper_hotkey_daemon — нативный глобальный перехватчик горячих клавиш.
 *
 * Компиляция:
 *   clang -O2 -Wall -framework ApplicationServices -framework Carbon \
 *         -o whisper_hotkey_daemon whisper_hotkey_daemon.c
 *
 * Использование:
 *   ./whisper_hotkey_daemon           # ⌃+⌥+⇧ (по умолчанию)
 *   ./whisper_hotkey_daemon ctrl+alt  # только две клавиши
 *
 * Вывод в stdout (одна строка):
 *   DOWN   — когда все клавиши сочетания нажаты
 *   UP     — когда хотя бы одна отпущена
 *   PING   — ответ на PING из stdin (heartbeat)
 *   READY  — при успешном старте
 *
 * Особенности:
 *   - CGEventTap с автоматическим переподключением при kCGEventTapDisabledByTimeout/UserInput
 *   - НЕ вызывает TSMGetInputSourceProperty → нет SIGTRAP на macOS 15+ (Sequoia)
 *   - Работает как отдельный процесс → краш здесь не убивает Python
 *   - PING/PONG через stdin для heartbeat watchdog'а со стороны Python
 */

#include <ApplicationServices/ApplicationServices.h>
#include <Carbon/Carbon.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <pthread.h>
#include <ctype.h>

/* ── Флаги модификаторов ── */
#define MOD_CTRL   kCGEventFlagMaskControl
#define MOD_ALT    kCGEventFlagMaskAlternate
#define MOD_SHIFT  kCGEventFlagMaskShift
#define MOD_CMD    kCGEventFlagMaskCommand

/* Сочетание по умолчанию: ⌃⌥⇧ без ⌘ */
static CGEventFlags g_target_flags = (MOD_CTRL | MOD_ALT | MOD_SHIFT);
static CGEventFlags g_reject_flags = MOD_CMD;

static CFMachPortRef g_tap       = NULL;
static bool          g_pressed   = false;
static volatile int  g_running   = 1;

/* ── Вывод без буферизации ── */
static void emit(const char *msg) {
    fputs(msg, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

/* ── Переподключение CGEventTap ── */
static void reenable_tap(void) {
    if (g_tap) {
        CGEventTapEnable(g_tap, true);
        fprintf(stderr, "[whisper_hotkey_daemon] CGEventTap re-enabled\n");
        fflush(stderr);
    }
}

/* ── Основной callback CGEventTap ── */
static CGEventRef tap_callback(
    CGEventTapProxy proxy,
    CGEventType     type,
    CGEventRef      event,
    void           *refcon
) {
    (void)proxy; (void)refcon;

    if (type == kCGEventTapDisabledByTimeout ||
        type == kCGEventTapDisabledByUserInput) {
        reenable_tap();
        return event;
    }

    if (type != kCGEventFlagsChanged) {
        return event;
    }

    CGEventFlags flags = CGEventGetFlags(event);
    bool combo = ((flags & g_target_flags) == g_target_flags)
              && ((flags & g_reject_flags) == 0);

    if (combo && !g_pressed) {
        g_pressed = true;
        emit("DOWN");
    } else if (!combo && g_pressed) {
        g_pressed = false;
        emit("UP");
    }

    return event;
}

/* ── Поток: читает stdin для PING/PONG heartbeat ── */
static void *stdin_reader(void *arg) {
    (void)arg;
    char buf[64];
    while (g_running && fgets(buf, sizeof(buf), stdin)) {
        /* Убираем пробелы/переводы строк */
        char *p = buf;
        while (*p && isspace((unsigned char)*p)) p++;
        size_t len = strlen(p);
        while (len > 0 && isspace((unsigned char)p[len-1])) p[--len] = '\0';

        if (strcmp(p, "PING") == 0) {
            emit("PONG");
        } else if (strcmp(p, "STOP") == 0) {
            g_running = 0;
            CFRunLoopStop(CFRunLoopGetMain());
            break;
        }
    }
    /* stdin закрыт → Python умер, завершаемся */
    if (g_running) {
        if (g_pressed) {
            g_pressed = false;
            emit("UP");
        }
        g_running = 0;
        CFRunLoopStop(CFRunLoopGetMain());
    }
    return NULL;
}

/* ── Разбор строки hotkey: "ctrl+alt+shift" ── */
static bool parse_hotkey(const char *spec) {
    if (!spec || !*spec) return false;
    CGEventFlags target = 0;
    CGEventFlags reject = MOD_CMD;  /* ⌘ всегда отклоняем */

    char buf[256];
    strncpy(buf, spec, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *tok = strtok(buf, "+");
    while (tok) {
        /* Приводим к нижнему регистру */
        for (char *c = tok; *c; c++) *c = (char)tolower((unsigned char)*c);

        if (strcmp(tok, "ctrl") == 0 || strcmp(tok, "control") == 0)
            target |= MOD_CTRL;
        else if (strcmp(tok, "alt") == 0 || strcmp(tok, "option") == 0 || strcmp(tok, "opt") == 0)
            target |= MOD_ALT;
        else if (strcmp(tok, "shift") == 0)
            target |= MOD_SHIFT;
        else if (strcmp(tok, "cmd") == 0 || strcmp(tok, "command") == 0) {
            target |= MOD_CMD;
            reject &= ~MOD_CMD;  /* ⌘ в сочетании — не отклоняем */
        } else {
            fprintf(stderr, "[whisper_hotkey_daemon] Неизвестный модификатор: %s\n", tok);
            return false;
        }
        tok = strtok(NULL, "+");
    }

    if (!target) return false;
    g_target_flags = target;
    g_reject_flags = reject;
    return true;
}

static void handle_signal(int sig) {
    (void)sig;
    if (g_pressed) {
        g_pressed = false;
        emit("UP");
    }
    g_running = 0;
    CFRunLoopStop(CFRunLoopGetMain());
}

int main(int argc, char *argv[]) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    signal(SIGTERM, handle_signal);
    signal(SIGINT,  handle_signal);
    signal(SIGPIPE, SIG_IGN);

    /* Разбор аргументов */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--hotkey") == 0 && i + 1 < argc) {
            if (!parse_hotkey(argv[++i])) {
                fprintf(stderr, "[whisper_hotkey_daemon] Неверное сочетание: %s\n", argv[i]);
                return 2;
            }
        } else if (strncmp(argv[i], "--hotkey=", 9) == 0) {
            if (!parse_hotkey(argv[i] + 9)) {
                fprintf(stderr, "[whisper_hotkey_daemon] Неверное сочетание: %s\n", argv[i] + 9);
                return 2;
            }
        } else if (argv[i][0] != '-') {
            /* Позиционный аргумент — сочетание */
            if (!parse_hotkey(argv[i])) {
                fprintf(stderr, "[whisper_hotkey_daemon] Неверное сочетание: %s\n", argv[i]);
                return 2;
            }
        }
    }

    /* Создаём CGEventTap */
    CGEventMask mask = CGEventMaskBit(kCGEventFlagsChanged);
    g_tap = CGEventTapCreate(
        kCGHIDEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,   /* активный tap — умеет переподключаться */
        mask,
        tap_callback,
        NULL
    );

    if (!g_tap) {
        fprintf(stderr,
            "[whisper_hotkey_daemon] ОШИБКА: CGEventTapCreate не удался.\n"
            "  Нужен доступ Accessibility / Input Monitoring:\n"
            "  Системные настройки → Конфиденциальность и безопасность\n"
            "  → Универсальный доступ (добавь Terminal или WhisperClient.app)\n");
        fflush(stderr);
        return 1;
    }

    CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(
        kCFAllocatorDefault, g_tap, 0);
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
    CGEventTapEnable(g_tap, true);

    fprintf(stderr,
        "[whisper_hotkey_daemon] started pid=%d hotkey_flags=0x%llx\n",
        (int)getpid(), (unsigned long long)g_target_flags);
    fflush(stderr);

    /* Запускаем поток чтения stdin (для PING/STOP) */
    pthread_t stdin_thread;
    pthread_create(&stdin_thread, NULL, stdin_reader, NULL);
    pthread_detach(stdin_thread);

    emit("READY");

    CFRunLoopRun();

    /* Чистый выход */
    if (g_pressed) {
        g_pressed = false;
        emit("UP");
    }

    if (g_tap) {
        CGEventTapEnable(g_tap, false);
        CFMachPortInvalidate(g_tap);
        CFRelease(g_tap);
    }

    return 0;
}
