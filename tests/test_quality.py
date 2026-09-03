"""Stable STT quality: punctuated prompt, compute type, no silent turbo."""
from __future__ import annotations

import unittest


class MergePromptTests(unittest.TestCase):
    def test_always_includes_punctuation(self) -> None:
        from whisper_quality import PUNCTUATION_PROMPT_SEED, merge_initial_prompt

        empty = merge_initial_prompt(None)
        self.assertIn(",", empty)
        self.assertIn(".", empty)
        self.assertIn("?", empty)
        self.assertTrue(empty.startswith(PUNCTUATION_PROMPT_SEED[:20]))

        with_vocab = merge_initial_prompt("Термины: Portal, Kubernetes.")
        self.assertIn("Portal", with_vocab)
        self.assertIn(",", with_vocab)
        self.assertIn(".", with_vocab)
        # seed is not duplicated
        self.assertEqual(with_vocab.count("Здравствуйте."), 1)

    def test_idempotent_if_seed_already_present(self) -> None:
        from whisper_quality import PUNCTUATION_PROMPT_SEED, merge_initial_prompt

        once = merge_initial_prompt(PUNCTUATION_PROMPT_SEED)
        twice = merge_initial_prompt(once)
        self.assertEqual(once.count("Здравствуйте."), 1)
        self.assertEqual(twice.count("Здравствуйте."), 1)


class TranscribeKwargsTests(unittest.TestCase):
    def test_decode_settings(self) -> None:
        from whisper_quality import local_transcribe_kwargs

        kw = local_transcribe_kwargs(language="ru", initial_prompt="Portal")
        self.assertEqual(kw["beam_size"], 1)
        self.assertEqual(kw["temperature"], 0.0)
        self.assertFalse(kw["condition_on_previous_text"])
        self.assertEqual(kw["language"], "ru")
        self.assertIn("Portal", kw["initial_prompt"])
        self.assertIn(",", kw["initial_prompt"])

    def test_long_audio_keeps_beam5(self) -> None:
        from whisper_quality import local_transcribe_kwargs

        kw = local_transcribe_kwargs(audio_sec=120.0)
        self.assertEqual(kw["beam_size"], 5)
        kw_short = local_transcribe_kwargs(audio_sec=12.0)
        self.assertEqual(kw_short["beam_size"], 1)

    def test_strip_prompt_echo(self) -> None:
        from whisper_quality import PUNCTUATION_PROMPT_SEED, strip_prompt_echo

        self.assertEqual(strip_prompt_echo(PUNCTUATION_PROMPT_SEED), "")
        self.assertEqual(
            strip_prompt_echo("Hello, this is a well-punctuated transcript."),
            "",
        )
        self.assertIn("привет", strip_prompt_echo("привет, как дела?").lower())


class ComputeTypeTests(unittest.TestCase):
    def test_explicit_wins(self) -> None:
        from whisper_quality import resolve_quality_compute_type

        self.assertEqual(
            resolve_quality_compute_type(device="cuda", explicit="int8"),
            "int8",
        )
        self.assertEqual(
            resolve_quality_compute_type(device="cpu", explicit=None),
            "int8",
        )
        self.assertEqual(
            resolve_quality_compute_type(device="cuda", explicit="auto"),
            resolve_quality_compute_type(device="cuda", explicit=None),
        )
        auto_cuda = resolve_quality_compute_type(device="cuda", explicit=None)
        self.assertIn(auto_cuda, ("float16", "int8_float16"))


class GroqModelTests(unittest.TestCase):
    def test_primary_default_is_large_v3(self) -> None:
        import os
        from unittest import mock

        from whisper_groq import DEFAULT_GROQ_MODEL, groq_transcription_model_primary

        self.assertEqual(DEFAULT_GROQ_MODEL, "whisper-large-v3")
        with mock.patch.dict(os.environ, {"GROQ_TRANSCRIPTION_MODEL": ""}, clear=False):
            os.environ.pop("GROQ_TRANSCRIPTION_MODEL", None)
            self.assertEqual(groq_transcription_model_primary(), "whisper-large-v3")


if __name__ == "__main__":
    unittest.main()
