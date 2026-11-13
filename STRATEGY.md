# Strategy and development results

## Approach

The hypothesis is that recent relative strength and longer-term positive trends may persist. The strategy trades Asset A through Asset F and assigns zero to Asset G.

Half the allocation uses a long-short component. It estimates each asset's beta to the equal-weight six-asset basket over 63 completed sessions. It combines 20-session beta-adjusted momentum and overnight momentum, standardizes both by recent volatility, clips scores to [-3, 3], and removes estimated market exposure and net exposure from that component.

The other half buys up to two assets with the strongest positive 120-session momentum, standardized by recent volatility. The full portfolio is not market neutral because this component is long-only.

Each component uses a 60-session covariance estimate to reduce exposure when forecast annual volatility exceeds 8%. It never scales a component above 100% gross. The final portfolio averages five daily signals, combines the components equally, and caps total absolute target weights at 100%.

## Holding control

A complete cash session is scheduled after an exposure cycle has lasted 14 calendar days of decision history. The zero target closes all actual positions at the following open. Re-entry is possible only after a later decision. This is a conservative holding rule, not a return-optimized parameter. Five-session averaging alone is not treated as proof that actual lots expire.

The longest continuous position-age bound in the supplied-data replay was 17 calendar days. The evaluator must honor zero targets and next-open execution. Exceptional market closures, suspended assets, or a different final interface require explicit evaluator handling; the program cannot force a fill when trading is unavailable.

## Reducing further overfitting

The final version retains the earlier hybrid and drops the later ranking replacement, short/long trend-agreement filter, machine-learning models, allocation searches and exposure boosts. No per-asset constants are fitted. The rules and holding convention were fixed before this final replay and were not changed to improve its results.

This does not undo prior selection bias. Earlier research tested many alternatives on these same observations. The original hybrid was itself assembled after inspecting component results. There is no untouched competition-data validation set left in this research.

## Exact-version development results

Data: 1,746 aligned A-F observations from October 28, 2016 through October 6, 2023. Scoring below covers 1,702 sessions from January 3, 2017 through October 6, 2023, including initial warm-up cash sessions. Signals use completed closes and execute at the next open. Cash and marked holdings are tracked, changed notional pays costs, and final liquidation is charged. Returns compound; annualization uses 252 sessions. Sharpe is relative to zero cash yield.

| One-way trading cost | Annual short-borrow assumption | Total return | Annualized return | Sharpe | Maximum drawdown |
|---|---|---:|---:|---:|---:|
| 5 bps | 0% | +73.41% | 8.49% | 1.36 | 7.41% |
| 5 bps | 1% | +72.11% | 8.37% | 1.34 | 7.48% |
| 20 bps | 0% | +30.40% | 4.01% | 0.67 | 10.90% |

These figures belong to this exact final version, including scheduled cash sessions. The earlier 1.82 Sharpe belonged to a different research variant and is not this submission's result.

Calendar returns at 5 bps with zero borrow were 2017: +9.34%, 2018: -0.28%, 2019: +13.65%, 2020: +19.90%, 2021: +10.43%, 2022: +1.33%, and available 2023: +4.29%. Annual results are diagnostics, not independent holdouts. More detailed values are included in the two results CSVs.

## Validation and limitations

The package includes tests for deterministic replay, reset, prefix invariance, zero-volatility prices, input validation, exclusion of G, gross caps, scheduled closures, cost accounting and next-open timing. On the supplied data, non-cash decisions reproduce the earlier signal implementation within numerical precision.

Separate public-data transfer tests of the original and later hybrid variants were weak. They do not validate this final calendar-wrapper version or prove a general trading edge. No external prices or model artifacts are required or included in this submission.

The six-asset universe is small. Relationships, volatility and borrowing costs can change. The simulator does not separately model dividends, financing, cash interest, taxes or market impact beyond the stated trading-cost assumption. Its default zero borrow cost is an assumption, not a verified multi-day competition rule. Scheduled closures add turnover and may reduce returns. Gross limits apply to rebalance targets, not continuously to prices drifting between executions. Positive development results do not establish hidden-period or future profitability.
