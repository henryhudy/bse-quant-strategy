# BSE final submission

Start with `strategy.py`. This is the original fixed-rule hybrid with numerical safeguards and scheduled cash sessions. It does not include the later rank-and-trend variant, machine learning, or increased exposure. Asset G is excluded.

## Run

Use Python 3.10 or newer. Open a terminal in the repository root (or extract the submission ZIP into one folder), and run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v test_strategy.py
python run_on_csv.py --data-dir /path/to/Fellows_Data --output allocations.csv
```

On Windows, activate with `.venv\Scripts\activate` instead. NumPy is the only dependency.

The data folder must contain `Asset_A.csv` through `Asset_F.csv`, with matching dates. Required columns are `Date` in YYYY-MM-DD format, `Open`, and `Close` or `Close/Last`. Currency symbols and commas in prices are accepted. Input data are not included.

The output contains `Decision_Date` and seven asset weights. Each row applies at the following session's open, never at the decision day's open. Positive weights are long, negative weights short, and zero means no holding. A weight of 0.10 means 10% of portfolio equity.

## Evaluator interface

```python
from strategy import on_day_close, reset_strategy

reset_strategy()  # Once before replaying development history.
weights = on_day_close(daily_data, portfolio_state)
```

`daily_data` is a dictionary keyed by `Asset_A` through `Asset_F`, with `Open`, `Close` and `Date` in each asset row. Alternatively, supply the common date as `daily_data['Date']` or `portfolio_state['date']`. The date is required for the holding control. Rows may use `Close/Last`. A dataframe indexed by asset also works without requiring pandas in this package.

Keep the same process or `Strategy()` instance across calls. Feed each completed day exactly once in increasing date order. Replay the development history before hidden scoring, then continue the same instance. The evaluator starts the scored portfolio in cash; it must not reset the strategy's warmed-up history at that point.

Execute the returned target at the next open, carrying holdings between sessions and charging costs on actual trades. **An all-zero target means liquidate every position and remain in cash for that session. Do not ignore it or reopen positions during that session.** The strategy can return nonzero targets again after the next completed observation.

The first 63 observations produce zero weights. The long-only component needs 121 observations. Invalid prices, missing assets, inconsistent dates and duplicate dates raise clear errors. Asset G is never inspected. Current equity and previous weights in `portfolio_state` are not needed. If supplied, `next_session_date` is used only to bring a scheduled closure forward when its execution would reach the calendar deadline; the included CSV runner and reported backtest do not supply this optional hint.

## Reproduce the development results

```sh
python backtest.py --data-dir /path/to/Fellows_Data --start 2017-01-01 --end 2023-10-06 --fee-bps 5 --output-dir results
```

This writes `daily.csv`, `annual.csv` and `summary.json`. Use `--fee-bps 20` for the cost stress or `--annual-borrow-rate 0.01` for the illustrative 1% short-borrow charge. This is a local simulator, not the official evaluator.

`STRATEGY.md` contains the explanation, exact-version results and limitations. `development_results.csv` and `annual_results.csv` contain the numerical summaries. Nothing in the runtime downloads data, reads hidden files, or loads a trained model.
