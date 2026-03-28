#!/usr/bin/env python3
"""
Клиент для Mac: запись с микрофона, отправка на Windows-сервер, вставка текста.
Запуск: python3 whisper-client-mac.py --server http://192.168.1.100:8000
Горячая клавиша: при запуске в терминале спросит строку (Enter = ⌃+⇧+⌥), либо --hotkey, либо --bind-hotkey

Рядом с Portal (⌘+⌃+P/C/V): по умолчанию ⌃+⇧+⌥ — три модификатора, без печатного символа (не пишет ` в поле и не бьётся с «терминал» в Cursor).
Переопределение: WHISPER_MAC_HOTKEY или флаг --hotkey; в WhisperClient.app хоткей задаётся в packaging/mac/run.sh.
См. PORTAL_AND_WHISPER_MAC.md

Журнал (вставка/сервер): ~/Library/Logs/WhisperMacClient.log (если нет прав — /tmp/WhisperMacClient.log); в Console фильтр «WHISPER_MAC»; после каждой строки flush на диск.
Полный текст распознавания в лог: WHISPER_MAC_DEBUG=1.
Перехват клавиш — отдельный поток с автоперезапуском; иконка 🎤/🔴 в строке меню — rumps (рекомендуется: pip install rumps; pick_python выберет интерпретатор с rumps).
Уведомления: whisper_notify, при сбое — osascript (отключить запасной путь: WHISPER_MAC_NO_OSASCRIPT_NOTIFY=1).
Опционально: WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC=N (авто-kick tap; по умолчанию ВЫКЛ — на macOS часто ломает хоткей, не включай без нужды).
osascript/System Events: WHISPER_MAC_OSASCRIPT_TIMEOUT=25 (сек) если вставка Cmd+V часто по таймауту.
Сервер: WHISPER_MAC_HEALTH_TIMEOUT=30 (сек) для GET / перед отправкой; WHISPER_MAC_TRANSCRIBE_TIMEOUT=900 (сек) ожидание ответа POST /transcribe; WHISPER_MAC_TRANSCRIBE_CONNECT_TIMEOUT=60 (сек) установка TCP (Tailscale).
Таймауты и порог эталона можно задать из меню 🎤 (или ~/.whisper/mac_client_prefs.json) — перекрывают env до сброса.
pynput: WHISPER_MAC_POST_TRANSCRIBE_LISTENER_KICK=1 — принудительный restart tap после каждой вставки (по умолчанию ВЫКЛ — иначе хоткей часто «умирает» после одной записи).
Вставка: сначала цепочка osascript (key code / keystroke, с PID и без), при провале — Quartz CGEventPost (без pynput из whisper-transcribe — иначе SIGTRAP). WHISPER_MAC_PASTE_QUARTZ_FIRST=1 — сначала только Quartz.
Хоткей по умолчанию без ⌘ (рядом с Portal).
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_rp = Path(__file__).resolve().parent
if str(_rp) not in sys.path:
    sys.path.insert(0, str(_rp))

# macOS: TSM/HIToolbox (раскладка) нельзя дёргать из фонового потока — иначе SIGTRAP в dispatch_assert_queue.
# Сброс модификаторов через pynput уходит в CGEvent/TSM; выполняем с main thread (rumps) или с потока listener.
_WhisperMainReleaseThunk = None
if sys.platform == "darwin":
    try:
        from Foundation import NSObject  # type: ignore[import-untyped]

        class _WhisperMainReleaseThunk(NSObject):  # type: ignore[misc, valid-type]
            def apply_(self, ctx: object) -> None:
                d = ctx  # NSMutableDictionary / dict
                c = d["client"]
                err = d["err"]
                try:
                    c._release_sticky_modifiers()
                except BaseException as e:
                    err[0] = e

    except ImportError:
        _WhisperMainReleaseThunk = None

try:
    import rumps
except ImportError:
    rumps = None  # type: ignore[misc, assignment]

try:
    import requests
    import sounddevice as sd
    import numpy as np
    import soundfile as sf
    from pynput import keyboard
    from pynput.keyboard import Controller as KeyboardController
    from pynput.keyboard import Key
    from pynput.keyboard import KeyCode
    import pyperclip
except ImportError as e:
    print(f"Ошибка импорта: {e}", file=sys.stderr)
    print("Установи: pip3 install requests sounddevice numpy soundfile 'pynput>=1.8.1' pyperclip", file=sys.stderr)
    sys.exit(1)


_MAC_LOGGER = logging.getLogger("whisper_mac")
_LOG_PATH: Path | None = None
# Один и тот же баннер за ~2 с — один раз (страховка от двойных путей доставки).
_LAST_MAC_BANNER: tuple[str, str, float] | None = None
_MAC_BANNER_DEDUP_SEC = 2.5

# Старт/стоп записи с хоткея: CoreAudio/sounddevice на части macOS не поднимают вход с потока CGEventTap
# (и с reader-потока внешнего hotkey daemon) — выполняем на main thread (NSRunLoop / headless drain).
_WhisperMainJobThunk = None
if sys.platform == "darwin":
    try:
        from Foundation import NSObject as _NSObjectJob  # type: ignore[import-untyped]

        class _WhisperMainJobThunk(_NSObjectJob):  # type: ignore[misc, valid-type]
            def apply_(self, ctx: object) -> None:
                d = ctx  # NSMutableDictionary или dict
                fn = d["fn"]
                try:
                    fn()
                except BaseException:
                    _MAC_LOGGER.exception("main_job_thunk_apply")

    except ImportError:
        _WhisperMainJobThunk = None

# Один процесс с меню-баром: две копии = две иконки 🎤 и «мёртвые» клики.
_MAC_MENU_BAR_LOCK_FP: object | None = None


def _mac_menu_bar_singleton_release() -> None:
    global _MAC_MENU_BAR_LOCK_FP
    fp = _MAC_MENU_BAR_LOCK_FP
    _MAC_MENU_BAR_LOCK_FP = None
    if fp is not None:
        try:
            fp.close()
        except OSError:
            pass


def _mac_menu_bar_singleton_acquire() -> tuple[bool, str]:
    """flock на ~/.whisper/mac_client_menu_bar.lock; второй экземпляр получает False."""
    global _MAC_MENU_BAR_LOCK_FP
    if sys.platform != "darwin":
        return True, ""
    try:
        import fcntl
    except ImportError:
        return True, ""
    d = Path.home() / ".whisper"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return True, ""
    p = d / "mac_client_menu_bar.lock"
    try:
        fp = open(p, "a+", encoding="utf-8")
    except OSError:
        return True, ""
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fp.close()
        hint = ""
        try:
            t = p.read_text(encoding="utf-8", errors="replace").strip().split()
            if t:
                hint = t[0]
        except OSError:
            pass
        return False, hint
    try:
        fp.seek(0)
        fp.truncate()
        fp.write(f"{os.getpid()}\n")
        fp.flush()
    except OSError:
        pass
    _MAC_MENU_BAR_LOCK_FP = fp
    atexit.register(_mac_menu_bar_singleton_release)
    _mac_log("info", "menu_bar_singleton_lock_ok pid=%s", os.getpid())
    return True, ""


class _FlushingFileHandler(logging.FileHandler):
    """После каждой записи flush — иначе при краше .app последние строки не попадают на диск."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_whisper_mac_logging() -> Path:
    """Файл ~/Library/Logs/WhisperMacClient.log; при ошибке — /tmp; всегда flush."""
    global _LOG_PATH
    fmt = logging.Formatter("%(asctime)s [WHISPER_MAC] %(levelname)s %(message)s")
    _MAC_LOGGER.setLevel(logging.DEBUG)
    _MAC_LOGGER.handlers.clear()

    candidates: list[Path] = []
    try:
        log_dir = Path.home() / "Library" / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        candidates.append(log_dir / "WhisperMacClient.log")
    except OSError:
        pass
    candidates.append(Path(tempfile.gettempdir()) / "WhisperMacClient.log")

    log_path = Path(tempfile.gettempdir()) / "WhisperMacClient.log"
    fh: logging.Handler | None = None
    for p in candidates:
        try:
            fh = _FlushingFileHandler(p, encoding="utf-8")
            log_path = p
            break
        except OSError as e:
            print(f"[Client] Лог-файл {p}: {e}", file=sys.stderr, flush=True)

    if fh is None:
        fh = logging.StreamHandler(sys.stderr)
        print("[Client] Пишу лог только в stderr (не удалось создать файл).", file=sys.stderr, flush=True)

    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    _MAC_LOGGER.addHandler(fh)
    if sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        _MAC_LOGGER.addHandler(sh)

    _LOG_PATH = log_path if fh is not None and isinstance(fh, _FlushingFileHandler) else None

    def _excepthook(exc_type, exc, tb) -> None:
        if _MAC_LOGGER.handlers:
            _MAC_LOGGER.error("uncaught_exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    _MAC_LOGGER.info("logging_ok path=%s", log_path)
    return log_path


def ingest_macos_python_crash_reports_into_log() -> None:
    """
    После SIGTRAP/краша Python не пишет в WhisperMacClient.log — отчёт остаётся в
    ~/Library/Logs/DiagnosticReports/Python-*.ips. При следующем старте подтягиваем
    новые отчёты, похожие на наш клиент (coalition / whisper-client-mac), одной строкой в лог.
    Отключить: WHISPER_MAC_SKIP_DIAGNOSTIC_INGEST=1
    """
    if sys.platform != "darwin":
        return
    if os.environ.get("WHISPER_MAC_SKIP_DIAGNOSTIC_INGEST", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    root = Path.home() / "Library" / "Logs" / "DiagnosticReports"
    if not root.is_dir():
        return
    state_dir = Path.home() / ".whisper"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    state_path = state_dir / "logged_macos_crash_incidents.json"
    try:
        blob = json.loads(state_path.read_text(encoding="utf-8"))
        seen: set[str] = set(blob.get("incidents", []))
    except Exception:
        seen = set()

    def _is_whisper_related(snippet: str) -> bool:
        s = snippet.lower()
        return (
            "local.whisper.client" in snippet
            or "whisper-client-mac.py" in snippet
            or "whisperclient.app" in s
            or "/whisper/whisper-client-mac" in s
        )

    try:
        files = sorted(
            root.glob("Python-*.ips"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:15]
    except OSError:
        return

    new_ids: list[str] = []
    for p in files:
        try:
            raw = p.read_bytes()[:200_000].decode("utf-8", errors="replace")
        except OSError:
            continue
        if not _is_whisper_related(raw):
            continue
        first_line = raw.split("\n", 1)[0].strip()
        try:
            meta = json.loads(first_line)
        except json.JSONDecodeError:
            continue
        inc = str(meta.get("incident_id") or p.stem).strip()
        if not inc or inc in seen:
            continue
        exc_type = ""
        term = ""
        m_exc = re.search(r'"exception"\s*:\s*\{[^}]*"type"\s*:\s*"([^"]+)"', raw)
        if m_exc:
            exc_type = m_exc.group(1)
        m_term = re.search(r'"indicator"\s*:\s*"([^"]+)"', raw)
        if m_term:
            term = m_term.group(1).replace("\\/", "/")
        top = ""
        m_tsm = re.search(r"TSMGetInputSourceProperty|_dispatch_assert_queue_fail", raw)
        if m_tsm:
            top = " (стек: dispatch_assert_queue / TSM — см. .ips)"
        _MAC_LOGGER.warning(
            "macos_diagnostic_ingested file=%s incident=%s captureTime=%s exception=%s termination=%s%s "
            "полный отчёт: %s",
            p.name,
            inc,
            meta.get("timestamp", "?"),
            exc_type or "?",
            term or "?",
            top,
            p,
        )
        seen.add(inc)
        new_ids.append(inc)

    if not new_ids:
        return
    try:
        # не раздуваем файл бесконечно
        keep = list(seen)[-400:]
        state_path.write_text(json.dumps({"incidents": keep}), encoding="utf-8")
    except OSError:
        pass


def _mac_log(level: str, msg: str, *args: object) -> None:
    log_fn = getattr(_MAC_LOGGER, level.lower(), None)
    if log_fn:
        log_fn(msg, *args)
    else:
        _MAC_LOGGER.info(msg, *args)


def _macos_touch_microphone_permission_if_bundle() -> None:
    """Один раз открываем default input при старте из .app.

    macOS не добавляет приложение в «Микрофон», пока кто-то реально не откроет вход.
    Раньше это происходило только при зажатии хоткея — из-за этого список казался «пустым».
    """
    if sys.platform != "darwin":
        return
    if not os.environ.get("WHISPER_FROM_APP_BUNDLE"):
        return
    try:
        with sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            blocksize=256,
        ):
            pass
    except OSError as e:
        _mac_log(
            "info",
            "mic_touch_bundle err=%s — проверь «Конфиденциальность и безопасность → Микрофон» (или «Python», если так в списке)",
            e,
        )
    except Exception as e:
        _mac_log("debug", "mic_touch_bundle unexpected err=%s", e)
    else:
        _mac_log("info", "mic_touch_bundle opened_default_input (диалог TCC мог появиться)")


def _rumps_apply_accessory_activation_policy() -> None:
    """Accessory-после инициализации статус-бара: иначе ранний setActivationPolicy ломает клики по NSStatusItem."""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory  # type: ignore[import]

        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        _mac_log("debug", "ns_activation_policy=accessory (rumps before_start)")
    except Exception as _e:
        _mac_log("debug", "ns_activation_policy_skip err=%s", _e)


def _fastapi_error_detail(resp: requests.Response) -> str:
    """Текст из JSON FastAPI/Starlette (`detail`) — чтобы в уведомлении было не только «500 Server Error»."""
    try:
        j = resp.json()
    except ValueError:
        body = (resp.text or "").strip()
        return (body[:400] if body else f"HTTP {resp.status_code}")
    if not isinstance(j, dict):
        return f"HTTP {resp.status_code}"
    d = j.get("detail")
    if isinstance(d, str):
        return d
    if isinstance(d, list):
        parts: list[str] = []
        for item in d[:5]:
            if isinstance(item, dict):
                parts.append(str(item.get("msg", item)))
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else f"HTTP {resp.status_code}"
    return f"HTTP {resp.status_code}"


def mac_banner_notification(title: str, body: str = "") -> None:
    """macOS: сначала whisper_notify из .app; при сбое — osascript (иначе тишина). Полный отказ от osascript: WHISPER_MAC_NO_OSASCRIPT_NOTIFY=1."""
    if sys.platform != "darwin":
        return
    if os.environ.get("WHISPER_MAC_NO_NOTIFICATIONS") == "1":
        return
    t = (title or "Whisper Client").strip()[:200]
    b = (body or "").strip()[:650]
    global _LAST_MAC_BANNER
    now = time.time()
    if _LAST_MAC_BANNER is not None:
        pt, pb, pts = _LAST_MAC_BANNER
        if pt == t and pb == b and (now - pts) < _MAC_BANNER_DEDUP_SEC:
            _MAC_LOGGER.debug("mac_banner_dedup title=%r", t[:80])
            return
    _LAST_MAC_BANNER = (t, b, now)
    payload = (t + "\n" + b).encode("utf-8")
    tool = (os.environ.get("WHISPER_NOTIFY_TOOL") or "").strip()
    from_app = os.environ.get("WHISPER_FROM_APP_BUNDLE") == "1"
    strict_no_osa = os.environ.get("WHISPER_MAC_NO_OSASCRIPT_NOTIFY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    def _notify_via_osascript() -> None:
        esc_t = t.replace("\\", "\\\\").replace('"', '\\"')
        esc_b = b.replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{esc_b}" with title "{esc_t}"',
                ],
                check=False,
                capture_output=True,
                timeout=10.0,
            )
        except Exception:
            pass

    if tool and Path(tool).is_file() and os.access(tool, os.X_OK):
        for attempt in (1, 2):
            _proc = None
            try:
                _proc = subprocess.Popen(
                    [tool],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                _, _err = _proc.communicate(input=payload, timeout=3.0)
                if _proc.returncode == 0:
                    return
                _MAC_LOGGER.debug(
                    "whisper_notify_nonzero_exit attempt=%s code=%s stderr=%r",
                    attempt,
                    _proc.returncode,
                    (_err or b"")[:300],
                )
            except subprocess.TimeoutExpired:
                # subprocess.run НЕ убивает дочерний процесс — делаем явно
                if _proc:
                    try:
                        _proc.kill()
                        _proc.communicate()
                    except Exception:
                        pass
                _MAC_LOGGER.debug("whisper_notify_timeout attempt=%s — killed", attempt)
            except Exception:
                _MAC_LOGGER.debug("whisper_notify_tool_failed attempt=%s", attempt, exc_info=True)
            if attempt == 1:
                time.sleep(0.15)
        if from_app and strict_no_osa:
            _MAC_LOGGER.warning(
                "mac_banner_whisper_notify_failed strict_no_osascript title=%r",
                t[:80],
            )
            try:
                subprocess.run(
                    [
                        "logger",
                        "-t",
                        "Whisper Client",
                        "%s: %s" % (t, b),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=3.0,
                )
            except Exception:
                pass
            return
        _MAC_LOGGER.info("mac_banner_osascript_fallback_after_whisper_notify title=%r", t[:60])
        _notify_via_osascript()
        return

    if from_app and strict_no_osa:
        _MAC_LOGGER.warning("mac_banner_no_notify_tool strict_no_osascript title=%r", t[:80])
        return
    _notify_via_osascript()


def _listener_idle_recycle_sec() -> float:
    """Опционально: перезапуск tap каждые N с простоя (может ломать macOS — по умолчанию ВЫКЛ)."""
    raw = (os.environ.get("WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC") or "").strip().lower()
    if raw in ("", "0", "no", "off", "false"):
        return 0.0
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 0.0


def _mac_osascript_timeout_sec(*, fallback: float) -> float:
    """
    Таймаут для osascript → System Events (вставка, фокус, снимок PID).
    При первом запуске macOS может долго будить System Events; 3 с часто мало → TimeoutExpired.
    Переопределение: WHISPER_MAC_OSASCRIPT_TIMEOUT=25 (секунды, 4…120).
    """
    raw = (os.environ.get("WHISPER_MAC_OSASCRIPT_TIMEOUT") or "").strip()
    if raw:
        try:
            return max(4.0, min(120.0, float(raw)))
        except ValueError:
            pass
    return max(4.0, min(120.0, fallback))


def _mac_notify_progress(body: str) -> None:
    """«Отправка на сервер» — по умолчанию только при запуске из .app (меньше шума в терминале)."""
    if os.environ.get("WHISPER_MAC_NOTIFY_PROGRESS", "1" if os.environ.get("WHISPER_FROM_APP_BUNDLE") else "0") != "1":
        return
    mac_banner_notification("Whisper", body)


_MAC_CLIENT_PREF_KEYS = frozenset(
    {"health_timeout", "transcribe_timeout", "transcribe_connect_timeout", "speaker_threshold"}
)


def _mac_client_prefs_path() -> Path:
    return Path.home() / ".whisper" / "mac_client_prefs.json"


def load_mac_client_prefs() -> dict[str, float]:
    path = _mac_client_prefs_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k in _MAC_CLIENT_PREF_KEYS:
        if k not in raw:
            continue
        try:
            out[k] = float(raw[k])
        except (TypeError, ValueError):
            continue
    return out


def merge_mac_client_prefs(updates: dict[str, float | None]) -> None:
    path = _mac_client_prefs_path()
    cur: dict[str, object] = {}
    try:
        if path.is_file():
            cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    for k, v in updates.items():
        if k not in _MAC_CLIENT_PREF_KEYS:
            continue
        if v is None:
            cur.pop(k, None)
        else:
            try:
                cur[k] = float(v)
            except (TypeError, ValueError):
                continue
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_mac_update_flow(*, notify_always: bool = False, notify_newer_only: bool = False) -> None:
    """Проверка GitHub Releases; при наличии .dmg — скачать в ~/Downloads."""
    import urllib.request
    import webbrowser

    try:
        from whisper_update_check import fetch_latest_release, is_remote_newer, pick_asset_url
        from whisper_version import get_version
    except ImportError:
        mac_banner_notification("Whisper", "Обнови WhisperClient.app (нет модулей версии/обновлений).")
        return

    cur = get_version()
    rel = fetch_latest_release()
    if rel is None:
        if notify_always:
            mac_banner_notification("Whisper", "Не удалось связаться с GitHub (сеть или лимит API).")
        _mac_log("warning", "update_check_no_release_response")
        return
    tag = (rel.get("tag_name") or "").strip()
    if not is_remote_newer(tag, cur):
        if notify_always:
            mac_banner_notification("Whisper", f"Установлена актуальная версия ({cur}).")
        return
    if notify_newer_only and not notify_always:
        mac_banner_notification(
            "Whisper",
            f"Доступна версия {tag}. Меню → Проверить обновления…",
        )
        return
    picked = pick_asset_url(rel, suffix=".dmg", contains="whisperclient")
    html = (rel.get("html_url") or "").strip() or "https://github.com/zapnikita95/whisper/releases"
    if not picked:
        assets = rel.get("assets") or []
        names = [(a.get("name") or "") for a in assets if isinstance(a, dict)]
        _mac_log(
            "warning",
            "update_no_dmg_asset tag=%s assets=%r — в релизе должен быть .dmg (CI: build-macos → publish)",
            tag,
            names[:20],
        )
        webbrowser.open(html)
        mac_banner_notification(
            "Whisper",
            "В релизе нет DMG в assets — открыта страница GitHub; скачай вручную или попроси собрать тег v*.",
        )
        return
    name, url = picked
    dest = Path.home() / "Downloads" / name
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WhisperMacClient/1.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            dest.write_bytes(resp.read())
        mac_banner_notification(
            "Whisper",
            f"Скачано {dest.name} — открой DMG и перетащи Whisper Client в Программы.",
        )
        _mac_log("info", "update_downloaded path=%s", dest)
    except Exception as e:
        _MAC_LOGGER.exception("update_download_failed")
        webbrowser.open(html)
        mac_banner_notification("Whisper", f"Скачивание не удалось ({e!s:.80}) — открыта страница релиза.")


def tray_icon_path() -> str | None:
    """Иконка для строки меню: WHISPER_MAC_RESOURCES (.app), рядом со скриптом, assets репозитория."""
    res = (os.environ.get("WHISPER_MAC_RESOURCES") or "").strip()
    if res:
        base = Path(res)
        for name in ("AppIcon.icns", "AppIcon.png"):
            p = base / name
            if p.is_file():
                return str(p)
    here = Path(__file__).resolve().parent
    for name in ("AppIcon.icns", "AppIcon.png"):
        p = here / name
        if p.is_file():
            return str(p)
    assets = here.parent / "assets" / "AppIcon.icns"
    if assets.is_file():
        return str(assets)
    return None


def _check_pynput_py313() -> None:
    """CPython 3.13 добавил Thread._handle — ломает pynput < 1.8 (TypeError: ThreadHandle not callable)."""
    if sys.version_info < (3, 13):
        return
    try:
        from importlib.metadata import version as pkg_version
    except ImportError:
        return
    raw = pkg_version("pynput")
    nums: list[int] = []
    for part in raw.split(".")[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    while len(nums) < 3:
        nums.append(0)
    if tuple(nums) < (1, 8, 0):
        print(
            f"[Client] У тебя Python 3.13 и pynput {raw} — глобальные клавиши падают.\n"
            f"[Client] Обнови: pip3 install -U 'pynput>=1.8.1'",
            file=sys.stderr,
        )
        if os.environ.get("WHISPER_FROM_APP_BUNDLE") == "1" and sys.platform == "darwin":
            fix = f"{sys.executable} -m pip install -U 'pynput>=1.8.1'"
            dlg = (
                f"Python 3.13 нужен pynput ≥ 1.8 (сейчас {raw}).\n\n"
                f"Скопируй в Терминал:\n{fix}"
            )
            esc = dlg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            try:
                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        f'display dialog "{esc}" buttons {{"OK"}} default button 1 '
                        'with title "Whisper Client — обнови pynput"',
                    ],
                    check=False,
                    capture_output=True,
                    timeout=120.0,
                )
            except Exception:
                pass
        sys.exit(1)


# Вызов перенесён в main() после configure_whisper_mac_logging — иначе при .app ошибка не попадает в файл лога.


# --- Модификаторы pynput → каноническое имя
_MOD_MAP: dict[Key, str] = {
    Key.cmd_l: "cmd",
    Key.cmd_r: "cmd",
    Key.cmd: "cmd",
    Key.alt_l: "alt",
    Key.alt_r: "alt",
    Key.alt: "alt",
    Key.ctrl_l: "ctrl",
    Key.ctrl_r: "ctrl",
    Key.ctrl: "ctrl",
    Key.shift_l: "shift",
    Key.shift_r: "shift",
    Key.shift: "shift",
}

_MOD_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "super": "cmd",
    "win": "cmd",
    "⌘": "cmd",
    "alt": "alt",
    "option": "alt",
    "⌥": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
    "^": "ctrl",
    "shift": "shift",
}

# Синонимы не-буквенных клавиш → один символ для токена c:X
_KEY_ALIASES = {
    "grave": "`",
    "backtick": "`",
    "tick": "`",
    "rbracket": "]",
    "bracket_right": "]",
    "rb": "]",
    "lbracket": "[",
    "bracket_left": "[",
    "lb": "[",
    "comma": ",",
    "period": ".",
    "dot": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "quote": "'",
    "apostrophe": "'",
    "minus": "-",
    "hyphen": "-",
    "equals": "=",
    "plus": "+",
}

_NAMED_KEY_TOKENS = frozenset(
    n
    for n in dir(Key)
    if not n.startswith("_")
    and not callable(getattr(Key, n, None))
    and isinstance(getattr(Key, n, None), Key)
)


def key_event_token(key) -> str | None:
    """Один токен для текущего события клавиши (для сравнения с HotkeySpec)."""
    if key in _MOD_MAP:
        return f"m:{_MOD_MAP[key]}"
    if isinstance(key, Key):
        return f"n:{key.name}"
    if isinstance(key, KeyCode):
        if key.char:
            ch = key.char
            if ch.isprintable() and ch not in "\r":
                return f"c:{ch}"
        if key.vk is not None:
            return f"v:{int(key.vk)}"
    return None


def is_valid_hotkey_tokens(tokens: frozenset[str]) -> bool:
    """Можно ли считать набор завершённым сочетанием (для --bind-hotkey)."""
    mods = [t for t in tokens if t.startswith("m:")]
    others = [t for t in tokens if not t.startswith("m:")]
    if len(mods) < 1:
        return False
    if not others:
        return len(mods) >= 2
    return len(others) >= 1


def validate_spec_tokens(tokens: frozenset[str]) -> None:
    if len(tokens) < 2:
        raise ValueError("Нужно минимум две клавиши в сочетании (например cmd+alt или ctrl+`).")
    if not is_valid_hotkey_tokens(tokens):
        raise ValueError(
            "Нужен хотя бы один модификатор (cmd/alt/ctrl/shift) и ещё клавиша, "
            "либо два модификатора (как cmd+alt)."
        )


@dataclass(frozen=True)
class HotkeySpec:
    tokens: frozenset[str]

    @staticmethod
    def default_mac_with_portal() -> HotkeySpec:
        """⌃+⇧+⌥ — только модификаторы: не вводят символ в текст и не совпадают с ⌃⇧` в Cursor (терминал)."""
        return HotkeySpec(frozenset({"m:shift", "m:ctrl", "m:alt"}))

    @staticmethod
    def default_option_ctrl() -> HotkeySpec:
        """⌥+⌃ (старое умолчание; может мешать другим приложениям с Ctrl)."""
        return HotkeySpec(frozenset({"m:alt", "m:ctrl"}))


def parse_hotkey_string(s: str) -> HotkeySpec:
    s = s.strip()
    if not s:
        raise ValueError("Пустая строка --hotkey")
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", s) if p.strip()]
    if not parts:
        raise ValueError("Пустое сочетание")
    toks: set[str] = set()
    for p in parts:
        if p in _MOD_ALIASES:
            toks.add(f"m:{_MOD_ALIASES[p]}")
        elif p in _KEY_ALIASES:
            toks.add(f"c:{_KEY_ALIASES[p]}")
        elif re.fullmatch(r"vk:\d+", p):
            toks.add(f"v:{int(p[3:])}")
        elif len(p) == 1:
            toks.add(f"c:{p}")
        elif p in _NAMED_KEY_TOKENS:
            toks.add(f"n:{p}")
        else:
            raise ValueError(
                f"Неизвестная клавиша «{p}». Примеры: cmd, alt, ctrl, shift, grave, rbracket, f5, vk:50"
            )
    ft = frozenset(toks)
    validate_spec_tokens(ft)
    return HotkeySpec(ft)


def describe_hotkey(spec: HotkeySpec) -> str:
    """Человекочитаемо для логов."""
    mod_order = ("cmd", "ctrl", "alt", "shift")
    mod_labels = {"cmd": "⌘", "alt": "⌥", "ctrl": "⌃", "shift": "⇧"}
    mods: list[str] = []
    keys: list[str] = []
    for t in spec.tokens:
        if t.startswith("m:"):
            name = t[2:]
            mods.append((mod_order.index(name) if name in mod_order else 99, mod_labels.get(name, name)))
        elif t.startswith("c:"):
            ch = t[2:]
            if ch == "`":
                keys.append("`")
            elif ch in "'\"\\":
                keys.append(repr(ch))
            else:
                keys.append(ch)
        elif t.startswith("n:"):
            keys.append(t[2:])
        elif t.startswith("v:"):
            keys.append(f"vk:{t[2:]}")
    mods.sort(key=lambda x: x[0])
    parts = [m[1] for m in mods] + sorted(keys)
    return "+".join(parts) if parts else str(spec.tokens)


def bind_hotkey_interactive(timeout: float = 90.0) -> HotkeySpec:
    print(
        "[Client] Привязка: зажми целиком сочетание (например ⌃+` или ⌃+]), затем отпусти все клавиши.",
        flush=True,
    )
    print("[Client] Ctrl+C — отмена и выход.", flush=True)
    pressed: set[str] = set()
    last_good: frozenset[str] | None = None
    done = threading.Event()
    out: list[HotkeySpec | None] = [None]

    def on_press(key):
        t = key_event_token(key)
        if t:
            pressed.add(t)

    def on_release(key):
        nonlocal last_good
        snap = frozenset(pressed)
        if is_valid_hotkey_tokens(snap):
            last_good = snap
        t = key_event_token(key)
        if t:
            pressed.discard(t)
        if not pressed and last_good is not None:
            try:
                validate_spec_tokens(last_good)
            except ValueError as e:
                print(f"[Client] Сочетание не подходит: {e}", flush=True)
                last_good = None
                return
            out[0] = HotkeySpec(last_good)
            print(f"[Client] Запомнил токены: {sorted(last_good)}", flush=True)
            done.set()

    with keyboard.Listener(
        on_press=on_press, on_release=on_release, suppress=False
    ) as listener:
        if done.wait(timeout):
            assert out[0] is not None
            return out[0]
    print("[Client] Таймаут привязки — остаётся ⌃+⇧+⌥ (shift+ctrl+alt).", flush=True)
    return HotkeySpec.default_mac_with_portal()


class _InProcessCGEventTap:
    """
    CGEventTap внутри Python-процесса через PyObjC Quartz.

    Преимущества перед внешним бинарём (whisper_hotkey_daemon):
    - Использует права Input Monitoring САМОГО Python-процесса → работает из .app без
      дополнительных разрешений (Python уже авторизован, т.к. pynput его добавил).
    - Нет TSM-крашей (SIGTRAP) — мы не вызываем pynput.Listener, только CGEventGetFlags.
    - Нет зависаний CGEventTapCreate — работает в том же процессе, что и rumps.
    - Автоматически переподключает tap при kCGEventTapDisabledByTimeout.

    Requires: pyobjc-framework-Quartz (уже в venv через pynput/rumps).
    """

    # Флаги по умолчанию: ⌃+⌥+⇧ без ⌘
    _DEFAULT_TARGET = 0xe0000   # ctrl|alt|shift
    _DEFAULT_REJECT = 0x100000  # cmd

    def __init__(
        self,
        on_down: "Callable[[], None]",
        on_up: "Callable[[], None]",
        target_flags: int = _DEFAULT_TARGET,
        reject_flags: int = _DEFAULT_REJECT,
    ) -> None:
        self._on_down = on_down
        self._on_up = on_up
        self._target_flags = target_flags
        self._reject_flags = reject_flags
        self._pressed = False
        self._pressed_lock = threading.Lock()
        self._stop = threading.Event()
        self._tap = None          # CGEventTapRef (CFMachPortRef)
        self._runloop = None      # CFRunLoopRef текущего tap-потока
        self._thread: threading.Thread | None = None
        self._callback_ref = None  # держим callable от GC

    @classmethod
    def flags_for_spec(cls, spec: "HotkeySpec") -> "tuple[int, int]":
        """Конвертирует HotkeySpec в (target_flags, reject_flags)."""
        _MAP = {
            "ctrl":  0x40000,
            "alt":   0x80000,
            "shift": 0x20000,
            "cmd":   0x100000,
        }
        target = 0
        reject = 0x100000  # по умолчанию отклоняем cmd
        for t in spec.tokens:
            if t.startswith("m:"):
                k = t[2:]
                if k in _MAP:
                    target |= _MAP[k]
                    if k == "cmd":
                        reject &= ~0x100000  # cmd в сочетании — не отклоняем
        return target, reject

    def start(self) -> bool:
        """Запускает CGEventTap в фоновом потоке. Возвращает True при успехе."""
        try:
            from Quartz import (
                CGEventTapCreate,
                CGEventGetFlags,
                CGEventTapEnable,
                kCGEventFlagsChanged,
                kCGHIDEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionDefault,
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
            )
            from CoreFoundation import (
                CFMachPortCreateRunLoopSource,
                CFRunLoopAddSource,
                CFRunLoopGetCurrent,
                CFRunLoopRun,
                CFRunLoopStop,
                kCFRunLoopCommonModes,
            )
        except ImportError as e:
            _mac_log("debug", "in_process_tap_no_quartz %s", e)
            return False

        self._stop.clear()
        ready_ev = threading.Event()
        fail: list[str] = []

        target = self._target_flags
        reject = self._reject_flags

        def _tap_thread() -> None:
            try:
                # Callback: вызывается из C-слоя PyObjC (GIL захватывается автоматически)
                def _cb(proxy, event_type, event, refcon):
                    if event_type in (
                        kCGEventTapDisabledByTimeout,
                        kCGEventTapDisabledByUserInput,
                    ):
                        t = self._tap
                        if t:
                            CGEventTapEnable(t, True)
                            _mac_log("debug", "in_process_tap_reenabled type=%s", event_type)
                        return event

                    if event_type != kCGEventFlagsChanged:
                        return event

                    flags = CGEventGetFlags(event)
                    combo = bool(
                        (flags & target) == target
                        and (flags & reject) == 0
                    )

                    down = up = False
                    with self._pressed_lock:
                        if combo and not self._pressed:
                            self._pressed = True
                            down = True
                        elif not combo and self._pressed:
                            self._pressed = False
                            up = True
                    if down:
                        try:
                            self._on_down()
                        except Exception:
                            _MAC_LOGGER.exception("in_process_tap_on_down")
                    elif up:
                        try:
                            self._on_up()
                        except Exception:
                            _MAC_LOGGER.exception("in_process_tap_on_up")

                    return event

                self._callback_ref = _cb  # защита от GC

                mask = 1 << kCGEventFlagsChanged
                tap = CGEventTapCreate(
                    kCGHIDEventTap,
                    kCGHeadInsertEventTap,
                    kCGEventTapOptionDefault,
                    mask,
                    _cb,
                    None,
                )

                if tap is None:
                    fail.append("CGEventTapCreate returned None — нет Input Monitoring?")
                    ready_ev.set()
                    return

                self._tap = tap
                src = CFMachPortCreateRunLoopSource(None, tap, 0)
                rl = CFRunLoopGetCurrent()
                self._runloop = rl
                CFRunLoopAddSource(rl, src, kCFRunLoopCommonModes)
                CGEventTapEnable(tap, True)

                ready_ev.set()
                _mac_log("debug", "in_process_tap_runloop_start target_flags=0x%x", target)
                CFRunLoopRun()  # блокирует до CFRunLoopStop

            except Exception as e:
                fail.append(str(e))
                ready_ev.set()
                _MAC_LOGGER.exception("in_process_tap_thread_error")

        self._thread = threading.Thread(
            target=_tap_thread,
            name="whisper-cg-event-tap",
            daemon=True,
        )
        self._thread.start()
        ready_ev.wait(timeout=3.0)

        if fail:
            _mac_log("warning", "in_process_tap_failed: %s", fail[0])
            return False

        if not (self._thread.is_alive() and self._tap is not None):
            _mac_log("warning", "in_process_tap_not_alive")
            return False

        _mac_log(
            "info",
            "in_process_cgeventtap_active target_flags=0x%x reject_flags=0x%x",
            target,
            reject,
        )
        return True

    def force_release_pressed(self) -> None:
        """После Cmd+V / долгой обработки флаги модификаторов могут не дать UP — сбрасываем модель."""
        with self._pressed_lock:
            self._pressed = False

    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._tap is not None
        )

    def stop(self) -> None:
        self._stop.set()
        with self._pressed_lock:
            self._pressed = False
        rl = self._runloop
        if rl is not None:
            try:
                from CoreFoundation import CFRunLoopStop
                CFRunLoopStop(rl)
            except Exception:
                pass
        tap = self._tap
        if tap is not None:
            try:
                from Quartz import CGEventTapEnable
                CGEventTapEnable(tap, False)
            except Exception:
                pass
            self._tap = None
        if self._thread:
            self._thread.join(timeout=3.0)


