"""Unit tests for spoken punctuation + vocab finalize (no GPU)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SpokenPunctuationTests(unittest.TestCase):
    def test_russian_comma(self) -> None:
        from whisper_text_post import apply_spoken_punctuation

        self.assertEqual(
            apply_spoken_punctuation("привет запятая как дела"),
            "привет, как дела",
        )

    def test_question_and_exclaim_short(self) -> None:
        from whisper_text_post import apply_spoken_punctuation

        self.assertEqual(
            apply_spoken_punctuation("серьёзно вопросительный"),
            "серьёзно?",
        )
        self.assertEqual(
            apply_spoken_punctuation("ура восклицательный"),
            "ура!",
        )

    def test_full_phrases(self) -> None:
        from whisper_text_post import apply_spoken_punctuation

        self.assertIn("?", apply_spoken_punctuation("что вопросительный знак"))
        self.assertIn("!", apply_spoken_punctuation("да восклицательный знак"))

    def test_semicolon_ellipsis(self) -> None:
        from whisper_text_post import apply_spoken_punctuation

        self.assertIn(";", apply_spoken_punctuation("а точка с запятой б"))
        self.assertIn("…", apply_spoken_punctuation("ну многоточие"))

    def test_english(self) -> None:
        from whisper_text_post import apply_spoken_punctuation

        self.assertEqual(
            apply_spoken_punctuation("hello comma world"),
            "hello, world",
        )


class FinalizeVocabTests(unittest.TestCase):
    def test_finalize_punct_then_vocab(self) -> None:
        from whisper_text_post import finalize_transcript

        vocab = {
            "version": 1,
            "global": {
                "terms": [],
                "replacements": [{"from": "кубернетес", "to": "Kubernetes"}],
                "context_hint": "",
            },
            "profiles": {},
        }
        out = finalize_transcript(
            "подними кубернетес запятая пожалуйста",
            spoken_punctuation=True,
            vocab=vocab,
        )
        self.assertEqual(out, "подними Kubernetes, пожалуйста")

    def test_vocab_file_roundtrip(self) -> None:
        from whisper_text_post import finalize_transcript
        import whisper_vocab as wv

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "vocab.json"
            data = {
                "version": 1,
                "global": {
                    "terms": ["Portal"],
                    "replacements": [{"from": "портал", "to": "Portal"}],
                    "context_hint": "",
                },
                "profiles": {},
            }
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(wv, "vocab_file_path", return_value=str(path)):
                wv.load_vocab(force=True)
                out = finalize_transcript("открой портал точка", spoken_punctuation=True)
                self.assertEqual(out, "открой Portal.")


if __name__ == "__main__":
    unittest.main()
