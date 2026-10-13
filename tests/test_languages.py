import contextlib
import io
import json
from pathlib import Path
from string import Formatter
import unittest
from unittest.mock import Mock, patch

import voicepack


ROOT = Path(__file__).resolve().parents[1]


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, voicepack, "MESSAGES", voicepack.MESSAGES)

    def test_translations_have_matching_keys_and_placeholders(self):
        catalogs = [json.loads((ROOT / "installer" / f"messages.{lang}.json").read_text(encoding="utf-8"))
                    for lang in ("en", "ru")]
        self.assertEqual(catalogs[0].keys(), catalogs[1].keys())
        formatter = Formatter()
        for key in catalogs[0]:
            with self.subTest(key=key):
                placeholders = []
                for catalog in catalogs:
                    value = catalog[key]
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.strip())
                    placeholders.append({field for _, field, _, _ in formatter.parse(value) if field is not None})
                    value.format(**dict.fromkeys(placeholders[-1], 100))
                self.assertEqual(*placeholders)

    def test_language_selection_retries_and_confirmation_stays_explicit(self):
        for selection, language, yes in (("1", "en", "YES"), ("2", "ru", "ДА")):
            with self.subTest(language=language), contextlib.redirect_stdout(io.StringIO()):
                with patch("builtins.input", side_effect=["invalid", selection]):
                    voicepack.choose_language()
                self.assertEqual(voicepack.MESSAGES["yes"], yes.lower())
                with patch("builtins.input", side_effect=["", "no", yes]):
                    self.assertFalse(voicepack.confirm("confirm_install"))
                    self.assertFalse(voicepack.confirm("confirm_restore"))
                    self.assertTrue(voicepack.confirm("confirm_install"))

    def test_check_and_help_never_prompt_or_connect(self):
        for language in ("en", "ru"):
            for argument in ("check", "--help"):
                with self.subTest(language=language, argument=argument):
                    output = io.StringIO()
                    with (patch("sys.argv", ["voicepack.py", argument, "--lang", language]),
                          patch("builtins.input") as prompt,
                          patch.object(voicepack, "DreameCloud") as cloud,
                          patch.object(voicepack, "validate"), contextlib.redirect_stdout(output)):
                        if argument == "--help":
                            with self.assertRaises(SystemExit) as exit:
                                voicepack.main()
                            self.assertEqual(exit.exception.code, 0)
                        else:
                            self.assertEqual(voicepack.main(), 0)
                        prompt.assert_not_called()
                        cloud.assert_not_called()
                    key = "cli_description" if argument == "--help" else "check_ok"
                    self.assertIn(voicepack.MESSAGES[key], output.getvalue())

    def test_status_translates_failure_and_handles_missing_progress(self):
        client = Mock()
        client.info.return_value = {"did": "test-device"}
        client.snapshot.return_value = {
            "battery": 100, "language": "RU", "state": 13, "error": 0,
            "voice": {"state": "fail", "progress": None},
        }
        for language in ("en", "ru"):
            voicepack.set_language(language)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                voicepack.execute("status", client, {}, {})
            self.assertIn(voicepack.MESSAGES["voice_fail"], output.getvalue())
            self.assertNotIn("None", output.getvalue())
            client.install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
