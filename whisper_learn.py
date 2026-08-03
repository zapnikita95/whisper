"""Learn vocabulary replacements from post-paste user edits (Pro / BYOK / local)."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

log = logging.getLogger("whisper_learn")

_last_suggest_mono = 0.0
_SUGGEST_COOLDOWN_SEC = 45.0


def learn_from_edits_enabled() -> bool:
    try:
        from whisper_groq import load_hotkey_prefs

        v = load_hotkey_prefs().get("learn_from_edits")
        if v is None:
            return True
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        pass
    return True


def _word_pairs(a: str, b: str) -> list[tuple[str, str]]:
    """Find simple 1:1 word substitutions between pasted and edited text."""
    wa = re.findall(r"[\w\-']+", a, flags=re.UNICODE)
    wb = re.findall(r"[\w\-']+", b, flags=re.UNICODE)
    if not wa or not wb:
        return []
    if abs(len(wa) - len(wb)) > 2:
        return []
    # Align by zip when lengths equal
    out: list[tuple[str, str]] = []
    if len(wa) == len(wb):
        for x, y in zip(wa, wb):
            if x.lower() != y.lower() and len(x) >= 3 and len(y) >= 2:
                out.append((x, y))
        return out[:3]
    # Fallback: unique tokens in a missing from b and vice versa
    sa, sb = {w.lower(): w for w in wa}, {w.lower(): w for w in wb}
    only_a = [sa[k] for k in sa if k not in sb]
    only_b = [sb[k] for k in sb if k not in sa]
    if len(only_a) == 1 and len(only_b) == 1:
        return [(only_a[0], only_b[0])]
    return []


def schedule_learn_from_clipboard(
    expected: str,
    *,
    delay_sec: float = 3.0,
    allowed: bool = True,
    get_clipboard: Callable[[], str] | None = None,
    on_suggest: Callable[[str, str], None] | None = None,
) -> None:
    """After paste, if user edits clipboard/text, suggest vocab replacement."""
    if not allowed or not learn_from_edits_enabled():
        return
    expected = (expected or "").strip()
    if len(expected) < 4:
        return

    def worker() -> None:
        global _last_suggest_mono
        time.sleep(max(1.0, delay_sec))
        try:
            if get_clipboard is None:
                import pyperclip

                current = (pyperclip.paste() or "").strip()
            else:
                current = (get_clipboard() or "").strip()
        except Exception:
            return
        if not current or current == expected:
            return
        # Ignore huge rewrites
        if abs(len(current) - len(expected)) > max(40, int(0.5 * len(expected))):
            return
        pairs = _word_pairs(expected, current)
        if not pairs:
            return
        now = time.monotonic()
        if now - _last_suggest_mono < _SUGGEST_COOLDOWN_SEC:
            return
        frm, to = pairs[0]
        if frm.lower() == to.lower():
            return
        _last_suggest_mono = now
        if on_suggest:
            try:
                on_suggest(frm, to)
                return
            except Exception:
                log.debug("on_suggest failed", exc_info=True)
        try:
            from whisper_vocab import add_replacement

            # Escape for regex from
            esc = re.escape(frm)
            add_replacement(esc, to)
            log.info("learn_vocab_auto from=%r to=%r", frm, to)
        except Exception:
            log.debug("learn auto-add failed", exc_info=True)

    threading.Thread(target=worker, name="whisper-learn", daemon=True).start()


def suggest_add_vocab(frm: str, to: str, *, auto_add: bool = False) -> str:
    """Return toast message; optionally add replacement immediately."""
    msg = f"Добавить в словарь: «{frm}» → «{to}»?"
    if auto_add:
        try:
            from whisper_vocab import add_replacement

            add_replacement(re.escape(frm), to)
            msg = f"В словарь: «{frm}» → «{to}»"
        except Exception:
            pass
    return msg
