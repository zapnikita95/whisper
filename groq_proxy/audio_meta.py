"""Estimate audio duration for metering (stdlib only)."""
from __future__ import annotations

import io
import struct
import wave


def estimate_audio_seconds(raw: bytes, filename: str | None = None) -> float:
    """Best-effort duration in seconds. Falls back to PCM heuristics."""
    if not raw:
        return 0.5
    # WAV via stdlib
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return max(0.1, frames / float(rate))
    except Exception:
        pass
    # Minimal RIFF/WAVE parse if wave module rejects odd headers
    try:
        if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
            # find fmt + data
            pos = 12
            channels = 1
            rate = 16000
            bits = 16
            data_size = 0
            while pos + 8 <= len(raw):
                chunk_id = raw[pos : pos + 4]
                chunk_size = struct.unpack_from("<I", raw, pos + 4)[0]
                pos += 8
                if chunk_id == b"fmt " and chunk_size >= 16:
                    channels = struct.unpack_from("<H", raw, pos + 2)[0] or 1
                    rate = struct.unpack_from("<I", raw, pos + 4)[0] or 16000
                    bits = struct.unpack_from("<H", raw, pos + 14)[0] or 16
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break
                pos += chunk_size + (chunk_size & 1)
            if data_size and rate:
                bytes_per_sec = max(1, channels * (bits // 8) * rate)
                return max(0.1, data_size / float(bytes_per_sec))
    except Exception:
        pass
    # Assume 16-bit mono 16 kHz PCM payload (clients usually send WAV)
    approx = len(raw) / 32000.0
    return max(0.5, min(3600.0, approx))