class _HotkeyDaemon:
    """
    Нативный CGEventTap-процесс вместо pynput Listener.

    Запускает whisper_hotkey_daemon (C-бинарь), читает DOWN/UP из его stdout
    и вызывает on_down/on_up. Автоматически отвечает на PING (heartbeat) и
    пересоздаёт процесс если он упал.

    Нет TSM-крашей (SIGTRAP на macOS 15+), нет зависания CGEventTapCreate.
    """

    _SEARCH_ENV = "WHISPER_HOTKEY_DAEMON"

    def __init__(
        self,
        on_down: "Callable[[], None]",
        on_up: "Callable[[], None]",
        hotkey_spec: str = "ctrl+alt+shift",
    ) -> None:
        self._on_down = on_down
        self._on_up = on_up
        self._hotkey_spec = hotkey_spec
        self._proc: subprocess.Popen[str] | None = None
        self._reader_t: threading.Thread | None = None
        self._stop = threading.Event()
        self._binary: Path | None = None

    def force_release_pressed(self) -> None:
        """Совместимость с _InProcessCGEventTap; состояние в отдельном процессе."""
        return

    # ── Поиск бинаря ──────────────────────────────────────────────────────────
    @classmethod
    def find_binary(cls) -> "Path | None":
        candidates: list[Path] = []

        env_val = (os.environ.get(cls._SEARCH_ENV) or "").strip()
        if env_val:
            candidates.append(Path(env_val))

        script_dir = Path(__file__).resolve().parent
        # рядом со скриптом (dev-режим + app-bundle Contents/MacOS)
        candidates.append(script_dir / "whisper_hotkey_daemon")
        # packaging/mac/ (после ручной сборки)
        candidates.append(script_dir / "packaging" / "mac" / "whisper_hotkey_daemon")
        # внутри собранного .app рядом с репо
        candidates.append(
            script_dir / "packaging" / "mac" / "WhisperClient.app"
            / "Contents" / "MacOS" / "whisper_hotkey_daemon"
        )

        for p in candidates:
            try:
                if p.is_file() and os.access(str(p), os.X_OK):
                    return p
            except OSError:
                continue
        return None

    # ── Старт ─────────────────────────────────────────────────────────────────
    def start(self) -> bool:
        binary = self.find_binary()
        if binary is None:
            _mac_log("warning", "hotkey_daemon_binary_not_found search_env=%s", self._SEARCH_ENV)
            return False
        self._binary = binary
        self._stop.clear()
        try:
            self._proc = subprocess.Popen(
                [str(binary), "--hotkey", self._hotkey_spec],
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            _mac_log("warning", "hotkey_daemon_popen_failed %s", e)
            return False

        # Ждём READY (daemon пишет его немедленно) или быстрый exit с ошибкой.
        ready = False
        if self._proc.stdout:
            import select as _select
            try:
                rlist, _, _ = _select.select([self._proc.stdout], [], [], 2.0)
            except Exception:
                rlist = []
            if rlist:
                try:
                    first_line = self._proc.stdout.readline()
                    stripped = first_line.strip()
                    if stripped == "READY":
                        ready = True
                    else:
                        rc = self._proc.poll()
                        stderr_tail = ""
                        if self._proc.stderr:
                            try:
                                stderr_tail = self._proc.stderr.read(2000)
                            except Exception:
                                pass
                        _mac_log(
                            "warning",
                            "hotkey_daemon_unexpected_first_line %r rc=%s stderr_tail=%r",
                            stripped,
                            rc,
                            (stderr_tail[-500:] if stderr_tail else ""),
                        )
                except Exception as e:
                    _mac_log("warning", "hotkey_daemon_readline_error %s", e)
            else:
                # 2с прошло без READY — проверяем, живой ли
                rc = self._proc.poll()
                stderr_txt = ""
                if rc is not None:
                    if self._proc.stderr:
                        try:
                            stderr_txt = self._proc.stderr.read(2000)
                        except Exception:
                            pass
                    _mac_log(
                        "warning",
                        "hotkey_daemon_exited_early rc=%s stderr=%r",
                        rc,
                        stderr_txt[:300],
                    )
                else:
                    _mac_log("warning", "hotkey_daemon_no_ready_in_2s")

        if not ready:
            try:
                self._proc.kill()
            except Exception:
                pass
            return False

        # Поток чтения stderr (DEBUG-уровень)
        if self._proc.stderr:
            threading.Thread(
                target=self._stderr_reader,
                daemon=True,
                name="whisper-hkd-stderr",
            ).start()

        # Основной поток: читает DOWN/UP/PONG
        self._reader_t = threading.Thread(
            target=self._stdout_reader,
            daemon=True,
            name="whisper-hkd-stdout",
        )
        self._reader_t.start()

        _mac_log(
            "info",
            "hotkey_daemon_started pid=%s binary=%s hotkey=%s",
            self._proc.pid,
            binary,
            self._hotkey_spec,
        )
        return True

    def _stderr_reader(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if line:
                    _mac_log("debug", "hkd_stderr: %s", line)
        except Exception:
            pass

    def _stdout_reader(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                if self._stop.is_set():
                    break
                token = line.strip()
                if token == "DOWN":
                    try:
                        self._on_down()
                    except Exception:
                        _MAC_LOGGER.exception("hotkey_daemon_on_down")
                elif token == "UP":
                    try:
                        self._on_up()
                    except Exception:
                        _MAC_LOGGER.exception("hotkey_daemon_on_up")
                # PONG — просто игнорируем (подтверждение heartbeat)
        except Exception as exc:
            if not self._stop.is_set():
                _mac_log("warning", "hotkey_daemon_stdout_reader_error %s", exc)
        finally:
            if not self._stop.is_set():
                _mac_log("error", "hotkey_daemon_process_died rc=%s", proc.returncode)

    # ── Heartbeat ─────────────────────────────────────────────────────────────
    def ping(self) -> bool:
        """Возвращает True если процесс ещё жив."""
        if not self.is_running():
            return False
        try:
            proc = self._proc
            if proc and proc.stdin:
                proc.stdin.write("PING\n")
                proc.stdin.flush()
        except Exception:
            return False
        return True

    # ── Состояние ─────────────────────────────────────────────────────────────
    def is_running(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def pid(self) -> "int | None":
        return self._proc.pid if self._proc else None

    def path(self) -> "Path | None":
        return self._binary

    # ── Остановка ─────────────────────────────────────────────────────────────
    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.write("STOP\n")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._reader_t:
            self._reader_t.join(timeout=3.0)


def _hotkey_spec_for_daemon(spec: "HotkeySpec") -> str:
    """Конвертирует HotkeySpec в строку для whisper_hotkey_daemon (ctrl+alt+shift)."""
    _mod_map = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "cmd": "cmd"}
    parts: list[str] = []
    for t in spec.tokens:
        if t.startswith("m:"):
            name = t[2:]
            if name in _mod_map:
                parts.append(_mod_map[name])
    # Стабильный порядок: ctrl alt shift cmd
    order = ["ctrl", "alt", "shift", "cmd"]
    parts.sort(key=lambda x: order.index(x) if x in order else 99)
    return "+".join(parts) if parts else "ctrl+alt+shift"


class WhisperClientMac:
    def __init__(
        self,
        server_url: str,
        language: str | None = None,
        spoken_punctuation: bool = True,
        hotkey: HotkeySpec | None = None,
        *,
        speaker_verify: bool = False,
        speaker_threshold: float | None = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.language = language
        self.spoken_punctuation = spoken_punctuation
        self.hotkey = hotkey or HotkeySpec.default_mac_with_portal()
        self._hotkey_label = describe_hotkey(self.hotkey)
        self.sample_rate = 16000
        self.channels = 1
        self._lock = threading.Lock()
        self._recording = False
        self._stop_record = threading.Event()
        # Состояние глобального hotkey (pynput иногда теряет key_up — без сброса ⌃⌥ «залипает» в памяти)
        self._hk_lock = threading.Lock()
        self._hk_pressed: set[str] = set()
        self._hk_combo_active = False
        self._hk_suppress = False
        self._record_thread: threading.Thread | None = None
        self._audio_chunks: list[bytes] = []
        self._busy = False
        self._kbd = KeyboardController()
        # Перезапуск глобального Listener после распознавания (macOS часто убивает tap после Cmd+V / synthetic keys)
        self._listener_ref: keyboard.Listener | None = None
        self._listener_ref_lock = threading.Lock()
        self._listener_thread: threading.Thread | None = None
        self._listener_start_lock = threading.Lock()
        # Просыпаемся из wait → stop() → новый tap (надёжнее одного join() на вечность).
        self._listener_cycle_restart = threading.Event()
        self._last_hotkey_event_monotonic = 0.0
        self._run_stop = False
        self._work_lock = threading.Lock()
        # PID процесса с полем ввода (frontmost при старте записи) — перед Cmd+V возвращаем фокус туда.
        self._paste_target_unix_id: int | None = None
        self._speaker_verify = speaker_verify
        self._speaker_threshold = speaker_threshold
        # run() выставляет: строка меню = main thread + NSRunLoop → безопасен performSelectorOnMainThread для kbd.
        self._menu_bar_mode = False
        self._listener_aux_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._main_thread_job_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        # Нативный CGEventTap-демон (заменяет pynput Listener на macOS 15+)
        self._hotkey_daemon: _HotkeyDaemon | None = None
        self._using_daemon = False
        self._pref_health_timeout: float | None = None
        self._pref_transcribe_timeout: float | None = None
        self._pref_transcribe_connect_timeout: float | None = None
        self._pref_speaker_threshold: float | None = None
        self._reload_mac_prefs_from_disk()

    def _reload_mac_prefs_from_disk(self) -> None:
        p = load_mac_client_prefs()
        self._pref_health_timeout = p.get("health_timeout")
        self._pref_transcribe_timeout = p.get("transcribe_timeout")
        self._pref_transcribe_connect_timeout = p.get("transcribe_connect_timeout")
        self._pref_speaker_threshold = p.get("speaker_threshold")

    def _merge_save_mac_prefs(self, **kwargs: float | None) -> None:
        merge_mac_client_prefs(dict(kwargs))
        self._reload_mac_prefs_from_disk()
        _mac_log("info", "mac_client_prefs_saved %s", load_mac_client_prefs())

    def _effective_health_timeout_sec(self) -> float:
        if self._pref_health_timeout is not None:
            return max(5.0, min(120.0, float(self._pref_health_timeout)))
        try:
            _hc_to = float((os.environ.get("WHISPER_MAC_HEALTH_TIMEOUT") or "30").strip() or "30")
        except ValueError:
            _hc_to = 30.0
        return max(5.0, min(120.0, _hc_to))

    def _effective_transcribe_timeouts(self) -> tuple[float, float]:
        if self._pref_transcribe_timeout is not None:
            _tx_read = max(60.0, min(3600.0, float(self._pref_transcribe_timeout)))
        else:
            try:
                _tx_read = float(
                    (os.environ.get("WHISPER_MAC_TRANSCRIBE_TIMEOUT") or "900").strip() or "900"
                )
            except ValueError:
                _tx_read = 900.0
            _tx_read = max(60.0, min(3600.0, _tx_read))
        if self._pref_transcribe_connect_timeout is not None:
            _tx_conn = max(10.0, min(300.0, float(self._pref_transcribe_connect_timeout)))
        else:
            try:
                _tx_conn = float(
                    (os.environ.get("WHISPER_MAC_TRANSCRIBE_CONNECT_TIMEOUT") or "60").strip()
                    or "60"
                )
            except ValueError:
                _tx_conn = 60.0
            _tx_conn = max(10.0, min(300.0, _tx_conn))
        return _tx_conn, _tx_read

    def _effective_speaker_threshold_override(self) -> float | None:
        if self._pref_speaker_threshold is not None:
            return float(self._pref_speaker_threshold)
        return self._speaker_threshold

    def request_shutdown(self) -> None:
        """Остановка клиента (меню «Выход», SIGINT)."""
        self._run_stop = True
        self._listener_cycle_restart.set()
        self._kick_listener_restart(force=True)
        d = self._hotkey_daemon
        if d:
            try:
                d.stop()
            except Exception:
                pass

    def _drain_main_thread_jobs(self) -> None:
        """Очередь задач для Python main (headless; запасной путь если thunk недоступен)."""
        while True:
            try:
                job = self._main_thread_job_queue.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception:
                _MAC_LOGGER.exception("main_thread_job_queue")

    def _invoke_recording_on_main_thread(self, fn: Callable[[], None]) -> None:
        """Старт/стоп записи с потока хоткея: на main — стабильнее CoreAudio (sounddevice)."""
        if sys.platform != "darwin":
            fn()
            return
        try:
            from Foundation import NSThread  # type: ignore[import-untyped]

            if NSThread.isMainThread():
                fn()
                return
        except Exception:
            pass
        if threading.current_thread() is threading.main_thread():
            fn()
            return

        if self._menu_bar_mode and _WhisperMainJobThunk is not None:
            try:
                thunk = _WhisperMainJobThunk.alloc().init()
                thunk.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "apply:", {"fn": fn}, False
                )
                return
            except Exception:
                _MAC_LOGGER.exception("invoke_recording_on_main_thunk_failed")

        self._main_thread_job_queue.put(fn)

    # ── Нативный CGEventTap daemon (macOS 15+, без TSM-крашей) ────────────────

    def _try_start_hotkey_daemon(self) -> bool:
        """
        Пробует запустить нативный CGEventTap (без pynput Listener).
        Порядок: 1) _InProcessCGEventTap (Quartz в Python-процессе) → нет проблем с правами .app
                 2) _HotkeyDaemon (внешний C-бинарь) → fallback для Terminal/dev-режима
        Возвращает True при успехе; иначе нужен pynput fallback.
        """
        if sys.platform != "darwin":
            return False

        # ── Вариант 1: CGEventTap прямо в Python-процессе (рекомендуется) ──────
        target, reject = _InProcessCGEventTap.flags_for_spec(self.hotkey)
        tap = _InProcessCGEventTap(
            on_down=lambda: self._invoke_recording_on_main_thread(self._start_recording),
            on_up=lambda: self._invoke_recording_on_main_thread(self._stop_recording_and_process),
            target_flags=target,
            reject_flags=reject,
        )
        if tap.start():
            self._hotkey_daemon = tap
            _mac_log("info", "hotkey=in_process_cgeventtap pynput_listener=DISABLED")
            return True

        # ── Вариант 2: внешний C-бинарь whisper_hotkey_daemon ─────────────────
        _mac_log("debug", "in_process_tap_failed trying external daemon")
        spec = _hotkey_spec_for_daemon(self.hotkey)
        daemon = _HotkeyDaemon(
            on_down=lambda: self._invoke_recording_on_main_thread(self._start_recording),
            on_up=lambda: self._invoke_recording_on_main_thread(self._stop_recording_and_process),
            hotkey_spec=spec,
        )
        if daemon.start():
            self._hotkey_daemon = daemon
            _mac_log(
                "info",
                "hotkey=external_daemon pid=%s binary=%s pynput_listener=DISABLED",
                daemon.pid(),
                daemon.path(),
            )
            return True

        return False

    def _ensure_daemon_running(self) -> None:
        """Watchdog: перезапускает tap если упал; fallback на pynput."""
        if self._run_stop:
            return
        d = self._hotkey_daemon
        if d and d.is_running():
            return
        _mac_log("warning", "hotkey_tap_dead restarting")
        ok = self._try_start_hotkey_daemon()
        if ok:
            try:
                mac_banner_notification("Whisper", "Перехват клавиш перезапущен.")
            except Exception:
                pass
        else:
            _mac_log("error", "hotkey_tap_restart_failed falling_back_to_pynput")
            self._using_daemon = False
            self._ensure_listener_thread()
            try:
                mac_banner_notification(
                    "Whisper",
                    "Нативный перехватчик недоступен — переключено на pynput.",
                )
            except Exception:
                pass

    def _ensure_listener_thread(self) -> None:
        """Поток pynput не должен «тихо умереть» и гасить весь клиент — поднимаем снова."""
        with self._listener_start_lock:
            if self._run_stop:
                return
            t = self._listener_thread
            if t is not None and t.is_alive():
                return
            had_dead = t is not None
            if had_dead:
                _mac_log(
                    "warning",
                    "listener_thread_restarting (previous thread dead; hotkeys were inactive)",
                )
                try:
                    mac_banner_notification(
                        "Whisper",
                        "Перехват клавиш перезапущен — снова можно диктовать.",
                    )
                except Exception:
                    pass
            self._listener_thread = threading.Thread(
                target=self._listener_loop,
                name="whisper-pynput-listener",
                daemon=False,
            )
            self._listener_thread.start()

    def _maybe_recover_stale_listener(self) -> None:
        """
        Поток whisper-pynput-listener жив, но экземпляр pynput.Listener внутри уже мёртв —
        иначе можно годами «молчать» без событий. Отличие от idle-recycle: реагируем только
        на is_alive()==False, а не по таймеру.
        """
        if self._run_stop:
            return
        with self._lock:
            if self._recording or self._busy:
                return
        with self._listener_ref_lock:
            lr = self._listener_ref
        if lr is None:
            return
        try:
            ok = lr.is_alive()
        except Exception:
            return
        if ok:
            return
        _mac_log("warning", "pynput_listener_instance_dead recovering_tap")
        self._kick_listener_restart(force=False)

    def _reset_hotkey_tracker(self) -> None:
        """Сброс модели «какие клавиши зажаты» — после вставки и после цикла распознавания."""
        with self._hk_lock:
            self._hk_suppress = False
            self._hk_pressed.clear()
            self._hk_combo_active = False

    def _reset_native_hotkey_tap_state(self) -> None:
        """In-process CGEventTap: иначе _pressed залипает True после одной сессии — второй хоткей молчит."""
        d = self._hotkey_daemon
        if d is None:
            return
        try:
            d.force_release_pressed()
        except Exception:
            _MAC_LOGGER.debug("reset_native_hotkey_tap_state", exc_info=True)

    def _kick_listener_restart(self, *, force: bool = False) -> None:
        """Останавливает текущий Listener; поток _listener_loop поднимет новый tap."""
        if not force and self._run_stop:
            return
        self._listener_cycle_restart.set()
        with self._listener_ref_lock:
            lr = self._listener_ref
        if lr is not None:
            try:
                lr.stop()
            except Exception:
                pass

    def _schedule_listener_kick(self, delay: float = 0.28) -> None:
        """Отложенный restart tap: сразу после Cmd+V из потока work иногда ловится дедлок/залипание CGEventTap."""

        def _run() -> None:
            time.sleep(delay)
            try:
                self._kick_listener_restart()
                _mac_log("debug", "listener_kick_after_delay delay=%.2fs", delay)
            except Exception:
                _MAC_LOGGER.exception("listener_kick_scheduled_failed")

        threading.Thread(target=_run, name="whisper-listener-kick", daemon=True).start()

    def _on_press_hotkey(self, key) -> None:
        self._last_hotkey_event_monotonic = time.monotonic()
        target = self.hotkey.tokens
        try:
            t = key_event_token(key)
            should_start = False
            with self._hk_lock:
                if self._hk_suppress:
                    return
                if t:
                    self._hk_pressed.add(t)
                if frozenset(self._hk_pressed) == target and not self._hk_combo_active:
                    self._hk_combo_active = True
                    should_start = True
            if should_start:
                self._invoke_recording_on_main_thread(self._start_recording)
        except Exception:
            _MAC_LOGGER.exception("on_press_hotkey")

    def _on_release_hotkey(self, key) -> None:
        self._last_hotkey_event_monotonic = time.monotonic()
        target = self.hotkey.tokens
        try:
            t = key_event_token(key)
            should_stop = False
            with self._hk_lock:
                if self._hk_suppress:
                    return
                if t:
                    self._hk_pressed.discard(t)
                if frozenset(self._hk_pressed) != target:
                    if self._hk_combo_active:
                        self._hk_combo_active = False
                        should_stop = True
            if should_stop:
                self._invoke_recording_on_main_thread(self._stop_recording_and_process)
        except Exception:
            _MAC_LOGGER.exception("on_release_hotkey")

    def _listener_loop(self) -> None:
        """Отдельный поток: бесконечно поднимает pynput Listener; kick / сбой — новый tap."""
        err_backoff = 0.25
        while not self._run_stop:
            try:
                with keyboard.Listener(
                    on_press=self._on_press_hotkey,
                    on_release=self._on_release_hotkey,
                    suppress=False,
                ) as listener:
                    with self._listener_ref_lock:
                        self._listener_ref = listener
                    self._listener_cycle_restart.clear()
                    _mac_log("info", "pynput_listener_active hotkey=%s", self._hotkey_label)
                    try:
                        while not self._run_stop:
                            self._drain_listener_aux_queue()
                            # Было 1 с — для очереди сброса модификаторов нужно чаще (см. WHISPER_MAC_LISTENER_POLL_SEC).
                            try:
                                _poll = float(
                                    (os.environ.get("WHISPER_MAC_LISTENER_POLL_SEC") or "0.25").strip() or "0.25"
                                )
                            except ValueError:
                                _poll = 0.25
                            _poll = max(0.05, min(2.0, _poll))
                            if self._listener_cycle_restart.wait(timeout=_poll):
                                self._listener_cycle_restart.clear()
                                try:
                                    listener.stop()
                                except Exception:
                                    pass
                                break
                            if not listener.is_alive():
                                break
                    finally:
                        with self._listener_ref_lock:
                            if self._listener_ref is listener:
                                self._listener_ref = None
                        try:
                            listener.join(timeout=4.0)
                        except Exception:
                            pass
            except Exception:
                _MAC_LOGGER.exception("pynput Listener crashed; will retry")
                _mac_log(
                    "warning",
                    "hotkey_listener_restart_after_error backoff=%.2fs",
                    err_backoff,
                )
                time.sleep(err_backoff)
                err_backoff = min(err_backoff * 1.6, 4.0)
                continue
            err_backoff = 0.25
            if self._run_stop:
                break
            _mac_log("debug", "listener_cycle_ended (kick or macOS); restart after pause")
            time.sleep(0.22)

    def _release_sticky_modifiers(self) -> None:
        """Сбрасываем модификаторы после горячих клавиш — иначе они «дотягиваются» до синтетической вставки."""
        for k in (
            Key.cmd,
            Key.cmd_l,
            Key.cmd_r,
            Key.alt,
            Key.alt_l,
            Key.alt_r,
            Key.shift,
            Key.shift_l,
            Key.shift_r,
            Key.ctrl,
            Key.ctrl_l,
            Key.ctrl_r,
        ):
            try:
                self._kbd.release(k)
            except Exception:
                pass

    def _drain_listener_aux_queue(self) -> None:
        """Команды с других потоков (сброс модификаторов), выполняются только здесь — в потоке pynput Listener."""
        while True:
            try:
                fn = self._listener_aux_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                _MAC_LOGGER.exception("listener_aux_queue")

    def _release_sticky_modifiers_via_listener_thread(self) -> None:
        """Headless / без PyObjC: тот же поток, что держит CGEventTap — не main, но не whisper-transcribe."""
        if threading.current_thread() is self._listener_thread:
            self._release_sticky_modifiers()
            return
        lt = self._listener_thread
        if lt is None or not lt.is_alive():
            _MAC_LOGGER.warning("release_mods_no_listener_thread_using_direct")
            self._release_sticky_modifiers()
            return
        done = threading.Event()
        err: list[BaseException | None] = [None]

        def _work() -> None:
            try:
                self._release_sticky_modifiers()
            except BaseException as e:
                err[0] = e
            finally:
                done.set()

        self._listener_aux_queue.put(_work)
        if not done.wait(timeout=5.0):
            _MAC_LOGGER.error("release_mods_listener_queue_timeout")
            return
        if err[0] is not None:
            raise err[0]

    def _release_sticky_modifiers_safe(self) -> None:
        """
        Не вызывать pynput KeyboardController из whisper-transcribe: на macOS 15+ ловится SIGTRAP
        (TSMGetInputSourceProperty / dispatch_assert_queue_fail).
        """
        if threading.current_thread() is self._listener_thread:
            self._release_sticky_modifiers()
            return
        if self._menu_bar_mode and _WhisperMainReleaseThunk is not None:
            try:
                from Foundation import NSThread  # type: ignore[import-untyped]

                if NSThread.isMainThread():
                    self._release_sticky_modifiers()
                    return
                err: list[BaseException | None] = [None]
                thunk = _WhisperMainReleaseThunk.alloc().init()
                ctx = {"client": self, "err": err}
                thunk.performSelectorOnMainThread_withObject_waitUntilDone_("apply:", ctx, True)
                if err[0] is not None:
                    raise err[0]
                return
            except Exception:
                _MAC_LOGGER.exception("release_mods_main_dispatch_failed_fallback_listener")
        self._release_sticky_modifiers_via_listener_thread()

    def _copy_to_clipboard_mac(self, text: str) -> None:
        """Нативный pbcopy — надёжнее по таймингу, чем pyperclip сразу перед Cmd+V."""
        subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
            timeout=5.0,
        )

    def _clipboard_preview(self, max_len: int = 120) -> str:
        try:
            r = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if r.returncode != 0:
                return ""
            s = (r.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
            if len(s) > max_len:
                return s[:max_len] + "…"
            return s
        except Exception:
            return ""

    def _clipboard_matches_expected(self, expected: str) -> bool:
        try:
            r = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if r.returncode != 0:
                return False
            got = (r.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
            exp = expected.replace("\r\n", "\n").replace("\r", "\n")
            return got == exp
        except Exception:
            return False

    def _snapshot_frontmost_unix_pid(self) -> int | None:
        """Кто был активным при зажатии хоткея — туда же шлём Cmd+V после распознавания."""
        try:
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to return unix id of first process whose frontmost is true',
                ],
                capture_output=True,
                text=True,
                timeout=_mac_osascript_timeout_sec(fallback=10.0),
            )
            if r.returncode != 0:
                _mac_log(
                    "warning",
                    "snapshot_frontmost_failed code=%s err=%s",
                    r.returncode,
                    (r.stderr or "").strip(),
                )
                return None
            pid = int((r.stdout or "").strip())
        except (ValueError, subprocess.TimeoutExpired, OSError) as e:
            _mac_log("warning", "snapshot_frontmost_parse_error %s", e)
            return None
        mine = os.getpid()
        if pid == mine:
            _mac_log(
                "warning",
                "frontmost_pid=%s совпадает с клиентом — кликни в поле ввода и повтори (иначе Cmd+V уйдёт не туда)",
                pid,
            )
            return None
        _mac_log("info", "paste_target_captured unix_pid=%s", pid)
        return pid

    def _activate_process_by_unix_id(self, uid: int) -> bool:
        if uid <= 0 or uid == os.getpid():
            return False
        try:
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'tell application "System Events" to set frontmost of first process whose unix id is {uid} to true',
                ],
                capture_output=True,
                text=True,
                timeout=_mac_osascript_timeout_sec(fallback=15.0),
            )
            if r.returncode != 0:
                _mac_log(
                    "warning",
                    "activate_pid=%s failed code=%s err=%s",
                    uid,
                    r.returncode,
                    (r.stderr or "").strip(),
                )
                return False
            time.sleep(0.35)
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            _mac_log("warning", "activate_pid=%s exception=%s", uid, e)
            return False

    def _mac_env_truthy(self, name: str) -> bool:
        return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")

    def _osascript_run(self, script: str, *, timeout: float | None = None) -> tuple[int, str]:
        to = timeout if timeout is not None else _mac_osascript_timeout_sec(fallback=18.0)
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=to,
            )
            err = ((r.stderr or r.stdout or "") or "").strip()
            return r.returncode, err
        except subprocess.TimeoutExpired:
            return -1, "timeout"
        except OSError as e:
            return -1, str(e)

    def _paste_via_quartz_cmd_v(self) -> bool:
        """Cmd+V через CGEventPost — можно из потока transcribe (не трогает TSM/pynput)."""
        if sys.platform != "darwin":
            return False
        try:
            from Quartz import (  # type: ignore[import-untyped]
                CGEventCreateKeyboardEvent,
                CGEventPost,
                CGEventSetFlags,
                kCGAnnotatedSessionEventTap,
                kCGEventFlagMaskCommand,
                kCGHIDEventTap,
                kCGSessionEventTap,
            )
        except ImportError:
            _mac_log("debug", "paste_quartz_skip no Quartz / pyobjc-framework-Quartz")
            return False
        taps = (
            kCGAnnotatedSessionEventTap,
            kCGSessionEventTap,
            kCGHIDEventTap,
        )
        key = 9  # физическая V, не зависит от раскладки
        for tap in taps:
            try:
                for down in (True, False):
                    ev = CGEventCreateKeyboardEvent(None, key, down)
                    if ev is None:
                        raise RuntimeError("CGEventCreateKeyboardEvent returned None")
                    CGEventSetFlags(ev, kCGEventFlagMaskCommand)
                    CGEventPost(tap, ev)
                time.sleep(0.06)
                _mac_log("info", "paste_quartz_sent tap=%r key=%s", tap, key)
                return True
            except Exception:
                _MAC_LOGGER.debug("paste_quartz_tap_fail", exc_info=True)
                continue
        return False

    def _paste_via_system_events(self, target_unix_pid: int | None = None) -> bool:
        """Цепочка Cmd+V: опционально сначала Quartz, иначе osascript (несколько вариантов), в конце снова Quartz."""
        if self._mac_env_truthy("WHISPER_MAC_PASTE_QUARTZ_FIRST"):
            if self._paste_via_quartz_cmd_v():
                return True

        timeout = _mac_osascript_timeout_sec(fallback=18.0)
        pid = target_unix_pid
        if pid is not None and (pid <= 0 or pid == os.getpid()):
            pid = None

        scripts: list[tuple[str, str]] = []
        if pid is not None:
            p = int(pid)
            scripts.append(
                (
                    "pid_keycode",
                    (
                        'tell application "System Events"\n'
                        f"    tell (first process whose unix id is {p})\n"
                        "        set frontmost to true\n"
                        "        delay 0.22\n"
                        "        key code 9 using command down\n"
                        "    end tell\n"
                        "end tell"
                    ),
                )
            )
            scripts.append(
                (
                    "pid_keystroke",
                    (
                        'tell application "System Events"\n'
                        f"    tell (first process whose unix id is {p})\n"
                        "        set frontmost to true\n"
                        "        delay 0.22\n"
                        '        keystroke "v" using command down\n'
                        "    end tell\n"
                        "end tell"
                    ),
                )
            )
        scripts.extend(
            [
                ("global_keycode", 'tell application "System Events" to key code 9 using command down'),
                (
                    "global_keystroke",
                    'tell application "System Events" to keystroke "v" using command down',
                ),
            ]
        )

        for attempt in range(1, 4):
            time.sleep(0.14 if attempt == 1 else 0.22)
            for method, sc in scripts:
                code, err = self._osascript_run(sc, timeout=timeout)
                if code == 0:
                    _mac_log("info", "paste_cmd_v_ok method=%s attempt=%s", method, attempt)
                    return True
                _mac_log(
                    "warning",
                    "paste_cmd_v_fail method=%s attempt=%s code=%s err=%s",
                    method,
                    attempt,
                    code,
                    err[:280] if err else "",
                )
            if attempt < 3:
                time.sleep(0.4)

        if not self._mac_env_truthy("WHISPER_MAC_PASTE_QUARTZ_FIRST") and self._paste_via_quartz_cmd_v():
            _mac_log("info", "paste_cmd_v_ok method=quartz_after_osascript")
            return True
        return False

    def _record_worker(self, max_duration: float = 120.0) -> None:
        chunks = []
        max_chunks = int(self.sample_rate / 1024 * max_duration) + 1
        n = 0
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=np.float32,
                blocksize=1024,
            ) as stream:
                while not self._stop_record.is_set() and n < max_chunks:
                    data, overflowed = stream.read(1024)
                    if overflowed:
                        print("[Client] Переполнение буфера!", flush=True)
                    chunks.append(data.tobytes())
                    n += 1
            with self._lock:
                self._audio_chunks = chunks
        except Exception as e:
            print(f"[Client] Ошибка записи: {e}", file=sys.stderr, flush=True)
            _mac_log("error", "record_worker_error %s", e)

    def _start_recording(self) -> None:
        with self._lock:
            # Если уже идёт запись - не начинаем новую
            if self._recording:
                return
            # Если обработка идёт - всё равно разрешаем новую запись (как на Windows)
            # Старая обработка продолжит в фоне, но результат может быть проигнорирован
            self._recording = True
        self._stop_record.clear()
        self._audio_chunks.clear()
        self._paste_target_unix_id = None
        # Кто frontmost — до потока записи и микрофона (иначе снимок часто ловит не то окно).
        self._paste_target_unix_id = self._snapshot_frontmost_unix_pid()

        # Микрофон сразу — до любых afplay/osascript (иначе съедается первое слово).
        self._record_thread = threading.Thread(
            target=self._record_worker,
            name="whisper-record",
            daemon=True,
        )
        self._record_thread.start()
        _mac_log("info", "recording_started hotkey=%s", self._hotkey_label)

        def _beep_async() -> None:
            try:
                subprocess.Popen(
                    ["afplay", "-v", "0.2", "/System/Library/Sounds/Pop.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                try:
                    print("\a", end="", flush=True)
                except Exception:
                    pass

        threading.Thread(target=_beep_async, name="whisper-beep", daemon=True).start()
        print(f"[Запись] Зажато {self._hotkey_label} — говори…", flush=True)

    def _stop_recording_and_process(self) -> None:
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            self._busy = True
        self._stop_record.set()
        if self._record_thread is not None:
            self._record_thread.join(timeout=5.0)
            self._record_thread = None
        chunks = self._audio_chunks[:]
        self._audio_chunks.clear()

        if not chunks:
            print("[Client] Нет аудио.", flush=True)
            mac_banner_notification("Whisper", "Нет аудио — проверь микрофон и доступ.")
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        # Объединяем аудио
        audio_data = np.frombuffer(b"".join(chunks), dtype=np.float32)
        min_samples = int(0.25 * self.sample_rate)
        if audio_data.size < min_samples:
            print("[Client] Запись слишком короткая.", flush=True)
            mac_banner_notification("Whisper", "Запись слишком короткая — держи хоткей дольше.")
            self._reset_hotkey_tracker()
            with self._lock:
                self._busy = False
            return

        # Снимок до фонового потока — пока не началась следующая запись, PID цели стабилен для этой сессии.
        paste_target_pid = self._paste_target_unix_id

        def work() -> None:
            # Один поток обработки за раз — иначе два kick подряд убивают свежий Listener.
            with self._work_lock:
                with self._lock:
                    self._busy = True
                try:
                    _work_body(paste_target_pid)
                finally:
                    self._reset_hotkey_tracker()
                    self._reset_native_hotkey_tap_state()
                    with self._lock:
                        self._busy = False
                    # По умолчанию не кикаем pynput после каждой вставки — часто «убивает» хоткей после одной записи.
                    _kick = (os.environ.get("WHISPER_MAC_POST_TRANSCRIBE_LISTENER_KICK") or "").strip().lower()
                    if not self._using_daemon and _kick in ("1", "true", "yes", "on"):
                        self._schedule_listener_kick()

        def _work_body(paste_pid: int | None) -> None:
            try:
                # Сохраняем во временный WAV
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                    sf.write(tmp_path, audio_data, self.sample_rate)

                try:
                    if self._speaker_verify:
                        try:
                            from speaker_verify import (
                                SpeakerRejected,
                                SpeakerVerifyUnavailable,
                                load_reference,
                                verify_wav_file_or_raise,
                            )
                        except ImportError:
                            _mac_log("warning", "speaker_verify_no_module install requirements-speaker.txt")
                        else:
                            ref = load_reference()
                            if ref is None:
                                _mac_log(
                                    "warning",
                                    "speaker_verify_enabled_but_no_enrollment use --enroll-speaker",
                                )
                            else:
                                try:
                                    verify_wav_file_or_raise(
                                        tmp_path,
                                        thr_override=self._effective_speaker_threshold_override(),
                                    )
                                except SpeakerRejected as e:
                                    print(f"[Client] {e}", flush=True)
                                    _mac_log("info", "speaker_rejected %s", e)
                                    mac_banner_notification("Whisper", str(e)[:220])
                                    return
                                except SpeakerVerifyUnavailable as e:
                                    _mac_log(
                                        "warning",
                                        "speaker_verify_skipped %s — отправка на сервер без проверки голоса",
                                        e,
                                    )

                    # Проверяем доступность сервера перед отправкой (меню / ~/.whisper/mac_client_prefs.json / env).
                    try:
                        _hc_to = self._effective_health_timeout_sec()
                        health_check = requests.get(f"{self.server_url}/", timeout=_hc_to)
                        if health_check.status_code != 200:
                            print(f"[Client] Сервер недоступен (код {health_check.status_code})", flush=True)
                            _mac_log(
                                "error",
                                "health_check status=%s url=%s",
                                health_check.status_code,
                                self.server_url,
                            )
                            raise ConnectionError("Сервер недоступен")
                    except requests.exceptions.RequestException as e:
                        print(f"[Client] Не удаётся подключиться к серверу: {e}", flush=True)
                        print(f"[Client] Проверь, что сервер запущен на {self.server_url}", flush=True)
                        _mac_log("error", "health_check_request_error %s url=%s", e, self.server_url)
                        raise

                    # Отправляем на сервер с повторными попытками
                    print("[Client] Отправка на сервер…", flush=True)
                    _mac_notify_progress("Отправка на сервер, жди ответ…")
                    _mac_log("info", "transcribe_upload_start url=%s paste_target_pid=%s", self.server_url, paste_pid)
                    max_retries = 3
                    response = None
                    _tx_conn, _tx_read = self._effective_transcribe_timeouts()
                    _post_timeout: float | tuple[float, float] = (_tx_conn, _tx_read)

                    for attempt in range(max_retries):
                        try:
                            with open(tmp_path, "rb") as f:
                                files = {"audio": ("audio.wav", f, "audio/wav")}
                                params = {}
                                if self.language:
                                    params["language"] = self.language
                                params["spoken_punctuation"] = str(self.spoken_punctuation).lower()

                                response = requests.post(
                                    f"{self.server_url}/transcribe",
                                    files=files,
                                    params=params,
                                    headers={"X-Whisper-Client": "mac"},
                                    timeout=_post_timeout,
                                )
                                if response.status_code >= 400:
                                    detail = _fastapi_error_detail(response)
                                    _mac_log(
                                        "error",
                                        "transcribe_http status=%s detail=%r",
                                        response.status_code,
                                        detail,
                                    )
                                    if response.status_code == 403:
                                        mac_banner_notification("Whisper — отклонено", detail[:220])
                                    else:
                                        mac_banner_notification(
                                            "Whisper — ошибка сервера",
                                            f"{response.status_code}: {detail}"[:220],
                                        )
                                    return
                                break  # успешно, выходим из цикла
                        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                            if attempt < max_retries - 1:
                                wait_time = (attempt + 1) * 2
                                print(
                                    f"[Client] Ошибка соединения (попытка {attempt + 1}/{max_retries}), повтор через {wait_time} сек…",
                                    flush=True,
                                )
                                time.sleep(wait_time)
                            else:
                                print(f"[Client] Не удалось подключиться после {max_retries} попыток", flush=True)
                                raise

                    if response is None:
                        raise ConnectionError("Не удалось получить ответ от сервера")

                    try:
                        result = response.json()
                    except ValueError:
                        body = (response.text or "")[:400]
                        _mac_log("error", "transcribe_bad_json status=%s body_prefix=%r", response.status_code, body)
                        print("[Client] Ответ сервера не JSON — см. ~/Library/Logs/WhisperMacClient.log", flush=True)
                        mac_banner_notification("Whisper — ошибка", "Некорректный ответ сервера (не JSON).")
                        raise
                    text = result.get("text", "").strip()
                    _mac_log(
                        "info",
                        "transcribe_ok chars=%d preview=%r language=%r",
                        len(text),
                        text[:160],
                        result.get("language"),
                    )
                    if os.environ.get("WHISPER_MAC_DEBUG"):
                        _mac_log("debug", "transcribe_full_text=%r", text)

                    if text:
                        # Не даём synthetic release от Controller/osascript попасть в pressed — иначе hotkey ломается.
                        paste_ok = False
                        with self._hk_lock:
                            self._hk_suppress = True
                        try:
                            # В режиме daemon ключи уже физически отпущены до UP → synthetic release не нужен
                            # (и может вызвать ложный DOWN у daemon через CGEventPost).
                            if not self._using_daemon:
                                self._release_sticky_modifiers_safe()
                            time.sleep(0.15)
                            if paste_pid is not None:
                                activated = self._activate_process_by_unix_id(paste_pid)
                                _mac_log(
                                    "info",
                                    "restore_focus pid=%s ok=%s",
                                    paste_pid,
                                    activated,
                                )
                            else:
                                _mac_log(
                                    "warning",
                                    "paste_target_pid_unknown — Cmd+V уйдёт в текущее frontmost-окно "
                                    "(кликни в поле ввода до хоткея; если Terminal/Python был активен — снимок PID отброшен)",
                                )
                            time.sleep(0.08)
                            self._copy_to_clipboard_mac(text)
                            time.sleep(0.06)
                            if self._clipboard_matches_expected(text):
                                _mac_log("info", "clipboard_ok after pbcopy (%d chars)", len(text))
                            else:
                                _mac_log(
                                    "warning",
                                    "clipboard_mismatch after pbcopy expected_prefix=%r got_preview=%r",
                                    text[:80],
                                    self._clipboard_preview(100),
                                )
                            time.sleep(0.12)
                            ok = self._paste_via_system_events(paste_pid)
                            paste_ok = bool(ok)
                            if ok:
                                print(f"[Client] Текст вставлен: {text[:60]}…", flush=True)
                                _mac_log("info", "paste_cmd_v_ok")
                            else:
                                pyperclip.copy(text)
                                print(
                                    f"[Client] Системная вставка не сработала (osascript). Текст в буфере: {text[:60]}…",
                                    flush=True,
                                )
                                print("[Client] Нажми Cmd+V в нужном поле.", flush=True)
                                _mac_log("warning", "paste_cmd_v_failed text_left_in_clipboard=yes")
                        except Exception as e:
                            try:
                                pyperclip.copy(text)
                            except Exception:
                                pass
                            print(f"[Client] Вставка не удалась ({e}), текст в буфере: {text[:60]}…", flush=True)
                            print("[Client] Нажми Cmd+V для вставки.", flush=True)
                            _MAC_LOGGER.error("paste_pipeline_error", exc_info=True)
                        finally:
                            self._reset_hotkey_tracker()
                            self._reset_native_hotkey_tap_state()
                        if os.environ.get("WHISPER_MAC_NOTIFY_SUCCESS", "1") != "0":
                            prev = text[:130] + ("…" if len(text) > 130 else "")
                            if paste_ok:
                                mac_banner_notification("Whisper — готово", prev)
                            else:
                                mac_banner_notification("Whisper — текст в буфере", prev + " — нажми Cmd+V.")
                    else:
                        print("[Client] Текст не распознан.", flush=True)
                        _mac_log("info", "transcribe_empty_text keys=%s", list(result.keys()))
                        mac_banner_notification(
                            "Whisper",
                            "Текст не распознан — говори громче или подольше.",
                        )
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            except requests.exceptions.ConnectionError as e:
                print(f"[Client] Ошибка соединения с сервером: {e}", file=sys.stderr, flush=True)
                print(f"[Client] Убедись, что сервер запущен на {self.server_url}", file=sys.stderr, flush=True)
                print(f"[Client] Проверь Tailscale соединение и брандмауэр Windows", file=sys.stderr, flush=True)
                mac_banner_notification("Whisper — нет связи", f"Сервер недоступен: {self.server_url}")
            except requests.exceptions.Timeout as e:
                print(f"[Client] Таймаут HTTP: {e}", file=sys.stderr, flush=True)
                print(
                    "[Client] Увеличь ожидание: WHISPER_MAC_HEALTH_TIMEOUT, "
                    "WHISPER_MAC_TRANSCRIBE_CONNECT_TIMEOUT, WHISPER_MAC_TRANSCRIBE_TIMEOUT (см. шапку whisper-client-mac.py).",
                    file=sys.stderr,
                    flush=True,
                )
                mac_banner_notification(
                    "Whisper — таймаут",
                    "Сеть или сервер не ответили в срок. Проверь Tailscale/ПК; при долгом Whisper задай WHISPER_MAC_TRANSCRIBE_TIMEOUT.",
                )
            except Exception as e:
                print(f"[Client] Ошибка: {e}", file=sys.stderr, flush=True)
                _MAC_LOGGER.exception("work_body_error")
                mac_banner_notification("Whisper — ошибка", str(e)[:200])
                import traceback

                traceback.print_exc()

        threading.Thread(target=work, name="whisper-transcribe", daemon=True).start()

    def run(self, *, menu_bar: bool = False) -> None:
        print(f"[Client] Удерживай {self._hotkey_label} — запись, отпусти все клавиши сочетания — распознавание.", flush=True)
        print(f"[Client] Сервер: {self.server_url}", flush=True)
        if menu_bar and rumps is not None:
            print("[Client] Иконка 🎤 в строке меню — «Выход» там же. Горячие клавиши без ⌘ (не трогаем Portal).", flush=True)
        else:
            print("[Client] Выход: Ctrl+C", flush=True)
        print(
            "[Client] Перехват клавиш в фоновом потоке с автоперезапуском (macOS / Portal / Cmd+V).",
            flush=True,
        )

        self._run_stop = False
        self._menu_bar_mode = bool(menu_bar and WhisperMenuBarApp is not None)

        def _sigint(_signum: int, _frame: object | None) -> None:
            print("\n[Client] Остановка…", flush=True)
            self.request_shutdown()

        signal.signal(signal.SIGINT, _sigint)

        # Пробуем нативный CGEventTap (в Python-процессе); если не вышло — pynput fallback.
        if sys.platform == "darwin":
            self._using_daemon = self._try_start_hotkey_daemon()
            if self._using_daemon:
                print(
                    "[Client] Нативный CGEventTap активен — "
                    "pynput Listener не используется.",
                    flush=True,
                )
            else:
                _mac_log(
                    "warning",
                    "native_tap_unavailable — fallback на pynput",
                )

        if not self._using_daemon:
            self._ensure_listener_thread()

        def _headless_main_loop() -> None:
            last_daemon_watchdog = 0.0
            while not self._run_stop:
                self._drain_main_thread_jobs()
                if self._using_daemon:
                    now = time.monotonic()
                    if now - last_daemon_watchdog >= 2.0:
                        self._ensure_daemon_running()
                        last_daemon_watchdog = now
                    time.sleep(0.02)
                else:
                    self._ensure_listener_thread()
                    self._maybe_recover_stale_listener()
                    t = self._listener_thread
                    if t is not None:
                        t.join(timeout=0.6)
                    else:
                        time.sleep(0.6)

        try:
            if menu_bar and WhisperMenuBarApp is not None:
                try:
                    WhisperMenuBarApp(self).run()
                except BaseException:
                    _MAC_LOGGER.exception("rumps_menu_bar_crashed_fallback_headless")
                    try:
                        mac_banner_notification(
                            "Whisper",
                            "Строка меню недоступна — клиент работает без иконки. См. ~/Library/Logs/WhisperMacClient.log",
                        )
                    except Exception:
                        pass
                    _headless_main_loop()
            else:
                _headless_main_loop()
        finally:
            self.request_shutdown()
            if self._listener_thread is not None:
                self._listener_thread.join(timeout=5.0)


if rumps is not None:

    class WhisperMenuBarApp(rumps.App):
        """Индикатор в menu bar. Хоткей Whisper без ⌘ — не пересекается с Portal (⌘⌃P/C/V)."""

        def __init__(self, client: WhisperClientMac) -> None:
            ip = tray_icon_path()
            _mac_log("debug", "tray_icon_path=%r", ip)
            try:
                from whisper_version import get_version as _gv

                self._app_version = _gv()
            except ImportError:
                self._app_version = "?"
            if ip:
                super().__init__("Whisper", icon=ip, quit_button=None)
                self._emoji_mode = False
            else:
                super().__init__("Whisper", title="🎤", quit_button=None)
                self._emoji_mode = True
                _mac_log("warning", "tray_icon_missing — emoji fallback (icon файл не найден)")

            self.client = client
            self._mi_server = rumps.MenuItem(self._server_title(), callback=None)
            _menu_timeouts = [
                rumps.MenuItem(
                    "По умолчанию (сброс файла настроек)",
                    callback=self._timeouts_preset_reset,
                ),
                rumps.MenuItem(
                    "Быстро · health 15с, TCP 30с, ответ 8 мин",
                    callback=self._timeouts_preset_fast,
                ),
                rumps.MenuItem(
                    "Норма · 30с, TCP 60с, ответ 15 мин",
                    callback=self._timeouts_preset_normal,
                ),
                rumps.MenuItem(
                    "Долго · 60с, TCP 90с, ответ 30 мин",
                    callback=self._timeouts_preset_long,
                ),
                rumps.MenuItem("Свои значения…", callback=self._timeouts_custom),
            ]
            _menu_speaker = [
                rumps.MenuItem(
                    "Сброс порога (как при запуске)",
                    callback=self._speaker_threshold_reset,
                ),
                rumps.MenuItem("Порог 0.60", callback=self._speaker_threshold_set_factory(0.60)),
                rumps.MenuItem("Порог 0.65", callback=self._speaker_threshold_set_factory(0.65)),
                rumps.MenuItem("Порог 0.70", callback=self._speaker_threshold_set_factory(0.70)),
                rumps.MenuItem("Порог 0.72", callback=self._speaker_threshold_set_factory(0.72)),
                rumps.MenuItem("Порог 0.75", callback=self._speaker_threshold_set_factory(0.75)),
                rumps.MenuItem("Своё число…", callback=self._speaker_threshold_custom),
            ]
            self.menu = [
                rumps.MenuItem(f"Версия {self._app_version}", callback=None),
                self._mi_server,
                rumps.separator,
                ("Таймауты сервера", _menu_timeouts),
                ("Порог эталона голоса", _menu_speaker),
                rumps.separator,
                rumps.MenuItem("Проверить обновления…", callback=self._check_updates_menu),
                rumps.MenuItem("Записать эталон голоса (45 с)…", callback=self._enroll_speaker_menu),
                rumps.separator,
                rumps.MenuItem("Перезапустить перехват клавиш", callback=self._restart_hotkey),
                rumps.MenuItem("Показать лог…", callback=self._open_log),
                rumps.MenuItem("Выход", callback=self._quit),
            ]
            # После initializeStatusBar() в rumps.App.run(), иначе клики по иконке часто «мёртвые».
            rumps.events.before_start.register(_rumps_apply_accessory_activation_policy)
            # Запрашиваем разрешение на уведомления из контекста работающего NSApp.
            # Таймер 3 с: к тому времени RunLoop уже запущен → completionHandler доставляется корректно.
            threading.Timer(3.0, self._request_notifications_permission).start()
            threading.Timer(12.0, self._startup_update_check_once).start()
            _ir = _listener_idle_recycle_sec()
            if _ir > 0:
                _mac_log(
                    "warning",
                    "listener_idle_recycle_on interval=%.0fs — на macOS периодический restart pynput часто роняет ⌃⌥⇧; "
                    "для стабильной работы убери WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC и не передавай --listener-idle-recycle-sec",
                    _ir,
                )

        def _server_title(self) -> str:
            u = self.client.server_url
            return u if len(u) <= 56 else u[:53] + "…"

        def _apply_status_bar_menu_fix(self) -> None:
            """macOS 11+: повесить NSMenu на NSStatusBarButton — иначе клик по иконке часто молчит."""
            try:
                inst = getattr(rumps.App, "*app_instance", None)
                if inst is None or not hasattr(inst, "_nsapp"):
                    return
                item = inst._nsapp.nsstatusitem
                if item is None:
                    return
                m = item.menu()
                btn = item.button()
                if btn is None or m is None:
                    return
                btn.setEnabled_(True)
                try:
                    btn.setAppearsDisabledWhenInactive_(False)
                except Exception:
                    pass
                try:
                    btn.setMenu_(m)
                except Exception:
                    pass
                item.setHighlightMode_(True)
                _mac_log("debug", "status_bar_menu_fix_applied")
            except Exception as _e:
                _mac_log("debug", "status_bar_menu_fix_skip err=%s", _e)

        def _request_notifications_permission(self) -> None:
            """Запрашивает разрешение на уведомления из контекста работающего NSApp.
            Только из работающего RunLoop completionHandler гарантированно достигает главного потока,
            а значит диалог авторизации реально появится на экране.
            """
            try:
                import UserNotifications as UN  # type: ignore[import]

                center = UN.UNUserNotificationCenter.currentNotificationCenter()

                def _handler(granted: bool, err: object) -> None:
                    if granted:
                        _mac_log("info", "notification_auth_granted")
                    else:
                        _mac_log(
                            "warning",
                            "notification_auth_denied — перейди в «Системные настройки → "
                            "Уведомления» и разреши «Whisper Client»",
                        )

                center.requestAuthorizationWithOptions_completionHandler_(
                    UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound,
                    _handler,
                )
            except Exception as _e:
                _mac_log("debug", "notification_auth_request_skip err=%s", _e)

        def _open_log(self, _sender) -> None:
            logf = Path.home() / "Library" / "Logs" / "WhisperMacClient.log"
            if not logf.is_file():
                logf = Path(tempfile.gettempdir()) / "WhisperMacClient.log"
            subprocess.run(["open", "-R", str(logf)], check=False)

        def _check_updates_menu(self, _sender) -> None:
            threading.Thread(
                target=lambda: run_mac_update_flow(notify_always=True),
                name="whisper-mac-update",
                daemon=True,
            ).start()

        def _timeouts_preset_reset(self, _sender) -> None:
            self.client._merge_save_mac_prefs(
                health_timeout=None,
                transcribe_timeout=None,
                transcribe_connect_timeout=None,
            )
            rumps.alert(
                "Таймауты",
                "Сброшены. Снова действуют значения по умолчанию и переменные окружения.",
            )

        def _timeouts_preset_fast(self, _sender) -> None:
            self.client._merge_save_mac_prefs(
                health_timeout=15.0,
                transcribe_connect_timeout=30.0,
                transcribe_timeout=480.0,
            )
            rumps.alert("Таймауты", "Сохранено: быстрый профиль (ответ до 8 мин).")

        def _timeouts_preset_normal(self, _sender) -> None:
            self.client._merge_save_mac_prefs(
                health_timeout=30.0,
                transcribe_connect_timeout=60.0,
                transcribe_timeout=900.0,
            )
            rumps.alert("Таймауты", "Сохранено: нормальный профиль (ответ до 15 мин).")

        def _timeouts_preset_long(self, _sender) -> None:
            self.client._merge_save_mac_prefs(
                health_timeout=60.0,
                transcribe_connect_timeout=90.0,
                transcribe_timeout=1800.0,
            )
            rumps.alert("Таймауты", "Сохранено: долгий профиль (ответ до 30 мин).")

        def _timeouts_custom(self, _sender) -> None:
            tc, tr = self.client._effective_transcribe_timeouts()
            h = self.client._effective_health_timeout_sec()
            default = f"{int(h)} {int(tc)} {int(tr)}"
            w = rumps.Window(
                message="Три числа через пробел: health_сек · tcp_сек · ответ_сек",
                title="Таймауты Whisper",
                default_text=default,
                dimensions=(420, 160),
            )
            out = w.run()
            if out is None:
                return
            parts = out.strip().split()
            if len(parts) != 3:
                rumps.alert("Ошибка", "Нужно ровно три числа через пробел.")
                return
            try:
                hv, cv, rv = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                rumps.alert("Ошибка", "Введи три числа.")
                return
            self.client._merge_save_mac_prefs(
                health_timeout=hv,
                transcribe_connect_timeout=cv,
                transcribe_timeout=rv,
            )
            rumps.alert("Таймауты", f"Сохранено: {hv:.0f} / {cv:.0f} / {rv:.0f} с")

        def _speaker_threshold_reset(self, _sender) -> None:
            self.client._merge_save_mac_prefs(speaker_threshold=None)
            rumps.alert(
                "Порог эталона",
                "Сброшен — используется порог при запуске и WHISPER_SPEAKER_THRESHOLD.",
            )

        def _speaker_threshold_set_factory(self, val: float):
            def _cb(_s) -> None:
                self.client._merge_save_mac_prefs(speaker_threshold=val)
                rumps.alert(
                    "Порог эталона",
                    f"Сохранено {val:.2f} (~/.whisper/mac_client_prefs.json).",
                )

            return _cb

        def _speaker_threshold_custom(self, _sender) -> None:
            cur: float | None = self.client._pref_speaker_threshold
            if cur is None:
                try:
                    from speaker_verify import threshold as _sv_thr

                    cur = float(_sv_thr())
                except Exception:
                    cur = 0.70
            w = rumps.Window(
                message="Косинусное сходство с эталоном: 0.50 … 0.95",
                title="Порог эталона",
                default_text=f"{cur:.4f}".rstrip("0").rstrip("."),
                dimensions=(380, 120),
            )
            out = w.run()
            if out is None:
                return
            try:
                v = float(out.replace(",", ".").strip())
            except ValueError:
                rumps.alert("Ошибка", "Нужно число.")
                return
            if not 0.45 <= v <= 0.99:
                rumps.alert("Ошибка", "Ожидается число от 0.45 до 0.99.")
                return
            self.client._merge_save_mac_prefs(speaker_threshold=v)
            rumps.alert("Порог эталона", f"Сохранено {v:.3f}")

        def _startup_update_check_once(self) -> None:
            if self.client._run_stop:
                return
            if os.environ.get("WHISPER_SKIP_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
                return
            try:
                run_mac_update_flow(notify_newer_only=True)
            except Exception:
                _MAC_LOGGER.debug("startup_update_check", exc_info=True)

        def _enroll_speaker_menu(self, _sender) -> None:
            ok = rumps.alert(
                title="Эталон голоса",
                message="После «Начать» пойдёт запись 45 секунд.\n\nГовори в обычном темпе одним голосом. Рядом не должно болтать других людей.\n\nНужны пакеты torch + resemblyzer (см. инструкцию HTML, один раз в Терминале).",
                ok="Начать",
                cancel="Отмена",
            )
            if ok != 1:
                return
            threading.Thread(target=self._enroll_record_worker, name="whisper-enroll", daemon=True).start()

        def _enroll_record_worker(self) -> None:
            sr = 16000
            dur_sec = 45
            frames = int(sr * dur_sec)
            tmp_path: str | None = None
            try:
                try:
                    from speaker_verify import embedding_path, enroll_from_wav
                except ImportError:
                    mac_banner_notification(
                        "Whisper",
                        "Нет модулей для эталона. Один раз в Терминале: python3 -m pip install torch resemblyzer",
                    )
                    return
                mac_banner_notification("Whisper", "Идёт запись 45 с — говори в микрофон…")
                rec = sd.rec(frames, samplerate=sr, channels=1, dtype="float32")
                sd.wait()
                flat = np.asarray(rec).reshape(-1)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    tmp_path = tf.name
                sf.write(tmp_path, flat, sr)
                enroll_from_wav(tmp_path)
                self.client._speaker_verify = True
                _mac_log("info", "enroll_menu_ok path=%s", embedding_path())
                mac_banner_notification(
                    "Whisper",
                    "Эталон сохранён. Проверка голоса включена для этой сессии; при следующем запуске .app — автоматически.",
                )
            except Exception as e:
                _MAC_LOGGER.exception("enroll_menu_failed")
                mac_banner_notification("Whisper", f"Ошибка записи эталона: {e!s:.120}")
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

        def _quit(self, _sender) -> None:
            self.client.request_shutdown()
            if self.client._listener_thread and self.client._listener_thread.is_alive():
                self.client._listener_thread.join(timeout=5.0)
            rumps.quit_application()

        def _restart_hotkey(self, _sender) -> None:
            """Перезапустить перехват клавиш вручную из меню."""
            if self.client._using_daemon:
                d = self.client._hotkey_daemon
                if d:
                    try:
                        d.stop()
                    except Exception:
                        pass
                    self.client._hotkey_daemon = None
                ok = self.client._try_start_hotkey_daemon()
                if ok:
                    mac_banner_notification("Whisper", "Перехват клавиш перезапущен.")
                else:
                    self.client._using_daemon = False
                    self.client._ensure_listener_thread()
                    mac_banner_notification("Whisper", "Нативный tap недоступен — переключено на pynput.")
            else:
                self.client._reset_hotkey_tracker()
                self.client._kick_listener_restart(force=True)
                mac_banner_notification("Whisper", "Перехват клавиш (pynput) перезапущен.")

        @rumps.timer(0.05)
        def _once_statusbar_menu_fix(self, sender) -> None:
            """Сразу после старта RunLoop: меню на кнопке статус-бара (macOS 11+)."""
            try:
                sender.stop()
            except Exception:
                pass
            if not getattr(self, "_statusbar_menu_fix_done", False):
                self._statusbar_menu_fix_done = True
                self._apply_status_bar_menu_fix()

        @rumps.timer(0.05)
        def _drain_main_thread_jobs_tick(self, _sender) -> None:
            self.client._drain_main_thread_jobs()

        @rumps.timer(0.5)
        def _tick(self, _sender) -> None:
            if self.client._run_stop:
                rumps.quit_application()
                return
            self._mi_server.title = self._server_title()
            if not self._emoji_mode:
                return
            rec = busy = False
            with self.client._lock:
                rec = self.client._recording
                busy = self.client._busy
            self.title = "🔴" if (rec or busy) else "🎤"

        @rumps.timer(2.0)
        def _watchdog_listener(self, _sender) -> None:
            if self.client._run_stop:
                return
            if self.client._using_daemon:
                self.client._ensure_daemon_running()
            else:
                self.client._ensure_listener_thread()
                self.client._maybe_recover_stale_listener()

        @rumps.timer(30.0)
        def _idle_recycle_listener(self, _sender) -> None:
            """Только если задано WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC>0 (по умолчанию выключено)."""
            sec = _listener_idle_recycle_sec()
            if sec <= 0 or self.client._run_stop:
                return
            now = time.time()
            nxt = getattr(self, "_idle_recycle_next_ts", 0.0)
            if nxt == 0.0:
                self._idle_recycle_next_ts = now + sec
                return
            if now < nxt:
                return
            with self.client._lock:
                if self.client._recording or self.client._busy:
                    self._idle_recycle_next_ts = now + sec
                    return
            self._idle_recycle_next_ts = now + sec
            _mac_log("info", "listener_idle_recycle kick interval=%.0fs (env)", sec)
            self.client._reset_hotkey_tracker()
            self.client._kick_listener_restart(force=False)

        @rumps.timer(90.0)
        def _sticky_hotkey_watchdog(self, _sender) -> None:
            """Сбрасывает «залипшую» модель модификаторов после долгого простоя (без перезапуска tap)."""
            if self.client._run_stop:
                return
            with self.client._lock:
                if self.client._recording or self.client._busy:
                    return
            last = getattr(self.client, "_last_hotkey_event_monotonic", 0.0)
            if last <= 0:
                return
            idle = time.monotonic() - last
            if idle < 180.0:
                return
            stuck = False
            with self.client._hk_lock:
                if self.client._hk_pressed or self.client._hk_combo_active or self.client._hk_suppress:
                    stuck = True
                    self.client._hk_pressed.clear()
                    self.client._hk_combo_active = False
                    self.client._hk_suppress = False
            if stuck:
                _mac_log("warning", "hotkey_sticky_state_cleared idle=%.0fs", idle)

else:
    WhisperMenuBarApp = None  # type: ignore[misc, assignment]


def main() -> int:
    log_path = configure_whisper_mac_logging()
    ingest_macos_python_crash_reports_into_log()
    _mac_log("info", "=== старт whisper-client-mac ===")
    try:
        _check_pynput_py313()
    except SystemExit as e:
        if e.code not in (0, None):
            _mac_log("error", "pynput_version_check_exit code=%s", e.code)
        raise

    if hasattr(threading, "excepthook"):
        _orig_thread_excepthook = threading.excepthook

        def _thread_excepthook(args: object) -> None:
            th = getattr(args, "thread", None)
            exc_t = getattr(args, "exc_type", None)
            exc_v = getattr(args, "exc_value", None)
            exc_tb = getattr(args, "exc_traceback", None)
            _MAC_LOGGER.error(
                "thread_crash name=%s",
                getattr(th, "name", "?"),
                exc_info=(exc_t, exc_v, exc_tb) if exc_t else None,
            )
            _orig_thread_excepthook(args)

        threading.excepthook = _thread_excepthook  # type: ignore[method-assign]

    # macOS при запуске .app из Finder добавляет -psn_0_… в argv; иначе parse_args() падает и приложение сразу завершается.
    sys.argv = [sys.argv[0]] + [
        a for a in sys.argv[1:] if not a.startswith("-psn_")
    ]

    p = argparse.ArgumentParser(
        description="Whisper клиент для Mac",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
В терминале при старте (если не указан --hotkey) спросит сочетание; Enter = ⌃+⇧+⌥.
Примеры:
  %(prog)s --server URL
  %(prog)s --server URL --hotkey shift+ctrl+grave
  %(prog)s --server URL --no-hotkey-prompt   # без вопроса, ⌃+⇧+⌥ (или WHISPER_MAC_HOTKEY)
  %(prog)s --server URL --bind-hotkey
        """.strip(),
    )
    p.add_argument(
        "--server",
        default=None,
        help="URL сервера (например: http://192.168.1.100:8000); не нужен только с --enroll-speaker",
    )
    p.add_argument("--language", default=None, help="ru, en или авто")
    p.add_argument(
        "--no-spoken-punctuation",
        action="store_true",
        help="Не заменять «запятая» на знаки",
    )
    p.add_argument(
        "--hotkey",
        default=None,
        metavar="COMBO",
        help="Сочетание через +: alt+ctrl, cmd+alt, ctrl+grave … (без флага — спросит в терминале)",
    )
    p.add_argument(
        "--no-hotkey-prompt",
        action="store_true",
        help="Не спрашивать сочетание в терминале; без --hotkey — ⌃+⇧+⌥ или WHISPER_MAC_HOTKEY",
    )
    p.add_argument(
        "--bind-hotkey",
        action="store_true",
        help="Зажми сочетание и отпусти — запомнить (вместо строки и промпта)",
    )
    p.add_argument(
        "--bind-timeout",
        type=float,
        default=90.0,
        metavar="SEC",
        help="Секунд ожидания при --bind-hotkey (по умолчанию 90)",
    )
    p.add_argument(
        "--no-menu-bar",
        action="store_true",
        help="Не показывать иконку в строке меню (нужен пакет rumps; см. README)",
    )
    p.add_argument(
        "--listener-idle-recycle-sec",
        type=float,
        default=None,
        metavar="SEC",
        help="Экспериментально: перезапускать pynput после N с без событий хоткея (0 = выключить). "
        "По умолчанию выкл; на macOS может ломать сочетание — не используй без необходимости.",
    )
    p.add_argument(
        "--enroll-speaker",
        metavar="WAV",
        default=None,
        help="Сохранить эталон голоса из WAV (~30–60 с); нужен pip install -r requirements-speaker.txt",
    )
    p.add_argument(
        "--speaker-verify",
        action="store_true",
        help="Перед отправкой на сервер сверять голос с эталоном (~/.whisper/speaker_embedding.npy)",
    )
    p.add_argument(
        "--speaker-threshold",
        type=float,
        default=None,
        metavar="0.0-1.0",
        help="Порог косинусного сходства (по умолчанию из WHISPER_SPEAKER_THRESHOLD или 0.70)",
    )
    args, _unknown_argv = p.parse_known_args()
    if _unknown_argv:
        _mac_log(
            "warning",
            "лишние argv (часто от Finder/Cocoa), игнорируем: %r",
            _unknown_argv,
        )

    if args.listener_idle_recycle_sec is not None:
        v = float(args.listener_idle_recycle_sec)
        if v <= 0:
            os.environ["WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC"] = "0"
        else:
            os.environ["WHISPER_MAC_LISTENER_IDLE_RECYCLE_SEC"] = str(int(max(60.0, v)))

    if not args.enroll_speaker and not args.server:
        p.error("нужен --server (или только --enroll-speaker WAV для эталона голоса)")

    if args.enroll_speaker:
        try:
            from speaker_verify import embedding_path, enroll_from_wav
        except ImportError:
            print(
                "[Client] Нет speaker_verify — установи: pip install -r requirements-speaker.txt",
                file=sys.stderr,
            )
            return 1
        try:
            enroll_from_wav(args.enroll_speaker)
            print(f"[Client] Эталон сохранён: {embedding_path()}", flush=True)
            return 0
        except Exception as e:
            print(f"[Client] enroll-speaker: {e}", file=sys.stderr)
            return 1

    try:
        from whisper_version import get_version as _app_ver

        _mac_log("info", "app_version=%s", _app_ver())
    except ImportError:
        pass

    _mac_log("info", "server=%s log_file=%s", args.server, log_path)
    if not sys.stdout.isatty():
        print(f"[Client] Подробный лог: {log_path}", flush=True)

    def _default_hotkey_str() -> str:
        raw = (os.environ.get("WHISPER_MAC_HOTKEY") or "").strip()
        return raw if raw else "shift+ctrl+alt"

    def read_hotkey_from_terminal() -> HotkeySpec:
        dflt = _default_hotkey_str()
        print(
            "[Client] Сочетание задаётся ТЕКСТОМ (латиницей), не путай с физическим нажатием клавиш в другом окне.",
            flush=True,
        )
        print(
            "[Client] Примеры:  shift+ctrl+alt   shift+ctrl+grave   alt+ctrl   ctrl+grave   shift+ctrl+rbracket",
            flush=True,
        )
        print(
            f"[Client] Пустой Enter = по умолчанию ({dflt}; задай WHISPER_MAC_HOTKEY или --hotkey чтобы поменять).",
            flush=True,
        )
        print(
            "[Client] Чтобы задать сочетание одним нажатием клавиш, закрой и запусти с флагом  --bind-hotkey",
            flush=True,
        )
        try:
            line = input("[Client] Строка сочетания: ").strip()
        except EOFError:
            line = ""
        if not line:
            return parse_hotkey_string(dflt)
        return parse_hotkey_string(line)

    try:
        if args.bind_hotkey:
            hotkey = bind_hotkey_interactive(timeout=args.bind_timeout)
        elif args.hotkey is not None:
            hotkey = parse_hotkey_string(args.hotkey)
        elif args.no_hotkey_prompt or not sys.stdin.isatty():
            hotkey = parse_hotkey_string(_default_hotkey_str())
        else:
            hotkey = read_hotkey_from_terminal()
    except ValueError as e:
        print(f"[Client] Ошибка горячей клавиши: {e}", file=sys.stderr)
        return 2

    print(f"[Client] Активное сочетание: {describe_hotkey(hotkey)}", flush=True)

    if os.environ.get("WHISPER_FROM_APP_BUNDLE"):
        subprocess.run(
            [
                "logger",
                "-t",
                "WhisperClient",
                "Старт pid=%s server=%s hotkey=%s"
                % (os.getpid(), args.server, describe_hotkey(hotkey)),
            ],
            check=False,
            capture_output=True,
            timeout=3.0,
        )
        if not sys.stdin.isatty():
            hk = describe_hotkey(hotkey)
            # Асинхронно — не блокируем старт приложения ожиданием whisper_notify/osascript
            _notif_text = f"Клиент в фоне. Удерживай {hk} — запись; отпусти — распознавание."
            threading.Thread(
                target=lambda: mac_banner_notification("Whisper Client", _notif_text),
                daemon=True,
                name="whisper-startup-notif",
            ).start()

    use_menu_bar = (
        sys.platform == "darwin"
        and WhisperMenuBarApp is not None
        and not args.no_menu_bar
        and os.environ.get("WHISPER_MAC_NO_MENU") != "1"
    )
    if use_menu_bar:
        _pid = os.getpid()
        _mac_log(
            "info",
            "menu_bar_quit_hint pid=%s — в «Завершении программ» не показывается; в Мониторинге ищи «Python» "
            "с командной строкой whisper-client-mac.py или: pkill -f whisper-client-mac.py",
            _pid,
        )
        print(
            "[Client] Закрыть клиент: в Терминале  pkill -f whisper-client-mac.py  "
            f"(pid {_pid}; в окне ⌥⌘⎋ его нет — это нормально для иконки только в меню-баре).",
            flush=True,
        )
        print(
            "[Client] Либо дважды кликни kill_whisper_client.command: в .app это "
            "Contents/Resources/ (через «Показать содержимое пакета»), в репо — packaging/mac/.",
            flush=True,
        )
        print(
            "[Client] Две иконки 🎤 подряд = два запущенных клиента; второй лучше не запускать — "
            "закрой лишний (pkill) или открой .app один раз.",
            flush=True,
        )
        if os.environ.get("WHISPER_MAC_GUI_PYTHONAPP") == "1":
            print(
                "[Client] Запуск через Python.app (из .app) — так строка меню стабильно показывает иконку 🎤.",
                flush=True,
            )
    if (
        os.environ.get("WHISPER_FROM_APP_BUNDLE")
        and sys.platform == "darwin"
        and WhisperMenuBarApp is None
        and not args.no_menu_bar
    ):
        print(
            "[Client] Иконка в строке меню: pip install rumps (тем же python3, что запускает клиент).",
            flush=True,
        )
        exe = sys.executable.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display dialog "Нет пакета rumps — не будет иконки 🎤 в строке меню.\\n\\nВыполни в Терминале:\\n{exe} -m pip install rumps" '
                'buttons {"OK"} default button 1 with title "Whisper Client"',
            ],
            check=False,
            capture_output=True,
        )
        _mac_log("warning", "rumps_missing executable=%s", sys.executable)

    _mac_log(
        "info",
        "runtime python=%s rumps_ok=%s menu_bar_requested=%s",
        sys.executable,
        rumps is not None,
        (
            sys.platform == "darwin"
            and rumps is not None
            and not args.no_menu_bar
            and os.environ.get("WHISPER_MAC_NO_MENU") != "1"
        ),
    )
    if os.environ.get("WHISPER_MAC_GUI_PYTHONAPP") == "1":
        _mac_log(
            "info",
            "status_bar_launch_via_python_app=1 (run.sh подставил Python.app для иконки в меню-баре из Finder)",
        )

    if os.environ.get("WHISPER_MAC_NO_SPEAKER_VERIFY", "").strip() == "1":
        spk = False
    else:
        spk = args.speaker_verify or (
            os.environ.get("WHISPER_SPEAKER_VERIFY", "").strip().lower() in ("1", "true", "yes")
        )

    if use_menu_bar and os.environ.get("WHISPER_MAC_ALLOW_MULTIPLE", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        _ok_lock, _other_hint = _mac_menu_bar_singleton_acquire()
        if not _ok_lock:
            _hint_esc = str(_other_hint).replace('"', "'") if _other_hint else ""
            _pid_apple = (
                f' & return & return & "Уже работает процесс pid {_hint_esc}."' if _hint_esc else ""
            )
            # В AppleScript перенос строки — «return», не \\n внутри литерала.
            _ascript = (
                'display dialog "Клиент Whisper уже запущен." & return & return & '
                '"Вторая копия даёт две иконки 🎤 и клик по меню часто ломается." & return & return & '
                '"Сначала завершите первый экземпляр: в Терминале выполните" & return & '
                '"pkill -f whisper-client-mac.py"'
                f"{_pid_apple} "
                'with title "Whisper Client" buttons {"OK"} default button 1'
            )
            try:
                subprocess.run(
                    ["osascript", "-e", _ascript],
                    check=False,
                    capture_output=True,
                    timeout=8.0,
                )
            except subprocess.TimeoutExpired:
                # Без Automation/доступа к «Управлению компьютером» диалог может не появиться — висит до timeout.
                _mac_log(
                    "warning",
                    "menu_bar_singleton_osascript_timeout other_pid_hint=%r — pkill -f whisper-client-mac.py",
                    _other_hint,
                )
                print(
                    "[Client] Уже запущен другой Whisper (см. лог). Завершить: pkill -f whisper-client-mac.py",
                    file=sys.stderr,
                    flush=True,
                )
            _mac_log("warning", "menu_bar_singleton_denied other_pid_hint=%r", _other_hint)
            # exit 2 macOS показывает как «приложение неожиданно завершилось» — здесь это штатный отказ второй копии
            return 0

    client = WhisperClientMac(
        server_url=args.server,
        language=args.language,
        spoken_punctuation=not args.no_spoken_punctuation,
        hotkey=hotkey,
        speaker_verify=spk,
        speaker_threshold=args.speaker_threshold,
    )
    _macos_touch_microphone_permission_if_bundle()
    try:
        client.run(menu_bar=use_menu_bar)
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
