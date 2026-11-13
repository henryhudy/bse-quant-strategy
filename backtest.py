"""Local next-open backtest of strategy.py, not the official scoring engine."""

from __future__ import annotations

import argparse
import calendar
import csv
import json
from datetime import date
from pathlib import Path

import numpy as np

from run_on_csv import read_history
from strategy import TRADED_ASSETS, Strategy, _price


def month_after(day: date) -> date:
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def simulate(dates, opens, closes, targets, fee_bps=5.0, annual_borrow_rate=0.0,
             start=None, end=None):
    if not np.isfinite(fee_bps) or not 0 <= fee_bps <= 100:
        raise ValueError("fee_bps must be between 0 and 100")
    if not np.isfinite(annual_borrow_rate) or not 0 <= annual_borrow_rate <= 1:
        raise ValueError("annual_borrow_rate must be between 0 and 1")
    for array in (opens, closes, targets):
        if np.asarray(array).shape != (len(dates), 6) or not np.isfinite(array).all():
            raise ValueError("Expected finite N-by-6 price and weight arrays")
    if (opens <= 0).any() or (closes <= 0).any():
        raise ValueError("Prices must be positive")
    if (np.abs(targets).sum(axis=1) > 1 + 1e-12).any():
        raise ValueError("Target gross exceeds 100%")
    if any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError("Dates must be strictly increasing")

    fee = fee_bps / 10000
    equity, cash = 1.0, 1.0
    held = np.zeros(6)
    first_held = [None] * 6
    records = []
    for i in range(1, len(dates)):
        day = dates[i]
        if (start is not None and day < start) or (end is not None and day > end):
            continue
        prior_equity = equity
        held_open = held * opens[i] / closes[i - 1]
        equity_open = cash + held_open.sum()
        target = targets[i - 1]
        equity_after_cost = equity_open
        for _ in range(12):
            equity_after_cost = equity_open - fee * np.abs(target * equity_after_cost - held_open).sum()
        holdings = target * equity_after_cost
        turnover_notional = float(np.abs(holdings - held_open).sum())
        cost = fee * turnover_notional
        if abs(equity_open - cost - equity_after_cost) > 1e-10:
            raise ArithmeticError("Transaction-cost reconciliation failed")
        age_bound = 0
        for j in range(6):
            if first_held[j] is not None:
                age_bound = max(age_bound, (day - first_held[j]).days)
                if day > month_after(first_held[j]):
                    raise ArithmeticError("A continuous position exceeded one calendar month")
            if abs(holdings[j]) < 1e-14:
                first_held[j] = None
            elif first_held[j] is None or np.sign(holdings[j]) != np.sign(held_open[j]):
                first_held[j] = day
        cash = equity_after_cost - float(holdings.sum())
        held = holdings * closes[i] / opens[i]
        borrow = annual_borrow_rate / 252 * 0.5 * (
            np.maximum(-holdings, 0).sum() + np.maximum(-held, 0).sum())
        cash -= borrow
        equity = cash + float(held.sum())
        if not np.isfinite(equity) or equity <= 0:
            raise ArithmeticError("Equity became invalid or nonpositive")
        records.append({"Date": day.isoformat(), "return": equity / prior_equity - 1,
                        "equity": equity, "gross": float(np.abs(target).sum()),
                        "turnover": turnover_notional / equity_open, "cost": cost / equity_open,
                        "borrow_cost": float(borrow / equity_open),
                        "position_age_bound_days": age_bound,
                        "cash_session": int(np.abs(target).sum() <= 1e-12)})
    if not records:
        raise ValueError("No trading sessions in the requested period")
    liquidation_notional = float(np.abs(held).sum())
    records[-1]["turnover"] += liquidation_notional / equity
    records[-1]["cost"] += fee * liquidation_notional / equity
    equity -= fee * liquidation_notional
    records[-1]["equity"] = equity
    records[-1]["return"] = equity / (records[-2]["equity"] if len(records) > 1 else 1.0) - 1
    np.testing.assert_allclose(np.cumprod([1 + r["return"] for r in records]),
                               [r["equity"] for r in records], rtol=1e-11, atol=1e-12)
    return records


def metrics(records):
    returns = np.array([r["return"] for r in records])
    equity = np.cumprod(1 + returns)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    vol = returns.std(ddof=1) if len(returns) > 1 else 0.0
    return {"first_date": records[0]["Date"], "last_date": records[-1]["Date"],
            "trading_days": len(records), "total_return": float(equity[-1] - 1),
            "cagr": float(equity[-1] ** (252 / len(records)) - 1),
            "sharpe_zero_cash_rate": float(returns.mean() / vol * np.sqrt(252)) if vol > 0 else None,
            "annual_volatility": float(vol * np.sqrt(252)),
            "maximum_drawdown": float((equity / peaks - 1).min()),
            "annual_turnover": float(np.mean([r["turnover"] for r in records]) * 252),
            "maximum_position_age_bound_days": max(r["position_age_bound_days"] for r in records),
            "cash_sessions": sum(r["cash_session"] for r in records)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--annual-borrow-rate", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    history = read_history(args.data_dir)
    dates, opens, closes, targets = [], [], [], []
    strategy = Strategy()
    for day, rows in history:
        dates.append(day)
        opens.append([_price(rows[a], "Open") for a in TRADED_ASSETS])
        closes.append([_price(rows[a], "Close") for a in TRADED_ASSETS])
        target = strategy.on_day_close(rows)
        targets.append([target[a] for a in TRADED_ASSETS])
    records = simulate(dates, np.array(opens), np.array(closes), np.array(targets),
                       args.fee_bps, args.annual_borrow_rate, args.start, args.end)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "daily.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    summary = {"fee_bps": args.fee_bps, "annual_borrow_rate": args.annual_borrow_rate,
               "cash_interest_rate": 0.0, **metrics(records)}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    years = sorted({r["Date"][:4] for r in records})
    annual = [{"year": y, **metrics([r for r in records if r["Date"].startswith(y)])} for y in years]
    with (args.output_dir / "annual.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(annual[0]))
        writer.writeheader()
        writer.writerows(annual)
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
