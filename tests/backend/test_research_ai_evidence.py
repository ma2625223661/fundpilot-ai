import copy
import json
import unittest
from datetime import date, timedelta
from research_ai_evidence import compact_company, event_company_context
from research_sector_ai import _batch_evidence
from research_sectors import history_metrics


def company():
    history=[{'date':(date(2026,1,1)+timedelta(days=i)).isoformat(),'close':10+i*.1} for i in range(121)]
    return {'ts_code':'600000.SH','name':'测试公司','as_of':'2026-05-01','history':history,
        'quote':{'close':22,'trade_date':'2026-05-01','source_id':'company_quotes'},
        'source_ids':['company_quotes','financials'], 'leader_verified':False,
        'membership_evidence':{'l2_name':'测试行业','snapshot_date':'2026-04-30','source_url':'https://example.com/business'},
        'financials':{'ann_date':'2026-04-30','end_date':'2026-03-31','roe':15,'netprofit_yoy':20},
        'sample_checks':{'业务或成分归属':True,'有效报价':True,'披露日财务':True,'近期61日走势':True}}


class CompactEvidenceTests(unittest.TestCase):
    def test_metrics_match_deterministic_history_and_preserve_dates_and_source(self):
        row=company();original=copy.deepcopy(row)
        compact=compact_company(row,'2026-05-01')
        self.assertEqual(row,original)
        self.assertNotIn('history',compact)
        for key,value in history_metrics(row['history'],'2026-05-01').items():
            self.assertEqual(compact['history_metrics'][key],value)
        self.assertEqual(compact['financials']['ann_date'],'2026-04-30')
        self.assertEqual(compact['membership_evidence']['source_url'],'https://example.com/business')
        self.assertEqual(compact['source_ids'],row['source_ids'])
        row['history'] += [{'date':'2099-01-01','close':1000000},{'date':'2026-05-01','close':float('nan')}]
        self.assertEqual(compact_company(row,'2026-05-01')['history_metrics'],compact['history_metrics'])

    def test_sector_payload_keeps_score_and_citations_with_no_full_series(self):
        row=company();report={'research_scope':'sectors','as_of':'2026-05-01',
            'snapshot':{'sources':[{'id':key,'status':'ok'} for key in row['source_ids']]},
            'sector_analysis':[{'id':'a','status':'ok','score':49.08,'score_status':'partial','score_maximum':70,
                'quote':{'source_id':'company_quotes','change_pct':1},'leaders':[row],
                'custom_index':{'history':row['history'],'history_count':121,'constituents':[{'code':'600000.SH','weight_pct':100}]}}]}
        original=copy.deepcopy(report);payload,direct=_batch_evidence(report,['a']);item=payload['sectors'][0]
        self.assertEqual(report,original)
        self.assertEqual(item['score'],49.08);self.assertEqual(item['score_maximum'],70)
        self.assertEqual(direct['a'],set(row['source_ids']))
        self.assertEqual({s['id'] for s in payload['sources']},set(row['source_ids']))
        self.assertNotIn('history',item['custom_index']);self.assertNotIn('history',item['leaders'][0])
        self.assertEqual(item['custom_index']['constituents'][0]['weight_pct'],100)

    def test_event_context_deduplicates_companies_without_losing_sector_membership(self):
        row=company();report={'company_evidence':{'sector_leaders':{'a':[row],'b':[row]}},'as_of':'2026-05-01'}
        payload=event_company_context(report)
        self.assertEqual(len(payload),1)
        self.assertEqual([m['sector_id'] for m in payload[0]['sector_memberships']],['a','b'])
        self.assertNotIn('history',payload[0]);self.assertNotIn('financials',payload[0])
        self.assertNotIn('membership_evidence',payload[0])
        self.assertEqual(payload[0]['sector_memberships'][0]['membership_evidence']['snapshot_date'],'2026-04-30')
        self.assertLess(len(json.dumps(payload)),len(json.dumps(report))/2)

    def test_company_event_only_includes_explicit_company_and_all_its_memberships(self):
        one=company();two={**company(),'ts_code':'600001.SH','name':'第二企业'}
        report={'company_evidence':{'sector_leaders':{'a':[one,two],'b':[one]}}}
        for code in ('600000.SH','600000'):
            with self.subTest(code=code):
                payload=event_company_context(report,[{'stock_codes':[code]}])
                self.assertEqual([row['ts_code'] for row in payload],['600000.SH'])
                self.assertEqual([item['sector_id'] for item in payload[0]['sector_memberships']],['a','b'])

    def test_unmapped_policy_keeps_business_graph_while_mapped_sector_filters_other_companies(self):
        one=company();two={**company(),'ts_code':'600001.SH','name':'第二企业'}
        report={'company_evidence':{'sector_leaders':{'a':[one],'b':[two]}}}
        self.assertEqual(len(event_company_context(report,[{}])),2)
        self.assertEqual([row['ts_code'] for row in event_company_context(report,[{'sector_ids':['a']}])],['600000.SH'])
        self.assertEqual(event_company_context(report,[]),[])

    def test_event_context_drops_empty_fields_and_preserves_explicit_false(self):
        row=company();row.update(industry=None,role='',business_evidence={})
        row['membership_evidence'].update(l1_name=None,l3_name='',evidence_type=None)
        payload=event_company_context({'company_evidence':{'sector_leaders':{'a':[row]}}})[0]
        self.assertNotIn('industry',payload);self.assertNotIn('role',payload);self.assertNotIn('business_evidence',payload)
        self.assertIs(payload['leader_verified'],False)
        membership=payload['sector_memberships'][0]['membership_evidence']
        self.assertNotIn('l1_name',membership);self.assertNotIn('l3_name',membership)

    def test_unrelated_company_announcements_are_not_repeated_in_every_sector_batch(self):
        report={'research_scope':'sectors','sector_analysis':[{'id':'a','sources':['quotes']}],
            'snapshot':{'sources':[{'id':'quotes','status':'ok'}, {'id':'official_cninfo','status':'ok'}],
                'news':[{'source_id':'official_cninfo','summary':'长公告'*20000}]},
            'event_analysis':{'events':[{'id':'a-event','sector_ids':['a'],'published_at':'2026-10-30'},
                {'id':'b-event','sector_ids':['b'],'reason':'无关事件'}]}}
        payload,_=_batch_evidence(report,['a'])
        self.assertEqual(payload['news'],[])
        self.assertEqual([row['id'] for row in payload['assessed_events']],['a-event'])
        self.assertLess(len(json.dumps(payload)),5000)


if __name__=='__main__':
    unittest.main()
