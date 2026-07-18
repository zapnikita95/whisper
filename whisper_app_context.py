"""Frontmost application detection + AI mode suggestion from context."""
from __future__ import annotations

import sys
from typing import Any

# Substrings matched against app name / window title / process (case-insensitive).
_EMAIL_HINTS = (
    "mail",
    "outlook",
    "gmail",
    "thunderbird",
    "sparrow",
    "airmail",
    "hotmail",
    "yandex.mail",
    "mail.ru",
)
_CHAT_HINTS = (
    "slack",
    "telegram",
    "whatsapp",
    "messages",
    "discord",
    "teams",
    "signal",
    "element",
    "mattermost",
    "zoom",
    "skype",
    "imessage",
    "viber",
)
_CODE_HINTS = (
    "cursor",
    "code",
    "visual studio",
    "vscode",
    "pycharm",
    "idea",
    "webstorm",
    "goland",
    "clion",
    "sublime",
    "atom",
    "neovim",
    "vim",
    "terminal",
    "iterm",
    "warp",
    "cmd.exe",
    "powershell",
    "windows terminal",
    "xcode",
    "android studio",
    "notepad++",
)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def suggest_ai_mode(app_name: str | None, *, free_fallback: str = "polish") -> str:
    """Map frontmost app → ai mode. Unknown → free_fallback (polish or raw)."""
    n = _norm(app_name)
    if not n:
        return free_fallback
    for h in _EMAIL_HINTS:
        if h.strip().lower() in n:
            return "email"
    for h in _CHAT_HINTS:
        if h.strip().lower() in n:
            return "chat"
    for h in _CODE_HINTS:
        if h.strip().lower() in n:
            return "code"
    return free_fallback


def frontmost_app_windows() -> str | None:
    """Process name or window title of the foreground window (Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        access = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
        hproc = kernel32.OpenProcess(access, False, pid.value)
        if not hproc:
            hproc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
        name: str | None = None
        if hproc:
            try:
                buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(512)
                # QueryFullProcessImageNameW
                q = getattr(kernel32, "QueryFullProcessImageNameW", None)
                if q and q(hproc, 0, buf, ctypes.byref(size)):
                    path = buf.value or ""
                    name = path.replace("\\", "/").rsplit("/", 1)[-1]
                    if name.lower().endswith(".exe"):
                        name = name[:-4]
            finally:
                kernel32.CloseHandle(hproc)
        if name and name.lower() not in ("explorer", "applicationframehost", "searchhost"):
            return name
        # Fallback: window title tail
        length = user32.GetWindowTextLengthW(hwnd) or 0
        if length <= 0:
            return name
        tbuf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, tbuf, length + 1)
        title = (tbuf.value or "").strip()
        for sep in (" — ", " - ", " – "):
            if sep in title:
                title = title.split(sep)[-1].strip()
                break
        return title or name
    except Exception:
        return None


def frontmost_app_mac() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace  # type: ignore[import-untyped]

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        name = str(app.localizedName() or "").strip()
        if not name:
            bid = str(app.bundleIdentifier() or "").strip()
            if bid:
                name = bid.rsplit(".", 1)[-1]
        if name.lower().startswith("python"):
            return None
        return name or None
    except Exception:
        return None


def frontmost_app() -> str | None:
    if sys.platform == "win32":
        return frontmost_app_windows()
    if sys.platform == "darwin":
        return frontmost_app_mac()
    return None


def context_snapshot() -> dict[str, Any]:
    app = frontmost_app()
    mode = suggest_ai_mode(app)
    return {"app": app, "suggested_mode": mode}
