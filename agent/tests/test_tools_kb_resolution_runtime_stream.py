from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

import tools  # noqa: E402


class ToolsKbResolutionTests(unittest.TestCase):
    def test_resolve_kb_dir_uses_env_override(self) -> None:
        kb_path = ROOT / "kb"
        with patch.dict(os.environ, {"KB_DIR": str(kb_path)}, clear=False):
            resolved = tools._resolve_kb_dir()
        self.assertEqual(resolved, kb_path)

    def test_load_kb_files_from_resolved_dir(self) -> None:
        loaded = tools._load_kb_files()
        self.assertGreaterEqual(len(loaded), 1)
        self.assertIn("policies.md", loaded)


if __name__ == "__main__":
    unittest.main()
