import argparse
import csv
import hashlib
import html
import json
import math
import random
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from .engine import Config, load_csv, run, walk_forward


def generate(path, seed=42, n=600):
    rng = random.Random(seed)
    prices = {'SYN_A': 100.0, 'SYN_B': 100.0, 'SYN_C': 100.0}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'symbol', 'open', 'close'])
        d, i = date(2022, 1, 3), 0
        while i < n:
            if d.weekday() < 5:
                common = rng.gauss(0, .004)
                for j, s in enumerate(prices):
                    regime = (i//100+j)%3
                    drift = (.001, -.0012, .0001)[regime]
                    op = prices[s]*math.exp(rng.gauss(0, .002))
                    shock = -.07 if i == 350 else 0
                    cl = op*math.exp(drift+common+rng.gauss(0, .007)+shock)
                    writer.writerow([d.isoformat(), s, f'{op:.8f}', f'{cl:.8f}'])
                    prices[s] = cl
                i += 1
            d += timedelta(days=1)


def report(bars, output, source):
    output.mkdir(parents=True, exist_ok=True)
    base = Config()
    runs = {'momentum': run(bars, base),
            'equal_weight': run(bars, base, strategy='equal_weight'),
            'cash': run(bars, base, strategy='cash'),
            'cost_50bps': run(bars, replace(base, cost_bps=50)),
            'signal_delay_1': run(bars, replace(base, signal_delay=1))}
    payload = {'data_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'data_source': str(source), 'bars': len(bars),
               'notice': 'Offline paper execution. Demo SYN_* assets are synthetic. No evidence of market profitability.',
               'runs': runs, 'walk_forward': walk_forward(bars)}
    (output/'report.json').write_text(json.dumps(payload, indent=2)+'\n')
    with (output/'orders.csv').open('w', newline='') as f:
        keys = ['date','symbol','side','quantity','price','cost','reason','signal_date']
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(runs['momentum']['ledger'])
    rows = ''
    for name, r in runs.items():
        m = r['metrics']
        rows += f'<tr><td>{name}</td><td>{m["total_return"]:.2%}</td><td>{m["max_drawdown"]:.2%}</td><td>{m["sharpe_zero_rf"]:.2f}</td><td>{r["cost_paid"]:.2f}</td></tr>'
    values = [v['equity'] for r in runs.values() for v in r['curve']]
    lo, hi = min(values), max(values)
    lines = ''
    colors = ['#2563eb','#16a34a','#64748b','#ea580c','#a855f7']
    for (name, r), color in zip(runs.items(), colors):
        pts = ' '.join(f'{30+i/(len(bars)-1)*900:.1f},{300-(v["equity"]-lo)/(hi-lo or 1)*250:.1f}' for i,v in enumerate(r['curve']))
        lines += f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/><text x="{30+colors.index(color)*180}" y="335" fill="{color}">{name}</text>'
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>LR-AutoInvest 实验报告</title><style>body{{font-family:system-ui;max-width:1050px;margin:40px auto;padding:20px;color:#172033;background:#f6f8fc}}section{{background:white;padding:24px;border-radius:16px;margin:20px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}svg{{width:100%}}</style><h1>LR-AutoInvest / 实验回执</h1><p>模拟执行 · 输入 {html.escape(str(source))} · {len(bars)} 个交易日</p><section><strong>{html.escape(payload['notice'])}</strong><p>曲线为模拟资产净值，不是实盘收益。现金利息、税费、流动性、停牌、涨跌停与公司行动未建模。</p></section><section><h2>净值对照（共用纵轴）</h2><p>范围 {lo:.0f} — {hi:.0f}；横轴为输入交易日顺序。</p><svg viewBox="0 0 970 355" role="img" aria-label="五种模拟净值对照">{lines}</svg></section><section><table><tr><th>实验</th><th>累计收益</th><th>最大回撤</th><th>Sharpe / 零无风险利率</th><th>成本</th></tr>{rows}</table></section><section><h2>滚动样本外验证</h2><p>180 日训练，60 日测试；候选窗口 20 / 40 / 80；只用训练段选择参数。各折现金重置，禁止把折收益当作连续实盘净值。</p><pre>{html.escape(json.dumps(payload['walk_forward'], ensure_ascii=False, indent=2))}</pre></section><small>数据 SHA-256: {payload['data_sha256']}</small></html>'''
    (output/'report.html').write_text(page, encoding='utf-8')
    print(json.dumps({k:v['metrics'] for k,v in runs.items()}, indent=2))
    print('Saved:', output/'report.html')


def main():
    parser = argparse.ArgumentParser(description='LR-AutoInvest offline paper research')
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo')
    demo.add_argument('--output', type=Path, default=Path('examples/demo-report'))
    demo.add_argument('--seed', type=int, default=42)
    back = sub.add_parser('backtest')
    back.add_argument('csv', type=Path)
    back.add_argument('--output', type=Path, default=Path('reports/custom'))
    args = parser.parse_args()
    if args.command == 'demo':
        source = args.output/'synthetic.csv'
        generate(source, args.seed)
    else:
        source = args.csv
    report(load_csv(source), args.output, source)


if __name__ == '__main__':
    main()
