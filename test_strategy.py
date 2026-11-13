"""Deterministic safety tests. Run: python -m unittest -v test_strategy.py"""

import copy
from datetime import date, timedelta
import unittest

import numpy as np

from backtest import simulate
from strategy import ALL_ASSETS, TRADED_ASSETS, Strategy, on_day_close, reset_strategy


def fixture(count=200):
    rng = np.random.default_rng(231)
    prices = np.full(6, 100.0)
    days, rows = [], []
    day = date(2020, 1, 2)
    while len(days) < count:
        if day.weekday() < 5:
            open_ = prices * np.exp(rng.normal(0.0002, 0.004, 6))
            prices = open_ * np.exp(rng.normal(0.0003, 0.008, 6))
            rows.append({a: {"Date": day.isoformat(), "Open": o, "Close": c}
                         for a, o, c in zip(TRADED_ASSETS, open_, prices)})
            days.append(day)
        day += timedelta(days=1)
    return days, rows


class StrategyTests(unittest.TestCase):
    def test_replay_and_reset(self):
        _, rows = fixture()
        a, b = Strategy(), Strategy()
        first = [a.on_day_close(row) for row in rows]
        self.assertEqual(first, [b.on_day_close(row) for row in rows])
        a.reset()
        self.assertEqual(first, [a.on_day_close(row) for row in rows])
        reset_strategy()
        self.assertEqual(first, [on_day_close(row) for row in rows])

    def test_prefix_and_output_limits(self):
        _, rows = fixture()
        full, prefix = Strategy(), Strategy()
        full_weights = [full.on_day_close(row) for row in rows]
        self.assertEqual(full_weights[:150], [prefix.on_day_close(row) for row in rows[:150]])
        for weights in full_weights:
            self.assertEqual(set(weights), set(ALL_ASSETS))
            self.assertEqual(weights["Asset_G"], 0.0)
            self.assertTrue(all(np.isfinite(w) for w in weights.values()))
            self.assertLessEqual(sum(abs(w) for w in weights.values()), 1 + 1e-12)

    def test_constant_data_is_safe(self):
        days, _ = fixture()
        s = Strategy()
        for day in days:
            row = {a: {"Date": day, "Open": 100, "Close": 100} for a in TRADED_ASSETS}
            self.assertTrue(all(w == 0 for w in s.on_day_close(row).values()))

    def test_g_never_read(self):
        _, rows = fixture()
        a, b = Strategy(), Strategy()
        for row in rows:
            extra = {**row, "Asset_G": object()}
            self.assertEqual(a.on_day_close(row), b.on_day_close(extra))

    def test_invalid_input_does_not_advance_state(self):
        _, rows = fixture()
        a, b = Strategy(), Strategy()
        for row in rows[:100]:
            a.on_day_close(row)
            b.on_day_close(row)
        for invalid in (0, -1, float("nan"), float("inf")):
            bad = copy.deepcopy(rows[100])
            bad["Asset_F"]["Close"] = invalid
            with self.assertRaises(ValueError):
                a.on_day_close(bad)
        self.assertEqual(a.on_day_close(rows[100]), b.on_day_close(rows[100]))

    def test_date_checks(self):
        days, rows = fixture(3)
        s = Strategy()
        no_dates = {a: {"Open": 100, "Close": 100} for a in TRADED_ASSETS}
        with self.assertRaises(ValueError):
            s.on_day_close(no_dates)
        s.on_day_close(no_dates, {"date": days[0]})
        with self.assertRaises(ValueError):
            s.on_day_close(rows[0])
        with self.assertRaises(ValueError):
            s.on_day_close(rows[1], {"date": days[2]})
        with self.assertRaises(ValueError):
            s.on_day_close(rows[1], {"next_session_date": days[0]})
        s.on_day_close(rows[1])

    def test_missing_asset_and_currency_strings(self):
        _, rows = fixture(1)
        bad = copy.deepcopy(rows[0])
        del bad["Asset_B"]
        with self.assertRaises(KeyError):
            Strategy().on_day_close(bad)
        row = {a: {"Date": "2020-01-02", "Open": "$1,000", "Close/Last": "$1,005"} for a in TRADED_ASSETS}
        self.assertTrue(all(w == 0 for w in Strategy().on_day_close(row).values()))

    def test_scheduled_cash_and_holding_age(self):
        days, rows = fixture()
        strategy = Strategy()
        targets, scheduled = [], 0
        for row in rows:
            target = strategy.on_day_close(row)
            targets.append([target[a] for a in TRADED_ASSETS])
            if strategy.last_was_scheduled_cash:
                scheduled += 1
                self.assertTrue(all(w == 0 for w in target.values()))
        self.assertGreater(scheduled, 5)
        opens = np.array([[row[a]["Open"] for a in TRADED_ASSETS] for row in rows])
        closes = np.array([[row[a]["Close"] for a in TRADED_ASSETS] for row in rows])
        records = simulate(days, opens, closes, np.array(targets))
        self.assertLessEqual(max(r["position_age_bound_days"] for r in records), 18)

    def test_calendar_hint_closes_at_deadline(self):
        days, rows = fixture()
        s = Strategy()
        for i, row in enumerate(rows):
            result = s.on_day_close(row)
            if s._cycle_start is not None:
                next_day = s._cycle_start + timedelta(days=14)
                result = s.on_day_close(rows[i + 1], {"next_session_date": next_day})
                self.assertTrue(s.last_was_scheduled_cash)
                self.assertTrue(all(w == 0 for w in result.values()))
                break
        else:
            self.fail("No nonzero cycle generated")

    def test_fee_and_execution_timing(self):
        days, _ = fixture(5)
        prices = np.full((5, 6), 100.0)
        target = np.zeros((5, 6))
        target[:, 0] = 1
        result = simulate(days, prices, prices, target)
        self.assertAlmostEqual(result[-1]["equity"], (1 - .0005) / (1 + .0005), places=12)
        open_, close = prices.copy(), prices.copy()
        close[2:, 0] = 200
        open_[3:, 0] = 200
        target[:2] = 0
        result = simulate(days, open_, close, target, fee_bps=0)
        np.testing.assert_allclose([r["equity"] for r in result], 1)


if __name__ == "__main__":
    unittest.main()
