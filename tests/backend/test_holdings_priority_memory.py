import copy
import unittest
from unittest.mock import patch
from research_memory import update_holdings_index, update_check_ledger, attach_holdings_index, retain_research
from research_categories import boards_for, board_for, build_board_coverage
from research_selection import build_sections
from research_universe import cap_research_codes, pick_research_codes, plan_research_codes
from research_auto import run_auto_research
from research_auto_ai import enrich_auto_report
from test_holdings_fixtures import portfolio

STAMP = '2026-10-30T16:00:00+08:00'


def sample(code, match=100, score=80):
    holdings = portfolio(['软件开发'], weights=(match, 100-match) if match < 100 else (100,))
    if match < 100:
        holdings['rows'][1]['tags'] = ['无关行业']
    fund = {'code': code, 'name': '独立' + code, 'fund_type': '股票型', 'holdings': holdings,
            'history': [{'date': STAMP[:10], 'nav': 1}], 'nav': 1, 'nav_date': STAMP[:10],
            'eligible': True, 'screen_group': 'equity', 'universe_bucket': 'medium_high'}
    quant = {'code': code, 'score': score, 'quality': 'ok', 'nav_date': STAMP[:10], 'action': '继续观察',
             'metrics': {'volatility_annual': 10, 'max_drawdown': -2},
             'thresholds': {'annual_volatility_limit': 30, 'drawdown_limit': 18}}
    return fund, quant


