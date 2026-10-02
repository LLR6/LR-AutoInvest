# Daily paper-account workflow

[中文](DAILY_WORKFLOW.md) · English · Author: LLR6

Try `python -m lr_autoinvest paper demo` and open `reports/paper-demo/dashboard.html`. The example uses seeded synthetic prices and an explicit historical as-of date. Repeating it does not duplicate orders.

## Import and check completed daily bars

```bash
python -m lr_autoinvest paper import exported.csv --symbol YOUR_SYMBOL --output local/prices.csv
python -m lr_autoinvest paper doctor local/prices.csv
```

The normalized format is `date,symbol,open,close`. The importer accepts the English fields and common Chinese equivalents for date, security code, open and close, with ISO or `YYYY/MM/DD` dates. Input must be UTF-8 (BOM accepted). It does not guess GBK encoding or arbitrary vendor formats. Leading zeroes in symbols are preserved. All assets must have aligned dates.

Supply licensed data with consistent price adjustments and completed daily bars. The tool has no live-data downloader and cannot infer whether an intraday bar was mislabeled as complete.

## Initialize once

```bash
python -m lr_autoinvest paper init --db local/my-paper.db --start 2024-01-02 --cash 100000 --lookback 40 --rebalance 10 --weight 0.6 --lot-size 100 --min-fee 5 --min-notional 1000 --cost-bps 10
```

Replace the start date with an actual input date having enough prior history. Lot size 100 and fee 5 are parameter examples, not exchange or broker rules. Lot size 0 allows fractional holdings. Use a single currency. Account configuration is frozen; parameter comparisons require separate databases. Existing databases cannot be overwritten.

## Update each day

```bash
python -m lr_autoinvest paper sync local/prices.csv --db local/my-paper.db
python -m lr_autoinvest paper plan --db local/my-paper.db
python -m lr_autoinvest paper dashboard --db local/my-paper.db --output reports/my-daily
```

Keep the full previously imported history in the input, not just the latest day. `sync` replays newly completed input days into a continuous simulated account; it does not place market orders. Repeated identical data returns `unchanged`. SQLite transactions serialize concurrent writers.

`plan` does not modify the account. It estimates next-input-day quantities from the latest close and reports momentum evidence, target weights, costs and reasons. The subsequent simulated open recalculates quantities from opening equity and applies cash and lot constraints. A plan is not a guaranteed fill.

Open the static `dashboard.html` offline, or read `account.json` and `plan.json` from your own scripts.

## Verify the account

```bash
python -m lr_autoinvest paper status --db local/my-paper.db
python -m lr_autoinvest paper audit --db local/my-paper.db
```

History revisions, stale prices, missing assets, non-finite/non-positive prices and suspicious jumps block updates. The default freshness allowance is four calendar days relative to the computer's local date. Holidays require an explicit appropriate as-of date or a configured allowance; no exchange calendar is built in. The default jump gate is 35% relative to the previous close; verify adjustments and genuine large moves before using a separate account with a different explicit threshold.

Hash-linked events and input summaries detect common accidental modification; they are not an externally immutable ledger. An attacker able to rewrite the full database and chain can defeat this check.

## Modeling limits

Daily, long-only, fixed-universe simulation with simplified opening fills. No settlement, limits, suspensions, volume, dividends, taxes or pending-order queues. Fees use the larger of proportional cost and minimum fee, not their sum. Tiny sells unable to cover fees may leave residual holdings. Drawdown stops can overshoot on gaps. Full-history replay is not a high-frequency incremental engine.
