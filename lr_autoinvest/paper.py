"""Persistent end-of-day paper account; no broker connection."""
import argparse
import hashlib
import html
import json
import math
import os
import tempfile
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path
from .engine import Config, load_csv, run
from . import __version__


class PaperError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def connect(path):
    if not Path(path).is_file():
        raise PaperError('Account missing. Run paper init first.')
    db=sqlite3.connect(path, timeout=20)
    db.execute('PRAGMA busy_timeout=20000')
    return db


def append(db, body):
    last=db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
    prev=last[0] if last else '0'*64
    payload=canonical(body)
    hashed=hashlib.sha256((prev+payload).encode()).hexdigest()
    db.execute('INSERT INTO events(payload,prev,hash) VALUES(?,?,?)',(payload,prev,hashed))


def verify(db):
    prev='0'*64
    events=[]
    for payload,p,h in db.execute('SELECT payload,prev,hash FROM events ORDER BY seq'):
        if p!=prev or hashlib.sha256((p+payload).encode()).hexdigest()!=h:
            raise PaperError('Audit chain mismatch. No account update allowed.')
        events.append(json.loads(payload));prev=h
    if not events or events[0]['type']!='init': raise PaperError('Missing initialization evidence')
    settings=json.loads(db.execute('SELECT payload FROM settings').fetchone()[0])
    if settings!=events[0]['settings']: raise PaperError('Account configuration changed')
    history=[json.loads(x[0]) for x in db.execute('SELECT payload FROM history ORDER BY date')]
    syncs=[e for e in events if e['type']=='sync']
    if history and (not syncs or digest(history)!=syncs[-1]['data_hash']):
        raise PaperError('Stored market history differs from audit evidence')
    if not history and syncs: raise PaperError('Missing stored market history')
    return settings,events,history


def initialize(path, settings):
    Config(**settings['config']).validate()
    date.fromisoformat(settings['start'])
    if settings['max_age']<0 or not math.isfinite(settings['max_jump']) or not 0<settings['max_jump']<=10:
        raise PaperError('Invalid data quality limits')
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation refuses accidental account overwrite.
    with path.open('xb'): pass
    db=sqlite3.connect(path)
    try:
        with db:
            db.execute('CREATE TABLE settings(payload TEXT NOT NULL)')
            db.execute('CREATE TABLE history(date TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL,prev TEXT NOT NULL,hash TEXT NOT NULL)')
            db.execute('INSERT INTO settings VALUES(?)',(canonical(settings),))
            append(db,{'type':'init','settings':settings})
    finally: db.close()
    return {'status':'initialized','db':str(path),'mode':'offline-paper'}


def doctor(bars, as_of, max_age=4, max_jump=.35):
    if not isinstance(max_age,int) or max_age<0 or not math.isfinite(max_jump) or not 0<max_jump<=10:
        raise PaperError('Invalid data quality limits')
    cutoff=date.fromisoformat(as_of)
    selected=[b for b in bars if date.fromisoformat(b['date'])<=cutoff]
    if not selected: raise PaperError('No completed daily bars on/before as-of')
    age=(cutoff-date.fromisoformat(selected[-1]['date'])).days
    if age>max_age: raise PaperError(f'Stale data: latest bar is {age} calendar days old; limit {max_age}')
    for a,b in zip(selected,selected[1:]):
        for s in a['assets']:
            previous=a['assets'][s]['close']
            jumps=[abs(b['assets'][s]['open']/previous-1),abs(b['assets'][s]['close']/previous-1)]
            if max(jumps)>max_jump:
                raise PaperError(f'Price jump requires review: {b["date"]} {s}; check corporate actions and adjustment basis')
    return selected,{'status':'passed','latest':selected[-1]['date'],'age_calendar_days':age,
                     'excluded_future_days':len(bars)-len(selected),'data_hash':digest(selected)}