class HoldingsPriorityTests(unittest.TestCase):
    def test_purity_precedes_historical_score_and_limits_three(self):
        pairs = [sample('000001', 51, 99), sample('000002', 60, 60),
                 sample('000003', 100, 40), sample('000004', 70, 50)]
        snapshot = {'as_of': STAMP, 'funds': [f for f,q in pairs]}
        sections = build_sections(snapshot, [q for f,q in pairs], {'funds': []},
                                  {'as_of': STAMP, 'regime': {'mode': 'risk_on'}, 'candidates': []})
        self.assertEqual([f['code'] for f in sections[0]['funds']], ['000003','000004','000002'])
        self.assertTrue(all(f['role']=='observation' for f in sections[0]['funds']))
        self.assertEqual(cap_research_codes([f['code'] for f,q in pairs], [f for f,q in pairs], STAMP),
                         ['000003','000004','000002'])

    def test_each_fund_enters_only_its_highest_matching_board(self):
        pairs = [sample('000001',100), sample('000002',100)]
        first, second = pairs[0][0], pairs[1][0]
        first['holdings'] = portfolio(['软件开发','CPO'], weights=(90,10))
        first['holdings']['rows'][1]['tags']=['软件开发']
        second['holdings'] = portfolio(['软件开发','CPO'], weights=(80,20))
        second['holdings']['rows'][1]['tags']=['CPO']
        sections=build_sections({'as_of':STAMP,'funds':[first,second]}, [q for f,q in pairs], {'funds':[]})
        by_id={s['id']:s for s in sections}
        self.assertEqual([f['code'] for f in by_id['sector_cpo']['funds']],['000002'])
        self.assertEqual([f['code'] for f in by_id['sector_technology']['funds']],['000001'])
        all_codes=[f['code'] for s in sections for f in s['funds']]
        self.assertEqual(len(all_codes),len(set(all_codes)))
        self.assertEqual(by_id['sector_cpo']['funds'][0]['board_comparison'][0]['id'],'sector_cpo')

    def test_multiple_boards_do_not_exceed_independent_round_limit(self):
        funds=[sample(f'{i:06d}')[0] for i in range(1,11)]
        for fund in funds:
            fund['holdings']=portfolio(['软件开发','CPO'])
        chosen=cap_research_codes([f['code'] for f in funds],funds,STAMP)
        self.assertEqual(len(chosen),3)
        counts={}
        for fund in funds:
            if fund['code'] in chosen:
                for board in boards_for(fund,'equity_active',STAMP):
                    counts[board['id']]=counts.get(board['id'],0)+1
        self.assertTrue(all(count<=3 for count in counts.values()))

    def test_parent_overlap_does_not_block_each_boards_best_funds(self):
        funds=[]
        for i in range(1,7):
            fund,_=sample(f'{i:06d}')
            tags=['银行'] if i<=3 else ['证券']
            fund['holdings']=portfolio(tags)
            funds.append(fund)
        plan=plan_research_codes([f['code'] for f in funds],funds,STAMP)
        self.assertEqual(len(plan['selected_codes']),6)
        self.assertEqual(plan['board_targets']['sector_banking'],['000001','000002','000003'])
        self.assertEqual(plan['board_targets']['sector_securities'],['000004','000005','000006'])
        self.assertTrue(all(len(codes)<=3 for codes in plan['board_targets'].values()))
        self.assertLessEqual(len(plan_research_codes([f['code'] for f in funds],funds,STAMP,limit=4)['selected_codes']),4)
        coverage=build_board_coverage({'funds':funds},plan['selected_codes'],{'as_of':STAMP,'funds':funds},[],[])
        by_id={board['id']:board for board in coverage}
        self.assertEqual(by_id['sector_banking']['deep_count'],3)
        self.assertEqual(by_id['sector_securities']['deep_count'],3)
        self.assertEqual(by_id['sector_finance']['deep_count'],0)

    def test_second_preflight_fills_new_boards_after_first_batch_converges(self):
        initial=[sample(f'{i:06d}')[0] for i in range(1,5)]
        extra=[sample(f'{i:06d}')[0] for i in range(5,8)]
        for fund in extra:
            fund['holdings']=portfolio(['银行'])
        all_funds=initial+extra
        def collect(codes=None,**kwargs):
            return {'as_of':STAMP,'funds':[copy.deepcopy(fund) for fund in all_funds if fund['code'] in (codes or [])],
                    'sources':[],'warnings':[],'market':[],'news':[]}
        with patch('research_auto.collect_universe',return_value={'as_of':STAMP,'funds':all_funds,'sources':[],'warnings':[]}), \
             patch('research_auto._search_unresolved_boards',return_value=({'boards':[],'sources':[],'warnings':[]},[])), \
             patch('research_auto.pick_holdings_preflight_codes',side_effect=[[f['code'] for f in initial],[f['code'] for f in extra],[]]), \
             patch('research_auto.collect_holdings',side_effect=lambda snapshot,**kwargs:copy.deepcopy(snapshot)) as preflight, \
             patch('research_auto.collect_research',side_effect=collect) as research:
            result=run_auto_research()
        self.assertEqual(preflight.call_count,2)
        self.assertEqual(result['universe']['coverage']['holdings_preflight_count'],7)
        self.assertEqual(set(result['universe']['selected_codes']),{'000001','000002','000003','000005','000006','000007'})
        self.assertEqual(research.call_count,1)
        self.assertTrue(all(len(codes)<=3 for codes in result['universe']['board_targets'].values()))

    def test_exploration_is_name_independent_and_rotates_unseen_holdings(self):
        funds=[sample(f'{i:06d}')[0] for i in range(1,10)]
        for fund in funds:
            fund.pop('holdings')
        universe={'as_of':STAMP,'funds':funds}
        first=pick_research_codes(universe,3)
        for fund in funds:
            fund['name']='任意'+fund['code']
        self.assertEqual(pick_research_codes(universe,3),first)
        for fund in funds:
            if fund['code'] in first:
                fund['holdings_checked_at']=STAMP
        self.assertFalse(set(first)&set(pick_research_codes(universe,3)))

    def test_new_failure_replaces_index_success_without_mutating_input(self):
        fund,_=sample('000001')
        previous=update_holdings_index([], [fund],STAMP)
        old=copy.deepcopy(previous)
        failed={**fund,'holdings':{'status':'error','rows':[]}}
        index=update_holdings_index(previous,[failed],STAMP)
        self.assertEqual(index[0]['holdings']['status'],'error')
        self.assertEqual(previous,old)
        universe={'funds':[copy.deepcopy(fund)]}
        attach_holdings_index(universe,index)
        self.assertEqual(board_for(universe['funds'][0],'equity_active',STAMP)['id'],'holdings_unclassified')

    def test_check_ledger_survives_full_portfolio_eviction_and_ignores_unchecked_rows(self):
        fund,_=sample('000001')
        ledger=update_check_ledger({},[fund,{'code':'000002'}],STAMP)
        self.assertEqual(ledger,{'000001':STAMP})
        universe={'funds':[{'code':'000001'},{'code':'000002'}]}
        attach_holdings_index(universe,[],ledger)
        self.assertEqual(universe['funds'][0]['holdings_checked_at'],STAMP)
        self.assertIsNone(universe['funds'][1]['holdings_checked_at'])
        self.assertNotIn('holdings',universe['funds'][0])
        self.assertEqual(update_check_ledger({'000002':'invalid','000003':'2026-11-01'},[],STAMP),{})

    def test_known_higher_exposure_is_selected_without_repeating_its_preflight(self):
        known,_=sample('000001',100)
        probe,_=sample('000002',60)
        def collect(codes=None,**kwargs):
            return {'as_of':STAMP,'funds':[copy.deepcopy(fund) for fund in [known,probe] if fund['code'] in (codes or [])],
                    'sources':[],'warnings':[],'market':[],'news':[]}
        with patch('research_auto.collect_universe',return_value={'as_of':STAMP,'funds':[known,probe],'sources':[],'warnings':[]}), \
             patch('research_auto._search_unresolved_boards',return_value=({'boards':[],'sources':[],'warnings':[]},[])), \
             patch('research_auto.pick_holdings_preflight_codes',side_effect=[['000002'],[]]), \
             patch('research_auto.collect_holdings',side_effect=lambda snapshot,**kwargs:copy.deepcopy(snapshot)), \
             patch('research_auto.collect_research',side_effect=collect):
            result=run_auto_research()
        self.assertEqual(result['universe']['selected_codes'],['000001','000002'])
        self.assertEqual(result['universe']['coverage']['reused_holdings_for_deep_count'],1)

    def test_retention_keeps_dates_and_recomputable_evidence_only(self):
        fund,_=sample('000001')
        previous={'as_of':'2026-10-29T16:00:00+08:00','funds':[fund], 'sources':[]}
        before=copy.deepcopy(previous)
        current={'as_of':STAMP,'funds':[],'sources':[]}
        self.assertEqual(retain_research(current,previous,{'funds':[fund]},[]),1)
        self.assertEqual(current['funds'][0]['nav_date'],fund['nav_date'])
        self.assertEqual(current['funds'][0]['research_origin'],'retained')
        self.assertEqual(current['funds'][0]['evidence_collected_at'],previous['as_of'])
        self.assertEqual(previous,before)

    def test_attempted_failed_nav_never_falls_back_to_previous_success(self):
        fund,_=sample('000001')
        current={'as_of':STAMP,'funds':[],'sources':[]}
        self.assertEqual(retain_research(current,{'funds':[fund]}, {'funds':[fund]},['000001']),0)

    def test_expired_future_and_currently_ineligible_evidence_is_not_retained(self):
        fund,_=sample('000001')
        for nav_date, eligible in [('2026-01-01',True),('2026-11-01',True),(STAMP[:10],False)]:
            old={**fund,'nav_date':nav_date}
            current={'as_of':STAMP,'funds':[],'sources':[]}
            self.assertEqual(retain_research(current,{'funds':[old]}, {'funds':[{**fund,'eligible':eligible}]},[]),0)

    def test_retention_respects_new_failed_holdings(self):
        fund,_=sample('000001')
        current={'as_of':STAMP,'funds':[],'sources':[]}
        new={**fund,'holdings':{'status':'error','rows':[]}}
        self.assertEqual(retain_research(current,{'funds':[fund]}, {'funds':[new]},[]),1)
        self.assertEqual(board_for(current['funds'][0],'equity_active',STAMP)['id'],'holdings_unclassified')

    def test_retained_funds_never_expand_paid_ai_targets(self):
        fund,quant=sample('000001')
        report={'snapshot':{'as_of':STAMP,'funds':[fund]},'quant':[quant],
                'analysis':{'funds':[{'code':fund['code']}]}, 'universe':{'selected_codes':[]}}
        with patch('research_auto_ai.provider_json',side_effect=AssertionError('no paid call')):
            enriched=enrich_auto_report(report,config={'enabled':True,'key':'offline-synthetic'})
        self.assertEqual(enriched['ai_research']['target_count'],0)
        self.assertEqual(enriched['ai_research']['requests_attempted'],0)


if __name__=='__main__':
    unittest.main()
