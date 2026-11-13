"""Fixed multi-day momentum strategy. Decisions execute at the next open.

Use completed Asset_A through Asset_F prices and an observation date. Asset_G
is never read and always receives zero. A scheduled all-cash session closes
actual holdings; five-session signal averaging is not treated as lot expiry.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

TRADED_ASSETS = tuple(f"Asset_{letter}" for letter in "ABCDEF")
ALL_ASSETS = TRADED_ASSETS + ("Asset_G",)
RISK_WINDOW = 63
SIGNAL_DAYS = 20
LONG_DAYS = 120
COVARIANCE_DAYS = 60
SMOOTH_DAYS = 5
COMPONENT_VOL_CEILING = 0.08
EXPOSURE_CYCLE_DAYS = 14


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as error:
            raise ValueError(f"Expected an ISO observation date, got {value!r}") from error


def _price(row: Any, field: str) -> float:
    if not hasattr(row, "get"):
        raise TypeError("Each asset row must have Open and Close prices")
    if field == "Close":
        value = row.get("Close", row.get("Close/Last", row.get("close")))
    else:
        value = row.get("Open", row.get("open"))
    if value is None:
        raise KeyError(f"Missing {field}")
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "")
    result = float(value)
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"Invalid {field}: {value!r}")
    return result


def _score(total: np.ndarray, volatility: np.ndarray, days: int) -> np.ndarray:
    score = np.divide(total, volatility * np.sqrt(days),
                      out=np.zeros_like(total), where=volatility > 1e-12)
    return np.clip(score, -3.0, 3.0)


def _neutralize(raw: np.ndarray, beta: np.ndarray) -> np.ndarray:
    constraints = np.vstack((np.ones_like(beta), beta))
    return raw - constraints.T @ np.linalg.pinv(constraints @ constraints.T) @ (constraints @ raw)


def _risk_scale(raw: np.ndarray, covariance: np.ndarray) -> np.ndarray:
    gross = float(np.abs(raw).sum())
    if gross <= 1e-12:
        return np.zeros(6)
    result = raw / gross
    annual_vol = np.sqrt(max(float(result @ covariance @ result), 0.0) * 252)
    if annual_vol > 0:
        result *= min(1.0, COMPONENT_VOL_CEILING / annual_vol)
    return result


class Strategy:
    """One instance per chronological evaluation. No fitted model or network IO."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._opens: list[np.ndarray] = []
        self._closes: list[np.ndarray] = []
        self._neutral: deque[np.ndarray] = deque(maxlen=SMOOTH_DAYS)
        self._long: deque[np.ndarray] = deque(maxlen=SMOOTH_DAYS)
        self._last_date: date | None = None
        self._cycle_start: date | None = None
        self.last_was_scheduled_cash = False

    @staticmethod
    def _tranches(opens: np.ndarray, closes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        empty = np.zeros(6)
        if len(closes) < RISK_WINDOW + 1:
            return empty, empty.copy()
        returns = closes[1:] / closes[:-1] - 1
        overnight = opens[1:] / closes[:-1] - 1
        market = returns.mean(axis=1)
        window = returns[-RISK_WINDOW:]
        market_window = market[-RISK_WINDOW:]
        centered = market_window - market_window.mean()
        denominator = float(centered @ centered)
        beta = np.ones(6)
        if denominator > 1e-14:
            beta = centered @ (window - window.mean(axis=0)) / denominator
        residual_vol = (window - market_window[:, None] * beta).std(axis=0, ddof=1)
        overnight_vol = overnight[-RISK_WINDOW:].std(axis=0, ddof=1)
        close_vol = window.std(axis=0, ddof=1)
        covariance = np.cov(returns[-COVARIANCE_DAYS:], rowvar=False, ddof=1)
        residual = returns[-SIGNAL_DAYS:] - market[-SIGNAL_DAYS:, None] * beta
        score = 0.5 * _score(residual.sum(axis=0), residual_vol, SIGNAL_DAYS)
        score += 0.5 * _score(overnight[-SIGNAL_DAYS:].sum(axis=0), overnight_vol, SIGNAL_DAYS)
        neutral = _risk_scale(_neutralize(score - np.median(score), beta), covariance)
        long_only = empty.copy()
        if len(closes) >= LONG_DAYS + 1:
            long_score = _score(returns[-LONG_DAYS:].sum(axis=0), close_vol, LONG_DAYS)
            leaders = np.argsort(long_score)[-2:]
            long_only[leaders] = np.maximum(long_score[leaders], 0.0)
            long_only = _risk_scale(long_only, covariance)
        return neutral, long_only

    def on_day_close(self, daily_data: Any,
                     portfolio_state: Mapping[str, Any] | None = None) -> dict[str, float]:
        """Return next-open weights, including scheduled all-zero liquidation targets.

        Date is required in asset rows, daily_data['Date'], or portfolio_state['date'].
        Optional portfolio_state['next_session_date'] is calendar information only.
        No current-day decision is ever executed at that day's open or close.
        """
        if portfolio_state is not None and not isinstance(portfolio_state, Mapping):
            raise TypeError("portfolio_state must be a mapping or None")
        state = portfolio_state if portfolio_state is not None else {}
        if isinstance(daily_data, Mapping):
            missing = [a for a in TRADED_ASSETS if a not in daily_data]
            if missing:
                raise KeyError(f"Missing required assets: {missing}")
            rows = [daily_data[a] for a in TRADED_ASSETS]
            root_date = daily_data.get("Date")
        elif hasattr(daily_data, "loc"):
            rows = [daily_data.loc[a] for a in TRADED_ASSETS]
            root_date = None
        else:
            raise TypeError("daily_data must contain Asset_A through Asset_F rows")

        dates = [v for v in (root_date, state.get("date")) if v is not None]
        dates.extend(row.get("Date") for row in rows if hasattr(row, "get") and row.get("Date") is not None)
        if not dates:
            raise ValueError("An observation Date is required for the calendar holding control")
        parsed = [_date(value) for value in dates]
        day = parsed[0]
        if any(other != day for other in parsed):
            raise ValueError("Observation dates do not agree")
        if self._last_date is not None and day <= self._last_date:
            raise ValueError("Feed each completed date once, in strictly increasing order")
        next_day = _date(state["next_session_date"]) if state.get("next_session_date") is not None else None
        if next_day is not None and next_day <= day:
            raise ValueError("next_session_date must be after the observation Date")

        # Validate all inputs before changing state.
        open_row = np.array([_price(row, "Open") for row in rows])
        close_row = np.array([_price(row, "Close") for row in rows])
        neutral, long_only = self._tranches(np.asarray([*self._opens, open_row]),
                                            np.asarray([*self._closes, close_row]))
        neutral_history = [*self._neutral, neutral][-SMOOTH_DAYS:]
        long_history = [*self._long, long_only][-SMOOTH_DAYS:]
        target = 0.5 * np.mean(neutral_history, axis=0) + 0.5 * np.mean(long_history, axis=0)
        if not np.isfinite(target).all():
            raise ArithmeticError("Non-finite target weights")
        gross = float(np.abs(target).sum())
        if gross > 1:
            target /= gross

        cycle_start = self._cycle_start
        scheduled_cash = False
        if cycle_start is not None:
            deadline = cycle_start + timedelta(days=EXPOSURE_CYCLE_DAYS)
            scheduled_cash = day >= deadline or (next_day is not None and next_day >= deadline)
        if scheduled_cash or np.abs(target).sum() <= 1e-12:
            target = np.zeros(6)
            cycle_start = None
        elif cycle_start is None:
            cycle_start = next_day if next_day is not None else day

        self._opens.append(open_row)
        self._closes.append(close_row)
        self._neutral.append(neutral)
        self._long.append(long_only)
        self._last_date = day
        self._cycle_start = cycle_start
        self.last_was_scheduled_cash = scheduled_cash
        result = dict(zip(TRADED_ASSETS, map(float, target)))
        result["Asset_G"] = 0.0
        return result


_DEFAULT_STRATEGY = Strategy()


def reset_strategy() -> None:
    _DEFAULT_STRATEGY.reset()


def on_day_close(daily_data: Any, portfolio_state: Mapping[str, Any] | None = None) -> dict[str, float]:
    return _DEFAULT_STRATEGY.on_day_close(daily_data, portfolio_state)
