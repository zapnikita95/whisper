"""Диалоги AppKit для колбэков меню rumps.

Tkinter из обработчика NSMenu на главном потоке часто даёт «тишину»: wait_window
блокирует CFRunLoop и окна Tk не получают события. NSAlert.runModal() встроен
в Cocoa и работает из того же потока.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from Foundation import NSMakeRect, NSObject  # type: ignore[import-untyped]

from whisper_mac_defaults import DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT

_NS_ALERT_FIRST = 1000
_NS_ALERT_SECOND = 1001


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


class _HostPortTestHandler(NSObject):
    """Кнопка «Проверить» внутри accessory view NSAlert."""

    hostField = None
    portField = None
    statusField = None
    on_test = None

    def testClicked_(self, sender) -> None:  # noqa: N802
        hf = self.hostField
        pf = self.portField
        sf = self.statusField
        tester = self.on_test or _test_whisper_server
        if hf is None or pf is None or sf is None:
            return
        h = hf.stringValue().strip()
        try:
            p = int(str(pf.stringValue()).strip())
        except ValueError:
            sf.setStringValue_("Порт: введи число.")
            return
        ok, msg = tester(h, p)
        sf.setStringValue_(("✓ " if ok else "✗ ") + msg)


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

    resp = alert.runModal()
    if resp != _NS_ALERT_FIRST:
        return None
    return str(field.stringValue())


def mac_cocoa_server_host_port_dialog(
    *,
    title: str,
    host: str,
    port: int,
    on_test: Callable[[str, int], tuple[bool, str]] | None = None,
) -> tuple[str, int] | None:
    """IP + порт + Проверить (внутри формы) + Сохранить / Отмена."""
    from AppKit import (  # type: ignore[import-untyped]
        NSAlert,
        NSBezelStyleRounded,
        NSButton,
        NSAlertStyleInformational,
        NSTextField,
        NSView,
    )

    alert = NSAlert.alloc().init()
    alert.setAlertStyle_(NSAlertStyleInformational)
    alert.setMessageText_(title)
    alert.setInformativeText_(
        "Адрес ПК с Whisper Server в Tailscale/LAN.\n"
        "127.0.0.1 на сервере — только локально на том ПК; для Mac нужен IP вида 100.x или локальной сети."
    )

    h0 = host.strip() or DEFAULT_SERVER_HOST
    try:
        p0 = int(port) if port else DEFAULT_SERVER_PORT
        if not (1 <= p0 <= 65535):
            p0 = DEFAULT_SERVER_PORT
    except (TypeError, ValueError):
        p0 = DEFAULT_SERVER_PORT

    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 440, 178))

    lab_h = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 138, 92, 17))
    lab_h.setStringValue_("IP или хост:")
    lab_h.setBezeled_(False)
    lab_h.setDrawsBackground_(False)
    lab_h.setEditable_(False)

    he = NSTextField.alloc().initWithFrame_(NSMakeRect(98, 135, 335, 22))
    he.setStringValue_(h0)

    lab_p = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 98, 92, 17))
    lab_p.setStringValue_("Порт:")
    lab_p.setBezeled_(False)
    lab_p.setDrawsBackground_(False)
    lab_p.setEditable_(False)

    pe = NSTextField.alloc().initWithFrame_(NSMakeRect(98, 95, 90, 22))
    pe.setStringValue_(str(p0))

    test_btn = NSButton.alloc().initWithFrame_(NSMakeRect(98, 58, 140, 28))
    test_btn.setTitle_("Проверить")
    test_btn.setBezelStyle_(NSBezelStyleRounded)

    status = NSTextField.wrappingLabelWithString_("Нажми «Проверить» для проверки GET / (JSON status/model).")
    status.setFrame_(NSMakeRect(0, 0, 440, 48))

    handler = _HostPortTestHandler.alloc().init()
    handler.hostField = he
    handler.portField = pe
    handler.statusField = status
    handler.on_test = on_test
    test_btn.setTarget_(handler)
    test_btn.setAction_("testClicked:")
    # NSButton не удерживает target — иначе GC/handler станет невалидным.
    container._whisper_hostport_handler = handler

    container.addSubview_(lab_h)
    container.addSubview_(he)
    container.addSubview_(lab_p)
    container.addSubview_(pe)
    container.addSubview_(test_btn)
    container.addSubview_(status)

    alert.setAccessoryView_(container)
    alert.addButtonWithTitle_("Сохранить")
    alert.addButtonWithTitle_("Отмена")

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
