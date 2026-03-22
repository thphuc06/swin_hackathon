"""
test_cusum_sliding_window_local.py
====================================
Test CUSUM Sliding Window behavior locally using MockDBConnection.
No real database or AWS credentials required.

Run:
    python tests/test_cusum_sliding_window_local.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'infrastructure', 'lambda', 'cusum_worker', 'dist_package'))

from cusum_engine import CUSUMDetector, CUSUMTimeSeriesDetector, estimate_baseline_stats
from cusum_state_manager import CUSUMStateManager, MockDBConnection
from datetime import datetime, timezone, timedelta


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_mock_db(amounts: list[float], user_id="u1", jar_id="food") -> MockDBConnection:
    """Build a MockDB pre-seeded with historical transactions."""
    db = MockDBConnection()
    db.transactions_table = [
        {"user_id": user_id, "jar_id": jar_id, "amount": a}
        for a in amounts
    ]
    return db


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ──────────────────────────────────────────────────────────────────────────────
# TEST 1: Normal spending – S+ should stay low, no drift
# ──────────────────────────────────────────────────────────────────────────────
def test_1_normal_spending():
    separator("TEST 1: Normal Spending (no drift expected)")
    BASELINE = [100_000] * 20  # 20 transactions of exactly 100k
    db = make_mock_db(BASELINE)
    manager = CUSUMStateManager(db)
    baseline = manager.get_baseline_stats("u1", "food", lookback_days=90)
    print(f"  Baseline → mean={baseline['mean']:,.0f}  sigma={baseline['sigma']:.2f}  n={baseline['sample_count']}")

    # Since sigma≈0 from constant data, use a safe fallback
    mean = baseline["mean"]
    sigma = max(baseline["sigma"] * 2.6, 1_500_000)

    detector = CUSUMDetector(reference_mean=mean*7, sigma=sigma, k_factor=0.5, h_factor=5.0)
    new_txns = [95_000, 102_000, 98_000, 101_000, 99_000]  # Still normal
    drifts = []
    for txn in new_txns:
        _, drift = detector.update(txn)
        drifts.append(drift)
        print(f"  txn={txn:>10,}  S+={detector.cumsum_pos:>12,.1f}  drift={drift}")

    assert not any(drifts), "❌ FAIL: Normal spending triggered a drift!"
    print("  ✅ PASS – No drift on normal spending.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 2: Sudden Spike (Z-score bypass) – single huge outlier
# ──────────────────────────────────────────────────────────────────────────────
def test_2_sudden_spike():
    separator("TEST 2: Sudden Spike (Z-score bypass)")
    BASELINE = [200_000] * 15
    db = make_mock_db(BASELINE)
    manager = CUSUMStateManager(db)
    baseline = manager.get_baseline_stats("u1", "food", lookback_days=90)
    mean = baseline["mean"]
    sigma = max(baseline["sigma"] * 2.6, 1_500_000)

    detector = CUSUMTimeSeriesDetector(
        reference_mean=mean * 7, sigma=sigma, k_factor=0.5, h_factor=5.0, z_score_threshold=4.0
    )
    # Normal warm-up
    for _ in range(5):
        state, _, _ = detector.update_series(200_000, datetime.now(timezone.utc).isoformat())

    # SPIKE: 20M – should trigger 'sudden_spike'
    state, drift, info = detector.update_series(20_000_000, datetime.now(timezone.utc).isoformat())
    print(f"  Spike txn: 20,000,000")
    print(f"  anomaly_type={info['type']}  severity={info['severity']}  spike={state.spike_detected}")
    assert info["type"] == "sudden_spike", f"❌ FAIL: expected sudden_spike, got {info['type']}"
    # After spike, S+ must NOT be inflated (accumulator was bypassed)
    assert state.cumsum_pos == 0.0, f"❌ FAIL: S+ should be 0 after spike bypass, got {state.cumsum_pos}"
    print("  ✅ PASS – Spike detected AND S+ not poisoned.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 3: Gradual Drift – sustained increase triggers upward drift
# ──────────────────────────────────────────────────────────────────────────────
def test_3_gradual_drift():
    separator("TEST 3: Gradual Upward Drift")
    BASELINE = [100_000] * 10
    mean = 100_000.0
    sigma = 20_000.0 * 2.6  # 52_000

    detector = CUSUMDetector(reference_mean=mean, sigma=sigma, k_factor=0.5, h_factor=5.0)
    # Gradual increase – each txn a bit above mean
    drifting_txns = [110_000, 120_000, 130_000, 140_000, 150_000,
                     160_000, 170_000, 180_000, 190_000, 200_000]
    drift_triggered = False
    for txn in drifting_txns:
        state, drift = detector.update(txn)
        status = "🔴 DRIFT!" if drift else "   "
        print(f"  txn={txn:>10,}  S+={state.cumsum_pos:>10,.1f}  {status}")
        if drift:
            drift_triggered = True
            break

    assert drift_triggered, "❌ FAIL: Gradual drift did NOT trigger an alert!"
    print("  ✅ PASS – Gradual upward drift detected.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 4: Sliding Window baseline – new transactions shift mean
# ──────────────────────────────────────────────────────────────────────────────
def test_4_sliding_window_baseline_shift():
    separator("TEST 4: Sliding Window – Baseline shift after new data")
    user_id, jar_id = "u1", "food"
    db = make_mock_db([100_000] * 10, user_id, jar_id)
    manager = CUSUMStateManager(db)

    baseline_before = manager.get_baseline_stats(user_id, jar_id, lookback_days=90)
    mean_before = baseline_before["mean"]
    print(f"  Baseline BEFORE: mean={mean_before:,.0f}")

    # Simulate adding new high-spending records (the "new reality" of the window)
    for amt in [500_000, 600_000, 700_000, 800_000, 900_000]:
        db.transactions_table.append({"user_id": user_id, "jar_id": jar_id, "amount": amt})

    baseline_after = manager.get_baseline_stats(user_id, jar_id, lookback_days=90)
    mean_after = baseline_after["mean"]
    print(f"  Baseline AFTER:  mean={mean_after:,.0f}")

    assert mean_after > mean_before, "❌ FAIL: Sliding window did not shift baseline up!"
    print(f"  ✅ PASS – Mean grew from {mean_before:,.0f} → {mean_after:,.0f}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 5: State persistence – S+ survives save/reload cycle
# ──────────────────────────────────────────────────────────────────────────────
def test_5_state_persistence():
    separator("TEST 5: State Persistence (Save → Load → Resume)")
    db = make_mock_db([150_000] * 10)
    manager = CUSUMStateManager(db)

    # Manually save a mid-drift state
    manager.save_state("u1", "food",
        cumsum_pos=300_000.0,
        cumsum_neg=0.0,
        reference_mean=150_000.0,
        reference_sigma=30_000.0,
        drift_detected=False,
        transaction_count=10,
    )

    # Reload and check continuity
    restored = manager.load_state("u1", "food")
    print(f"  Restored S+={restored['cumsum_pos']:,.1f}  S-={restored['cumsum_neg']:,.1f}")
    assert restored["cumsum_pos"] == 300_000.0, "❌ FAIL: S+ not correctly reloaded!"
    assert restored["transaction_count"] == 10, "❌ FAIL: transaction_count not correctly reloaded!"
    print("  ✅ PASS – CUSUM state persisted and restored correctly.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 6: Reset after drift – S+ resets to 0 after firing
# ──────────────────────────────────────────────────────────────────────────────
def test_6_reset_after_drift():
    separator("TEST 6: Reset After Drift – S+ resets to 0")
    mean, sigma = 100_000.0, 52_000.0
    detector = CUSUMDetector(reference_mean=mean, sigma=sigma, k_factor=0.5, h_factor=5.0)

    # Feed high transactions until drift fires
    for _ in range(15):
        state, drift = detector.update(200_000)
        if drift:
            print(f"  Drift fired! Post-reset S+={state.cumsum_pos}  S-={state.cumsum_neg}")
            assert state.cumsum_pos == 0.0, f"❌ FAIL: S+ should be 0 after reset, got {state.cumsum_pos}"
            print("  ✅ PASS – S+ correctly reset to 0 after drift.")
            return

    assert False, "❌ FAIL: Drift never fired after 15 high transactions!"


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        test_1_normal_spending,
        test_2_sudden_spike,
        test_3_gradual_drift,
        test_4_sliding_window_baseline_shift,
        test_5_state_persistence,
        test_6_reset_after_drift,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"\n  {e}")
            failed += 1
        except Exception as e:
            print(f"\n  ❌ EXCEPTION in {test_fn.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    separator(f"RESULTS: {passed}/{len(tests)} passed, {failed} failed")
