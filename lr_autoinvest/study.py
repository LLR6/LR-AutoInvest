"""Paired cost sensitivity on synthetic paths; not evidence of market alpha."""
import argparse
import json
import statistics
import tempfile
from pathlib import Path
from .__main__ import generate
from .engine import Config, load_csv, run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seeds',type=int,default=20)
    p.add_argument('--output',type=Path,default=Path('examples/study.json'))
    a=p.parse_args()
    if not 2 <= a.seeds <= 1000: p.error('seeds must be between 2 and 1000')
    rows=[]
    with tempfile.TemporaryDirectory() as d:
        for seed in range(a.seeds):
            source=Path(d)/'synthetic.csv'
            generate(source,seed=seed)
            bars=load_csv(source)
            row={'seed':seed}
            for cost in (0,10,50):
                row[str(cost)]=run(bars,Config(cost_bps=cost))['metrics']
            rows.append(row)
    summary={}
    for cost in (0,10,50):
        returns=[r[str(cost)]['total_return'] for r in rows]
        summary[str(cost)]={'median_return':statistics.median(returns),
            'min_return':min(returns),'max_return':max(returns),
            'negative_paths':sum(x<0 for x in returns),
            'median_drawdown':statistics.median(r[str(cost)]['max_drawdown'] for r in rows)}
    result={'notice':'Synthetic paired experiment; no profitability inference for real markets.',
            'seeds':a.seeds,'summary_by_cost_bps':summary,'raw':rows,
            'median_paired_return_change_50_minus_10':statistics.median(r['50']['total_return']-r['10']['total_return'] for r in rows)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='raw'},indent=2))


if __name__=='__main__': main()
