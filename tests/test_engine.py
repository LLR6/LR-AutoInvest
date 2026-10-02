import copy
import tempfile
import unittest
from pathlib import Path
from lr_autoinvest.engine import Config, load_csv, run, walk_forward
from lr_autoinvest.__main__ import generate


def bars(prices):
    return [{'date':f'2024-01-{i+1:02d}', 'assets': {'A': {'open':p, 'close':p}}} for i,p in enumerate(prices)]


class AccountingTests(unittest.TestCase):
    def test_known_fee_and_shares(self):
        r = run(bars([100, 100]), Config(max_weight=.5, cost_bps=100, initial_cash=1000), strategy='equal_weight')
        self.assertAlmostEqual(r['curve'][0]['holdings']['A'], 5)
        self.assertAlmostEqual(r['curve'][0]['cash'], 495)
        self.assertAlmostEqual(r['curve'][-1]['equity'], 995)
        self.assertAlmostEqual(r['cost_paid'], 5)

    def test_full_investment_cannot_borrow_fee(self):
        r = run(bars([100, 100]), Config(max_weight=1, cost_bps=100), strategy='equal_weight')
        self.assertGreaterEqual(r['curve'][0]['cash'], -1e-8)
        self.assertAlmostEqual(r['curve'][0]['equity'], 100000/1.01)

    def test_signal_executes_after_observation(self):
        r = run(bars([100,110,120,130,140]), Config(lookback=2, rebalance=1))
        self.assertEqual(r['ledger'][0]['date'], '2024-01-04')
        self.assertEqual(r['ledger'][0]['signal_date'], '2024-01-03')

    def test_future_changes_do_not_change_past(self):
        original = bars([100+i for i in range(20)])
        altered = copy.deepcopy(original)
        for b in altered[12:]:
            b['assets']['A'] = {'open': 1, 'close': 10000}
        c = Config(lookback=2, rebalance=2)
        a, b = run(original,c), run(altered,c)
        self.assertEqual(a['curve'][:12], b['curve'][:12])
        self.assertEqual([x for x in a['ledger'] if x['date']<'2024-01-13'],
                         [x for x in b['ledger'] if x['date']<'2024-01-13'])

    def test_open_gap_is_not_erased(self):
        r = run(bars([100,50]), Config(max_weight=.5, cost_bps=0), strategy='equal_weight')
        self.assertAlmostEqual(r['curve'][-1]['equity'], 75000)

    def test_halt_latches_and_sells_next_open(self):
        r = run(bars([100,50,50,200]), Config(max_weight=1,cost_bps=0,drawdown_stop=.1),strategy='equal_weight')
        self.assertTrue(r['curve'][2]['halted'])
        self.assertEqual(r['curve'][2]['holdings']['A'],0)
        self.assertEqual(r['curve'][-1]['equity'],50000)

    def test_cash_baseline(self):
        r = run(bars([100,50,200]),strategy='cash')
        self.assertEqual(r['metrics']['total_return'],0)
        self.assertEqual(r['ledger'],[])

    def test_bad_config(self):
        for c in (Config(cost_bps=-1),Config(max_weight=2),Config(initial_cash=float('nan'))):
            with self.assertRaises(ValueError):
                run(bars([100,100]),c)

    def test_csv_rejects_bad_data(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.csv'
            for body in ('2024-01-01,A,nan,100\n','2024-01-01,A,100,100\n2024-01-01,A,100,100\n',
                         '2024-01-01,A,100,100\n2024-01-02,B,100,100\n'):
                p.write_text('date,symbol,open,close\n'+body)
                with self.assertRaises(ValueError): load_csv(p)

    def test_fold_selection_does_not_see_test_period(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.csv'
            generate(p,n=300)
            a=load_csv(p)
            b=copy.deepcopy(a)
            for bar in b[180:]:
                for v in bar['assets'].values(): v['open']*=2; v['close']*=3
            f1,f2=walk_forward(a),walk_forward(b)
            self.assertEqual(f1[0]['chosen_lookback'],f2[0]['chosen_lookback'])
            self.assertEqual(f1[0]['train_sharpe'],f2[0]['train_sharpe'])

    def test_demo_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'a.csv',Path(d)/'b.csv'
            generate(a);generate(b)
            self.assertEqual(a.read_bytes(),b.read_bytes())


if __name__ == '__main__': unittest.main()
