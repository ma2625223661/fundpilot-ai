import copy
import itertools
import unittest
from decimal import Decimal

from research_balanced_score import (TECH, CYCLE, trend_points, fundamental_points,
    catalyst_points, score_company, research_tier, apply_market_risks,round_points)
from research_event_ai import OFFICIAL_EVENT_SOURCES

NOW='2026-10-31T14:00:00+08:00'
SOURCE=sorted(OFFICIAL_EVENT_SOURCES)[0]


def company(revenue=10, profit=20, eps=1):
    return {'financials':{'ann_date':'2026-10-30','end_date':'2026-09-30',
                         'tr_yoy':revenue,'netprofit_yoy':profit,'eps':eps}}


def sector():
    return {'id':'sector_pcb','metrics':{'return_20d':0,'return_60d':0,'ma20_gap':0},
            'leaders':[company(),company()]}


def event(score=80, **changes):
    row={'id':'event:'+str(score),'sector_ids':['sector_pcb'],'impact_score':score,
         'direction':'positive' if score>0 else 'negative',
         'published_at':'2026-10-30T18:00:00+08:00','source_ids':[SOURCE]}
    row.update(changes)
    return row


class BalancedScoreTests(unittest.TestCase):
    def test_cent_rounding_is_explicit_half_up(self):
        self.assertEqual(round_points(1.005),1.01)
        self.assertEqual(round_points(-1.005),-1.01)

    def test_displayed_components_sum_to_displayed_total_without_hidden_millipoints(self):
        s=sector();s['leaders']=[company(50,48.528571)]
        s['metrics']={'return_20d':-27.632,'return_60d':-20.521,'ma20_gap':-24.321}
        result=score_company(s,{'status':'completed','events':[event(71),event(-43)]},NOW)
        b=result['breakdown'];values=[b[k]['points'] for k in ('fundamentals','trend','catalysts')]
        self.assertTrue(all(Decimal(str(v)).as_tuple().exponent>=-2 for v in values))
        expected=max(Decimal(0),min(Decimal(100),sum((Decimal(str(v)) for v in values),Decimal(0))))
        self.assertEqual(Decimal(str(result['score'])),expected)

    def test_channel_weights_have_interpretable_neutral_and_extreme_values(self):
        self.assertEqual(fundamental_points([company()],NOW)['points'],28)
        self.assertEqual(trend_points(sector()['metrics'])['points'],15)
        self.assertEqual(fundamental_points([company(500,500,1)],NOW)['points'],40)
        self.assertEqual(fundamental_points([company(-100,-1000,-1)],NOW)['points'],0)

    def test_signed_effect_is_only_in_catalysts_and_total_is_bounded(self):
        for return_value, growth, impact in itertools.product((-1000,0,1000),(-1000,0,1000),(-100,0,100)):
            s=sector();s['metrics']={k:return_value for k in s['metrics']}
            s['leaders']=[company(growth,growth,1 if growth>=0 else -1)]
            meta={'status':'completed','events':[event(impact)] if impact else []}
            result=score_company(s,meta,NOW);b=result['breakdown']
            self.assertTrue(0<=b['trend']['points']<=30)
            self.assertTrue(0<=b['fundamentals']['points']<=40)
            self.assertTrue(-30<=b['catalysts']['points']<=30)
            self.assertTrue(0<=result['score']<=100)
        s['metrics']={k:1000 for k in s['metrics']};s['leaders']=[company(500,500)]
        self.assertEqual(score_company(s,{'status':'completed','events':[event(100)]},NOW)['score'],100)
        s['metrics']={k:-1000 for k in s['metrics']};s['leaders']=[company(-1000,-1000,-1)]
        self.assertEqual(score_company(s,{'status':'completed','events':[event(-100)]},NOW)['score'],0)

    def test_catalysts_use_both_sides_and_do_not_reward_duplicate_volume(self):
        rows=[event(80),event(-60),event(40)]
        first=catalyst_points({'status':'completed','events':rows},'sector_pcb',NOW)
        self.assertEqual(first['points'],6)
        self.assertEqual(first,catalyst_points({'status':'completed','events':rows*6},'sector_pcb',NOW))

    def test_unofficial_stale_future_wrong_direction_and_weak_events_do_not_score(self):
        invalid=[event(80,source_ids=['blog']),event(80,published_at='2026-11-01'),
                 event(80,published_at='2026-10-01'),event(80,direction='negative'),
                 event(39),event(True),event(80,sector_ids=['another'])]
        self.assertEqual(catalyst_points({'status':'completed','events':invalid},'sector_pcb',NOW)['points'],0)

    def test_unknown_events_are_null_not_assessed_neutral_and_do_not_get_a_tier(self):
        for status in ('scheduled','pending','error','not_configured','data_unavailable'):
            result=score_company(sector(),{'status':status},NOW)
            self.assertEqual(result['score'],43)
            self.assertIsNone(result['complete_score'])
            self.assertIsNone(result['breakdown']['catalysts']['points'])
            self.assertEqual(result['score_maximum'],70)
            self.assertEqual(result['possible_range'],[13,73])
        neutral=score_company(sector(),{'status':'completed','events':[]},NOW)
        self.assertEqual(neutral['score_status'],'complete')
        self.assertEqual(neutral['breakdown']['catalysts']['points'],0)

    def test_partial_batch_known_events_affect_stage_and_leave_truthful_bounds(self):
        base=score_company(sector(),{},NOW)
        result=score_company(sector(),{'status':'partial','eligible_count':14,'assessed_count':12,'events':[event(-80)]},NOW)
        self.assertEqual(result['score'],base['score']-24)
        self.assertEqual(result['score_maximum'],100)
        self.assertEqual(result['possible_range'],[13,49])
        self.assertEqual(result['score_status'],'provisional')
        self.assertIsNone(result['breakdown']['catalysts']['points'])
        truncated=score_company(sector(),{'status':'completed','eligible_count':14,'assessed_count':12,'events':[]},NOW)
        self.assertEqual(truncated['score_status'],'provisional')

    def test_future_financials_and_missing_channels_cannot_gain_neutral_points(self):
        s=sector();s['leaders'][0]['financials']['ann_date']='2026-11-01'
        result=score_company(s,{'status':'completed','events':[]},NOW)
        self.assertEqual(result['breakdown']['fundamentals']['coverage_pct'],50)
        self.assertEqual(result['score_status'],'provisional')
        self.assertIsNone(result['complete_score'])
        s['leaders'][1]['financials'].pop('eps')
        self.assertLess(score_company(s,{'status':'completed'},NOW)['score'],result['score'])
        s['leaders'][1]['financials']['ann_date']='2026-11-01'
        self.assertIsNone(score_company(s,{},NOW))

    def test_financial_median_limits_one_company_outlier_and_bounds_missing_medians(self):
        f=fundamental_points([company(),company(),company(1e9,1e9)],NOW)
        self.assertEqual(f['points'],28)
        rows=[company(),{'financials':None}]
        partial=fundamental_points(rows,NOW)
        for unknown in (company(-1000,-1000,-1),company(),company(1000,1000,1)):
            full=fundamental_points([rows[0],unknown],NOW)['points']
            self.assertLessEqual(partial['possible_range'][0],full)
            self.assertGreaterEqual(partial['possible_range'][1],full)

    def test_missing_trend_does_not_become_zero(self):
        s=sector();s['metrics'].pop('return_60d')
        self.assertIsNone(score_company(s,{},NOW))

    def test_continuous_tier_boundaries_and_fundamental_gate(self):
        for score,expected in [(0,'avoid'),(29.99,'avoid'),(30,'cautious'),(49.99,'cautious'),
                               (50,'neutral'),(64.99,'neutral'),(65,'optimistic'),(100,'optimistic')]:
            self.assertEqual(research_tier(score,28,18,19,True)['id'],expected)
        self.assertEqual(research_tier(80,27.99,25,30,True)['id'],'neutral')
        self.assertEqual(research_tier(65,30,17,18,True)['id'],'optimistic')
        self.assertEqual(research_tier(70,40,30,0,False)['id'],'pending')

    def test_support_condition_is_implied_by_total_at_least_65_under_valid_bounds(self):
        # If catalyst<=0 and trend<18, even maximum fundamentals yield <58.
        self.assertLess(40+17.999+0,65)
        for f,t,e in itertools.product(range(41),range(31),range(-30,31)):
            if f+t+e>=65:self.assertTrue(t>=18 or e>0)

    def test_risk_profiles_are_real_catalog_ids_with_unit_weight_sums(self):
        from research_sectors import sector_catalog
        ids={s['id'] for s in sector_catalog()}
        self.assertFalse((TECH|CYCLE)-ids)
        report={'as_of':NOW,'strategy':{'panic':{'score':40,'quote_as_of':'2026-10-30T15:00:00+08:00'},'macro_evidence':
            {'status':'ok','risk_score':30,'published_at':'2026-10-31T09:30:00+08:00'}},
            'sector_analysis':[{'id':'sector_pcb'},{'id':'sector_oil_gas'},
                {'id':'money','status':'ok','score_scope':'money_liquidity','recommendation_index':10,'as_of':'2026-10-30'}]}
        apply_market_risks(report)
        tech,cycle=report['sector_analysis'][:2]
        self.assertGreater(tech['market_risk']['score'],cycle['market_risk']['score'])
        for s in (tech,cycle):
            self.assertAlmostEqual(sum(s['market_risk']['weights'].values()),1)
            self.assertEqual(s['market_risk']['status'],'complete')
        before=copy.deepcopy(report);apply_market_risks(report);self.assertEqual(report,before)

    def test_risk_missing_or_stale_components_remain_partial(self):
        report={'as_of':NOW,'strategy':{'panic':{'score':70,'quote_as_of':'2026-10-30T15:00:00+08:00'},'macro_evidence':
            {'status':'ok','risk_score':10,'published_at':'2026-11-01'}},
            'sector_analysis':[{'id':'sector_pcb'},{'id':'money','status':'stale','score_scope':'money_liquidity','recommendation_index':90}]}
        apply_market_risks(report);risk=report['sector_analysis'][0]['market_risk']
        self.assertEqual(risk['score'],70);self.assertEqual(risk['coverage_pct'],35)
        self.assertEqual(risk['status'],'partial');self.assertIsNone(risk['components']['macro'])

    def test_previous_close_risk_cannot_survive_a_later_open_session(self):
        report={'as_of':'2026-11-02T14:30:00+08:00','strategy':{'panic':
            {'score':10,'quote_as_of':'2026-10-30T15:00:00+08:00'}},'sector_analysis':[{'id':'sector_pcb'}]}
        apply_market_risks(report)
        self.assertIsNone(report['sector_analysis'][0]['market_risk']['score'])


if __name__=='__main__':unittest.main()
