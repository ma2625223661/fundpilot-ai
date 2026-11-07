import copy
import hashlib
import unittest
from datetime import date, timedelta

import research_dynamic_boards as dynamic
from research_holdings import holdings_row_limit


AS_OF = '2026-10-30'


def stock(code='600001', weight=30, industry='光学光电子', **updates):
    result = {'code': code, 'name': '展示名称', 'instrument_type': 'stock',
              'weight_pct': weight, 'tag_status': 'ok', 'tags': ['概念与交易标签'],
              'industry_tags': [industry] if industry else [],
              'industry_source_url': 'https://datacenter.eastmoney.com/stock/' + code,
              'industry_source_field': 'INDEXNAME'}
    result.update(updates)
    return result


def fund(code='000001', rows=None, **updates):
    result = {'code': code, 'name': '基金名称仅用于展示', 'holdings': {
        'status': 'ok', 'report_date': '2026-09-30',
        'rows': rows if rows is not None else [stock(), stock('600002', 20, '银行')],
        'source_url': 'https://fundf10.eastmoney.com/ccmx_' + code + '.html',
        'invalid_row_count': 0}}
    result.update(updates)
    return result


def lookthrough():
    article = 'AN202610300000000001'
    return {'row_limit': 20, 'target_code': '512800', 'article_id': article,
            'target_weight_pct': 90, 'market_value': 10000000, 'report_date': '2026-09-30',
            'target_stock_report_date': '2026-09-30',
            'source_url': 'https://fund.eastmoney.com/gonggao/000001,' + article + '.html',
            'content_source_url': 'https://np-cnotice-stock.eastmoney.com/api/content/ann?client_source=web&show_all=1&art_code=' + article,
            'target_stock_source_url': 'https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?FCODE=512800&deviceid=Wap&plat=Wap&product=EFund&version=2.0.0',
            'method': '原基金实际ETF权重×目标ETF披露股票占净值权重÷100'}


