import copy
import json
import unittest
from unittest.mock import patch
import urllib.parse

import research_discovery as rd


def search_payload(rows):
    values = []
    for code, name in rows:
        values.append({'CATEGORY': 700, 'CODE': code, 'NAME': name,
                       'FundBaseInfo': {'FCODE': code, 'SHORTNAME': name, 'FTYPE': '指数型-股票'}})
    return json.dumps({'ErrCode': 0, 'Datas': values}, ensure_ascii=False)


def product_page(code='000001', name='测试半导体指数A', kind='指数型-股票'):
    return (f'<html><head><title>{name}({code})基金净值_行情—天天基金网</title></head><body>'
            f'<div class="fundDetail-tit"><div>{name}<span>(</span>'
            f'<span class="ui-num">{code}</span></div>)</div>'
            f'<table><tr><td>类型：<a>{kind}</a>&nbsp;|&nbsp;中高风险</td></tr></table>'
            '<p>正文含123456，不能将其当基金代码。</p></body></html>')


def rss(items):
    return '<rss><channel>' + ''.join(f'<item><title>{title}</title><link>{url}</link></item>' for title, url in items) + '</channel></rss>'


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        with rd._cache_lock:
            rd._cache.clear()

    def coverage(self, identity='sector_semiconductor', status='no_match'):
        return [{'id': identity, 'status': status, 'displayed_count': 0}]

    def test_official_search_requires_fund_category_and_matching_structured_identity(self):
        payload = json.loads(search_payload([('000001', '测试半导体指数A')]))
        payload['Datas'] += [
            {'CATEGORY': 600, 'CODE': '399001', 'NAME': '测试指数'},
            {'CATEGORY': 700, 'CODE': '000002', 'NAME': '伪名称',
             'FundBaseInfo': {'FCODE': '000099', 'SHORTNAME': '伪名称'}},
            {'CATEGORY': 700, 'CODE': '000003', 'NAME': '伪名称',
             'FundBaseInfo': {'FCODE': '000003', 'SHORTNAME': '另一个名称'}},
        ]
        self.assertEqual([f['code'] for f in rd.parse_search(json.dumps(payload))], ['000001'])
        for bad in ('{}', '{"ErrCode":1,"Datas":[]}', 'var result = evil();'):
            with self.assertRaises(ValueError):
                rd.parse_search(bad)

    def test_product_identity_comes_from_header_and_title_not_body_or_search_title(self):
        result = rd.parse_product_page(product_page(), '000001')
        self.assertEqual(result, {'code': '000001', 'name': '测试半导体指数A',
                                 'fund_type': '指数型-股票', 'source_url': 'https://fund.eastmoney.com/000001.html'})
        for invalid in (product_page().replace('fundDetail-tit', 'other'),
                        product_page().replace('000001</span>', '000002</span>'),
                        product_page().replace('测试半导体指数A(000001)基金', '另一基金(000001)基金'),
                        '<title>测试(000001)基金</title><p>测试基金000001</p>'):
            with self.assertRaises(ValueError):
                rd.parse_product_page(invalid, '000001')

    def test_product_url_allows_only_exact_trusted_fund_structure(self):
        self.assertEqual(rd.product_url('http://fund.eastmoney.com/000001.html'), 'https://fund.eastmoney.com/000001.html')
        for url in ('https://fund.eastmoney.com.evil.test/000001.html',
                    'https://evil.test/000001.html', 'https://fund.eastmoney.com/stock/000001.html',
                    'https://quote.eastmoney.com/sz000001.html', 'https://fund.eastmoney.com/000001.html?q=other',
                    'https://u:p@fund.eastmoney.com/000001.html', 'https://fund.eastmoney.com:444/000001.html',
                    'file:///000001.html', 'https://fund.eastmoney.com/１２３４５６.html', None):
            self.assertIsNone(rd.product_url(url), url)

    def test_related_etf_navigation_in_title_container_does_not_reject_feeder_identity(self):
        for suffix in ('查看相关ETF&gt;', '查看相关ETF联接&gt;'):
            page = product_page('022275', '合成港股红利ETF联接C').replace(')</div>', ') <a>' + suffix + '</a></div>')
            parsed = rd.parse_product_page(page, '022275')
            self.assertEqual(parsed['name'], '合成港股红利ETF联接C')
            self.assertEqual(parsed['code'], '022275')
        for suffix in ('另一只基金(999999)', '任意宣传'):
            with self.assertRaises(ValueError):
                rd.parse_product_page(product_page().replace(')</div>', ')' + suffix + '</div>'), '000001')

    def test_rss_retains_title_and_product_link_without_reading_arbitrary_codes(self):
        records = rd.parse_bing_rss(rss([
            ('任意宣传123456', 'https://evil.test/123456.html'),
            ('真实基金检索标题', 'http://fund.eastmoney.com/000001.html'),
            ('重复标题', 'https://fund.eastmoney.com/000001.html'),
        ]))
        self.assertEqual(records, [{'code': '000001', 'source_url': 'https://fund.eastmoney.com/000001.html', 'search_title': '真实基金检索标题'}])
        for bad in ('<html>搜索受限</html>', '<!DOCTYPE rss [<!ENTITY e "x">]><rss><channel/></rss>'):
            with self.assertRaises(ValueError):
                rd.parse_bing_rss(bad)

    def test_success_is_discovery_only_with_query_link_title_and_actual_attempts(self):
        def fetch(url, timeout):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, rd.TIMEOUT)
            return search_payload([('000001', '测试半导体指数A')]) if 'FundSearch' in url else product_page()
        before = self.coverage()
        original = copy.deepcopy(before)
        with patch.object(rd, '_fetch_text', side_effect=fetch) as request:
            result = rd.discover_public_candidates(before)
        self.assertEqual(before, original)
        self.assertEqual(request.call_count, 2)
        board = result['boards'][0]
        self.assertEqual(board['status'], 'ok')
        self.assertTrue(board['success'])
        fund = board['candidates'][0]
        for field in ('code', 'name', 'fund_type', 'source_url', 'search_url', 'search_title', 'searched_at'):
            self.assertTrue(fund[field])
        self.assertEqual(fund['status'], 'discovery_only')
        self.assertNotIn('eligible', fund)
        self.assertNotIn('board_id', fund)
        self.assertNotIn('holdings', fund)
        self.assertEqual(len(result['sources']), 2)
        self.assertTrue(all(item['attempted'] and item['success'] and item['query'] for item in result['sources']))

    def test_empty_official_search_falls_back_to_public_rss_and_verifies_real_name(self):
        def fetch(url, timeout):
            if 'FundSearch' in url:
                return search_payload([])
            if 'bing.com' in url:
                return rss([('错误营销标题与999999', 'https://fund.eastmoney.com/000001.html')])
            return product_page()
        with patch.object(rd, '_fetch_text', side_effect=fetch):
            result = rd.discover_public_candidates(self.coverage())
        fund = result['boards'][0]['candidates'][0]
        self.assertEqual(fund['name'], '测试半导体指数A')
        self.assertEqual(fund['code'], '000001')
        self.assertEqual(fund['search_title'], '错误营销标题与999999')
        self.assertEqual(fund['search_provider'], 'bing_rss')
        self.assertEqual(len(result['sources']), 4)

    def test_official_failure_is_preserved_when_rss_succeeds(self):
        def fetch(url, timeout):
            if 'FundSearch' in url:
                raise TimeoutError()
            return rss([('基金', 'https://fund.eastmoney.com/000001.html')]) if 'bing.com' in url else product_page()
        with patch.object(rd, '_fetch_text', side_effect=fetch):
            result = rd.discover_public_candidates(self.coverage())
        self.assertEqual(result['boards'][0]['status'], 'partial')
        self.assertFalse(result['sources'][0]['success'])
        self.assertEqual(result['sources'][0]['status'], 'error')
        self.assertTrue(result['warnings'])

    def test_search_and_page_name_mismatch_is_never_accepted(self):
        def fetch(url, timeout):
            if 'FundSearch' in url:
                return search_payload([('000001', '搜索显示的另一只基金')])
            if 'bing.com' in url:
                return rss([])
            return product_page()
        with patch.object(rd, '_fetch_text', side_effect=fetch):
            result = rd.discover_public_candidates(self.coverage())
        self.assertFalse(result['boards'][0]['candidates'])
        self.assertFalse(result['boards'][0]['success'])
        self.assertIn('名称不一致', result['boards'][0]['error'])

    def test_max_three_boards_and_three_candidates_with_bounded_requests(self):
        rows = [('00000' + str(i), f'测试半导体{i}指数A') for i in range(1, 7)]
        def fetch(url, timeout):
            if 'FundSearch' in url:
                return search_payload(rows)
            code = url.rsplit('/', 1)[1][:-5]
            return product_page(code, dict(rows)[code])
        coverage = [{'id': identity, 'status': 'no_match'} for identity in list(rd.BOARDS)[:6]]
        with patch.object(rd, '_fetch_text', side_effect=fetch) as request:
            result = rd.discover_public_candidates(coverage, limit_boards=1000, max_per_board=1000)
        self.assertEqual(len(result['boards']), 3)
        self.assertEqual(request.call_count, 12)
        self.assertTrue(all(len(item['candidates']) == 3 for item in result['boards']))
        self.assertTrue(all(len(item['attempts']) <= 5 for item in result['boards']))

    def test_all_page_failures_do_not_expand_product_request_budget(self):
        def fetch(url, timeout):
            if 'FundSearch' in url:
                return search_payload([(f'{i:06d}', f'测试{i}基金') for i in range(1, 30)])
            raise TimeoutError()
        with patch.object(rd, '_fetch_text', side_effect=fetch) as request:
            result = rd.discover_public_candidates(self.coverage())
        self.assertEqual(request.call_count, 4)
        self.assertEqual(len(result['sources']), 4)
        self.assertFalse(result['boards'][0]['candidates'])
        self.assertEqual(result['boards'][0]['status'], 'error')

    def test_page_budget_prioritizes_distinct_otc_name_clues_without_granting_eligibility(self):
        rows = [('159001', '测试半导体ETF'), ('000001', '测试半导体混合A'),
                ('000002', '测试半导体混合C'), ('000003', '另一半导体混合C'),
                ('000004', '第三半导体混合C')]
        def fetch(url, timeout):
            if 'FundSearch' in url:
                return search_payload(rows)
            code = url.rsplit('/', 1)[1][:-5]
            return product_page(code, dict(rows)[code])
        with patch.object(rd, '_fetch_text', side_effect=fetch) as request:
            result = rd.discover_public_candidates(self.coverage())
        self.assertEqual(request.call_count, 4)
        candidates = result['boards'][0]['candidates']
        self.assertEqual([item['code'] for item in candidates], ['000002', '000003', '000004'])
        self.assertTrue(all('eligible' not in item for item in candidates))

    def test_no_results_and_errors_are_distinguished(self):
        def empty(url, timeout):
            return search_payload([]) if 'FundSearch' in url else rss([])
        with patch.object(rd, '_fetch_text', side_effect=empty):
            result = rd.discover_public_candidates(self.coverage())
        board = result['boards'][0]
        self.assertEqual(board['status'], 'empty')
        self.assertTrue(board['attempted'])
        self.assertFalse(board['success'])
        self.assertFalse(result['warnings'])
        with patch.object(rd, '_fetch_text', side_effect=TimeoutError()):
            failed = rd.discover_public_candidates(self.coverage(), refresh=True)
        self.assertEqual(failed['boards'][0]['status'], 'error')
        self.assertTrue(failed['boards'][0]['attempted'])
        self.assertTrue(failed['warnings'])

    def test_cache_is_detached_and_retains_original_attempt_time(self):
        def empty(url, timeout):
            return search_payload([]) if 'FundSearch' in url else rss([])
        with patch.object(rd, '_fetch_text', side_effect=empty) as request:
            first = rd.discover_public_candidates(self.coverage())
            first['boards'][0]['query'] = '调用方改动'
            cached = rd.discover_public_candidates(self.coverage())
        self.assertEqual(request.call_count, 3)
        self.assertTrue(cached['boards'][0]['cache_hit'])
        self.assertFalse(cached['boards'][0]['attempted_this_run'])
        self.assertNotEqual(cached['boards'][0]['query'], '调用方改动')
        self.assertEqual(cached['boards'][0]['searched_at'], first['boards'][0]['searched_at'])
        self.assertEqual(cached['sources'][0]['searched_at'], first['sources'][0]['searched_at'])

    def test_unsearched_directions_rotate_ahead_of_cached_directions(self):
        coverage = [{'id': identity, 'status': 'no_match'} for identity in list(rd.BOARDS)[:6]]
        def empty(url, timeout):
            return search_payload([]) if 'FundSearch' in url else rss([])
        with patch.object(rd, '_fetch_text', side_effect=empty):
            first = rd.discover_public_candidates(coverage)
            second = rd.discover_public_candidates(coverage)
        self.assertFalse(set(item['board_id'] for item in first['boards']) & set(item['board_id'] for item in second['boards']))

    def test_saved_search_times_keep_rotation_after_process_cache_is_lost(self):
        ids = list(rd.BOARDS)[:6]
        coverage = [{'id': identity, 'status': 'no_match'} for identity in ids]
        for row in coverage[:3]:
            row['web_search'] = {'searched_at': '2026-10-30T17:00:00+08:00'}
        def empty(url, timeout):
            return search_payload([]) if 'FundSearch' in url else rss([])
        with patch.object(rd, '_fetch_text', side_effect=empty):
            result = rd.discover_public_candidates(coverage)
        self.assertEqual(set(item['board_id'] for item in result['boards']), set(ids[3:]))

    def test_explicit_query_fallback_can_discover_candidates_without_assigning_membership(self):
        queries = []
        def fetch(url, timeout):
            if 'FundSearch' in url:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['key'][0]
                queries.append(query)
                return search_payload([] if query == 'CXO' else [('000001', '合成医疗混合C')])
            return product_page('000001', '合成医疗混合C')
        with patch.object(rd, '_fetch_text', side_effect=fetch):
            result = rd.discover_public_candidates(self.coverage('sector_cxo'))
        self.assertEqual(queries, ['CXO', '医疗'])
        self.assertEqual(result['boards'][0]['candidates'][0]['status'], 'discovery_only')
        self.assertNotIn('board_id', result['boards'][0]['candidates'][0])

    def test_generic_unclassified_bucket_never_spends_public_search_budget(self):
        with patch.object(rd, '_fetch_text', side_effect=AssertionError('not a research direction')):
            result = rd.discover_public_candidates(self.coverage('holdings_unclassified', 'holdings_pending'))
        self.assertFalse(result['boards'])

    def test_network_failures_are_isolated_between_boards(self):
        coverage = self.coverage() + self.coverage('sector_liquor')
        def fetch(url, timeout):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            query = (params.get('key') or params.get('q') or [''])[0]
            if '白酒' in query:
                raise TimeoutError()
            if 'FundSearch' in url:
                return search_payload([('000001', '测试半导体指数A')])
            return product_page()
        with patch.object(rd, '_fetch_text', side_effect=fetch):
            result = rd.discover_public_candidates(coverage)
        by_id = {item['board_id']: item for item in result['boards']}
        self.assertEqual(by_id['sector_liquor']['status'], 'error')
        self.assertEqual(by_id['sector_semiconductor']['status'], 'ok')

    def test_existing_candidates_unresearched_samples_unknown_ids_and_zero_limits_do_not_search(self):
        coverage = [None, {'id': 'unknown', 'status': 'no_match'},
                    {'id': 'sector_semiconductor', 'status': 'candidate'},
                    {'id': 'sector_liquor', 'status': 'not_researched'},
                    {'id': 'sector_cpo', 'status': 'no_match', 'displayed_count': 1}]
        with patch.object(rd, '_fetch_text', side_effect=AssertionError('unexpected network')):
            self.assertFalse(rd.discover_public_candidates(coverage)['boards'])
            self.assertFalse(rd.discover_public_candidates(self.coverage(), limit_boards=0)['boards'])
            self.assertFalse(rd.discover_public_candidates(self.coverage(), max_per_board=0)['boards'])
            self.assertFalse(rd.discover_public_candidates(None)['boards'])


if __name__ == '__main__':
    unittest.main()
