"""
T+5/T+10/T+20 trading-day calculation tests for sector_tracker.

Tests use a tuple-based representation: (date_str, close, avg_price)
to avoid depending on astock_data.get_kline for unit tests.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import date
from sector_tracker import find_trading_day_after, calc_t_n_metrics


def test_find_trading_day_after_5_days():
    # 5 trading days after a base date
    bars = [
        # (date_str, close, avg_price)
        ("2026-06-01", 10.0, 10.0),
        ("2026-06-02", 10.2, 10.1),
        ("2026-06-03", 10.4, 10.3),
        ("2026-06-04", 10.6, 10.5),
        ("2026-06-05", 10.8, 10.7),
        ("2026-06-08", 11.0, 10.9),  # skip weekend
        ("2026-06-09", 11.2, 11.1),
        ("2026-06-10", 11.4, 11.3),
    ]
    base = date(2026, 6, 1)
    # 5 trading days AFTER base (base excluded): index 1..5 → 06-02, 03, 04, 05, 08
    out = find_trading_day_after(bars, base, n=5)
    assert out is not None
    assert out[0] == "2026-06-08"
    assert abs(out[1] - 11.0) < 0.01


def test_find_trading_day_after_not_enough_data():
    bars = [("2026-06-01", 10.0, 10.0)]
    out = find_trading_day_after(bars, date(2026, 6, 1), n=5)
    assert out is None


def test_calc_t_n_metrics():
    t0 = 10.0
    out = calc_t_n_metrics(t0_price=t0, t_n_price=11.0)
    assert abs(out - 10.0) < 0.01

    out2 = calc_t_n_metrics(t0_price=10.0, t_n_price=9.0)
    assert abs(out2 - (-10.0)) < 0.01

    out3 = calc_t_n_metrics(t0_price=0, t_n_price=10.0)
    assert out3 is None
