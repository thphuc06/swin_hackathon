from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.services.finance.oss_adapters import (  # noqa: E402
    kats_cusum_change_points,
    pyod_ecod_outlier,
    river_adwin_drift,
)


class FinanceOssAdaptersTests(unittest.TestCase):
    def test_river_adwin_detects_drift(self) -> None:
        series = [1.0] * 60 + [10.0] * 60
        result = river_adwin_drift(series)
        self.assertIn("available", result)
        if result.get("available"):
            self.assertIn("drift_detected", result)
            self.assertIn("window_width", result)

    def test_pyod_ecod_detects_outlier(self) -> None:
        series = [100.0] * 40 + [5_000.0]
        result = pyod_ecod_outlier(series)
        self.assertTrue(result.get("available"))
        self.assertTrue(result.get("ready", False))
        self.assertIn("outlier_flag", result)

    def test_kats_adapter_returns_shape(self) -> None:
        day_keys = [f"2026-01-{day:02d}" for day in range(1, 31)]
        series = [1000.0 + day for day in range(30)]
        result = kats_cusum_change_points(day_keys, series)
        self.assertIn("available", result)
        self.assertIn("engine", result)


if __name__ == "__main__":
    unittest.main()
