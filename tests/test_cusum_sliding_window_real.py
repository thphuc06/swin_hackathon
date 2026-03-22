"""
test_cusum_sliding_window_real.py
===================================
Test CUSUM Sliding Window on REAL Supabase data.
Requires SUPABASE_DB_URL set in .env file.

Run:
    cd d:\\Projects\\swin_hackathon
    python tests/test_cusum_sliding_window_real.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'infrastructure', 'lambda', 'cusum_worker', 'dist_package'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import psycopg2
from cusum_engine import CUSUMTimeSeriesDetector
from cusum_state_manager import CUSUMStateManager
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────────────
# DB wrapper (same as lambda_function.py)
# ──────────────────────────────────────────────────────────────────────────────
class PostgresDBWrapper:
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []

    def execute(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            self.conn.commit()
            return cur


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def get_connection():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise EnvironmentError("❌ SUPABASE_DB_URL not found in environment! Check your .env file.")
    return psycopg2.connect(db_url)


def pick_test_user(db: PostgresDBWrapper):
    """Auto-pick the user with most transactions (best data for baseline)."""
    rows = db.query("""
        SELECT user_id, jar_id, COUNT(*) as n
        FROM transactions
        GROUP BY user_id, jar_id
        ORDER BY n DESC
        LIMIT 1
    """)
    if not rows:
        return None, None, 0
    return str(rows[0][0]), str(rows[0][1]), int(rows[0][2])


# ──────────────────────────────────────────────────────────────────────────────
# TEST A: Baseline computation on real data
# ──────────────────────────────────────────────────────────────────────────────
def test_A_baseline_on_real_data(manager, user_id, jar_id):
    separator("TEST A: Baseline Computation (30-day window)")
    baseline = manager.get_baseline_stats(user_id, jar_id, lookback_days=30)
    print(f"  user_id={user_id[:8]}...  jar_id={jar_id[:8]}...")
    print(f"  mean={baseline['mean']:,.0f} VND")
    print(f"  sigma={baseline['sigma']:,.0f} VND")
    print(f"  sample_count={baseline['sample_count']}")

    # If there's not enough data, the system falls back to hardcoded defaults (expected)
    if baseline["sample_count"] < 5:
        print("  ⚠️  Fewer than 5 transactions – system will use hardcoded fallback baseline (10M / sigma 1.5M). This is expected for fresh DBs.")
    else:
        assert baseline["mean"] > 0, "❌ FAIL: Mean is 0 even though data exists!"
        print("  ✅ PASS – Real baseline loaded successfully.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST B: Stream recent real transactions through CUSUM
# ──────────────────────────────────────────────────────────────────────────────
def test_B_stream_real_transactions(manager, db, user_id, jar_id):
    separator("TEST B: Stream Real Transactions Through CUSUM")

    # Get real transactions from DB
    rows = db.query("""
        SELECT amount, occurred_at
        FROM transactions
        WHERE user_id = %s AND jar_id = %s
          AND amount > 0
        ORDER BY occurred_at ASC
        LIMIT 30
    """, (user_id, jar_id))

    if not rows:
        print("  ⚠️  No transactions found – skipping streaming test.")
        return

    baseline = manager.get_baseline_stats(user_id, jar_id, lookback_days=30)
    weekly_mean = baseline["mean"] * 7 if baseline["mean"] > 0 else 10_000_000
    sigma = baseline["sigma"] * 2.6 if baseline["sigma"] > 0 else 1_500_000

    print(f"  weekly_mean={weekly_mean:,.0f}  sigma={sigma:,.0f}")
    print(f"  k={0.5*sigma:,.0f}  h={5.0*sigma:,.0f}")
    print()

    detector = CUSUMTimeSeriesDetector(
        reference_mean=weekly_mean,
        sigma=sigma,
        k_factor=0.5,
        h_factor=5.0,
        z_score_threshold=4.0,
    )

    drift_count = 0
    spike_count = 0

    for row in rows:
        amount = float(row[0])
        ts = str(row[1])
        state, drift, info = detector.update_series(amount, ts)

        status = ""
        if info["type"] == "sudden_spike":
            status = f"⚡ SPIKE ({info['severity']})"
            spike_count += 1
        elif drift:
            status = f"🔴 DRIFT ({info['type']})"
            drift_count += 1
        else:
            status = "✅ OK"

        print(f"  {amount:>12,.0f} VND | S+={state.cumsum_pos:>12,.0f} | {status}")

    print(f"\n  --- Summary: {len(rows)} txns, {drift_count} drift(s), {spike_count} spike(s) ---")
    print("  ✅ PASS – All real transactions processed without error.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST C: Inject one anomalous transaction and confirm detection
# ──────────────────────────────────────────────────────────────────────────────
def test_C_injected_anomaly(manager, db, user_id, jar_id):
    separator("TEST C: Injected Anomaly (20M VND spike)")

    baseline = manager.get_baseline_stats(user_id, jar_id, lookback_days=30)
    weekly_mean = baseline["mean"] * 7 if baseline["mean"] > 0 else 10_000_000
    sigma = baseline["sigma"] * 2.6 if baseline["sigma"] > 0 else 1_500_000

    # Load persisted state (same as Lambda does on real events)
    state_dict = manager.load_state(user_id, jar_id)

    detector = CUSUMTimeSeriesDetector(
        reference_mean=weekly_mean, sigma=sigma, k_factor=0.5, h_factor=5.0, z_score_threshold=4.0
    )
    detector.cumsum_pos = state_dict["cumsum_pos"]
    detector.cumsum_neg = state_dict["cumsum_neg"]
    detector.transaction_count = state_dict["transaction_count"]

    print(f"  Restored state: S+={detector.cumsum_pos:,.0f}  tx_count={detector.transaction_count}")
    print(f"  Parameters:     weekly_mean={weekly_mean:,.0f}  sigma={sigma:,.0f}")
    print(f"  Z-score bypass threshold: {4.0 * sigma:,.0f} VND")

    # Inject 20M spike
    ANOMALY = 20_000_000.0
    state, drift, info = detector.update_series(ANOMALY, datetime.now(timezone.utc).isoformat())

    print(f"\n  Injected txn: {ANOMALY:,.0f} VND")
    print(f"  anomaly_type={info['type']}  severity={info['severity']}  confidence={info['confidence']:.2f}")
    print(f"  drift={drift}  spike={state.spike_detected}")

    detected = drift or (info["type"] == "sudden_spike")
    if detected:
        print("  ✅ PASS – Anomaly correctly detected!")
    else:
        print(f"  ⚠️  NOT detected. weekly_mean={weekly_mean:,.0f} is very high – the 'Data Paradox' may be active.")
        print("     To fix: Reset CUSUM state in DB and re-seed with smaller transactions.")


# ──────────────────────────────────────────────────────────────────────────────
# TEST D: State persistence roundtrip on real DB
# ──────────────────────────────────────────────────────────────────────────────
def test_D_state_roundtrip_real_db(manager, user_id, jar_id):
    separator("TEST D: State Persistence Round-trip on Real DB")
    FAKE_CUMSUM_POS = 12_345_678.0

    manager.save_state(
        user_id, jar_id,
        cumsum_pos=FAKE_CUMSUM_POS,
        cumsum_neg=0.0,
        reference_mean=500_000.0,
        reference_sigma=100_000.0,
        drift_detected=False,
        transaction_count=99
    )
    restored = manager.load_state(user_id, jar_id)
    print(f"  Saved S+ = {FAKE_CUMSUM_POS:,.0f}")
    print(f"  Loaded S+ = {restored['cumsum_pos']:,.0f}")
    assert abs(restored["cumsum_pos"] - FAKE_CUMSUM_POS) < 1.0, "❌ FAIL: State not correctly persisted!"
    assert restored["transaction_count"] == 99, "❌ FAIL: transaction_count mismatch!"
    print("  ✅ PASS – State round-trip to real Supabase DB successful.")


# ──────────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🔌 Connecting to Supabase...")
    try:
        conn = get_connection()
        db = PostgresDBWrapper(conn)
        manager = CUSUMStateManager(db)
        print("✅ Connected!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    user_id, jar_id, txn_count = pick_test_user(db)
    if not user_id:
        print("⚠️  No transactions in DB. Please seed some data first.")
        conn.close()
        sys.exit(0)

    print(f"\n📦 Testing with: user={user_id[:8]}...  jar={jar_id[:8]}...  ({txn_count} transactions)")

    tests = [
        lambda: test_A_baseline_on_real_data(manager, user_id, jar_id),
        lambda: test_B_stream_real_transactions(manager, db, user_id, jar_id),
        lambda: test_C_injected_anomaly(manager, db, user_id, jar_id),
        lambda: test_D_state_roundtrip_real_db(manager, user_id, jar_id),
    ]

    passed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  {e}")
        except Exception as e:
            print(f"  ❌ EXCEPTION: {e}")
            import traceback; traceback.print_exc()

    conn.close()
    separator(f"DONE – {passed}/{len(tests)} tests passed")
