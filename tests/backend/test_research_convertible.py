"""Offline identity, dedicated scoring and full-pipeline convertible checks."""
import copy
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import research_sectors as sectors
import research_sector_references as refs
from research_convertible_model import score_convertible
from research_trading_calendar import is_trading_day

NOW = '2026-10-31T05:00:00+08:00'
BOARD = {'id': 'convertible_bond', 'title': '可转债', 'group': 'defensive'}


def history(count=80):
    day, rows = date(2026, 10, 30), []
    while len(rows) < count:
        if is_trading_day(day):
            rows.append({'date': day.isoformat(), 'close': 100 + (count-len(rows)) * .1, 'return_pct': .1})
        day -= timedelta(days=1)
    return list(reversed(rows))


def quote():
    return {'board_id': 'convertible_bond', 'sector_id': 'convertible_bond', 'code': '000832',
            'name': '中证转债', 'last': 443.12, 'change_pct': -2.1, 'as_of': '2026-10-30',
            'data_frequency': 'daily', 'as_of_precision': 'date', 'asset_type': 'convertible_bond',
            'return_type': 'publisher_index', 'history_secid': 'official:csindex:000832',
            'source_id': 'sector_reference:convertible_bond', 'scope_note': '沪深上市可转换债券；编制方案细节未核实'}


class ConvertibleResearchTests(unittest.TestCase):
    def test_reference_identity_and_unknown_coupon_details_are_explicit(self):
        ref = refs.VERIFIED_REFERENCES['convertible_bond']
        self.assertEqual((ref['code'], ref['title'], ref['asset_type']),
                         ('000832', '中证可转换债券指数', 'convertible_bond'))
        self.assertIn('编制方案PDF未取得', ref['scope_note'])
        payload = {'code': '200', 'data': [{'indexCode': '000832', 'indexNameCnAll': ref['title'],
            'tradeDate': '20261030', 'close': 443.12, 'changePct': -2.1}]}
        self.assertEqual(refs.parse_csindex_history(payload, ref, NOW)[0]['close'], 443.12)
        payload['data'][0]['indexCode'] = 'H11001'
        with self.assertRaises(ValueError):
            refs.parse_csindex_history(payload, ref, NOW)

    def test_model_is_reproducible_and_stock_pressure_caps_are_dedicated(self):
        metrics = {'sample_count': 80, 'return_5d': 2, 'return_20d': 5, 'return_60d': 8,
                   'ma20_gap': 1, 'annual_volatility': 10, 'max_drawdown': -2}
        result = score_convertible(metrics, 1, {'mode': 'risk_on'})
        self.assertEqual(result['raw_score'], 69)
        self.assertEqual(result['score'], 69)
        for mode, ceiling in [('defensive', 49), ('cautious', 64), ('unknown', 49)]:
            self.assertEqual(score_convertible(metrics, 1, {'mode': mode})['score'], ceiling)
        for bad in ({**metrics, 'sample_count': 60}, {**metrics, 'return_60d': None},
                    {**metrics, 'max_drawdown': float('nan')}):
            self.assertIsNone(score_convertible(bad, 1, {'mode': 'risk_on'}))
        self.assertIsNone(score_convertible(metrics, True, {'mode': 'risk_on'}))

    def test_convertible_never_uses_ordinary_bond_model_and_unknown_credit_is_not_invented(self):
        with patch.object(sectors, 'score_bond', side_effect=AssertionError('ordinary government-bond model')):
            row = sectors.analyze_sector(BOARD, quote(), history(), [], [], NOW, {'mode': 'defensive'})
        self.assertEqual(row['score_model'], 'convertible_trend_v1')
        self.assertLessEqual(row['recommendation_index'], 49)
        self.assertIsNone(row['asset_research']['conversion_premium'])
        self.assertIsNone(row['asset_research']['yield_to_maturity'])
        self.assertEqual(row['asset_research']['credit_data_status'], 'unavailable')
        self.assertIn('信用、转股估值及强赎回售条款尚未核验', row['summary'])
        missing = sectors.analyze_sector(BOARD, quote(), history(60), [], [], NOW, {'mode': 'risk_on'})
        self.assertIsNone(missing['recommendation_index'])

    def test_pipeline_counts_valid_convertible_reference_separately_without_stock_financials(self):
        source = {'id': 'sector_reference:convertible_bond', 'status': 'ok', 'as_of': '2026-10-30'}
        with patch.object(sectors, 'sector_catalog', return_value=[BOARD]), \
             patch.object(sectors, 'now_iso', return_value=NOW), \
             patch.object(sectors, 'collect_sector_market', return_value={'market': [], 'news': [], 'sources': [], 'warnings': []}), \
             patch.object(sectors, 'collect_sector_quotes', return_value=([], [])), \
             patch.object(sectors, 'collect_verified_references', return_value=([quote()], [source], {'official:csindex:000832': history()})), \
             patch.object(sectors, 'collect_macro_risk', return_value=({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'})), \
             patch.object(sectors, 'fetch_text', return_value=''), \
             patch.object(sectors, 'collect_sector_histories', return_value=({}, [])), \
             patch('research_tushare.gather_sector_company_evidence', return_value={'sector_leaders': {}, 'sources': [], 'warnings': []}), \
             patch('research_leader_index.collect_leader_histories'):
            report = sectors.run_sector_research()
        row = report['sector_analysis'][0]
        self.assertEqual(row['score_model'], 'convertible_trend_v1')
        self.assertTrue(all(r['status'] == 'ok' for r in row['requirements']))
        self.assertEqual(row['leaders'], [])
        self.assertEqual(report['coverage']['convertible_bond_scored_count'], 1)
        self.assertEqual(report['coverage']['bond_scored_count'], 0)
        self.assertEqual(report['coverage']['financial_sector_count'], 0)
        self.assertEqual(report['coverage']['fully_ready_sector_count'], 1)
        self.assertIn('信用、转股估值及条款未接入', row['requirements'][0]['note'])


if __name__ == '__main__':
    unittest.main()
