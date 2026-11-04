import copy
import unittest

import research_overseas as r
from test_research_overseas import OverseasPriceTests


class OverseasExpansionTests(unittest.TestCase):
    def test_new_financially_complete_companies_expand_without_bad_optional_member(self):
        now,rows=OverseasPriceTests().samples(('AAPL.US','MSFT.US','NVDA.US','AMZN.US','GOOG.US'))
        rows[3]['financials']={'ann_date':'2026-08-01','end_date':'2026-06-30','tr_yoy':10}
        rows[4]['financials']={}
        original=copy.deepcopy(rows)
        built=r.build_overseas_indicator({'id':'overseas_us_equity','title':'美股'},rows,now)
        self.assertTrue(built['meta']['ready'])
        self.assertEqual(built['meta']['sample_count'],4)
        self.assertIn('GOOG.US',[row['code']for row in built['meta']['excluded']])
        self.assertEqual(original,rows)

    def test_declared_cny_facts_do_not_mix_convenience_translation(self):
        def row(value):return {'start':'2025-01-01','end':'2025-12-31','filed':'2026-04-01','val':value}
        facts={'cik':1549802,'facts':{'us-gaap':{'Revenues':{'units':{'CNY':[row(100)],'USD':[row(14)]}},
            'ProfitLoss':{'units':{'CNY':[row(10)],'USD':[row(1.4)]}}}}}
        financial=r.parse_sec_financials(facts,'2026-10-31T13:15:00+08:00')
        self.assertEqual(financial['currency'],'CNY')
        self.assertEqual(financial['revenue'],100)

    def test_undeclared_multiple_currencies_remain_unknown(self):
        def row(value):return {'start':'2025-01-01','end':'2025-12-31','filed':'2026-04-01','val':value}
        facts={'cik':9999,'facts':{'ifrs-full':{'Revenue':{'units':{'EUR':[row(100)],'USD':[row(110)]}}}}}
        self.assertEqual(r.parse_sec_financials(facts,'2026-10-31T13:15:00+08:00'),{})

    def test_ifrs_revenue_and_reported_eur_survive_cache_compaction(self):
        def row(value):return {'start':'2025-01-01','end':'2025-12-31','filed':'2026-04-01','val':value}
        facts={'cik':9999,'facts':{'ifrs-full':{'Revenue':{'units':{'EUR':[row(100)]}},'ProfitLoss':{'units':{'EUR':[row(10)]}}}}}
        compact=r.compact_sec_facts(facts)
        self.assertEqual(r.parse_sec_financials(compact,'2026-10-31T13:15:00+08:00')['currency'],'EUR')


if __name__=='__main__':unittest.main()
