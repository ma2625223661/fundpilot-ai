"""Clock/quote controlled tests. No live provider credentials or paid requests."""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_data import CHINA
from research_live_schedule import quote_due, next_quote_time, presentation
from research_live_update import refresh_company_quotes, retain_interpretations, event_signatures
from research_schedule import default_market_schedule, schedule_signature
from research_sector_ai import enrich_sector_report
from research_subscriptions import content_identity, interpretation_price
from test_research_schedule_window import Clock
from test_research_leader_index import member, BOARD
from test_research_sector_ai import evidence, response
from test_research_event_ai import report as event_report, response as event_response, CONFIG as EVENT_CONFIG


def dt(value):
    return datetime.fromisoformat(value+'+08:00')


class PublicScheduleTests(unittest.TestCase):
    def test_sessions_lunch_close_weekend_and_holiday(self):
        for time, due in [('09:29:59',None),('09:30:00','09:30:00'),('09:34:59','09:30:00'),
                          ('09:35:00','09:35:00'),('11:30:00','11:30:00'),('11:35:00',None),
                          ('12:15:00',None),('13:00:00','13:00:00'),('15:00:00','15:00:00'),
                          ('15:05:00','15:05:00'),('15:10:00',None)]:
            with self.subTest(time=time):
                self.assertEqual(quote_due(dt('2026-10-30T'+time)),dt('2026-10-30T'+due) if due else None)
        self.assertEqual(next_quote_time(dt('2026-10-30T11:40:00')),dt('2026-10-30T13:00:00'))
        self.assertEqual(next_quote_time(dt('2026-10-30T15:10:00')),dt('2026-11-02T09:30:00'))
        for day in ('2026-11-01','2026-10-01'):
            self.assertIsNone(quote_due(dt(day+'T10:00:00')))
        self.assertEqual(presentation(dt('2026-10-30T12:00:00'))[0],'lunch')

    def test_attempts_skip_duplicate_ticks_and_never_replay_backlog(self):
        self.assertIsNone(quote_due(dt('2026-10-30T10:04:00'),dt('2026-10-30T10:00:01')))
        self.assertEqual(next_quote_time(dt('2026-10-30T10:04:00'),dt('2026-10-30T10:00:01')),
                         dt('2026-10-30T10:05:00'))
        self.assertEqual(quote_due(dt('2026-10-30T10:44:00'),dt('2026-10-30T09:30:00')),
                         dt('2026-10-30T10:40:00'))
        with patch('research_live_schedule.is_trading_day',return_value=None), \
             patch('research_live_schedule.next_trading_day',return_value=None):
            self.assertIsNone(quote_due(dt('2026-10-30T10:00:00')))
            self.assertIsNone(next_quote_time(dt('2026-10-30T10:00:00')))


