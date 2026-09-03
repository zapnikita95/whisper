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


class DictationSpeedPrefsTests(unittest.TestCase):
    def test_migrates_server_to_groq_first(self) -> None:
        from whisper_groq import ensure_hotkey_default_prefs

        prefs = {
            "transcribe_backend": "server",
            "groq_proxy_enabled": True,
            "cloud_token": "wsk_test_token_for_migrate",
            "model_key": "large-v3",
            "notifications": True,
            "paste_mode": "auto",
            "ai_mode": "raw",
            "groq_proxy_url": "https://whisper-groq-proxy-production.up.railway.app",
        }
        with mock.patch("whisper_groq.load_hotkey_prefs", return_value=dict(prefs)):
            with mock.patch("whisper_groq.save_hotkey_prefs") as save:
                with mock.patch("whisper_groq.groq_api_key_from_env", return_value=None):
                    out = ensure_hotkey_default_prefs()
        self.assertEqual(out["transcribe_backend"], "groq_then_server")
        self.assertTrue(out.get("dictation_speed_v1"))
        save.assert_called()

    def test_auto_vram_prefers_groq_when_configured(self) -> None:
        from whisper_groq import resolve_auto_vram_backend_order

        with mock.patch("whisper_groq.groq_is_configured", return_value=True):
            with mock.patch(
                "whisper_system_profile.nvidia_vram_snapshot",
                return_value={"vram_free_gb": 12.0},
            ):
                with mock.patch("whisper_groq.read_hotkey_model_key_pref", return_value="large-v3"):
                    with mock.patch("whisper_groq.read_hotkey_auto_vram_margin_pref", return_value=0.8):
                        order = resolve_auto_vram_backend_order("large-v3")
        self.assertEqual(order[0], "groq")
        self.assertIn("server", order)


if __name__ == "__main__":
    unittest.main()
