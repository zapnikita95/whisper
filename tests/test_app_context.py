"""Tests for app context + voice prefixes."""
from __future__ import annotations

import unittest


class SuggestModeTests(unittest.TestCase):
    def test_apps(self) -> None:
        from whisper_app_context import suggest_ai_mode

        self.assertEqual(suggest_ai_mode("Slack"), "chat")
        self.assertEqual(suggest_ai_mode("Telegram Desktop"), "chat")
        self.assertEqual(suggest_ai_mode("Cursor"), "code")
        self.assertEqual(suggest_ai_mode("Code"), "code")
        self.assertEqual(suggest_ai_mode("Gmail"), "email")
        self.assertEqual(suggest_ai_mode("Chrome"), "polish")


class VoicePrefixTests(unittest.TestCase):
    def test_prefixes(self) -> None:
        from whisper_ai_modes import resolve_effective_mode, strip_voice_prefix

        t, m = strip_voice_prefix("письмо перенесём созвон")
        self.assertEqual(m, "email")
        self.assertTrue(t.startswith("перенесём"))
        t, m = resolve_effective_mode(
            "как код print(1)", app_name="Slack", pref_mode="auto"
        )
        self.assertEqual(m, "code")
        self.assertIn("print", t)
        t, m = resolve_effective_mode("привет", app_name="Cursor", pref_mode="auto")
        self.assertEqual(m, "code")
        t, m = resolve_effective_mode("привет", app_name="Cursor", pref_mode="chat")
        self.assertEqual(m, "chat")


if __name__ == "__main__":
    unittest.main()
