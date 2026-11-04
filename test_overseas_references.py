import copy
import json
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import research_overseas_references as r


NOW='2026-10-31T13:15:00+08:00'


def payload(spec=None):
    spec=spec or r.REFERENCES['overseas_in_equity']
    zone=ZoneInfo(spec['zone']);day=datetime(2026,10,30,15,30,tzinfo=zone)
    days=[]
    while len(days)<80:
        if day.weekday()<5:days.append(day)
        day-=timedelta(days=1)
    days.reverse()
    meta={'symbol':spec['symbol'],'instrumentType':'INDEX','currency':spec['currency'],
        'exchangeTimezoneName':spec['zone'],'longName':' '.join(spec['tokens']),
        'regularMarketTime':days[-1].timestamp(),
        'currentTradingPeriod':{'regular':{'end':days[-1].timestamp()}}}
    return {'chart':{'result':[{'meta':meta,'timestamp':[day.timestamp() for day in days],
        'indicators':{'quote':[{'close':[100+i for i in range(len(days))]}]}}]}}


def hk_payload(symbol='HSI',as_of='2026-11-02T20:00:00+08:00'):
    from research_overseas import recent_sessions
    days=recent_sessions('HK',as_of,80)
    quote=['']*76
    name,english=('恒生指数','Hang Seng Index') if symbol=='HSI' else ('恒生科技指数','Hang Seng TECH Index')
    quote[1],quote[2],quote[3]=name,symbol,'179'
    quote[30],quote[46],quote[63],quote[75]=days[-1]+' 16:30:00',english,'ZS','HKD'
    quote[30]=quote[30].replace('-','/')
    return {'code':0,'data':{'hk'+symbol:{'qt':{'hk'+symbol:quote},
        'day':[[day,'100',str(100+i)] for i,day in enumerate(days)]}}}