class FreeAdmissionTests(unittest.TestCase):
    def setUp(self):
        Clock.set('2026-10-30T14:50:01+08:00')
        clock=patch('research_auto.datetime',Clock);clock.start();self.addCleanup(clock.stop)
        self.config={'enabled':True,'key':'offline-only','revision':1,'model':'gpt-6.1-sol',
                     'reasoning_effort':'medium','schedule':default_market_schedule()}

    def engine(self, runner=None, ai_runner=None):
        def sample(**_):
            row=evidence(1);row['as_of']=Clock.now(CHINA).isoformat();return row
        engine=AutoResearchEngine(research_scope='sectors',runner=runner or sample,
            ai_runner=ai_runner or enrich_sector_report,config_provider=lambda:dict(self.config))
        self.addCleanup(engine.close)
        engine._ai_schedule_state={'signature':schedule_signature(self.config),
                                  'next_run_at':'2026-10-30T14:50:00+08:00'}
        return engine

    def test_free_refresh_in_paid_window_blocks_event_sector_and_review_admission(self):
        engine=self.engine()
        due=engine._ai_due(self.config)
        with patch('research_sector_ai.provider_json') as paid,patch('research_event_ai.provider_json') as events:
            self.assertTrue(engine.request_scan(public_only=True))
            engine._worker.join(3)
        paid.assert_not_called();events.assert_not_called()
        self.assertEqual(engine._state['status'],'ready',engine._state.get('error'))
        self.assertEqual(engine._ai_due(self.config),due,'free refresh cannot consume the paid slot')
        self.assertFalse(engine._state['report']['automatic']['paid_api_calls'])
        self.assertEqual(engine._state['report']['ai_research']['request_count'],0)

    def test_scan_crossing_paid_start_keeps_due_then_paid_run_is_once(self):
        calls=[]
        def collect(**_):
            Clock.set('2026-10-30T14:51:00+08:00')
            row=evidence(1);row['as_of']=Clock.now(CHINA).isoformat();return row
        def ai(report,config,can_start_request,**kwargs):
            allowed=bool(config.get('enabled') and can_start_request())
            calls.append(allowed)
            report['ai_research']={'revision':1,'request_count':int(allowed),'configuration_enabled':True}
            return report
        engine=self.engine(collect,ai)
        Clock.set('2026-10-30T14:49:00+08:00')
        for public in (True,False,False):
            engine.request_scan(public_only=public);engine._worker.join(3)
            self.assertEqual(engine._state['status'],'ready')
        self.assertEqual(calls,[False,True,False])
        self.assertEqual(engine._ai_due(self.config),dt('2026-11-02T09:20:00'))


class LiveEvidenceTests(unittest.TestCase):
    def test_closed_reference_history_cache_avoids_repeated_downloads(self):
        from research_sectors import collect_sector_histories
        history=[{'date':'2026-10-29','close':100}]
        quote={'name':'指数','code':'sh000001','as_of':'2026-10-30T10:00:00+08:00',
               'history_secid':'tencent:sh000001','data_frequency':'intraday'}
        source={'id':'sector_history:tencent:sh000001','status':'ok','as_of':'2026-10-29'}
        cached={'tencent:sh000001':{'rows':history,'source':source}}
        with patch('research_sectors.fetch_text') as fetch:
            rows,sources=collect_sector_histories({'board':quote},'2026-10-30T10:00:10+08:00',cached=cached)
        fetch.assert_not_called()
        self.assertEqual(rows['tencent:sh000001'],history)
        self.assertEqual(sources[0]['as_of'],'2026-10-29')

    def basket(self):
        rows=[member(),member('000001.SZ')]
        for row in rows:
            row['history']=[p for p in row['history'] if p['date']<'2026-10-30']
            row['financials']['ann_date']='2026-10-29'
        return {'sector_leaders':{BOARD['id']:rows},'sources':[]}

    def quote(self,code,change):
        return {'name':code,'as_of':'2026-10-30T10:00:00+08:00','trade_date':'2026-10-30',
                'close':10*(1+change/100),'pct_chg':change,'amount':1000,'is_intraday':True}

    def test_new_quotes_change_trend_and_score_without_changing_closed_history_or_financials(self):
        from research_leader_index import build_indicator,apply_indicator,refresh_custom_scores
        from research_sectors import analyze_sector
        baseline=self.basket();before=copy.deepcopy(baseline);results=[]
        for change in (-5,5):
            with patch('research_public_data.fetch_quotes',side_effect=lambda codes,_:{c:self.quote(c,change) for c in codes}):
                company=refresh_company_quotes(baseline,'2026-10-30T10:00:10+08:00')
            rows=company['sector_leaders'][BOARD['id']]
            self.assertEqual(rows[0]['financials'],before['sector_leaders'][BOARD['id']][0]['financials'])
            bundle=build_indicator(BOARD,rows,'2026-10-30T10:00:10+08:00')
            row=analyze_sector(BOARD,bundle['quote'],bundle['history'],[bundle['source']],[],
                '2026-10-30T10:00:10+08:00',{'mode':'risk_on'})
            apply_indicator(row,bundle,rows,'2026-10-30T10:00:10+08:00')
            refresh_custom_scores({'sector_analysis':[row],'as_of':'2026-10-30T10:00:10+08:00'})
            self.assertTrue(row['metrics']['is_intraday'])
            self.assertEqual(row['custom_index']['history_end'],'2026-10-29')
            self.assertEqual(row['custom_index']['live_point']['date'],'2026-10-30')
            results.append(row)
        self.assertLess(results[0]['score_components']['trend_points'],results[1]['score_components']['trend_points'])
        self.assertLess(results[0]['recommendation_index'],results[1]['recommendation_index'])
        self.assertEqual(baseline,before)

    def test_missing_quote_does_not_reuse_old_quote_or_shrink_basket_into_complete_score(self):
        from research_leader_index import build_indicator
        baseline=self.basket()
        with patch('research_public_data.fetch_quotes',return_value={'600000.SH':self.quote('600000.SH',1)}):
            company=refresh_company_quotes(baseline,'2026-10-30T10:00:10+08:00')
        rows=company['sector_leaders'][BOARD['id']]
        self.assertEqual(rows[1]['quote'],{})
        self.assertFalse(build_indicator(BOARD,rows,'2026-10-30T10:00:10+08:00')['meta']['ready'])


