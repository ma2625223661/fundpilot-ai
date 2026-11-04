import copy
import json
import unittest
from unittest.mock import patch

import research_beijing_history as bj
from research_leader_index import collect_leader_histories

NOW = '2026-10-31T13:30:00+08:00'
CODE = '920414.BJ'


def fixture():
    raw = [{'day': '2026-10-29', 'close': '12'}, {'day': '2026-10-30', 'close': '6'}]
    factors = {'total': 2, 'data': [{'d': '2026-10-30', 'f': '1'}, {'d': '1900-01-01', 'f': '2'}]}
    quote = ['欧普泰', '6', '12', '6'] + ['']*26 + ['2026-10-30', '15:30:00']
    return ['/* provider comment */\nvar=(' + json.dumps(raw) + ');',
            'var bj920414qfq=' + json.dumps(factors) + '\n/* check */',
            'var hq_str_bj920414="' + ','.join(quote) + '";']


class BeijingHistoryTests(unittest.TestCase):
    def parse(self, values):
        return bj.parse_history(*values, CODE, '欧普泰', NOW)

    def test_matches_factor_by_date_and_does_not_invent_split_return(self):
        rows = self.parse(fixture())
        self.assertEqual(rows, [{'date': '2026-10-29', 'close': 6}, {'date': '2026-10-30', 'close': 6}])

    def test_future_factor_does_not_change_asof_anchor(self):
        values = fixture()
        values[1] = 'var bj920414qfq=' + json.dumps({'total':3, 'data':[
            {'d':'2026-11-02','f':'1'}, {'d':'2026-10-30','f':'2'}, {'d':'1900-01-01','f':'4'}]})
        self.assertEqual(self.parse(values), self.parse(fixture()))

    def test_requires_same_security_factor_identity_and_independent_close(self):
        for index, old, new in ((1,'bj920414','bj920493'), (2,'bj920414','bj920493'),
                                (2,'欧普泰','另一公司'), (0,'"6"','"7"')):
            values = fixture()
            values[index] = values[index].replace(old,new)
            with self.subTest(index=index, old=old), self.assertRaises(ValueError):
                self.parse(values)

    def test_missing_truncated_or_invalid_factor_never_assumed_one(self):
        for data in ({'total':0,'data':[]}, {'total':2,'data':[{'d':'1900-01-01','f':'1'}]},
                     {'total':1,'data':[{'d':'1900-01-01','f':'NaN'}]},
                     {'total':1,'data':[{'d':'2026-10-30','f':'1'}]}):
            values=fixture();values[1]='var bj920414qfq='+json.dumps(data)
            with self.subTest(data=data), self.assertRaises(ValueError):self.parse(values)

    def test_stale_daily_close_and_non_bj_codes_rejected(self):
        values=fixture();values[0]=values[0].replace('2026-10-30','2026-10-28')
        with self.assertRaises(ValueError):self.parse(values)
        for code in ('600000.SH','920414.BJ;whoami','920414'):
            with self.assertRaises(ValueError):bj.urls(code)

    def test_collector_keeps_cached_factor_and_identity_evidence(self):
        from test_research_leader_index import member
        row=member(CODE)
        cached={'rows':row['history'],'provider':'sina_bj','url':'https://quotes.sina.cn/test',
                'metadata':{'factor_url':'https://finance.sina.com.cn/factor',
                            'identity_url':'https://hq.sinajs.cn/test','method':bj.METHOD}}
        company={'sector_leaders':{'test':[row]}}
        with patch('research_public_data._get',return_value=cached), \
             patch('research_public_data._save'), \
             patch('research_public_data._fetched_at',return_value=NOW):
            collect_leader_histories(company,NOW)
        self.assertEqual(company['sector_leaders']['test'][0]['history'],cached['rows'])
        ids={s['id'] for s in company['sources']}
        self.assertIn('leader_history_factor:'+CODE,ids)
        self.assertIn('leader_history_identity:'+CODE,ids)


if __name__=='__main__':unittest.main()
