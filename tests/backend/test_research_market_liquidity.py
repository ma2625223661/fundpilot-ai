"""Checks for the standalone market liquidity presentation."""
import copy
import unittest

from research_market_liquidity import build_market_liquidity


def report(score=53, status='ok'):
    return {
        'strategy': {'risk_overview': {'liquidity': 47,
                                       'source_ids': ['sector_reference:money', 'macro:nbs_pmi']}},
        'sector_analysis': [{
            'id': 'money', 'status': status, 'score_scope': 'money_liquidity',
            'recommendation_index': score, 'as_of': '2026-10-30',
            'trend': '资金趋宽',
            'score_method': '资金利率模型',
            'quote': {'as_of': '2026-10-30'},
            'metrics': {'sample_count': 121, 'annual_rate_pct': 1.289,
                        'rate_change_1d_bp': .7, 'rate_change_5d_bp': 1.8,
                        'rate_change_20d_bp': -7.2, 'rate_change_60d_bp': -12.4,
                        'rate_std_20d_bp': 3.288461},
            'sources': [{'id': 'sector_reference:money', 'name': 'Shibor'}],
        }],
    }


class MarketLiquidityTests(unittest.TestCase):
    def test_exposes_health_score_and_inverse_risk_score(self):
        value = build_market_liquidity(report())
        self.assertEqual(value['score'], 53.0)
        self.assertEqual(value['risk_score'], 47.0)
        self.assertEqual(value['label'], '中性')
        self.assertEqual(value['sample_count'], 121)
        self.assertEqual(value['source_ids'], ['sector_reference:money'])

    def test_does_not_mutate_report(self):
        source = report()
        original = copy.deepcopy(source)
        build_market_liquidity(source)
        self.assertEqual(source, original)

    def test_unavailable_score_does_not_fill_neutral_value(self):
        value = build_market_liquidity(report(score=None, status='partial'))
        self.assertIsNone(value['score'])
        self.assertIsNone(value['risk_score'])
        self.assertEqual(value['status'], 'unavailable')
        self.assertIn('专用历史', value['missing'][0])

    def test_rejects_non_liquidity_sector_score(self):
        value = build_market_liquidity({
            'sector_analysis': [{'id': 'money', 'status': 'ok',
                                 'score_scope': 'reference_trend',
                                 'recommendation_index': 90}],
        })
        self.assertIsNone(value['score'])
        self.assertEqual(value['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
