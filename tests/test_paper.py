import copy
import csv
import json
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from lr_autoinvest import __version__
from lr_autoinvest.engine import Config, load_csv, run
from lr_autoinvest.__main__ import generate
from lr_autoinvest.paper import initialize, sync, view, plan, export, normalize, PaperError


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'prices.csv';generate(self.source,n=300)
        self.bars=load_csv(self.source);self.db=self.root/'account.db'
        self.settings={'config':asdict(Config(lookback=20,lot_size=100,min_fee=5,min_notional=1000)),
            'start':self.bars[100]['date'],'strategy':'momentum','max_age':4,'max_jump':.35,'engine_version':__version__}
        initialize(self.db,self.settings)

    def tearDown(self):self.tmp.cleanup()

    def test_restart_and_duplicate_import(self):
        first=sync(self.db,self.source,self.bars[150]['date'])
        a=view(self.db)
        second=sync(self.db,self.source,self.bars[150]['date'])
        b=view(self.db)
        self.assertEqual(second['status'],'unchanged')
        self.assertEqual(first['new_days'],51)
        self.assertEqual(a,b)

    def test_incremental_import_equals_one_shot(self):
        sync(self.db,self.source,self.bars[150]['date'])
        sync(self.db,self.source,self.bars[200]['date'])
        a=view(self.db)
        other=self.root/'other.db';initialize(other,self.settings)
        sync(other,self.source,self.bars[200]['date']);b=view(other)
        self.assertEqual(a['curve'],b['curve']);self.assertEqual(a['orders'],b['orders'])

    def test_revision_is_rejected_atomically(self):
        sync(self.db,self.source,self.bars[150]['date']);before=view(self.db)
        with self.source.open() as f:rows=list(csv.DictReader(f))
        rows[0]['close']=str(float(rows[0]['close'])*1.001)
        with self.source.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['date','symbol','open','close']);writer.writeheader();writer.writerows(rows)
        with self.assertRaises(PaperError):sync(self.db,self.source,self.bars[200]['date'])
        self.assertEqual(before,view(self.db))

    def test_stale_data_does_not_update(self):
        before=view(self.db)
        with self.assertRaises(PaperError):sync(self.db,self.source,'2030-01-01')
        self.assertEqual(before,view(self.db))

    def test_large_jump_blocks_update(self):
        with self.source.open() as f:rows=list(csv.DictReader(f))
        rows[450]['open']=str(float(rows[450]['open'])*2)
        with self.source.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['date','symbol','open','close']);writer.writeheader();writer.writerows(rows)
        with self.assertRaises(PaperError):sync(self.db,self.source,self.bars[200]['date'])
        self.assertEqual(view(self.db)['event_count'],1)

    def test_audit_detects_event_tampering(self):
        sync(self.db,self.source,self.bars[150]['date'])
        with sqlite3.connect(self.db) as db:db.execute("UPDATE events SET payload='{}' WHERE seq=2")
        with self.assertRaises(PaperError):view(self.db)

    def test_audit_detects_history_tampering(self):
        sync(self.db,self.source,self.bars[150]['date'])
        with sqlite3.connect(self.db) as db:
            row=db.execute('SELECT date,payload FROM history LIMIT 1').fetchone()
            payload=json.loads(row[1]);payload['assets']['SYN_A']['close']+=1
            db.execute('UPDATE history SET payload=? WHERE date=?',(json.dumps(payload),row[0]))
        with self.assertRaises(PaperError):view(self.db)

    def test_plan_matches_next_open_direction_and_is_read_only(self):
        # Next index 140 is a scheduled rebalance, after an account start at 100.
        sync(self.db,self.source,self.bars[139]['date']);before=view(self.db)
        proposal=plan(self.db,self.bars[139]['date']);after=view(self.db)
        self.assertEqual(before,after)
        self.assertTrue(proposal['estimated_orders'])
        next_result=run(self.bars,Config(**self.settings['config']),start=100,end=141)
        next_orders=[o for o in next_result['ledger'] if o['date']==self.bars[140]['date']]
        self.assertEqual([(o['symbol'],o['side']) for o in proposal['estimated_orders']],[(o['symbol'],o['side']) for o in next_orders])
        self.assertEqual(proposal['signal_date'],self.bars[139]['date'])

    def test_stale_plan_blocked(self):
        sync(self.db,self.source,self.bars[-1]['date'])
        with self.assertRaises(PaperError):plan(self.db,'2030-01-01')

    def test_no_account_overwrite(self):
        with self.assertRaises(FileExistsError):initialize(self.db,self.settings)

    def test_execution_lots_and_minimum_fees(self):
        sync(self.db,self.source,self.bars[200]['date'])
        account=view(self.db)
        self.assertTrue(account['orders'])
        for order in account['orders']:
            self.assertAlmostEqual(order['quantity']%100,0,places=7)
            self.assertGreaterEqual(order['cost'],5)
        for state in account['curve']:self.assertGreaterEqual(state['cash'],-1e-6)

    def test_chinese_export_import_preserves_symbol(self):
        source=self.root/'export.csv';source.write_text('日期,开盘,收盘\n2024/01/02,100,101\n2024/01/03,102,103\n',encoding='utf-8-sig')
        output=self.root/'normalized.csv'
        result=normalize(source,output,symbol='001234')
        self.assertEqual(result['assets'],['001234'])
        self.assertEqual(load_csv(output)[0]['date'],'2024-01-02')
        with self.assertRaises(PaperError):normalize(source,output,symbol='001234')

    def test_invalid_import_does_not_leave_output(self):
        source=self.root/'bad.csv';source.write_text('date,open,close\n2024-01-02,nan,101\n')
        output=self.root/'bad-out.csv'
        with self.assertRaises(ValueError):normalize(source,output,symbol='A')
        self.assertFalse(output.exists())

    def test_concurrent_sync_does_not_duplicate(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:sync(self.db,self.source,self.bars[150]['date']),range(2)))
        self.assertEqual(sorted(r['status'] for r in results),['unchanged','updated'])
        self.assertEqual(view(self.db)['event_count'],2)

    def test_dashboard_export(self):
        sync(self.db,self.source,self.bars[200]['date'])
        out=self.root/'export';export(self.db,out,self.bars[200]['date'])
        self.assertIn('每日工作台',(out/'dashboard.html').read_text())
        self.assertEqual(json.loads((out/'account.json').read_text())['audit'],'verified')


if __name__=='__main__':unittest.main()