class ForeignReferenceTests(unittest.TestCase):
    def test_hk_index_provider_requires_exact_identity_and_completed_close(self):
        now='2026-11-02T20:00:00+08:00'
        for symbol,identity in [('HSI','overseas_hang_seng'),('HSTECH','overseas_hang_seng_technology')]:
            p=hk_payload(symbol)
            rows=r.parse_tencent_hk_index(p,identity,now)
            self.assertEqual((len(rows),rows[-1]['date']),(80,'2026-11-02'))
            for index,value in [(2,'wrong'),(46,'other index'),(63,'ETF'),(75,'USD'),(3,'180')]:
                bad=copy.deepcopy(p);bad['data']['hk'+symbol]['qt']['hk'+symbol][index]=value
                with self.subTest(symbol=symbol,index=index),self.assertRaises(ValueError):
                    r.parse_tencent_hk_index(bad,identity,now)
            missing=copy.deepcopy(p);missing['data']['hk'+symbol]['day'].pop()
            with self.assertRaisesRegex(ValueError,'最近交易日'):
                r.parse_tencent_hk_index(missing,identity,now)

    def test_hk_intraday_identity_never_promotes_unfinished_bar(self):
        p=hk_payload()
        p['data']['hkHSI']['qt']['hkHSI'][30]='2026/11/02 14:00:00'
        rows=r.parse_tencent_hk_index(p,'overseas_hang_seng','2026-11-02T14:01:00+08:00')
        self.assertEqual(rows[-1]['date'],'2026-10-30')

    def test_hsi_collection_uses_verified_same_index_source_and_session_cache_key(self):
        with patch('research_overseas._cached',return_value=json.dumps(hk_payload())) as cache:
            q,sources,key,history=r._collect('overseas_hang_seng','2026-11-02T20:00:00+08:00')
        self.assertTrue(r.reference_quote_fresh(q,'2026-11-02T20:00:00+08:00'))
        self.assertEqual(q['name'],'恒生指数')
        self.assertEqual(q['as_of'],'2026-11-02')
        self.assertIn('HSI:2026-11-02',cache.call_args.args[0])
        self.assertTrue(all(s['name'].startswith('腾讯财经') for s in sources))

    def test_euro_missing_currency_retains_index_points_without_inventing_currency(self):
        spec=r.REFERENCES['overseas_eu_equity'];p=payload(spec)
        meta=p['chart']['result'][0]['meta'];meta.update(currency=None,exchangeName='ZRH')
        rows,checked=r.parse_index(p,spec,NOW)
        self.assertTrue(rows);self.assertIsNone(checked['currency'])
        for field,value in [('currency','USD'),('symbol','other'),('exchangeName','unknown')]:
            bad=copy.deepcopy(p);bad['chart']['result'][0]['meta'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):r.parse_index(bad,spec,NOW)

    def test_identity_currency_type_and_zone_are_required(self):
        for key,value in [('symbol','other'),('currency','USD'),('instrumentType','ETF'),('exchangeTimezoneName','Asia/Shanghai')]:
            p=payload();p['chart']['result'][0]['meta'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):r.parse_index(p,r.REFERENCES['overseas_in_equity'],NOW)

    def test_only_complete_local_day_is_retained(self):
        p=payload();result=p['chart']['result'][0]
        result['meta']['regularMarketTime']=datetime(2026,10,30,13,50,tzinfo=ZoneInfo('Asia/Kolkata')).timestamp()
        rows,_=r.parse_index(p,r.REFERENCES['overseas_in_equity'],'2026-10-30T16:25:00+08:00')
        self.assertEqual(rows[-1]['date'],'2026-10-29')

    def test_stale_future_and_short_history_are_rejected(self):
        for mode in ['stale','future','short']:
            p=payload();v=p['chart']['result'][0]
            if mode=='stale':v['meta']['regularMarketTime']-=86400*10
            elif mode=='future':v['meta']['regularMarketTime']+=86400*10
            else:v['timestamp']=v['timestamp'][-60:];v['indicators']['quote'][0]['close']=v['indicators']['quote'][0]['close'][-60:]
            with self.subTest(mode=mode),self.assertRaises(ValueError):r.parse_index(p,r.REFERENCES['overseas_in_equity'],NOW)

    def quote(self):
        return {'score_scope':'reference_trend','reference_session_completed':True,
            'reference_timezone':'Asia/Kolkata','reference_observed_at':NOW,
            'reference_latest_completed_date':'2026-10-30','reference_session_end':'2026-10-30T15:30:00+05:30',
            'as_of':'2026-10-30','market':'IN'}

    def test_native_freshness_expires_after_unverified_next_close(self):
        q=self.quote()
        self.assertTrue(r.reference_quote_fresh(q,NOW))
        self.assertFalse(r.reference_quote_fresh(q,'2026-11-02T18:30:00+08:00'))
        self.assertFalse(r.reference_quote_fresh(dict(q,as_of='2026-10-29'),NOW))
        self.assertFalse(r.reference_quote_fresh(dict(q,reference_session_completed=False),NOW))
        self.assertFalse(r.reference_quote_fresh(dict(q,reference_observed_at='2026-11-01T13:15:00+08:00'),NOW))

    def test_hk_uses_hk_completed_session_not_weekday_guess(self):
        q=dict(self.quote(),reference_timezone='Asia/Hong_Kong',market='HK')
        self.assertTrue(r.reference_quote_fresh(q,NOW))
        q.update(as_of='2026-10-19',reference_latest_completed_date='2026-10-19',
            reference_observed_at='2026-10-20T08:00:00+08:00')
        self.assertFalse(r.reference_quote_fresh(q,'2026-10-20T08:00:00+08:00'))

    def test_vn_identity_requires_index_and_exact_exchange(self):
        metadata={'symbol':'VNINDEX','ticker':'VNINDEX','type':'INDEX','exchange-listed':'HOSE',
            'timezone':'Asia/Bangkok','session':'0900-1500'}
        p=payload();v=p['chart']['result'][0]
        bars={'s':'ok','t':v['timestamp'],'c':v['indicators']['quote'][0]['close']}
        rows=r.parse_vnindex(bars,metadata,NOW)
        self.assertEqual(rows[-1]['date'],'2026-10-30')
        for key,value in [('symbol','VNIETF'),('type','stock'),('exchange-listed','HNX')]:
            with self.subTest(key=key),self.assertRaises(ValueError):r.parse_vnindex(bars,dict(metadata,**{key:value}),NOW)

    def collected(self,key,as_of):
        days=[row['date'] for row in r.parse_index(payload(),r.REFERENCES['overseas_in_equity'],NOW)[0]]
        slope=2 if key=='overseas_in_equity' else 1
        history=[{'date':day,'close':100+slope*i}for i,day in enumerate(days)]
        q=dict(self.quote(),board_id=key)
        return q,[],key,history

    def test_composite_requires_all_members_and_uses_returns_not_index_levels(self):
        spec={'name':'有限样本','members':['overseas_in_equity','overseas_jp_equity'],'scope':'各本币收益等权，不含汇率'}
        with patch.dict(r.COMPOSITES,{'test':spec},clear=True),patch.object(r,'_collect',side_effect=self.collected):
            quotes,_,histories=r.collect_overseas_references([{'id':'test'}],NOW)
        self.assertEqual(len(quotes),1)
        rows=histories[quotes[0]['history_secid']]
        self.assertEqual(rows[0]['close'],100)
        self.assertAlmostEqual(rows[1]['close'],101.5)
        self.assertTrue(r.reference_quote_fresh(quotes[0],NOW))
        def missing(key,as_of):
            if key=='overseas_jp_equity':raise ValueError('source missing')
            return self.collected(key,as_of)
        with patch.dict(r.COMPOSITES,{'test':spec},clear=True),patch.object(r,'_collect',side_effect=missing):
            quotes,sources,_=r.collect_overseas_references([{'id':'test'}],NOW)
        self.assertFalse(quotes)
        self.assertTrue(any(s['id']=='overseas_reference:test' and s['status']=='error' for s in sources))


if __name__=='__main__':unittest.main()
