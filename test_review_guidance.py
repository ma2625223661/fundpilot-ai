"""Recommendation policy, missing evidence and strict risk caps; no AI requests."""
import copy
import unittest

from research_review_guidance import review_guidance
from test_research_review import sector


def item(score=90, **changes):
    return {'status':'completed','score':score,'return_pct':4.5,'excess_pct':2,
            'drawdown_pct':1,'period_end':'2026-10-30','source_ids':['leader:test'],**changes}


class GuidanceTests(unittest.TestCase):
    def test_exact_thresholds_and_zero(self):
        company=sector()
        for score,action in [(0,'avoid'),(29.99,'avoid'),(30,'cautious'),(49.99,'cautious'),
                             (50,'observe'),(64.99,'observe'),(65,'track'),(100,'track')]:
            with self.subTest(score=score):
                result=review_guidance(item(score),company)
                self.assertEqual(result['recommendation_index'],score)
                self.assertEqual(result['action'],action)

    def test_partial_research_is_not_normalized_to_full_score(self):
        company=sector()
        company.update(score_status='provisional',research_score=None,confirmed_score=69,recommendation_index=69)
        result=review_guidance(item(95),company)
        self.assertEqual(result['recommendation_index'],49)
        self.assertEqual(result['current_research_action'],'wait')
        self.assertIn('不折算',result['caps'][0]['reason'])
        self.assertEqual(company['confirmed_score'],69)

    def test_high_total_still_needs_fundamentals_gate(self):
        company=sector()
        company['recommendation_index']=85
        company['score_breakdown']['fundamentals']['points']=20
        result=review_guidance(item(100),company)
        self.assertEqual(result['recommendation_index'],64)
        self.assertEqual(result['action'],'observe')

    def test_strictest_cap_wins_without_double_penalties(self):
        company=sector()
        company.update(risk='高风险')
        company['market_risk']['score']=75
        result=review_guidance(item(80,drawdown_pct=12,return_pct=-8,excess_pct=-9),company)
        self.assertEqual(result['recommendation_index'],29)
        self.assertEqual(result['effective_cap'],29)
        self.assertEqual({c['maximum'] for c in result['caps']},{100,49,29,64})
        self.assertEqual(review_guidance(item(5,drawdown_pct=12),company)['recommendation_index'],5)

    def test_market_and_quote_risk_caps(self):
        for risk,expected in [(69,90),(70,49),(84.99,49),(85,29),(100,29),(None,49)]:
            company=sector();company['market_risk']['score']=risk
            self.assertEqual(review_guidance(item(),company)['recommendation_index'],expected)
        for risk,expected in [('低风险',90),('中风险',90),('高风险',49),('高风险 · 特大风险',29),('',49)]:
            company=sector();company['risk']=risk
            self.assertEqual(review_guidance(item(),company)['recommendation_index'],expected)
        company=sector();company['market_risk'].update(score=20,status='partial')
        self.assertEqual(review_guidance(item(),company)['recommendation_index'],49)

    def test_negative_return_and_relative_lag_block_optimistic_tier(self):
        self.assertEqual(review_guidance(item(return_pct=-.1),sector())['recommendation_index'],64)
        self.assertEqual(review_guidance(item(excess_pct=-.1),sector())['recommendation_index'],64)

    def test_incomplete_or_stale_data_never_becomes_zero_or_favorable(self):
        for changes in [{'status':'partial','score':None},{'status':'pending'},
                        {'score':float('nan')},{'score':101},{'excess_pct':None}]:
            result=review_guidance(item(**changes),sector())
            self.assertIsNone(result['recommendation_index'])
            self.assertEqual(result['action'],'wait')
        self.assertIsNone(review_guidance(item(),sector(),current=False)['recommendation_index'])

    def test_source_scores_are_not_mutated_and_plans_are_conditional(self):
        company=sector();observed=item(5,return_pct=-16,excess_pct=-19,drawdown_pct=16)
        before=copy.deepcopy((company,observed))
        result=review_guidance(observed,company)
        self.assertEqual((company,observed),before)
        self.assertEqual(result['action'],'avoid')
        self.assertIn('暂缓新增',result['before_participation'])
        self.assertIn('原定风控',result['if_holding'])
        self.assertTrue(result['checks'])
        self.assertIn('未使用你的持仓',result['note'])


if __name__=='__main__':unittest.main()
