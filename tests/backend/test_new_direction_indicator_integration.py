"""New business pools reach the real sector model only with complete inputs."""
import copy
import unittest
from contextlib import ExitStack
from datetime import date,timedelta
from unittest.mock import patch

import research_sectors as sectors
from research_overseas import recent_sessions
from research_trading_calendar import is_trading_day

NOW='2026-10-31T06:00:00+08:00'


def company(identity):
    overseas=identity=='overseas_healthcare'
    if overseas:
        days=recent_sessions('US',NOW)
        codes=('ABBV.US','MRK.US')
    else:
        day=date(2026,10,30);days=[]
        while len(days)<61:
            if is_trading_day(day):days.append(day.isoformat())
            day-=timedelta(days=1)
        days=list(reversed(days));codes=('601899.SH','600938.SH') if identity=='commodities' else ('601601.SH','601319.SH')
    rows=[]
    for code in codes:
        quote={'trade_date':'2026-10-30','close':112,'pct_chg':.2,'is_intraday':False}
        if overseas:quote['market']='US'
        rows.append({'ts_code':code,'name':code,'as_of':'2026-10-30' if overseas else '2026-10-30T16:14:50+08:00',
            'quote':quote,'history':[{'date':day,'close':100+i*.2} for i,day in enumerate(days)],
            'source_ids':['business:'+code,'leader_history:'+code],
            'membership_evidence':{'l1_name':'官网业务证据样本池','snapshot_date':'2026-10-31','evidence_type':'public_business'},
            'selection_basis':'有限核验公司样本池','price_adjustment':'adjusted',
            'financials':{'ann_date':'2026-08-29','end_date':'2026-06-30','tr_yoy':10,'netprofit_yoy':5}})
    return {'sector_leaders':{identity:rows},'sources':[],'warnings':[],'provider':'public_multisource'}


class NewDirectionModelIntegration(unittest.TestCase):
    def setUp(self):
        from test_helpers.isolated_public_cache import isolate_public_cache
        isolate_public_cache(self)

    def run_report(self,identity,evidence):
        board=next(row for row in sectors.sector_catalog() if row['id']==identity)
        mocks={
            'now_iso':NOW,'sector_catalog':[board],
            'collect_macro_risk':({'status':'unavailable','risk_score':None},{'id':'macro:nbs_pmi','status':'error'}),
            'collect_long_wave_evidence':({},[]),
            'collect_sector_market':{'market':[],'news':[],'sources':[],'warnings':[]},
            'collect_sector_quotes':([],[]),'collect_verified_references':([],[],{}),
            'fetch_text':'','collect_sector_histories':({},[])}
        with ExitStack() as stack:
            for name,value in mocks.items():stack.enter_context(patch.object(sectors,name,return_value=copy.deepcopy(value)))
            stack.enter_context(patch('research_public_data.gather_public_company_evidence',return_value=evidence))
            stack.enter_context(patch('research_leader_index.collect_leader_histories'))
            stack.enter_context(patch('research_overseas.collect_overseas_references', return_value=([], [], {})))
            return sectors.run_sector_research(data_config={'provider':'baostock','secondary_provider':'public_multisource'})

    def test_insurance_and_us_pharma_run_real_independent_models(self):
        for identity in ('sector_insurance','overseas_healthcare','commodities'):
            with self.subTest(identity=identity):
                report=self.run_report(identity,company(identity))
                row=report['sector_analysis'][0]
                self.assertTrue(row['custom_index']['ready'])
                self.assertEqual(row['custom_index']['sample_count'],2)
                self.assertEqual(row['score_model'],'company_research_v2')
                self.assertTrue(all(r['status']=='ok' for r in row['requirements']))
                self.assertIsNotNone(row['score_breakdown']['trend']['points'])
                self.assertIsNotNone(row['score_breakdown']['fundamentals']['points'])
                self.assertIsNotNone(row['recommendation_index'])
                self.assertLessEqual(row['recommendation_index'],49)
                self.assertEqual(row['event_score_status'],'unassessed')
                self.assertEqual(report['coverage']['fully_ready_sector_count'],1)
                self.assertFalse(report['automatic']['paid_api_calls'])

    def test_missing_finance_or_recent_history_blocks_composite_in_both_pools(self):
        for identity in ('sector_insurance','overseas_healthcare','commodities'):
            for gap in ('financial','history'):
                evidence=company(identity)
                member=evidence['sector_leaders'][identity][0]
                if gap=='financial':member['financials']=None
                else:member['history'].pop(-2)
                with self.subTest(identity=identity,gap=gap):
                    report=self.run_report(identity,evidence)
                    row=report['sector_analysis'][0]
                    self.assertIsNone(row['recommendation_index'])
                    self.assertIsNone(row['score'])
                    self.assertEqual(row['status'],'partial')
                    self.assertEqual(report['coverage']['fully_ready_sector_count'],0)
                    self.assertTrue(any(r['status']!='ok' for r in row['requirements']))


if __name__=='__main__':unittest.main()
