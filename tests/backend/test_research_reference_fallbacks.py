import json
import unittest
from datetime import date,timedelta
from unittest.mock import patch

import research_reference_fallbacks as fallback
import research_sector_references as references

AS_OF='2026-10-31T13:00:00+08:00'


def rate_row(day='2026-10-30',rate=1.289,**overrides):
    row={'REPORT_DATE':day+' 00:00:00','IR_RATE':rate,'CHANGE_RATE':0.7,
         'REPORT_PERIOD':'隔夜(O/N)','MARKET_CODE':'001','CURRENCY_CODE':'CNY',
         'INDICATOR_ID':'001'}
    row.update(overrides)
    return row


def payload(rows):
    return {'success':True,'code':0,'result':{'data':rows}}


def history(count=70,rate=1.3):
    end=date(2026,10,30)
    return [{'date':(end-timedelta(days=count-i-1)).isoformat(),'annual_rate_pct':rate}
            for i in range(count)]


class MoneyReferenceTests(unittest.TestCase):
    def test_identity_rejects_other_currency_tenor_or_market(self):
        for mismatch in ({'CURRENCY_CODE':'USD'},{'INDICATOR_ID':'002'},
                         {'REPORT_PERIOD':'一周(1W)'},{'MARKET_CODE':'002'}):
            with self.assertRaisesRegex(ValueError,'不一致'):
                fallback.parse_money_history(payload([rate_row(**mismatch)]),AS_OF)

    def test_bad_payload_is_never_an_empty_zero_rate(self):
        for data in ({'success':False,'code':0,'result':{'data':[]}},
                     {'success':True,'code':500,'result':{'data':[]}},payload([])):
            with self.assertRaises(ValueError):fallback.parse_money_history(data,AS_OF)

    def test_future_negative_invalid_and_duplicate_dates_are_filtered(self):
        rows=[rate_row(),rate_row('2026-11-01',2),rate_row('2026-10-29',-1),
              rate_row('2026-10-28',float('nan')),rate_row('2026-10-30',1.3)]
        got=fallback.parse_money_history(payload(rows),AS_OF)
        self.assertEqual(got,[{'date':'2026-10-30','annual_rate_pct':1.3}])

    def test_intraday_cutoff_retains_only_completed_day(self):
        got=fallback.parse_money_history(payload([rate_row(),rate_row('2026-10-29',1.282)]),
                                         '2026-10-30T09:10:00+08:00')
        self.assertEqual([r['date'] for r in got],['2026-10-29'])

    @patch('research_reference_fallbacks.fetch_text')
    def test_percent_and_basis_points_never_become_stock_returns(self,fetch):
        fetch.return_value=json.dumps(payload([rate_row(),rate_row('2026-10-29',1.282)]))
        quotes,sources,histories=fallback.collect_money_reference(AS_OF)
        quote=quotes[0]
        self.assertEqual(quote['last'],1.289)
        self.assertEqual(quote['change_bp'],0.7)
        self.assertIsNone(quote['change_pct'])
        self.assertEqual(quote['score_scope'],'money_liquidity')
        self.assertEqual(quote['value_unit'],'annual_rate_pct')
        self.assertTrue(all('close' not in r and 'return_pct' not in r
                            for r in histories[fallback.MONEY_HISTORY_ID]))
        self.assertTrue(all(s['as_of']=='2026-10-30' and s['status']=='partial' for s in sources))

    @patch('research_reference_fallbacks.fetch_text',side_effect=OSError('offline'))
    def test_source_failure_is_preserved(self,fetch):
        quotes,sources,histories=fallback.collect_money_reference(AS_OF)
        self.assertEqual((quotes,histories),([],{}))
        self.assertEqual(sources[0]['status'],'error')
        self.assertEqual(sources[0]['board_id'],'money')
        self.assertTrue(sources[0]['error'])

    def test_model_needs_recent_sufficient_history(self):
        self.assertIsNone(fallback.score_money_rate(history(60),AS_OF))
        self.assertIsNone(fallback.score_money_rate(history(70),'2026-11-30T16:00:00+08:00'))
        sparse=history(61)
        sparse[0]['date']='2025-01-01'
        self.assertIsNone(fallback.score_money_rate(sparse,AS_OF))

    def test_stable_rates_are_neutral_and_not_investment_returns(self):
        scored=fallback.score_money_rate(history(),AS_OF)
        self.assertEqual(scored['score'],50)
        self.assertEqual(scored['metrics']['rate_change_60d_bp'],0)
        self.assertEqual(scored['score_scope'],'money_liquidity')
        self.assertIn('不是股票回报',scored['method'])

    def test_lower_rates_raise_liquidity_score_with_explicit_bp(self):
        rows=history()
        for i,r in enumerate(rows):r['annual_rate_pct']=2-i*.001
        scored=fallback.score_money_rate(rows,AS_OF)
        self.assertEqual(scored['metrics']['rate_change_20d_bp'],-2)
        self.assertGreater(scored['score'],50)
        self.assertNotIn('return_20d',scored['metrics'])


class RemainingReferenceTests(unittest.TestCase):
    def test_exact_new_identities_do_not_use_adjacent_style_or_fund_data(self):
        expected={'style_cashflow':'932365','style_bluechip':'000903',
                  'style_dividend_low_volatility':'H30269','sector_finance':'932075',
                  'sector_transport':'000945','sector_home_appliances':'930697',
                  'sector_eldercare':'399812','sector_steel':'930606',
                  'sector_fintech':'930986','sector_travel':'930633',
                  'index_beijing':'899050','index_chinext':'399006','short_bond':'H11015'}
        for identity,code in expected.items():
            self.assertEqual(references.VERIFIED_REFERENCES[identity]['code'],code)
        self.assertNotIn('H11025',{r['code'] for r in references.VERIFIED_REFERENCES.values()})
        self.assertEqual(references.VERIFIED_REFERENCES['short_bond']['asset_type'],'bond')
        self.assertNotIn('style_microcap',references.VERIFIED_REFERENCES)
        self.assertNotIn('sector_auto_vehicle',references.VERIFIED_REFERENCES)

    @patch('research_sector_references._collect_one')
    def test_only_requested_failing_sources_are_collected(self,collect):
        collect.side_effect=ValueError('test source unavailable')
        quotes,sources,histories=references.collect_verified_references(AS_OF,board_ids=['short_bond'])
        self.assertEqual(collect.call_count,1)
        self.assertEqual({s['board_id'] for s in sources},{'short_bond'})


if __name__=='__main__':unittest.main()