def sync(path,csv_path,as_of):
    bars=load_csv(csv_path)
    db=connect(path)
    try:
        db.execute('BEGIN IMMEDIATE')
        settings,events,history=verify(db)
        if settings['engine_version']!=__version__: raise PaperError('Engine version changed; use a new account to compare')
        selected,health=doctor(bars,as_of,settings['max_age'],settings['max_jump'])
        if len(selected)<len(history) or selected[:len(history)]!=history:
            raise PaperError('Historical revision or missing prefix: old prices cannot silently rewrite this account. Create a new comparison account.')
        if selected==history:
            db.rollback()
            return {'status':'unchanged','new_orders':0,'new_days':0,'health':health}
        indices=[i for i,b in enumerate(selected) if b['date']>=settings['start']]
        if not indices: raise PaperError('No bars on/after account start')
        if selected[indices[0]]['date']!=settings['start']:
            raise PaperError('Account start must be an actual input trading date')
        config=Config(**settings['config'])
        result=run(selected,config,start=indices[0],strategy=settings['strategy'])
        old_date=history[-1]['date'] if history else ''
        new_curve=[v for v in result['curve'] if v['date']>old_date]
        new_orders=[v for v in result['ledger'] if v['date']>old_date]
        for b in selected[len(history):]:
            db.execute('INSERT INTO history VALUES(?,?)',(b['date'],canonical(b)))
        body={'type':'sync','as_of':as_of,'data_hash':health['data_hash'],'health':health,
              'new_curve':new_curve,'new_orders':new_orders,'cost_paid_total':result['cost_paid'],
              'metrics':result['metrics']}
        append(db,body)
        db.commit()
        return {'status':'updated','new_days':len(new_curve),'new_orders':len(new_orders),
                'last_date':selected[-1]['date'],'equity':result['curve'][-1]['equity'],'health':health}
    except Exception:
        db.rollback();raise
    finally: db.close()


def view(path):
    db=connect(path)
    try:
        # A read transaction sees a consistent account even during another process's sync.
        db.execute('BEGIN')
        settings,events,history=verify(db)
        curve=[v for e in events if e['type']=='sync' for v in e['new_curve']]
        orders=[v for e in events if e['type']=='sync' for v in e['new_orders']]
        syncs=[e for e in events if e['type']=='sync']
        return {'mode':'offline-paper','audit':'verified','settings':settings,'history':history,
                'curve':curve,'orders':orders,'event_count':len(events),
                'cost_paid':syncs[-1]['cost_paid_total'] if syncs else 0,
                'metrics':syncs[-1]['metrics'] if syncs else None}
    finally: db.close()


def plan(path,as_of):
    account=view(path)
    c=Config(**account['settings']['config'])
    bars,health=doctor(account['history'],as_of,account['settings']['max_age'],account['settings']['max_jump'])
    if not account['curve']: raise PaperError('Sync prices before generating a plan')
    if len(bars)!=len(account['history']): raise PaperError('Cannot plan in the past from a newer account')
    latest=account['curve'][-1]
    last=len(bars)-1-c.signal_delay
    indices=[i for i,b in enumerate(bars) if b['date']>=account['settings']['start']]
    next_t=len(bars)
    targets=dict.fromkeys(latest['holdings'],0.0)
    scores={}
    peak=max([c.initial_cash]+[v['equity'] for v in account['curve']])
    halt=latest['halted'] or 1-latest['equity']/peak>=c.drawdown_stop
    strategy=account['settings']['strategy']
    scheduled=(next_t-indices[0])%c.rebalance==0
    reason='保持现有持仓：下一输入交易日未到调仓周期'
    if halt: reason='回撤停止：下一开盘尝试清仓，停止状态锁定'
    elif strategy=='cash': reason='现金基线'
    elif not scheduled:
        targets={s:latest['holdings'][s]*bars[-1]['assets'][s]['close']/latest['equity'] for s in targets}
    elif strategy=='equal_weight':
        targets={s:min(c.max_weight,1/len(targets)) for s in targets};reason='等权再平衡'
    elif last<c.lookback: reason='历史不足：保持现金等待完整窗口'
    else:
        scores={s:bars[last]['assets'][s]['close']/bars[last-c.lookback]['assets'][s]['close']-1 for s in targets}
        winner=max(targets,key=lambda s:(scores[s],s))
        if scores[winner]>0: targets[winner]=c.max_weight
        reason='正动量排名选择，现金保留剩余比例' if scores[winner]>0 else '所有资产动量非正：转为现金'
    estimates=[]
    for s,w in targets.items():
        ref=bars[-1]['assets'][s]['close']
        qty=abs(latest['equity']*w/ref-latest['holdings'][s])
        if c.lot_size: qty=math.floor((qty+1e-10)/c.lot_size)*c.lot_size
        side='buy' if latest['equity']*w/ref>latest['holdings'][s] else 'sell'
        notional=qty*ref
        if qty>1e-8 and (notional>=c.min_notional or halt):
            estimates.append({'symbol':s,'side':side,'estimated_quantity':qty,'reference_close':ref,
                              'estimated_cost':max(notional*c.cost_bps/10000,c.min_fee)})
    estimates.sort(key=lambda o: (o['side']!='sell',o['symbol']))
    return {'mode':'proposal-only','as_of':as_of,'signal_date':bars[last]['date'] if last>=0 else None,
            'health':health,'reason':reason,'momentum_scores':scores,'target_weights':targets,
            'estimated_orders':estimates,'account_equity':latest['equity'],
            'notice':'仅模拟调仓草案。数量基于最近收盘，不是成交承诺；下一开盘重新估值、检查现金、取整和计费。无实际下单。'}


