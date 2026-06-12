#!/usr/bin/env python3
"""Захват микрофона в отдельном процессе (.app / rumps → in-process sd.rec даёт peak=0)."""
from __future__ import annotations

import json
import os
import signal
import sys
import time

import numpy as np
import sounddevice as sd
import soundfile as sf


def _resolve_input_device() -> int:
    dev = sd.default.device
    if hasattr(dev, "__getitem__"):
        return int(dev[0])
    return int(dev)


def _ptt_capture(out_wav: str, device_idx: int | None) -> dict:
    idx = device_idx if device_idx is not None else _resolve_input_device()
    max_sec = float(os.environ.get("WHISPER_MIC_CAPTURE_MAX_SEC", "600"))
    max_frames = int(max_sec * 16000)
    started = time.monotonic()
    stop = False

    def _on_stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGUSR1, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    rec = sd.rec(max_frames, samplerate=16000, channels=1, dtype="float32", device=idx)
    while not stop:
        time.sleep(0.02)
    sd.stop()
    elapsed = max(time.monotonic() - started, 0.05)
    frames = min(int(elapsed * 16000) + 2000, len(rec))
    audio = np.asarray(rec[:frames], dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    sf.write(out_wav, audio, 16000)
    name = ""
    try:
        name = str(sd.query_devices(idx).get("name", idx))
    except Exception:
        name = str(idx)
    return {
        "ok": True,
        "peak": peak,
        "samples": int(audio.size),
        "duration": round(elapsed, 3),
        "device_idx": idx,
        "device": name,
        "out": out_wav,
    }


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "ptt":
        print(json.dumps({"ok": False, "error": "usage: whisper_mic_capture.py ptt OUT.wav [device_idx]"}))
        return 2
    out_wav = sys.argv[2]
    dev: int | None = None
    if len(sys.argv) > 3:
        try:
            dev = int(sys.argv[3])
        except ValueError:
            dev = None
    try:
        result = _ptt_capture(out_wav, dev)
        print(json.dumps(result), flush=True)
        return 0 if result.get("peak", 0) > 0.002 or result.get("samples", 0) > 4000 else 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
