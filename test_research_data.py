import json
import unittest
from unittest.mock import patch
import research_data as rd


class ResearchDataTests(unittest.TestCase):
    def setUp(self):
        with rd._cache_lock:
            rd._cache.clear()

    def test_fund_returns_use_provider_dividend_adjusted_return_not_nav_delta(self):
        rows = [{'x': 1793030400000, 'y': 2.0, 'equityReturn': 1.2, 'unitMoney': ''},
                {'x': 1793116800000, 'y': 1.5, 'equityReturn': 0.1, 'unitMoney': '分红'}]
        js = 'var fS_name="测试基金";var fS_code="110020";var Data_netWorthTrend=' + json.dumps(rows) + ';'
        fund = rd.parse_fund(js, '110020')
        self.assertEqual(fund['history'][-1]['return_pct'], 0.1)
        self.assertEqual(fund['nav'], 1.5)
        self.assertEqual(fund['nav_date'], '2026-10-28')
        with self.assertRaises(ValueError):
            rd.parse_fund(js, '000001')

    def test_js_is_not_executed_and_missing_returns_are_not_invented(self):
        with self.assertRaises(ValueError):
            rd.assignment('var fS_name = function(){ return "evil"; }();', 'fS_name')
        js = 'var fS_name="测试";var fS_code="110020";var Data_netWorthTrend=[{"x":1793116800000,"y":1.2}];'
        self.assertIsNone(rd.parse_fund(js, '110020')['history'][0]['return_pct'])

    def test_quote_timestamp_is_provider_time(self):
        fields = [''] * 34
        fields[1], fields[3], fields[30], fields[32] = '沪深300', '4000', '20261029150000', '-1.25'
        result = rd.parse_market('v_sh000300="' + '~'.join(fields) + '";')
        self.assertEqual(result[0]['change_pct'], -1.25)
        self.assertEqual(result[0]['as_of'], '2026-10-29T15:00:00+08:00')

    def test_news_dates_and_safe_links(self):
        data = {'result': {'data': [
            {'title': '基金市场回顾', 'url': 'https://finance.sina.com.cn/a', 'ctime': '1793116800', 'intro': '<b>摘要</b>'},
            {'title': '基金市场恶意链接', 'url': 'javascript:alert(1)'},
            {'title': '股票索赔律师宣传', 'url': 'https://finance.sina.com.cn/b'},
        ]}}
        result = rd.parse_news(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['summary'], '摘要')
        self.assertEqual(result[0]['published_at'], '2026-10-28T00:00:00+08:00')

    def test_failure_is_visible_and_cached_result_is_independent(self):
        with patch('research_data.fetch_text', side_effect=TimeoutError()):
            result = rd.collect_research(['110020'])
        self.assertEqual(result['funds'], [])
        self.assertEqual(len(result['sources']), 5)
        self.assertTrue(all(source['status'] == 'error' for source in result['sources']))
        result['warnings'].clear()
        cached = rd.collect_research(['110020'])
        self.assertTrue(cached['cache_hit'])
        self.assertTrue(cached['warnings'])

    def test_invalid_codes_rejected_before_network(self):
        with patch('research_data.fetch_text') as fetch:
            for invalid in [['https://example.com'], ['1'], ['../etc/passwd'], [f'{i:06}' for i in range(9)]]:
                with self.assertRaises(ValueError):
                    rd.collect_research(invalid)
            fetch.assert_not_called()

    def test_fund_only_batch_does_not_repeat_common_sources_or_poison_cache(self):
        with patch('research_data.fetch_text', side_effect=TimeoutError()) as fetch:
            reduced = rd.collect_research(['110020'], include_common=False)
            self.assertEqual(len(reduced['sources']), 2)
            self.assertTrue(all(s['id'].startswith(('nav:', 'announcements_')) for s in reduced['sources']))
            self.assertFalse(any('qt.gtimg.cn' in str(call) or 'sina.com' in str(call) for call in fetch.call_args_list))
            full = rd.collect_research(['110020'])
            self.assertEqual(len(full['sources']), 5)
            self.assertFalse(full['cache_hit'])

    def test_one_source_failure_preserves_others(self):
        js = 'var fS_name="测试";var fS_code="110020";var Data_netWorthTrend=[{"x":1793116800000,"y":1.2,"equityReturn":0.3}];'
        def fake_fetch(url, encoding='utf-8-sig'):
            if '/pingzhongdata/' in url:
                return js
            raise TimeoutError()
        with patch('research_data.fetch_text', side_effect=fake_fetch):
            result = rd.collect_research(['110020'])
        self.assertEqual(len(result['funds']), 1)
        self.assertEqual(result['funds'][0]['nav'], 1.2)
        nav_source = next(s for s in result['sources'] if s['id'] == 'nav:110020')
        self.assertEqual(nav_source['status'], 'ok')
        self.assertTrue(any(s['status'] == 'error' for s in result['sources']))

    def test_announcement_metadata_does_not_claim_full_text(self):
        data = {'ErrCode': 0, 'Data': [{'ID': 'AN20261027123456', 'TITLE': '季度报告', 'PUBLISHDATEDesc': '2026-10-27', 'NEWCATEGORY': '3'}]}
        row = rd.parse_announcements(data, '110020')[0]
        self.assertEqual(row['published_at'], '2026-10-27')
        self.assertIn('正文未读取', row['content_scope'])


if __name__ == '__main__':
    unittest.main()