class DynamicBoardTests(unittest.TestCase):
    def test_sourced_majority_creates_missing_board_with_full_ratio_and_sources(self):
        result = dynamic.discover_dynamic_boards([fund()], {}, AS_OF)
        self.assertEqual(len(result), 1)
        board = result[0]
        self.assertEqual(board['label'], '光学光电子')
        self.assertEqual(board['tags'], ['光学光电子'])
        self.assertTrue(board['dynamic'])
        self.assertTrue(board['requires_holdings_match'])
        self.assertEqual(board['specificity'], 1)
        self.assertEqual(board['hierarchy_depth'], 1)
        evidence = board['evidence'][0]
        self.assertEqual(evidence['matched_weight_pct'], 30)
        self.assertEqual(evidence['disclosed_weight_pct'], 50)
        self.assertEqual(evidence['matched_disclosed_pct'], 60)
        self.assertEqual(evidence['coverage_pct'], 100)
        self.assertFalse(evidence['ratio_is_lower_bound'])
        self.assertEqual(evidence['report_date'], '2026-09-30')
        self.assertIn('ccmx_000001.html', evidence['source_url'])
        self.assertEqual(evidence['stock_evidence'][0]['source_field'], 'INDEXNAME')
        self.assertIn('仅代表已披露部分', evidence['scope'])
        self.assertIn('不代表实时总仓位', evidence['scope'])

    def test_unknown_classification_remains_in_denominator_and_records_lower_bound(self):
        rows = [stock(weight=30), stock('600002', 20, None, tag_status='unknown')]
        result = dynamic.discover_dynamic_boards([fund(rows=rows)], {}, AS_OF)
        evidence = result[0]['evidence'][0]
        self.assertEqual(evidence['matched_disclosed_pct'], 60)
        self.assertTrue(evidence['ratio_is_lower_bound'])
        self.assertEqual(evidence['coverage_pct'], 60)
        self.assertEqual(evidence['unclassified_disclosed_pct'], 40)
        rows[0]['weight_pct'] = 10
        self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=rows)], {}, AS_OF), [])

    def test_majority_uses_exact_decimal_and_has_no_75_percent_gate(self):
        for weight, expected in [(50, False), (49.999999, False), (50.000001, True), (60, True), (75, True)]:
            with self.subTest(weight=weight):
                rows = [stock(weight=weight), stock('600002', 100 - weight, None)]
                result = dynamic.discover_dynamic_boards([fund(rows=rows)], {}, AS_OF)
                self.assertEqual(bool(result), expected)

    def test_plain_concept_tags_and_unsourced_industry_tags_do_not_create_boards(self):
        for updates in ({'industry_tags': []}, {'industry_source_url': ''},
                        {'industry_tags': [], 'tag_evidence': [{'tag': '算力租赁', 'kind': 'concept', 'source_url': 'https://example.com/stock'}]},
                        {'tag_status': 'unknown'}, {'industry_source_url': 'javascript:alert(1)'},
                        {'industry_source_url': 'https://user:secret@example.com/stock'}):
            with self.subTest(updates=updates):
                rows = [stock(weight=50, tags=['光学光电子'], **updates)]
                self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=rows)], {}, AS_OF), [])

    def test_explicit_industry_evidence_supports_identity_source_and_depth(self):
        row = stock(weight=50, industry=None, tag_evidence=[{
            'tag': '光学元件', 'kind': 'industry', 'source_url': 'https://example.com/classification',
            'source_field': 'industry.level3', 'hierarchy_depth': 3, 'security_code': '600001'}])
        board = dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF)[0]
        self.assertEqual(board['label'], '光学元件')
        self.assertEqual(board['hierarchy_depth'], 3)
        row['tag_evidence'][0]['security_code'] = '600002'
        self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF), [])

    def test_industry_tag_dicts_preserve_the_explicit_classification_contract(self):
        row = stock(weight=50, industry=None, industry_tags=[{
            'tag': '光学元件', 'source_url': 'https://example.com/industry', 'level': 3}])
        board = dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF)[0]
        self.assertEqual(board['hierarchy_depth'], 3)
        row['industry_tags'][0]['kind'] = 'concept'
        self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF), [])

    def test_channels_index_memberships_events_and_styles_never_become_industries(self):
        for tag in ['融资融券', '沪股通', '深股通', '港股通', 'MSCI中国', '富时罗素',
                    '沪深300', '中证500', 'ETF重仓', '业绩预增', 'ST板块', '*ST',
                    '回购增持', '股权转让', '次新股', '高股息', '昨日涨停']:
            with self.subTest(tag=tag):
                self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=[stock(weight=50, industry=tag)])], {}, AS_OF), [])

    def test_existing_exact_tag_suppresses_duplicate_but_parent_does_not_hide_new_child(self):
        funds = [fund()]
        self.assertEqual(dynamic.discover_dynamic_boards(funds, {'sector_optics': {'光学光电子'}}, AS_OF), [])
        result = dynamic.discover_dynamic_boards(funds, {'sector_technology': {'电子', '计算机'}}, AS_OF)
        self.assertEqual(result[0]['label'], '光学光电子')
        self.assertEqual([entry['id'] for entry in dynamic.discover_dynamic_boards(funds, {}, AS_OF, registry=result)], [result[0]['id']])
        self.assertEqual([entry['id'] for entry in dynamic.discover_dynamic_boards(funds, {}, AS_OF, registry={'boards': result})], [result[0]['id']])
        wine = fund(rows=[stock(weight=50, industry='白酒Ⅲ')])
        self.assertEqual(dynamic.discover_dynamic_boards([wine], {'sector_liquor': {'白酒', '白酒Ⅱ'}}, AS_OF), [])
        wine2 = fund('000002', rows=[stock(weight=50, industry='白酒Ⅱ')])
        self.assertEqual(len(dynamic.discover_dynamic_boards([wine, wine2], {}, AS_OF)), 1)

    def test_names_do_not_change_classification_ids_or_priority(self):
        funds = [fund(), fund('000002', [stock(weight=45), stock('600002', 5, '银行')])]
        before = dynamic.discover_dynamic_boards(funds, {}, AS_OF)
        for item in funds:
            item['name'] = '银行保险白酒基金'
            for row in item['holdings']['rows']:
                row['name'] = '无行业线索'
        after = dynamic.discover_dynamic_boards(funds, {}, AS_OF)
        self.assertEqual([(item['id'], item['label'], item['best_matched_disclosed_pct']) for item in before],
                         [(item['id'], item['label'], item['best_matched_disclosed_pct']) for item in after])
        self.assertEqual(after[0]['evidence'][0]['fund_code'], '000002')
        self.assertEqual(after[0]['supporting_fund_count'], 2)

    def test_more_matching_weight_ranks_first_and_deeper_industry_breaks_ties(self):
        funds = [fund('000001', [stock(weight=30, industry='光学光电子'), stock('600002', 20, None)]),
                 fund('000002', [stock(weight=40, industry='塑料制品'), stock('600002', 10, None)]),
                 fund('000003', [stock(weight=40, industry='光学元件', industry_level=3), stock('600002', 10, None)])]
        result = dynamic.discover_dynamic_boards(funds, {}, AS_OF)
        self.assertEqual([board['label'] for board in result], ['光学元件', '塑料制品', '光学光电子'])

    def test_invalid_rows_do_not_inflate_share_by_being_dropped(self):
        valid = stock(weight=30)
        invalid_rows = [None, {**valid, 'code': ''}, {**valid, 'instrument_type': None},
                        {**valid, 'code': '600002', 'weight_pct': float('nan')},
                        {**valid, 'code': '600002', 'weight_pct': True},
                        {**valid, 'code': '600002', 'weight_pct': float('inf')},
                        {**valid, 'code': '600002', 'weight_pct': -1},
                        {**valid, 'code': '600002', 'weight_pct': 101}, valid]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid):
                self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=[valid, invalid])], {}, AS_OF), [])
        item = fund()
        item['holdings']['invalid_row_count'] = 1
        self.assertEqual(dynamic.discover_dynamic_boards([item], {}, AS_OF), [])

    def test_explicit_nonstock_rows_are_excluded_without_lookthrough(self):
        row = stock('512800', 90, '光学光电子', instrument_type='fund')
        self.assertEqual(dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF), [])
        result = dynamic.discover_dynamic_boards([fund(rows=[stock(weight=10), row])], {}, AS_OF)
        self.assertEqual(result[0]['evidence'][0]['disclosed_weight_pct'], 10)
        self.assertEqual(result[0]['evidence'][0]['matched_disclosed_pct'], 100)

    def test_stale_future_missing_reports_and_source_without_url_are_rejected(self):
        for report in ('2026-11-01', '2026-01-01', None, 'bad date'):
            item = fund()
            item['holdings']['report_date'] = report
            self.assertEqual(dynamic.discover_dynamic_boards([item], {}, AS_OF), [])
        item = fund()
        item['holdings']['source_url'] = ''
        self.assertEqual(dynamic.discover_dynamic_boards([item], {}, AS_OF), [])
        item = fund()
        item['holdings']['report_date'] = (date(2026, 10, 30) - timedelta(days=180)).isoformat()
        self.assertTrue(dynamic.discover_dynamic_boards([item], {}, AS_OF))
        self.assertEqual(dynamic.discover_dynamic_boards([fund()], {}, 'bad date'), [])

    def test_definition_and_evidence_counts_are_bounded_and_inputs_are_not_mutated(self):
        funds = [fund(f'{index + 1:06}', [stock(weight=40, industry=f'真实行业{index:03}')]) for index in range(150)]
        before = copy.deepcopy(funds)
        result = dynamic.discover_dynamic_boards(funds, {}, AS_OF, limit=999)
        self.assertEqual(len(result), 24)
        self.assertEqual(dynamic.discover_dynamic_boards(funds, {}, AS_OF, limit=0), [])
        self.assertEqual(funds, before)
        proposals = []
        for index in range(150):
            proposals += dynamic.discover_dynamic_boards(funds[index:index + 1], {}, AS_OF)
        registry = dynamic.merge_dynamic_board_registry([], proposals, AS_OF, limit=999)
        self.assertEqual(len(registry), 128)
        self.assertEqual(dynamic.merge_dynamic_board_registry(registry, proposals, AS_OF), registry)
        self.assertEqual(dynamic.merge_dynamic_board_registry(registry, proposals, AS_OF, limit=0), [])

    def test_registry_preserves_stable_id_and_adds_evidence_without_duplicates(self):
        first = dynamic.discover_dynamic_boards([fund()], {}, AS_OF)
        expected = 'sector_dynamic_' + hashlib.sha256('光学光电子'.encode('utf-8')).hexdigest()[:12]
        self.assertEqual(first[0]['id'], expected)
        second = dynamic.discover_dynamic_boards([fund('000002', [stock(weight=50)])], {}, AS_OF)
        before = copy.deepcopy(first)
        merged = dynamic.merge_dynamic_board_registry(first, second, '2026-10-31')
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['id'], expected)
        self.assertEqual(merged[0]['updated_at'], '2026-10-31')
        self.assertEqual(merged[0]['supporting_fund_count'], 2)
        self.assertEqual(merged[0]['best_matched_disclosed_pct'], 100)
        self.assertEqual({item['fund_code'] for item in merged[0]['evidence']}, {'000001', '000002'})
        self.assertEqual(first, before)
        merged[0]['evidence'][0]['fund_code'] = '999999'
        self.assertEqual(first, before)

    def test_only_credible_etf_lookthrough_allows_twenty_rows(self):
        rows = [stock(f'{600000 + index:06}', 2) for index in range(20)]
        item = fund(rows=rows)
        self.assertEqual(dynamic.discover_dynamic_boards([item], {}, AS_OF), [])
        item['holdings']['lookthrough'] = {'row_limit': 20}
        self.assertEqual(dynamic.discover_dynamic_boards([item], {}, AS_OF), [])
        item['holdings']['lookthrough'] = lookthrough()
        self.assertEqual(holdings_row_limit(item['holdings']), 20)
        result = dynamic.discover_dynamic_boards([item], {}, AS_OF)
        self.assertEqual(len(result[0]['evidence'][0]['stock_evidence']), 20)
        restored = dynamic.merge_dynamic_board_registry([], result, AS_OF)
        self.assertEqual(restored, result)
        result[0]['evidence'][0]['lookthrough']['target_code'] = 'bad'
        self.assertEqual(dynamic.merge_dynamic_board_registry([], result, AS_OF), [])

    def test_bad_saved_registry_evidence_is_rejected_without_crashing_or_promotion(self):
        original = dynamic.discover_dynamic_boards([fund()], {}, AS_OF)
        changes = [('fund_code', 'bad'), ('source_url', 'javascript:bad'),
                   ('report_date', '2027-01-01'), ('report_date', '2025-01-01'),
                   ('matched_weight_pct', '30'), ('matched_weight_pct', True),
                   ('matched_disclosed_pct', float('nan')), ('coverage_pct', float('inf')),
                   ('disclosed_weight_pct', {}), ('classification_sources', []),
                   ('stock_evidence', []), ('matched_disclosed_pct', 75)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                saved = copy.deepcopy(original)
                saved[0]['evidence'][0][key] = value
                self.assertEqual(dynamic.merge_dynamic_board_registry([], saved, AS_OF), [])
        saved = copy.deepcopy(original)
        saved[0]['evidence'][0]['stock_evidence'][0]['tag'] = '银行'
        self.assertEqual(dynamic.merge_dynamic_board_registry([], saved, AS_OF), [])
        self.assertEqual(len(dynamic.discover_dynamic_boards([fund()], {}, AS_OF, registry=saved)), 1)
        saved = copy.deepcopy(original)
        saved[0].update(best_matched_disclosed_pct='bad', supporting_fund_count={}, hierarchy_depth={})
        result = dynamic.merge_dynamic_board_registry([], saved, AS_OF)
        self.assertEqual(result[0]['best_matched_disclosed_pct'], 60)
        self.assertEqual(result[0]['supporting_fund_count'], 1)
        self.assertEqual(result[0]['hierarchy_depth'], 1)

    def test_plural_mobile_industry_evidence_keeps_original_source_after_tag_merge(self):
        row = stock(weight=50, industry=None, tag_evidence=[{
            'tags': ['光学元件'], 'kind': 'industry', 'source_url': 'https://example.com/mobile',
            'source_field': 'INDEXNAME', 'hierarchy_depth': 3, 'security_code': '600001'}])
        row['industry_tags'] = ['光学元件']
        row['industry_source_url'] = ''
        row['tag_source_url'] = 'https://example.com/PageAjax'
        board = dynamic.discover_dynamic_boards([fund(rows=[row])], {}, AS_OF)[0]
        self.assertEqual(board['evidence'][0]['classification_sources'], ['https://example.com/mobile'])

    def test_registered_industry_refreshes_its_evidence_without_using_new_board_budget(self):
        original = dynamic.discover_dynamic_boards([fund()], {}, AS_OF)
        newer = fund('000002', [stock(weight=50)])
        updates = dynamic.discover_dynamic_boards([newer], {original[0]['id']: {'光学光电子'}},
                                                 '2026-10-31', registry=original, limit=0)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['id'], original[0]['id'])
        self.assertEqual(updates[0]['discovered_at'], AS_OF)
        self.assertEqual(updates[0]['updated_at'], '2026-10-31')
        self.assertEqual(updates[0]['evidence'][0]['fund_code'], '000002')
        merged = dynamic.merge_dynamic_board_registry(original, updates, '2026-10-31')
        self.assertEqual(merged[0]['updated_at'], '2026-10-31')
        self.assertEqual(merged[0]['supporting_fund_count'], 2)
        self.assertEqual(merged[0]['best_matched_disclosed_pct'], 100)


if __name__ == '__main__':
    unittest.main()
