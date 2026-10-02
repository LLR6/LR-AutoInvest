import csv
import math
import statistics
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Config:
    lookback: int = 40
    rebalance: int = 10
    max_weight: float = 0.6
    cost_bps: float = 10.0
    drawdown_stop: float = 0.15
    signal_delay: int = 0
    initial_cash: float = 100000.0
    lot_size: int = 0
    min_notional: float = 0.0
    min_fee: float = 0.0

    def validate(self):
        if any(not isinstance(x, int) or isinstance(x, bool) for x in (self.lookback, self.rebalance, self.signal_delay, self.lot_size)):
            raise ValueError('Window, frequency and delay must be integers')
        if self.lookback < 2 or self.rebalance < 1 or self.signal_delay < 0:
            raise ValueError('Invalid window or execution delay')
        if not 0 <= self.max_weight <= 1 or not 0 < self.drawdown_stop <= 1:
            raise ValueError('Invalid risk limits')
        if self.lot_size < 0 or self.min_notional < 0 or self.min_fee < 0:
            raise ValueError('Invalid execution constraints')
        if not 0 <= self.cost_bps < 10000 or not self.initial_cash > 0:
            raise ValueError('Invalid costs or capital')
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Non-finite configuration')


def load_csv(path):
    with Path(path).open(newline='', encoding='utf-8') as f:
        raw = list(csv.DictReader(f))
    if not raw:
        raise ValueError('Empty data')
    book = {}
    for r in raw:
        d, symbol = date.fromisoformat(r['date']).isoformat(), r['symbol'].strip()
        op, cl = float(r['open']), float(r['close'])
        if not symbol or not all(math.isfinite(x) and x > 0 for x in (op, cl)):
            raise ValueError('Invalid price or symbol')
        if symbol in book.setdefault(d, {}):
            raise ValueError('Duplicate date/symbol')
        book[d][symbol] = {'open': op, 'close': cl}
    days = sorted(book)
    symbols = sorted(book[days[0]])
    if any(sorted(book[d]) != symbols for d in days):
        raise ValueError('Unaligned universe: missing prices; no silent forward fill')
    return [{'date': d, 'assets': book[d]} for d in days]


def metrics(equity, initial):
    values = [initial] + equity
    returns = [b/a-1 for a, b in zip(values, values[1:])]
    peak, dd = initial, 0.0
    for v in equity:
        peak = max(peak, v)
        dd = max(dd, 1-v/peak)
    vol = statistics.stdev(returns) if len(returns) > 1 else 0.0
    return {'total_return': equity[-1]/initial-1 if equity else 0,
            'max_drawdown': dd, 'annualized_volatility': vol*math.sqrt(252),
            'sharpe_zero_rf': statistics.mean(returns)/vol*math.sqrt(252) if vol else 0.0}


def run(bars, config=Config(), start=0, end=None, strategy='momentum'):
    config.validate()
    end = len(bars) if end is None else end
    if not bars or not 0 <= start < end <= len(bars):
        raise ValueError('Invalid data interval')
    if strategy not in ('momentum', 'equal_weight', 'cash'):
        raise ValueError('Unknown strategy')
    symbols = sorted(bars[0]['assets'])
    cash = config.initial_cash
    units = {s: 0.0 for s in symbols}
    peak, prior_equity, halted = cash, cash, False
    ledger, curve, costs = [], [], 0.0
    fee = config.cost_bps/10000
    for t in range(start, end):
        bar = bars[t]
        opens = {s: bar['assets'][s]['open'] for s in symbols}
        equity_open = cash + sum(units[s]*opens[s] for s in symbols)
        if 1-prior_equity/peak >= config.drawdown_stop:
            halted = True
        last = t-1-config.signal_delay
        ready = last >= config.lookback
        scheduled = (t-start) % config.rebalance == 0
        targets, reason = None, 'hold'
        if halted:
            targets, reason = dict.fromkeys(symbols, 0.0), 'drawdown_halt_latched'
        elif strategy == 'cash':
            targets, reason = dict.fromkeys(symbols, 0.0), 'cash_baseline'
        elif scheduled and (ready or strategy == 'equal_weight'):
            targets = dict.fromkeys(symbols, 0.0)
            if strategy == 'equal_weight':
                targets = {s: min(config.max_weight, 1/len(symbols)) for s in symbols}
                reason = 'equal_weight'
            else:
                scores = {s: bars[last]['assets'][s]['close']/bars[last-config.lookback]['assets'][s]['close']-1 for s in symbols}
                winner = max(symbols, key=lambda s: (scores[s], s))
                if scores[winner] > 0:
                    targets[winner] = config.max_weight
                reason = 'positive_momentum' if scores[winner] > 0 else 'no_positive_momentum'
        if targets is not None:
            # Sell first, then buy. Cap requested buys to cash including fees.
            desired = {s: equity_open*targets[s]/opens[s] for s in symbols}
            for side in ('sell', 'buy'):
                for s in symbols:
                    delta = desired[s]-units[s]
                    qty = max(0.0, -delta if side == 'sell' else delta)
                    if side == 'buy':
                        qty = min(qty, max(0, cash)/(opens[s]*(1+fee)), max(0, cash-config.min_fee)/opens[s])
                    if config.lot_size:
                        qty = math.floor((qty+1e-10)/config.lot_size)*config.lot_size
                    if qty < 1e-9 or (qty*opens[s] < config.min_notional and not halted):
                        continue
                    notional = qty*opens[s]
                    charge = max(notional*fee, config.min_fee)
                    if side == 'sell' and cash+notional < charge:
                        continue
                    units[s] += qty if side == 'buy' else -qty
                    cash += (-notional if side == 'buy' else notional)-charge
                    costs += charge
                    ledger.append({'date': bar['date'], 'symbol': s, 'side': side,
                        'quantity': qty, 'price': opens[s], 'cost': charge, 'reason': reason,
                        'signal_date': bars[last]['date'] if last >= 0 else None})
        equity = cash + sum(units[s]*bar['assets'][s]['close'] for s in symbols)
        if cash < -1e-6 or any(x < -1e-9 for x in units.values()):
            raise RuntimeError('Accounting invariant violated')
        peak, prior_equity = max(peak, equity), equity
        curve.append({'date': bar['date'], 'equity': equity, 'cash': cash,
                      'holdings': dict(units), 'halted': halted})
    return {'config': asdict(config), 'strategy': strategy,
            'metrics': metrics([r['equity'] for r in curve], config.initial_cash),
            'cost_paid': costs, 'ledger': ledger, 'curve': curve}


def walk_forward(bars, train=180, test=60, windows=(20, 40, 80), cost_bps=10):
    if train <= max(windows)+1 or test < 1:
        raise ValueError('Training interval too short')
    folds = []
    for split in range(train, len(bars)-test+1, test):
        candidates = []
        for window in windows:
            config = Config(lookback=window, cost_bps=cost_bps)
            result = run(bars, config, split-train, split)
            candidates.append((result['metrics']['sharpe_zero_rf'], window))
        score, chosen = max(candidates, key=lambda x: (x[0], -x[1]))
        oos = run(bars, Config(lookback=chosen, cost_bps=cost_bps), split, split+test)
        folds.append({'train_start': bars[split-train]['date'], 'train_end': bars[split-1]['date'],
                      'test_start': bars[split]['date'], 'test_end': bars[split+test-1]['date'],
                      'chosen_lookback': chosen, 'train_sharpe': score,
                      'test_metrics': oos['metrics']})
    if not folds:
        raise ValueError('Not enough data for a full fold')
    return folds