def export(path,output,as_of):
    account=view(path)
    proposal=plan(path,as_of)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    public={k:v for k,v in account.items() if k!='history'}
    (output/'account.json').write_text(json.dumps(public,ensure_ascii=False,indent=2)+'\n')
    (output/'plan.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n')
    rows=''.join(f'<tr><td>{html.escape(o["date"])}</td><td>{html.escape(o["symbol"])}</td><td>{o["side"]}</td><td>{o["quantity"]:.4f}</td><td>{o["cost"]:.2f}</td></tr>' for o in account['orders'][-30:])
    latest=account['curve'][-1]
    label='合成数据演示' if all(s.startswith('SYN_') for s in latest['holdings']) else '导入行情：来源由使用者确认'
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>LR-AutoInvest 每日工作台</title><style>body{{font-family:system-ui;max-width:1050px;margin:30px auto;padding:20px;color:#172033;background:#f4f7fb}}section{{background:white;padding:24px;border-radius:16px;margin:18px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.good{{color:#13734c}}</style><h1>LR-AutoInvest 每日工作台</h1><p>{label} · 离线模拟账户 · 最近行情 {latest['date']} · 查看日 {html.escape(as_of)}</p><section><h2>账户状态</h2><p class="good">审计链校验通过 · {account['event_count']} 个事件 · {len(account['orders'])} 笔模拟交易</p><h3>权益 {latest['equity']:,.2f} / 现金 {latest['cash']:,.2f}</h3><p>累计成本 {account['cost_paid']:,.2f} · 停止锁定 {latest['halted']}</p><pre>{html.escape(json.dumps(latest['holdings'],ensure_ascii=False,indent=2))}</pre></section><section><h2>下一输入交易日的调仓草案</h2><p>{html.escape(proposal['reason'])}</p><p>{html.escape(proposal['notice'])}</p><pre>{html.escape(json.dumps(proposal['estimated_orders'],ensure_ascii=False,indent=2))}</pre><h3>动量证据与目标权重</h3><pre>{html.escape(json.dumps({'scores':proposal['momentum_scores'],'weights':proposal['target_weights']},ensure_ascii=False,indent=2))}</pre></section><section><h2>最近 30 笔模拟交易</h2><table><tr><th>日期</th><th>资产</th><th>方向</th><th>份额</th><th>成本</th></tr>{rows}</table></section><section><h2>运行约定</h2><p>仅使用已完成日线；CSV 的复权口径和日期由导入者确认。账户记账不能证明行情真实。历史修订、过期行情和大幅跳变会阻止更新。哈希链可检测常见意外修改，不能抵抗能重写整个数据库的攻击者。</p><pre>{html.escape(json.dumps(account['settings'],ensure_ascii=False,indent=2))}</pre></section></html>'''
    (output/'dashboard.html').write_text(page,encoding='utf-8')
    return {'status':'exported','dashboard':str(output/'dashboard.html'),'audit':'verified'}


def normalize(source, output, symbol=None, overwrite=False):
    aliases={'date':('date','日期','交易日期'), 'symbol':('symbol','代码','证券代码'),
             'open':('open','开盘','开盘价'), 'close':('close','收盘','收盘价')}
    import csv
    with Path(source).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        headers={h.strip().lower():h for h in reader.fieldnames or []}
        columns={k:next((headers[a] for a in names if a in headers),None) for k,names in aliases.items()}
        if not all(columns[k] for k in ('date','open','close')):
            raise PaperError('Expected 日期/开盘/收盘 or date/open/close columns')
        if not symbol and not columns['symbol']:raise PaperError('Single-asset export needs --symbol')
        rows=[]
        for r in reader:
            d=r[columns['date']].strip().replace('/','-')
            date.fromisoformat(d)
            rows.append({'date':d,'symbol':symbol or r[columns['symbol']].strip(),
                         'open':r[columns['open']].strip(),'close':r[columns['close']].strip()})
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() and not overwrite:raise PaperError('Output exists; choose another path or use --overwrite')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',newline='',encoding='utf-8',dir=output.parent,delete=False) as f:
            temporary=Path(f.name)
            writer=csv.DictWriter(f,fieldnames=['date','symbol','open','close'])
            writer.writeheader();writer.writerows(rows)
        bars=load_csv(temporary)
        if overwrite:os.replace(temporary,output)
        else:
            # Exclusive output creation also refuses a concurrent overwrite.
            with output.open('xb') as f:f.write(temporary.read_bytes())
        return {'status':'normalized','output':str(output),'days':len(bars),'assets':sorted(bars[0]['assets'])}
    finally:
        if temporary and temporary.exists():temporary.unlink()


def demonstration(output):
    from .__main__ import generate
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    source=output/'synthetic.csv';generate(source,n=300)
    bars=load_csv(source);dbpath=output/'paper.db'
    settings={'config':asdict(Config(lookback=20,lot_size=100,min_fee=5,min_notional=1000)),
        'start':bars[100]['date'],'strategy':'momentum','max_age':4,'max_jump':.35,'engine_version':__version__}
    if not dbpath.exists():initialize(dbpath,settings)
    evidence={'dataset':'synthetic fixed-seed example, not live prices',
        'first_sync':sync(dbpath,source,bars[139]['date']),
        'repeat_sync':sync(dbpath,source,bars[139]['date']),
        'plan':plan(dbpath,bars[139]['date']),
        'dashboard':export(dbpath,output,bars[139]['date'])}
    stale_error=None
    try:sync(dbpath,source,'2030-01-01')
    except PaperError as exc:stale_error=str(exc)
    evidence['stale_import_blocked']=stale_error
    (output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    return {'status':'demonstrated','repeat':evidence['repeat_sync']['status'],
        'stale_import_blocked':bool(stale_error),'dashboard':str(output/'dashboard.html')}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    demo=sub.add_parser('demo');demo.add_argument('--output',type=Path,default=Path('reports/paper-demo'))
    imp=sub.add_parser('import');imp.add_argument('csv',type=Path);imp.add_argument('--symbol');imp.add_argument('--output',type=Path,required=True);imp.add_argument('--overwrite',action='store_true')
    init=sub.add_parser('init');init.add_argument('--db',type=Path,required=True);init.add_argument('--start',required=True)
    init.add_argument('--cash',type=float,default=100000);init.add_argument('--lookback',type=int,default=40)
    init.add_argument('--rebalance',type=int,default=10);init.add_argument('--weight',type=float,default=.6)
    init.add_argument('--cost-bps',type=float,default=10);init.add_argument('--min-fee',type=float,default=0)
    init.add_argument('--lot-size',type=int,default=0);init.add_argument('--min-notional',type=float,default=0)
    init.add_argument('--drawdown-stop',type=float,default=.15)
    init.add_argument('--strategy',choices=['momentum','equal_weight','cash'],default='momentum')
    init.add_argument('--max-age',type=int,default=4);init.add_argument('--max-jump',type=float,default=.35)
    for action in ('sync','plan','dashboard','audit','status','doctor'):
        cmd=sub.add_parser(action)
        if action!='doctor':cmd.add_argument('--db',type=Path,required=True)
        if action in ('sync','doctor'):cmd.add_argument('csv',type=Path)
        if action in ('sync','plan','dashboard','doctor'):cmd.add_argument('--as-of',default=date.today().isoformat())
        if action=='doctor':cmd.add_argument('--max-age',type=int,default=4);cmd.add_argument('--max-jump',type=float,default=.35)
        if action=='dashboard':cmd.add_argument('--output',type=Path,default=Path('reports/daily'))
    args=parser.parse_args(argv)
    try:
        if args.action=='demo':result=demonstration(args.output)
        elif args.action=='import':result=normalize(args.csv,args.output,args.symbol,args.overwrite)
        elif args.action=='init':
            config=Config(lookback=args.lookback,rebalance=args.rebalance,max_weight=args.weight,
                cost_bps=args.cost_bps,drawdown_stop=args.drawdown_stop,initial_cash=args.cash,
                lot_size=args.lot_size,min_fee=args.min_fee,min_notional=args.min_notional)
            result=initialize(args.db,{'config':asdict(config),'start':args.start,'strategy':args.strategy,
                'max_age':args.max_age,'max_jump':args.max_jump,'engine_version':__version__})
        elif args.action=='sync':result=sync(args.db,args.csv,args.as_of)
        elif args.action=='plan':result=plan(args.db,args.as_of)
        elif args.action=='dashboard':result=export(args.db,args.output,args.as_of)
        elif args.action=='doctor':result=doctor(load_csv(args.csv),args.as_of,args.max_age,args.max_jump)[1]
        else:
            account=view(args.db)
            result={'audit':account['audit'],'events':account['event_count'],'orders':len(account['orders']),
                    'last_state':account['curve'][-1] if account['curve'] else None,'metrics':account['metrics']}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,sqlite3.Error,KeyError) as exc:
        print(json.dumps({'status':'blocked','reason':str(exc)},ensure_ascii=False))
        raise SystemExit(2)


if __name__=='__main__':main()
