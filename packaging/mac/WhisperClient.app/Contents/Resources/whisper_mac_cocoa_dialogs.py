"""Диалоги AppKit для колбэков меню rumps.

Tkinter из обработчика NSMenu на главном потоке часто даёт «тишину»: wait_window
блокирует CFRunLoop и окна Tk не получают события. NSAlert.runModal() встроен
в Cocoa и работает из того же потока.

Внутри accessory не используем NSButton + NSObject target — на части сборок PyObjC это давало краш.
Проверка сервера — до показа диалога (авто-скан) и отдельный пункт меню «Проверить связь».
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from Foundation import NSMakeRect  # type: ignore[import-untyped]

from whisper_mac_defaults import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT

_NS_ALERT_FIRST = 1000
_NS_ALERT_SECOND = 1001


def _activate_for_modal_dialog() -> None:
    """Whisper Client — LSUIElement (нет Dock). Иначе NSAlert не выходит на передний план."""
    try:
        from AppKit import NSApplication  # type: ignore[import-untyped]

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def _test_whisper_server(host: str, port: int) -> tuple[bool, str]:
    host = host.strip()
    if not host:
        return False, "Укажи IP или имя хоста."
    try:
        p = int(port)
        if not (1 <= p <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return False, "Порт должен быть числом 1–65535."
    url = f"http://{host}:{p}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WhisperMacTest/1"})
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        d = json.loads(raw)
        if d.get("status") == "ok" and "model" in d:
            return True, f"Ок: {url}\nМодель: {d.get('model', '?')}"
        return False, "Ответ не похож на Whisper Server (ожидался JSON status=ok, model)."
    except Exception as e:
        return False, str(e)[:240]


def mac_cocoa_ask_string(
    *,
    title: str,
    message: str,
    default: str = "",
    password: bool = False,
) -> str | None:
    """Одна строка; None = отмена."""
    from AppKit import (  # type: ignore[import-untyped]
        NSAlert,
        NSAlertStyleInformational,
        NSSecureTextField,
        NSTextField,
    )

    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleInformational)
    alert.setMessageText_(title)
    alert.setInformativeText_(message)

    if password:
        field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 22))
    else:
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 22))
    field.setStringValue_(default)

    alert.setAccessoryView_(field)
    alert.addButtonWithTitle_("Сохранить")
    alert.addButtonWithTitle_("Отмена")

    _activate_for_modal_dialog()
    resp = alert.runModal()
    if resp != _NS_ALERT_FIRST:
        return None
    return str(field.stringValue())


def mac_cocoa_server_host_port_dialog(
    *,
    title: str,
    host: str,
    port: int,
    scan_summary: str = "",
) -> tuple[str, int] | None:
    """IP + порт + текст результата авто-поиска; только Сохранить / Отмена (без NSObject-кнопок)."""
    from AppKit import (  # type: ignore[import-untyped]
        NSAlert,
        NSAlertStyleInformational,
        NSTextField,
        NSView,
    )

    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleInformational)
    alert.setMessageText_(title)
    alert.setInformativeText_(
        "Адрес ПК с Whisper Server в Tailscale/LAN.\n"
        "127.0.0.1 на сервере — только локально на том ПК; для Mac нужен IP вида 100.x или локальной сети.\n"
        "Перед открытием окна выполнен автоматический поиск API на портах (как при старте)."
    )

    h0 = host.strip() or DEFAULT_SERVER_HOST
    try:
        p0 = int(port) if port else DEFAULT_SERVER_PORT
        if not (1 <= p0 <= 65535):
            p0 = DEFAULT_SERVER_PORT
    except (TypeError, ValueError):
        p0 = DEFAULT_SERVER_PORT

    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 440, 230))

    lab_h = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 198, 92, 17))
    lab_h.setStringValue_("IP или хост:")
    lab_h.setBezeled_(False)
    lab_h.setDrawsBackground_(False)
    lab_h.setEditable_(False)

    he = NSTextField.alloc().initWithFrame_(NSMakeRect(98, 195, 335, 22))
    he.setStringValue_(h0)

    lab_p = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 158, 92, 17))
    lab_p.setStringValue_("Порт:")
    lab_p.setBezeled_(False)
    lab_p.setDrawsBackground_(False)
    lab_p.setEditable_(False)

    pe = NSTextField.alloc().initWithFrame_(NSMakeRect(98, 155, 90, 22))
    pe.setStringValue_(str(p0))

    sum_txt = (scan_summary or "").strip() or "Авто-поиск: ещё не выполнялся."
    try:
        status = NSTextField.wrappingLabelWithString_(sum_txt)
        status.setFrame_(NSMakeRect(0, 0, 440, 135))
    except AttributeError:
        status = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 440, 135))
        status.setStringValue_(sum_txt)
        status.setEditable_(False)
        status.setBezeled_(True)

    container.addSubview_(lab_h)
    container.addSubview_(he)
    container.addSubview_(lab_p)
    container.addSubview_(pe)
    container.addSubview_(status)

    alert.setAccessoryView_(container)
    alert.addButtonWithTitle_("Сохранить")
    alert.addButtonWithTitle_("Отмена")

    _activate_for_modal_dialog()
    resp = alert.runModal()
    if resp != _NS_ALERT_FIRST:
        return None

    hs = he.stringValue().strip()
    if not hs:
        return None
    try:
        pt = int(str(pe.stringValue()).strip())
        if not (1 <= pt <= 65535):
            return None
    except (TypeError, ValueError):
        return None
    return hs, pt
