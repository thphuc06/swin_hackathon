from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from response.synthesizer_bedrock import _sanitize_prose_line  # noqa: E402


class SynthesizerCleanupTests(unittest.TestCase):
    def test_collapse_adjacent_duplicate_phrase_vi(self) -> None:
        raw = "Muc tieu hien tai chua kha thi chua kha thi."
        cleaned = _sanitize_prose_line(raw, language="vi")
        self.assertEqual(cleaned.lower().count("khả thi"), 1)
        self.assertNotIn("chua kha thi chua kha thi", cleaned.lower())

    def test_remove_adjacent_duplicate_numeric_rendering_vi(self) -> None:
        raw = "Can khoang thieu so voi muc tieu la 50 trieu 50,000,000."
        cleaned = _sanitize_prose_line(raw, language="vi")
        self.assertIn("50 trieu", cleaned.lower())
        self.assertNotIn("50,000,000", cleaned)


if __name__ == "__main__":
    unittest.main()
