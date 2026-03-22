"""
test_income_engine.py
======================
Unit tests cho income_engine.py — pure Python, không cần DB hay AWS.

Run:
    python tests/test_income_engine.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'infrastructure', 'lambda', 'cusum_worker', 'dist_package'))

from income_engine import analyze_income_vs_spend


def separator(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)


def test_income_exceeds_spend():
    separator("TEST 1: Income vượt chi tiêu → gợi ý")
    s = analyze_income_vs_spend(income=20_000_000, monthly_spend=12_000_000)
    assert s.should_suggest is True,          f"should_suggest sai: {s.should_suggest}"
    assert s.surplus == 8_000_000,            f"surplus sai: {s.surplus}"
    assert s.surplus_pct == 40.0,             f"surplus_pct sai: {s.surplus_pct}"
    assert s.suggested_saving_amount == 5_600_000, f"suggested sai: {s.suggested_saving_amount}"
    assert s.severity == "medium",            f"severity sai: {s.severity}"   # 40% → medium (25-50%)
    assert s.title != "",                     "title trống"
    assert "5,600,000" in s.detail,           f"detail không chứa số gợi ý: {s.detail}"
    print(f"  surplus={s.surplus:,.0f}  pct={s.surplus_pct}%  suggest={s.suggested_saving_amount:,.0f}")
    print("  ✅ PASS")


def test_income_less_than_spend():
    separator("TEST 2: Income < Chi tiêu → không gợi ý")
    s = analyze_income_vs_spend(income=8_000_000, monthly_spend=10_000_000)
    assert s.should_suggest is False
    assert s.surplus < 0
    assert s.title == ""
    print(f"  surplus={s.surplus:,.0f}  pct={s.surplus_pct}%")
    print("  ✅ PASS")


def test_surplus_below_threshold():
    separator("TEST 3: Thặng dư 5% < ngưỡng 10% → không gợi ý")
    s = analyze_income_vs_spend(income=10_000_000, monthly_spend=9_500_000)
    assert s.should_suggest is False
    assert s.surplus_pct == 5.0, f"surplus_pct sai: {s.surplus_pct}"
    print(f"  surplus_pct={s.surplus_pct}% (ngưỡng 10%)")
    print("  ✅ PASS")


def test_zero_income():
    separator("TEST 4: Income = 0 → không crash")
    s = analyze_income_vs_spend(income=0, monthly_spend=5_000_000)
    assert s.should_suggest is False
    assert s.surplus_pct == 0.0
    print("  ✅ PASS")


def test_saving_rounding():
    separator("TEST 5: Làm tròn xuống 10,000 VND")
    # surplus = 7,777,777 → 70% = 5,444,443.9 → làm tròn = 5,440,000
    s = analyze_income_vs_spend(income=15_000_000, monthly_spend=7_222_223)
    assert s.should_suggest is True
    assert s.suggested_saving_amount % 10_000 == 0, f"Không chia hết 10k: {s.suggested_saving_amount}"
    print(f"  suggested={s.suggested_saving_amount:,.0f} VND (chia hết 10k)")
    print("  ✅ PASS")


def test_exact_threshold():
    separator("TEST 6: Đúng ngưỡng 10% → phải gợi ý")
    s = analyze_income_vs_spend(income=10_000_000, monthly_spend=9_000_000)
    assert s.should_suggest is True
    assert s.surplus_pct == 10.0, f"surplus_pct sai: {s.surplus_pct}"
    print(f"  surplus_pct={s.surplus_pct}% (đúng ngưỡng)")
    print("  ✅ PASS")


def test_high_surplus_severity():
    separator("TEST 7: Thặng dư ≥ 50% → severity=high")
    s = analyze_income_vs_spend(income=10_000_000, monthly_spend=4_000_000)
    # surplus=6M, surplus_pct=60% → high
    assert s.should_suggest is True
    assert s.severity == "high", f"severity sai: {s.severity}"
    print(f"  surplus_pct={s.surplus_pct}%  severity={s.severity}")
    print("  ✅ PASS")


if __name__ == "__main__":
    tests = [
        test_income_exceeds_spend,
        test_income_less_than_spend,
        test_surplus_below_threshold,
        test_zero_income,
        test_saving_rounding,
        test_exact_threshold,
        test_high_surplus_severity,
    ]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ EXCEPTION: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    separator(f"RESULTS: {passed}/{len(tests)} passed, {failed} failed")
