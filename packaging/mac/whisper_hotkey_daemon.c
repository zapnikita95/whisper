/*
 * whisper_hotkey_daemon — нативный глобальный перехватчик горячих клавиш.
 *
 * Компиляция:
 *   clang -O2 -Wall -framework ApplicationServices -framework Carbon \
 *         -o whisper_hotkey_daemon whisper_hotkey_daemon.c
 *
 * Использование:
 *   ./whisper_hotkey_daemon           # ⌃+⌥+⇧ (по умолчанию)
 *   ./whisper_hotkey_daemon fn        # клавиша Fn / Globe (PTT)
 *   ./whisper_hotkey_daemon ctrl+alt  # только две клавиши
 *
 * Вывод в stdout (одна строка):
 *   DOWN   — когда все клавиши сочетания нажаты
 *   UP     — когда хотя бы одна отпущена
 *   PING   — ответ на PING из stdin (heartbeat)
 *   READY  — при успешном старте
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

#define MOD_CTRL   kCGEventFlagMaskControl
#define MOD_ALT    kCGEventFlagMaskAlternate
#define MOD_SHIFT  kCGEventFlagMaskShift
#define MOD_CMD    kCGEventFlagMaskCommand
#define MOD_FN     kCGEventFlagMaskSecondaryFn

/* Сочетание по умолчанию: ⌃⌥⇧ без ⌘ */
static CGEventFlags g_target_flags = (MOD_CTRL | MOD_ALT | MOD_SHIFT);
static CGEventFlags g_reject_flags = MOD_CMD;
static bool         g_fn_only      = false;

static CFMachPortRef g_tap       = NULL;
static bool          g_pressed   = false;
static volatile int  g_running   = 1;

static void emit(const char *msg) {
    fputs(msg, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static void reenable_tap(void) {
    if (g_tap) {
        CGEventTapEnable(g_tap, true);
        fprintf(stderr, "[whisper_hotkey_daemon] CGEventTap re-enabled\n");
        fflush(stderr);
    }
}

static bool fn_keycode(int64_t keycode) {
    /* Fn / Globe на разных MacBook (63 = Function, 179 = Globe). */
    return keycode == 63 || keycode == 179;
}

static bool flags_combo(CGEventFlags flags) {
    if (g_fn_only) {
        bool fn_down = (flags & MOD_FN) != 0;
        bool others  = (flags & (MOD_CMD | MOD_CTRL | MOD_ALT | MOD_SHIFT)) != 0;
        return fn_down && !others;
    }
    return ((flags & g_target_flags) == g_target_flags)
        && ((flags & g_reject_flags) == 0);
}

static void press_down(void) {
    if (!g_pressed) {
        g_pressed = true;
        emit("DOWN");
    }
}

static void press_up(void) {
    if (g_pressed) {
        g_pressed = false;
        emit("UP");
    }
}

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

    if (g_fn_only) {
        if (type == kCGEventFlagsChanged) {
            bool combo = flags_combo(CGEventGetFlags(event));
            if (combo) {
                press_down();
            } else {
                press_up();
            }
            return event;
        }
        if (type == kCGEventKeyDown || type == kCGEventKeyUp) {
            int64_t keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode);
            if (fn_keycode(keycode)) {
                if (type == kCGEventKeyDown) {
                    press_down();
                } else {
                    press_up();
                }
            }
            return event;
        }
        return event;
    }

    if (type != kCGEventFlagsChanged) {
        return event;
    }

    bool combo = flags_combo(CGEventGetFlags(event));
    if (combo) {
        press_down();
    } else {
        press_up();
    }

    return event;
}

static void *stdin_reader(void *arg) {
    (void)arg;
    char buf[64];
    while (g_running && fgets(buf, sizeof(buf), stdin)) {
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
    if (g_running) {
        press_up();
        g_running = 0;
        CFRunLoopStop(CFRunLoopGetMain());
    }
    return NULL;
}

static bool parse_hotkey(const char *spec) {
    if (!spec || !*spec) return false;
    CGEventFlags target = 0;
    CGEventFlags reject = MOD_CMD;
    g_fn_only = false;

    char buf[256];
    strncpy(buf, spec, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *tok = strtok(buf, "+");
    while (tok) {
        for (char *c = tok; *c; c++) *c = (char)tolower((unsigned char)*c);

        if (strcmp(tok, "ctrl") == 0 || strcmp(tok, "control") == 0)
            target |= MOD_CTRL;
        else if (strcmp(tok, "alt") == 0 || strcmp(tok, "option") == 0 || strcmp(tok, "opt") == 0)
            target |= MOD_ALT;
        else if (strcmp(tok, "shift") == 0)
            target |= MOD_SHIFT;
        else if (strcmp(tok, "cmd") == 0 || strcmp(tok, "command") == 0) {
            target |= MOD_CMD;
            reject &= ~MOD_CMD;
        } else if (strcmp(tok, "fn") == 0 || strcmp(tok, "function") == 0 || strcmp(tok, "globe") == 0) {
            target |= MOD_FN;
        } else {
            fprintf(stderr, "[whisper_hotkey_daemon] Неизвестный модификатор: %s\n", tok);
            return false;
        }
        tok = strtok(NULL, "+");
    }

    if (!target) return false;

    if (target == MOD_FN) {
        g_fn_only = true;
        g_target_flags = MOD_FN;
        g_reject_flags = MOD_CMD | MOD_CTRL | MOD_ALT | MOD_SHIFT;
    } else {
        g_target_flags = target;
        g_reject_flags = reject;
    }
    return true;
}

static void handle_signal(int sig) {
    (void)sig;
    press_up();
    g_running = 0;
    CFRunLoopStop(CFRunLoopGetMain());
}

int main(int argc, char *argv[]) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    signal(SIGTERM, handle_signal);
    signal(SIGINT,  handle_signal);
    signal(SIGPIPE, SIG_IGN);

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
            if (!parse_hotkey(argv[i])) {
                fprintf(stderr, "[whisper_hotkey_daemon] Неверное сочетание: %s\n", argv[i]);
                return 2;
            }
        }
    }

    CGEventMask mask = CGEventMaskBit(kCGEventFlagsChanged);
    if (g_fn_only) {
        mask |= CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp);
    }

    g_tap = CGEventTapCreate(
        kCGHIDEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        mask,
        tap_callback,
        NULL
    );

    if (!g_tap) {
        fprintf(stderr,
            "[whisper_hotkey_daemon] ОШИБКА: CGEventTapCreate не удался.\n"
            "  Нужен доступ Accessibility / Input Monitoring:\n"
            "  Системные настройки → Конфиденциальность и безопасность\n"
            "  → Мониторинг ввода (добавь WhisperClient.app)\n");
        fflush(stderr);
        return 1;
    }

    CFRunLoopSourceRef src = CFMachPortCreateRunLoopSource(
        kCFAllocatorDefault, g_tap, 0);
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes);
    CGEventTapEnable(g_tap, true);

    fprintf(stderr,
        "[whisper_hotkey_daemon] started pid=%d hotkey_flags=0x%llx fn_only=%d\n",
        (int)getpid(), (unsigned long long)g_target_flags, g_fn_only ? 1 : 0);
    fflush(stderr);

    pthread_t stdin_thread;
    pthread_create(&stdin_thread, NULL, stdin_reader, NULL);
    pthread_detach(stdin_thread);

    emit("READY");

    CFRunLoopRun();

    press_up();

    if (g_tap) {
        CGEventTapEnable(g_tap, false);
        CFMachPortInvalidate(g_tap);
        CFRelease(g_tap);
    }

    return 0;
}