class RetentionTests(unittest.TestCase):
    def test_valid_narrative_preserves_unlock_identity_price_and_original_date(self):
        from test_research_sector_ai import CONFIG
        previous=enrich_sector_report(evidence(1),CONFIG,requester=lambda _,ids,__:response(ids))
        previous['as_of']='2026-10-30T14:50:00+08:00'
        previous['sector_analysis'][0]['ai_generated_at']=previous['as_of']
        fresh=evidence(1);fresh['as_of']='2026-10-30T14:55:00+08:00'
        old=previous['sector_analysis'][0];old_id=content_identity(old)
        retain_interpretations(fresh,previous,CONFIG)
        new=fresh['sector_analysis'][0]
        self.assertTrue(new['ai_live_retained'])
        self.assertEqual(content_identity(new),old_id)
        self.assertEqual(new['ai_generated_at'],old['ai_generated_at'])
        self.assertEqual(interpretation_price(new),interpretation_price(old))
        for change in ({'risk':'高风险'},{'status':'stale'}):
            value=evidence(1);value['as_of']=fresh['as_of'];value['sector_analysis'][0].update(change)
            retain_interpretations(value,previous,CONFIG)
            self.assertNotIn('ai_reason',value['sector_analysis'][0])

    def test_event_reuse_keeps_assessment_date_new_or_expired_events_remain_pending(self):
        from research_event_ai import enrich_event_report
        previous=enrich_event_report(event_report(),EVENT_CONFIG,requester=lambda *_:event_response())
        previous['ai_research']={'revision':EVENT_CONFIG['revision']}
        previous['event_analysis']['generated_at']=previous['as_of']
        fresh=event_report();fresh['as_of']='2026-10-31T09:15:00+08:00'
        retain_interpretations(fresh,previous,EVENT_CONFIG)
        self.assertTrue(fresh['event_analysis']['retained'])
        self.assertEqual(fresh['event_analysis']['as_of'],previous['as_of'])
        self.assertEqual(fresh['event_analysis']['request_count'],0)
        value=event_report(2);value['as_of']=fresh['as_of']
        retain_interpretations(value,previous,EVENT_CONFIG)
        self.assertEqual(value['event_analysis']['status'],'partial')
        self.assertGreater(value['event_analysis']['unassessed_count'],0)
        expired=event_report();expired['as_of']='2026-11-08T09:15:00+08:00'
        retain_interpretations(expired,previous,EVENT_CONFIG)
        self.assertNotIn('event_analysis',expired)


if __name__=='__main__':
    unittest.main()
