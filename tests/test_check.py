import copy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check import check_audio, check_catalog, validate


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / "voicepack/events.json").read_text(encoding="utf-8"))
        cls.package = json.loads((ROOT / "voicepack/manifest.json").read_text(encoding="utf-8"))["package"]
        cls.audio_ids = {row["id"] for row in cls.rows}
        cls.audio = (ROOT / "samples/find.ogg").read_bytes()

    def test_current_repository(self):
        validate(ROOT)

    def test_wrong_sample_rate_is_rejected(self):
        data = bytearray(self.audio)
        offset = data.index(b"\x01vorbis")
        data[offset + 12:offset + 16] = (44100).to_bytes(4, "little")
        with self.assertRaisesRegex(ValueError, "16000 Hz"):
            check_audio(bytes(data))

    def test_embedded_vendor_is_rejected(self):
        data = bytearray(self.audio)
        offset = data.index(b"\x03vorbis")
        data[offset + 7] = 1
        with self.assertRaisesRegex(ValueError, "metadata"):
            check_audio(bytes(data))

    def test_truncated_audio_is_rejected(self):
        with self.assertRaises(ValueError):
            check_audio(self.audio[:40])

    def test_replacing_an_event_with_a_duplicate_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[-1] = copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            check_catalog(rows, self.audio_ids, self.package)

    def test_broken_event_redirect_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["remap_to"] = max(self.audio_ids) + 1
        with self.assertRaisesRegex(ValueError, "remap"):
            check_catalog(rows, self.audio_ids, self.package)

    def test_inconsistent_duplicate_groups_are_rejected(self):
        rows = copy.deepcopy(self.rows)
        row = next(row for row in rows if len(row["same_ids"]) > 1)
        row["same_ids"] = [row["id"]]
        with self.assertRaisesRegex(ValueError, "Asymmetric"):
            check_catalog(rows, self.audio_ids, self.package)


if __name__ == "__main__":
    unittest.main()
