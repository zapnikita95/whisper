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


class ProxyCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        from whisper_groq import reset_proxy_health_state

        reset_proxy_health_state()

    def tearDown(self) -> None:
        from whisper_groq import reset_proxy_health_state

        reset_proxy_health_state()

    def test_railway_before_layero(self) -> None:
        from whisper_groq import (
            FALLBACK_GROQ_PROXY_URL,
            LAYERO_GROQ_PROXY_URL,
            groq_proxy_url_candidates,
        )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHISPER_GROQ_PROXY_URL", None)
            os.environ.pop("GROQ_PROXY_URL", None)
            got = groq_proxy_url_candidates(LAYERO_GROQ_PROXY_URL)
        self.assertEqual(got[0], FALLBACK_GROQ_PROXY_URL.rstrip("/"))
        self.assertIn(LAYERO_GROQ_PROXY_URL.rstrip("/"), got)
        self.assertGreater(got.index(LAYERO_GROQ_PROXY_URL.rstrip("/")), 0)

    def test_dead_layero_dropped(self) -> None:
        from whisper_groq import (
            LAYERO_GROQ_PROXY_URL,
            groq_proxy_url_candidates,
            mark_proxy_unreachable,
        )

        mark_proxy_unreachable(LAYERO_GROQ_PROXY_URL)
        got = groq_proxy_url_candidates(LAYERO_GROQ_PROXY_URL)
        self.assertNotIn(LAYERO_GROQ_PROXY_URL.rstrip("/"), got)

    def test_http_deadline_cuts_hang(self) -> None:
        import time

        import requests
        from whisper_groq import http_call_deadline

        def _hang() -> requests.Response:
            time.sleep(30)
            raise AssertionError("should not finish")

        t0 = time.perf_counter()
        with self.assertRaises(requests.ConnectTimeout):
            http_call_deadline(_hang, deadline_sec=0.6)
        self.assertLess(time.perf_counter() - t0, 2.5)


class AiModeFailOpenTests(unittest.TestCase):
    def test_apply_returns_raw_on_timeout(self) -> None:
        import requests
        from whisper_ai_modes import apply_ai_mode

        with mock.patch(
            "whisper_ai_modes.post_groq_chat_completion",
            side_effect=requests.ConnectTimeout("layero"),
        ):
            out = apply_ai_mode(
                "привет",
                "polish",
                has_byok=True,
                local_stt_ok=True,
            )
        self.assertEqual(out, "привет")

    def test_error_toast_blank_for_pool(self) -> None:
        from whisper_ai_modes import ai_mode_error_toast

        err = RuntimeError(
            "HTTPSConnectionPool(host='whisper-groq-proxy.layero.app', port=443): Max retries exceeded"
        )
        self.assertEqual(ai_mode_error_toast(err), "")


if __name__ == "__main__":
    unittest.main()
