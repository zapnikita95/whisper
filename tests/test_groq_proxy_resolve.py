"""Proxy enable resolution: UI prefs beat stale .env 0 (RF 403)."""
from __future__ import annotations

import os
import unittest
from unittest import mock


class ProxyEnabledTests(unittest.TestCase):
    def test_prefs_true_beats_env_zero(self) -> None:
        from whisper_groq import resolve_groq_proxy_enabled

        with mock.patch.dict(os.environ, {"WHISPER_GROQ_PROXY_ENABLED": "0"}, clear=False):
            self.assertTrue(resolve_groq_proxy_enabled(True))

    def test_prefs_false_stays_off(self) -> None:
        from whisper_groq import resolve_groq_proxy_enabled

        with mock.patch.dict(os.environ, {"WHISPER_GROQ_PROXY_ENABLED": ""}, clear=False):
            os.environ.pop("WHISPER_GROQ_PROXY_ENABLED", None)
            os.environ.pop("GROQ_PROXY_ENABLED", None)
            self.assertFalse(resolve_groq_proxy_enabled(False))

    def test_default_on(self) -> None:
        from whisper_groq import resolve_groq_proxy_enabled

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHISPER_GROQ_PROXY_ENABLED", None)
            os.environ.pop("GROQ_PROXY_ENABLED", None)
            self.assertTrue(resolve_groq_proxy_enabled(None))


if __name__ == "__main__":
    unittest.main()
