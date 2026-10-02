# LR-AutoInvest

[中文](README.md) · English

Import daily prices, keep a continuous paper account, and inspect explainable rebalance proposals.

**CSV import → data checks → SQLite paper account → next-day plan → offline dashboard**

Python 3.10+ · MIT · Author: LLR6 · No third-party runtime dependencies.

This is a runnable research prototype with a transparent long-only momentum strategy. It has no brokerage integration. Published examples use seeded synthetic prices, not evidence of market profitability.

## Try the daily workflow

```bash
git clone https://github.com/LLR6/LR-AutoInvest.git
cd LR-AutoInvest
python -m lr_autoinvest paper demo
```

Open `reports/paper-demo/dashboard.html`. Run the command again: the persistent account reports `unchanged` without duplicate orders. The demo also records a blocked stale-data update. See the [actual demonstration receipt](examples/paper-demo/evidence.json) and [daily workflow](docs/DAILY_WORKFLOW_EN.md).

| Practical problem | Implemented behavior |
| --- | --- |
| Every run starts from cash | Persistent SQLite account and append-only events |
| Retries or concurrent updates duplicate orders | Transactional writes and identical-input idempotency |
| Revised prices silently rewrite results | Previously imported history must match; revisions block updates |
| Old prices still produce plans | Explicit as-of date and freshness checks |
| Small trades ignore costs | Configurable lot size, minimum fee and minimum notional |
| Rebalance decisions are opaque | Momentum scores, target weights, signal dates and reasons |
| Results stay in the terminal | Offline HTML dashboard and account/plan JSON |

26 tests cover accounting, concurrent idempotency, revision and stale-data rejection, future-data isolation and execution timing.

## Research experiments

```bash
python -m lr_autoinvest demo
python -m lr_autoinvest.study
python -m unittest discover -s tests -v
```

The engine observes closes through the previous trading day and simulates execution at the next open. It sells before buying, includes transaction costs, forbids borrowing and shorting, and latches a drawdown stop. Walk-forward experiments use 180 training days and 60 test days, selecting 20/40/80-day lookbacks only in training. Each test fold resets to cash, so these folds are not a continuous portfolio.

Across 20 seeded synthetic paths of 600 trading days, median cumulative returns were 5.41%, 3.86% and -3.64% at 0, 10 and 50 bps per side. These are reproducible model outputs illustrating cost sensitivity, not expected investment returns. [Raw results](examples/study.json) · [Research notes and references](docs/RESEARCH.md).

## Bring your own historical prices

```csv
date,symbol,open,close
2024-01-02,ASSET_A,100.0,101.2
2024-01-02,ASSET_B,80.0,79.9
2024-01-03,ASSET_A,101.3,102.0
2024-01-03,ASSET_B,80.0,80.4
```

```bash
python -m lr_autoinvest backtest your_prices.csv --output reports/my-run
```

All assets must have aligned dates and positive finite prices. At least 240 trading days are required for a default walk-forward fold. Use consistent adjustment conventions for opens and closes, retain source/licensing information, and use completed daily bars. Data is user-supplied; the tool does not download live prices.

## Scope and limitations

Daily bars, long-only holdings, cash, a fixed asset universe and simplified opening fills. There is no modeling of exchange calendars, settlement rules, price limits, suspensions, volume, dividends, taxes, currency conversion or unfilled order queues. A drawdown threshold is a trigger, not a loss guarantee: opening gaps can exceed it. Plan quantities use the latest close and may differ from subsequent simulated fills.

Fees are `max(notional × proportional cost, minimum fee)` per trade. Audit hashes detect common accidental modifications but cannot prevent someone with write access from rewriting the database and its entire hash chain. Full-history replay currently grows with imported history.

Optional CLI installation: `python -m pip install -e .`.
