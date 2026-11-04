import copy
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import research_holdings as rh


def html_response(code='161725', day='2026-09-30', rows=None):
    rows = rows or [('600519', '贵州茅台', '18.54%'), ('600809', '山西汾酒', '17.92%')]
    body = ''.join('<tr><td>1</td><td>' + c + '</td><td>' + n + '</td><td>--</td><td>' + w + '</td></tr>' for c, n, w in rows)
    content = f'<h4><a href="http://fund.eastmoney.com/{code}.html">基金</a>截止至：{day}</h4><table><thead><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>最新价</th><th>占净值<br/>比例</th></tr></thead><tbody>{body}</tbody></table>'
    return 'var apidata={content:' + json.dumps(content, ensure_ascii=False) + ',arryear:[2026]};'


def disclosed(rows=None):
    rows = rows or [{'code': '600519', 'name': '贵州茅台', 'weight_pct': 25, 'tags': ['白酒Ⅱ'], 'tag_status': 'ok'},
                    {'code': '600809', 'name': '山西汾酒', 'weight_pct': 15, 'tags': ['白酒Ⅱ'], 'tag_status': 'ok'},
                    {'code': '600036', 'name': '招商银行', 'weight_pct': 10, 'tags': ['银行'], 'tag_status': 'ok'}]
    rows = copy.deepcopy(rows)
    for row in rows:
        if isinstance(row, dict):
            row.setdefault('instrument_type', 'stock')
    return {'code': '161725', 'holdings': {'status': 'ok', 'report_date': '2026-09-30', 'rows': rows,
            'source_url': 'https://fundf10.eastmoney.com/ccmx_161725.html', 'source_id': 'holdings:161725'}}


class HoldingTests(unittest.TestCase):
    def setUp(self):
        with rh._cache_lock:
            rh._cache.clear()
        memberships = patch('research_holdings.fetch_membership_context', return_value={})
        self.memberships = memberships.start()
        self.addCleanup(memberships.stop)

    def test_quoted_html_is_decoded_without_executing_js_and_latest_period_used(self):
        first = html_response(day='2026-06-30')
        older = json.JSONDecoder().raw_decode(first[first.index('content:')+8:])[0]
        newer = json.JSONDecoder().raw_decode(html_response()[first.index('content:')+8:])[0]
        result = rh.parse_holdings('var apidata={content:' + json.dumps(older + newer) + '};', '161725')
        self.assertEqual(result['report_date'], '2026-09-30')
        self.assertEqual(result['rows'][0]['code'], '600519')
        self.assertEqual(result['rows'][0]['weight_pct'], 18.54)
        self.assertEqual(result['disclosed_weight_pct'], 36.46)
        with self.assertRaises(ValueError):
            rh.parse_holdings('var apidata={content:evil()};', '161725')
        with self.assertRaises(ValueError):
            rh.parse_holdings(html_response(code='000001'), '161725')

    def test_weights_require_net_asset_column_and_valid_values(self):
        with self.assertRaises(ValueError):
            rh.parse_holdings(html_response().replace('占净值', '占股票市值'), '161725')
        with self.assertRaises(ValueError):
            rh.parse_holdings(html_response(rows=[('600519','贵州茅台','90%'),('600809','山西汾酒','90%')]), '161725')
        with self.assertRaises(ValueError):
            rh.parse_holdings(html_response().replace('2026-09-30','未来'), '161725')

    def test_security_identity_mismatch_is_not_a_theme(self):
        data = {'ssbk': [{'SECURITY_CODE':'600519','BOARD_NAME':'白酒Ⅱ'}]}
        self.assertEqual(rh.parse_security_tags(data, '600519'), ['白酒Ⅱ'])
        with self.assertRaises(ValueError):
            rh.parse_security_tags(data, '600809')

    def test_matching_uses_disclosed_nav_weight_and_exact_tags(self):
        fund = disclosed()
        result = rh.verify_board(fund, 'sector_liquor', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['weight_pct'], 40)
        self.assertEqual(result['matched_weight_pct'], 40)
        self.assertEqual(result['disclosed_weight_pct'], 50)
        self.assertEqual(result['matched_disclosed_pct'], 80)
        self.assertEqual(result['rule_version'], 'single_board_holdings_rank_v4')
        self.assertIn('取消75%限制', result['rule'])
        self.assertIn('仅代表已披露股票部分', result['rule'])
        self.assertEqual(result['matched_names'], ['贵州茅台', '山西汾酒'])
        self.assertEqual(rh.verify_board(fund, 'sector_cpo', '2026-10-30')['status'], 'mismatch')
        self.assertEqual(rh.verify_board(disclosed([{'code':'300308','name':'通信样本','weight_pct':50,'tags':['通信'],'tag_status':'ok'}]), 'sector_cpo', '2026-10-30')['status'], 'mismatch')
        self.assertEqual(fund, disclosed())

    def test_stale_future_missing_dates_unknown_and_foreign_are_not_promoted(self):
        for timestamp in ('2025-12-31', '2026-11-30', None):
            fund = disclosed()
            fund['holdings']['report_date'] = timestamp
            self.assertEqual(rh.verify_board(fund, 'sector_liquor', '2026-10-30')['status'], 'unknown')
        self.assertEqual(rh.verify_board({}, 'sector_liquor', '2026-10-30')['status'], 'unknown')
        for board in ('overseas_hk_internet', 'index_dual50', 'dividend'):
            self.assertEqual(rh.verify_board(disclosed(), board, '2026-10-30')['status'], 'unknown')
        self.assertEqual(rh.verify_board({}, 'bond')['status'], 'not_required')

    def test_disclosure_age_boundary_keeps_180_days_but_rejects_181(self):
        as_of = datetime(2026, 10, 30).date()
        fund = disclosed()
        fund['holdings']['report_date'] = (as_of - timedelta(days=180)).isoformat()
        self.assertEqual(rh.verify_board(fund, 'sector_liquor', as_of)['status'], 'matched')
        fund['holdings']['report_date'] = (as_of - timedelta(days=181)).isoformat()
        self.assertEqual(rh.verify_board(fund, 'sector_liquor', as_of)['status'], 'unknown')

    def test_partial_or_target_etf_disclosure_never_implies_lookthrough(self):
        rows = [{'code':'512800','name':'金融ETF','weight_pct':90,'tags':['白酒Ⅱ'],'tag_status':'ok','instrument_type':'fund'}]
        self.assertEqual(rh.verify_board(disclosed(rows), 'sector_liquor', '2026-10-30')['status'], 'unknown')
        rows = [{'code':'600519','name':'贵州茅台','weight_pct':10,'tags':['白酒Ⅱ'],'tag_status':'ok'},
                {'code':'600809','name':'未知','weight_pct':50,'tags':[],'tag_status':'unknown'}]
        result = rh.verify_board(disclosed(rows), 'sector_liquor', '2026-10-30')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['coverage_pct'], 16.67)

    def test_duplicate_invalid_and_nonfinite_rows_cannot_inflate_matching_weight(self):
        row = {'code':'600519','name':'贵州茅台','weight_pct':12,'tags':['白酒Ⅱ'],'tag_status':'ok'}
        rows = [row, copy.deepcopy(row), {**row, 'code':'600809','weight_pct':float('nan')},
                {**row, 'code':'600036','weight_pct':True}, {**row, 'code':'','weight_pct':30}]
        result = rh.verify_board(disclosed(rows), 'sector_liquor', '2026-10-30')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['weight_pct'], 12)
        self.assertEqual(result['disclosed_weight_pct'], 12)
        self.assertEqual(result['matched_weight_pct'], 12)

    def test_broad_parent_tags_do_not_verify_distinct_narrow_sectors(self):
        cases = [
            ('sector_healthcare', ['医药生物', '医疗器械']),
            ('sector_gold_equity', ['贵金属']),
            ('sector_semiconductor', ['半导体及元件', 'PCB概念']),
        ]
        for board, tags in cases:
            with self.subTest(board=board):
                rows = [{'code':'600519','name':'测试持仓','weight_pct':50,
                         'tags':tags,'tag_status':'ok'}]
                result = rh.verify_board(disclosed(rows), board, '2026-10-30')
                self.assertEqual(result['status'], 'mismatch')
                self.assertEqual(result['matched_weight_pct'], 0)
        for board, tag in [('sector_healthcare','化学制药'), ('sector_gold_equity','黄金概念'),
                           ('sector_semiconductor','半导体'), ('sector_medical','医疗器械')]:
            with self.subTest(explicit=tag):
                rows = [{'code':'600519','name':'测试持仓','weight_pct':50,
                         'tags':[tag],'tag_status':'ok'}]
                self.assertEqual(rh.verify_board(disclosed(rows), board, '2026-10-30')['status'], 'matched')

    def test_all_added_sector_tags_match_only_their_explicit_exposure(self):
        cases = [
            ('sector_brain_computer', '脑机接口'),
            ('sector_home_appliances', '家电行业'),
            ('sector_coal', '煤炭行业'),
            ('sector_eldercare', '养老概念'),
            ('sector_lithium_mining', '锂矿概念'),
            ('sector_solid_state_battery', '固态电池'),
            ('sector_steel', '钢铁行业'),
            ('sector_rare_earth_magnet', '稀土永磁'),
            ('sector_nonferrous', '有色金属'),
            ('sector_auto_vehicle', '汽车整车'),
            ('sector_power', '电力行业'),
            ('sector_energy_storage', '储能'),
            ('sector_photovoltaic', '光伏设备'),
            ('sector_construction_machinery', '工程机械'),
            ('sector_grid_equipment', '电网设备'),
            ('sector_commercial_aerospace', '商业航天'),
            ('sector_advanced_manufacturing', '先进制造风格'),
            ('sector_memory_chip', '存储芯片'),
            ('sector_mlcc', 'MLCC'),
        ]
        for board, tag in cases:
            with self.subTest(board=board, tag=tag):
                rows = [{'code': '600001', 'name': '没有行业线索的样本证券', 'weight_pct': 30,
                         'tags': [tag], 'tag_status': 'ok', 'instrument_type': 'stock'},
                        {'code': '600002', 'name': '其他证券', 'weight_pct': 5,
                         'tags': ['银行'], 'tag_status': 'ok', 'instrument_type': 'stock'}]
                result = rh.verify_board(disclosed(rows), board, '2026-10-30')
                self.assertEqual(result['status'], 'matched')
                self.assertEqual(result['matched_weight_pct'], 30)
                self.assertEqual(result['disclosed_weight_pct'], 35)
                self.assertEqual(result['coverage_pct'], 100)
                self.assertEqual(result['report_date'], '2026-09-30')
                self.assertEqual(result['source_id'], 'holdings:161725')
                self.assertIn('不代表', result['limitations'])

    def test_new_sector_refinements_reject_parent_and_neighbor_tags(self):
        cases = [
            ('sector_brain_computer', ['医疗器械', '人工智能']),
            ('sector_home_appliances', ['消费', '消费电子']),
            ('sector_coal', ['资源能源', '石油石化']),
            ('sector_eldercare', ['医疗服务', '医药生物']),
            ('sector_lithium_mining', ['能源金属', '锂电池', '电池']),
            ('sector_solid_state_battery', ['电池', '锂电池', '新能源']),
            ('sector_steel', ['资源能源', '有色金属']),
            ('sector_rare_earth_magnet', ['小金属', '有色金属']),
            ('sector_nonferrous', ['资源能源', '煤炭', '钢铁']),
            ('sector_auto_vehicle', ['汽车', '汽车零部件', '新能源车']),
            ('sector_power', ['公用事业', '电力设备', '电网设备']),
            ('sector_energy_storage', ['新能源', '电池', '光伏设备']),
            ('sector_photovoltaic', ['新能源', '储能', '电网设备']),
            ('sector_construction_machinery', ['机械设备', '通用设备', '专用设备']),
            ('sector_grid_equipment', ['电力', '电力设备', '电力行业']),
            ('sector_commercial_aerospace', ['航天装备', '卫星导航', '低空经济']),
            ('sector_advanced_manufacturing', ['机械设备', '工业4.0', '高端装备']),
            ('sector_memory_chip', ['半导体', '芯片概念', '集成电路']),
            ('sector_mlcc', ['电子', '元件', 'PCB概念']),
        ]
        for board, tags in cases:
            with self.subTest(board=board):
                # Even a company/fund name spelling out the wanted sector
                # cannot compensate for missing explicit source membership.
                rows = [{'code': '600001', 'name': board + '专营股票', 'weight_pct': 50,
                         'tags': tags, 'tag_status': 'ok', 'instrument_type': 'stock'}]
                result = rh.verify_board(disclosed(rows), board, '2026-10-30')
                self.assertEqual(result['status'], 'mismatch')
                self.assertEqual(result['matched_weight_pct'], 0)

    def test_majority_admits_below_75_and_uses_unrounded_half_boundary(self):
        for match_weight, other_weight, ratio, expected in (
                (20, 20, 50, 'mismatch'),
                (20.000001, 19.999999, 50.0000025, 'matched'),
                (19.999999, 20.000001, 49.9999975, 'mismatch'),
                (24, 16, 60, 'matched'),
                (28, 12, 70, 'matched'),
                (29.996, 10.004, 74.99, 'matched'),
                (30, 10, 75, 'matched'),
                (30.004, 9.996, 75.01, 'matched'),
                (29.999999, 10.000001, 74.9999975, 'matched'),
                (30.000001, 9.999999, 75.0000025, 'matched'),
                (.21, .07, 75, 'matched')):
            with self.subTest(ratio=ratio):
                rows = [{'code': '600001', 'name': '光伏样本', 'weight_pct': match_weight,
                         'tags': ['光伏设备'], 'tag_status': 'ok'},
                        {'code': '600002', 'name': '其他样本', 'weight_pct': other_weight,
                         'tags': ['银行'], 'tag_status': 'ok'}]
                result = rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['matched_weight_pct'], match_weight)
                self.assertAlmostEqual(result['matched_disclosed_pct'], ratio)

    def test_small_total_nav_passes_when_disclosed_stock_ratio_exceeds_75(self):
        rows = [{'code': '600001', 'name': '光伏样本', 'weight_pct': 6.5,
                 'tags': ['光伏设备'], 'tag_status': 'ok'},
                {'code': '600002', 'name': '其他样本', 'weight_pct': 1.5,
                 'tags': ['银行'], 'tag_status': 'ok'}]
        result = rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_weight_pct'], 6.5)
        self.assertEqual(result['disclosed_weight_pct'], 8)
        self.assertEqual(result['matched_disclosed_pct'], 81.25)
        self.assertIn('不设主题占基金净值最低比例', result['rule'])
        rows[0]['tags'] = ['银行']
        self.assertEqual(rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')['status'], 'mismatch')

    def test_unknown_stock_tags_stay_in_denominator_without_creating_match(self):
        rows = [{'code': '600001', 'name': '光伏样本', 'weight_pct': 30,
                 'tags': ['光伏设备'], 'tag_status': 'ok'},
                {'code': '600002', 'name': '股票标签未取得', 'weight_pct': 10,
                 'tags': [], 'tag_status': 'unknown'}]
        result = rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_disclosed_pct'], 75)
        self.assertEqual(result['disclosed_weight_pct'], 40)
        self.assertEqual(result['coverage_pct'], 75)
        self.assertTrue(result['ratio_is_lower_bound'])
        self.assertEqual(result['unclassified_weight_pct'], 10)
        self.assertEqual(result['unclassified_disclosed_pct'], 25)
        self.assertIn('已确认至少', result['reason'])
        rows[0]['weight_pct'] = 31
        result = rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertAlmostEqual(result['matched_disclosed_pct'], 31 / 41 * 100)

    def test_explicit_nonstock_rows_do_not_enter_stock_denominator(self):
        rows = [{'code': '600001', 'name': '光伏样本', 'weight_pct': 6,
                 'tags': ['光伏设备'], 'tag_status': 'ok'},
                {'code': '600002', 'name': '其他股票', 'weight_pct': 1,
                 'tags': ['银行'], 'tag_status': 'ok'},
                {'code': '512000', 'name': '目标ETF', 'weight_pct': 70,
                 'tags': ['银行'], 'tag_status': 'ok', 'instrument_type': 'fund'},
                {'code': '110001', 'name': '测试债券', 'weight_pct': 20,
                 'tags': ['银行'], 'tag_status': 'ok', 'instrument_type': 'bond'}]
        result = rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['disclosed_weight_pct'], 7)
        self.assertEqual(result['matched_weight_pct'], 6)
        self.assertAlmostEqual(result['matched_disclosed_pct'], 6 / 7 * 100)

    def test_unknown_or_missing_instrument_types_cannot_inflate_stock_ratio(self):
        for instrument in (None, '', 'unknown', {}, []):
            with self.subTest(instrument=instrument):
                fund = disclosed()
                fund['holdings']['rows'][-1]['instrument_type'] = instrument
                result = rh.verify_board(fund, 'sector_liquor', '2026-10-30')
                self.assertEqual(result['status'], 'unknown')
                self.assertIn('类型不明', result['reason'])
        fund = disclosed()
        del fund['holdings']['rows'][-1]['instrument_type']
        self.assertEqual(rh.verify_board(fund, 'sector_liquor', '2026-10-30')['status'], 'unknown')

    def test_stock_identity_cannot_be_inferred_from_etf_or_bond_name(self):
        for name in ('光伏ETF', '光伏主题基金', '光伏可转债'):
            with self.subTest(name=name):
                rows = [{'code': '600001', 'name': name, 'weight_pct': 6,
                         'tags': ['光伏设备'], 'tag_status': 'ok', 'instrument_type': 'stock'}]
                self.assertEqual(rh.verify_board(disclosed(rows), 'sector_photovoltaic', '2026-10-30')['status'], 'unknown')

    def test_parser_only_establishes_stock_identity_from_stock_table(self):
        with self.assertRaises(ValueError):
            rh.parse_holdings(html_response().replace('股票代码', '证券代码').replace('股票名称', '证券名称'), '161725')
        result = rh.parse_holdings(html_response(rows=[('600519', '贵州茅台', '6%'),
                                                      ('512000', '白酒ETF', '70%'),
                                                      ('110001', '样本债券', '20%')]), '161725')
        self.assertEqual([row['instrument_type'] for row in result['rows']], ['stock', 'fund', 'bond'])
        self.assertEqual(result['disclosed_weight_pct'], 6)

    def test_parser_keeps_bad_row_diagnostic_instead_of_inflating_remaining_match(self):
        for bad in [('600809', '其他股票', '--'), ('600519', '重复股票', '6%'),
                    ('不明代码', '其他股票', '20%')]:
            with self.subTest(bad=bad):
                holdings = rh.parse_holdings(html_response(rows=[('600519', '贵州茅台', '6%'), bad]), '161725')
                self.assertEqual(holdings['invalid_row_count'], 1)
                holdings['rows'][0].update(tag_status='ok', tags=['白酒Ⅱ'])
                result = rh.verify_board({'holdings': holdings}, 'sector_liquor', '2026-10-30')
                self.assertEqual(result['status'], 'unknown')
                self.assertIn('不明行', result['reason'])

    def test_new_styles_indices_and_bond_profiles_cannot_bypass_registry_gate(self):
        from research_categories import BOARDS
        boards = [
            'style_dividend_low_volatility', 'style_cashflow', 'style_bluechip',
            'style_microcap', 'style_quant', 'style_small_micro_quant',
            'index_beijing', 'index_sse50', 'index_csi300', 'index_csi500',
            'index_chinext', 'index_star', 'index_dual50', 'dividend',
            'overseas_sp500', 'overseas_nasdaq', 'overseas_asia_pacific',
            'long_bond', 'fixed_income_plus',
        ]
        rows = [{'code': '600001', 'name': '名称不提供证据', 'weight_pct': 50,
                 'tags': ['沪股通', '上证50_', '沪深300_', '中证500_', '红利股', '低波动',
                          '量化', '先进制造风格', '股权投资', 'QFII重仓'], 'tag_status': 'ok'}]
        for board in boards:
            with self.subTest(board=board):
                self.assertTrue(BOARDS[board]['requires_holdings_match'])
                result = rh.verify_board(disclosed(rows), board, '2026-10-30')
                self.assertEqual(result['status'], 'unknown')
                if board in rh.supported_board_ids():
                    self.assertEqual(result['matched_weight_pct'], 0)
                else:
                    self.assertIsNone(result['matched_weight_pct'])
                self.assertNotEqual(result['reason'], '该资产方向不适用股票主题匹配。')
                self.assertTrue(result['rule'])
        self.assertIn('久期', rh.verify_board(disclosed(rows), 'long_bond')['reason'])
        self.assertIn('资产配置', rh.verify_board(disclosed(rows), 'fixed_income_plus')['reason'])
        self.assertIn('指数成分', rh.verify_board(disclosed(rows), 'index_csi300')['reason'])
        self.assertIn('风格', rh.verify_board(disclosed(rows), 'style_cashflow')['reason'])

    def test_future_registry_ids_require_proof_unless_explicitly_exempted(self):
        from research_categories import BOARDS
        additions = {'future_style': {'id': 'future_style', 'requires_holdings_match': True},
                     'plain_asset': {'id': 'plain_asset', 'requires_holdings_match': False},
                     'unspecified_asset': {'id': 'unspecified_asset'}}
        with patch.dict(BOARDS, additions):
            self.assertEqual(rh.verify_board(disclosed(), 'future_style')['status'], 'unknown')
            self.assertEqual(rh.verify_board(disclosed(), 'plain_asset')['status'], 'not_required')
            self.assertEqual(rh.verify_board(disclosed(), 'unspecified_asset')['status'], 'unknown')
        self.assertEqual(rh.verify_board(disclosed(), 'unregistered_direction')['status'], 'unknown')
        self.assertEqual(rh.verify_board(disclosed(), 'bond')['status'], 'not_required')

    def test_malformed_tag_containers_and_target_etfs_cannot_create_theme_exposure(self):
        for tags in ('储能', {'储能': True}, [['储能']], [None], []):
            with self.subTest(tags=tags):
                rows = [{'code': '600001', 'name': '储能', 'weight_pct': 50,
                         'tags': tags, 'tag_status': 'ok'}]
                result = rh.verify_board(disclosed(rows), 'sector_energy_storage', '2026-10-30')
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['matched_weight_pct'], 0)
                self.assertEqual(result['coverage_pct'], 0)
        rows = [{'code': '512000', 'name': '储能ETF', 'weight_pct': 90,
                 'tags': ['储能'], 'tag_status': 'ok', 'instrument_type': 'fund'}]
        self.assertEqual(rh.verify_board(disclosed(rows), 'sector_energy_storage', '2026-10-30')['status'], 'unknown')

    @patch('research_holdings._fetch')
    def test_cached_collection_is_independent_and_etf_instrument_not_queried(self, fetch):
        def response(url):
            if 'FundMNInverstPosition' in url:
                raise ValueError('mobile source unavailable')
            if 'FundArchivesDatas' in url:
                return html_response()
            code = '600519' if 'SH600519' in url else '600809'
            return json.dumps({'ssbk':[{'SECURITY_CODE':code,'BOARD_NAME':'白酒Ⅱ'}]})
        fetch.side_effect = response
        result = rh.fetch_holdings('161725')
        self.assertEqual(fetch.call_count, 4)
        result['rows'].clear()
        self.assertEqual(len(rh.fetch_holdings('161725')['rows']), 2)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual(rh.fetch_security_tags('03690')['tag_status'], 'unknown')
        self.assertEqual(fetch.call_count, 4)

    @patch('research_holdings.fetch_holdings')
    def test_collection_preserves_nav_and_provenance_and_isolates_failure(self, fetch):
        holdings = disclosed()['holdings']
        holdings.update(scope='前十大', fetched_at='2026-10-30T12:00:00+08:00')
        fetch.side_effect = [holdings, RuntimeError('raw upstream secret')]
        history = [{'date':'2026-09-30','nav':1.2}]
        snapshot = {'funds':[{'code':'161725','nav':1.2,'history':history},
                             {'code':'000001','nav':2.3,'history':history}], 'sources':[], 'warnings':[]}
        result = rh.collect_holdings(snapshot)
        self.assertEqual(snapshot['sources'], [])
        self.assertEqual(result['funds'][0]['nav'], 1.2)
        self.assertEqual(result['funds'][1]['holdings']['status'], 'error')
        self.assertEqual(len(result['sources']), 2)
        self.assertNotIn('raw upstream secret', json.dumps(result))
        self.assertEqual(result['sources'][0]['as_of'], '2026-09-30')

    @patch('research_holdings.fetch_holdings')
    def test_missing_or_invalid_history_skips_network_but_missing_type_does_not(self, fetch):
        valid = [{'date':'2026-09-30','nav':1.2}]
        funds = [{'code':'000001'}, {'code':'000002','history':[]},
                 {'code':'000003','history':[{'date':'invalid','nav':1.2}]},
                 {'code':'000004','history':[{'date':'2026-09-30','nav':float('nan')}]},
                 {'code':'000005','history':valid,'fund_type':'货币型'},
                 {'code':'000006','history':valid,'fund_type':'债券型-中短债'},
                 {'code':'000007','history':valid},
                 {'code':'000008','history':valid,'fund_type':'混合型-偏股'}]
        holdings = disclosed()['holdings']
        holdings.update(scope='前十大')
        fetch.return_value = holdings
        result = rh.collect_holdings({'funds':funds,'sources':[],'warnings':[]})
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, {'000007','000008'})
        self.assertEqual(len(result['sources']), 2)
        self.assertTrue(all('holdings' not in fund for fund in result['funds'][:6]))
        self.assertTrue(all(fund['holdings']['status'] == 'ok' for fund in result['funds'][6:]))

    @patch('research_holdings.fetch_holdings')
    def test_preflight_accepts_recent_ranking_nav_without_creating_history(self, fetch):
        today = datetime.now(rh.CHINA).date()
        holdings = disclosed()['holdings']
        holdings.update(scope='前十大')
        fetch.return_value = holdings
        funds = [
            {'code': '000001', 'name': '排行基金', 'nav': 1.23,
             'nav_date': today.isoformat(), 'fund_type': '混合型-偏股'},
            {'code': '000002', 'name': '空历史基金', 'nav': 2.34,
             'nav_date': (today - timedelta(days=7)).isoformat(), 'fund_type': '股票型',
             'history': []},
        ]
        result = rh.collect_holdings({'funds': funds, 'sources': [], 'warnings': []}, preflight=True)
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, {'000001', '000002'})
        self.assertTrue(all(fund['holdings']['status'] == 'ok' for fund in result['funds']))
        self.assertNotIn('history', result['funds'][0])
        self.assertEqual(result['funds'][1].get('history'), [])

    @patch('research_holdings.fetch_holdings')
    def test_preflight_rejects_invalid_nav_dates_and_explicit_defensive_types(self, fetch):
        today = datetime.now(rh.CHINA).date()
        valid_date = today.isoformat()
        funds = [
            {'code': '000001', 'nav': 0, 'nav_date': valid_date, 'fund_type': '股票型'},
            {'code': '000002', 'nav': -1, 'nav_date': valid_date, 'fund_type': '股票型'},
            {'code': '000003', 'nav': float('nan'), 'nav_date': valid_date, 'fund_type': '股票型'},
            {'code': '000004', 'nav': True, 'nav_date': valid_date, 'fund_type': '股票型'},
            {'code': '000005', 'nav': 1.2, 'nav_date': 'invalid', 'fund_type': '股票型'},
            {'code': '000006', 'nav': 1.2, 'nav_date': (today + timedelta(days=1)).isoformat(), 'fund_type': '股票型'},
            {'code': '000007', 'nav': 1.2, 'nav_date': (today - timedelta(days=8)).isoformat(), 'fund_type': '股票型'},
            {'code': '000008', 'nav': 1.2, 'nav_date': valid_date, 'fund_type': '货币型'},
            {'code': '000009', 'nav': 1.2, 'nav_date': valid_date, 'fund_type': '债券型-纯债'},
            {'code': '000010', 'nav': 1.2, 'nav_date': valid_date, 'fund_type': '债券型-短债'},
        ]
        result = rh.collect_holdings({'funds': funds, 'sources': [], 'warnings': []}, preflight=True)
        fetch.assert_not_called()
        self.assertEqual(result['sources'], [])
        self.assertTrue(all('holdings' not in fund for fund in result['funds']))

    @patch('research_holdings.fetch_holdings')
    def test_preflight_false_keeps_missing_history_rejected_and_existing_history_accepted(self, fetch):
        holdings = disclosed()['holdings']
        holdings.update(scope='前十大')
        fetch.return_value = holdings
        today = datetime.now(rh.CHINA).date()
        funds = [
            {'code': '000001', 'nav': 1.2, 'nav_date': today.isoformat(), 'fund_type': '股票型'},
            {'code': '000002', 'nav': 1.2, 'nav_date': today.isoformat(), 'fund_type': '股票型',
             'history': [{'date': today.isoformat(), 'nav': 1.2}]},
        ]
        result = rh.collect_holdings({'funds': funds, 'sources': [], 'warnings': []})
        fetch.assert_called_once_with('000002', False)
        self.assertNotIn('holdings', result['funds'][0])
        self.assertEqual(result['funds'][1]['holdings']['status'], 'ok')

    def official_row(self, code='00700', weight=30, matched=True, complete=True,
                     day='2026-10-30', board='overseas_hang_seng_technology'):
        config = next(item for item in rh.INDEX_CONFIG.values() if board in item['boards'])
        source = {'matched': matched, 'index_code': config['index_code'],
            'index_name': config['index_name'], 'source_date': day,
            'source_url': 'https://www.hsi.com.hk/api/official', 'provider': '官方成分',
            'complete': complete, 'mapping_scope': '当前映射，不是报告日成分',
            'list_scope': '完整成分' if complete else '官方前十'}
        return {'code': code, 'name': '证券' + code, 'weight_pct': weight,
            'instrument_type': 'stock', 'tag_status': 'unknown', 'tags': [],
            'market_membership': {'code': code, 'region': 'hk', 'memberships': {
                board: {'matched': matched, 'sources': [source]}}}}

    def test_official_membership_uses_attached_codes_and_preserves_both_dates_without_network(self):
        rows = [self.official_row(), self.official_row('09999', 10, False)]
        fund = disclosed(rows)
        with patch('research_holdings._fetch', side_effect=AssertionError('no network')):
            result = rh.verify_board(fund, 'overseas_hang_seng_technology', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_disclosed_pct'], 75)
        self.assertEqual(result['report_date'], '2026-09-30')
        self.assertEqual(result['mapping_source_dates'], ['2026-10-30'])
        self.assertEqual(result['stock_evidence'][0]['membership_sources'][0]['index_code'], '02083.00')
        self.assertEqual(result['coverage_pct'], 100)

    def test_partial_official_list_missing_stock_stays_unknown_in_denominator(self):
        board = 'overseas_hk_dividend'
        rows = [self.official_row(weight=30, complete=False, board=board),
                self.official_row('09999', 10, None, False, board=board)]
        result = rh.verify_board(disclosed(rows), board, '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_disclosed_pct'], 75)
        self.assertTrue(result['ratio_is_lower_bound'])
        self.assertEqual(result['unclassified_disclosed_pct'], 25)
        rows[0]['weight_pct'] = 5
        self.assertEqual(rh.verify_board(disclosed(rows), board, '2026-10-30')['status'], 'unknown')

    def test_stale_future_wrong_identity_or_unofficial_membership_never_matches(self):
        for mode in ('stale', 'future', 'identity', 'source', 'index'):
            row = self.official_row()
            source = row['market_membership']['memberships']['overseas_hang_seng_technology']['sources'][0]
            if mode == 'stale': source['source_date'] = '2026-10-20'
            elif mode == 'future': source['source_date'] = '2026-11-01'
            elif mode == 'identity': row['market_membership']['code'] = '00001'
            elif mode == 'source': source['source_url'] = 'https://example.test/membership'
            else: source['index_code'] = '00001.00'
            with self.subTest(mode=mode):
                result = rh.verify_board(disclosed([row]), 'overseas_hang_seng_technology', '2026-10-30')
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['matched_disclosed_pct'], 0)
        row = self.official_row()
        row.pop('market_membership')
        row.update(tag_status='ok', tags=['恒生科技', '互联网', '信息技术'], industry_tags=['恒生科技'])
        self.assertEqual(rh.verify_board(disclosed([row]), 'overseas_hang_seng_technology', '2026-10-30')['status'], 'unknown')

    def test_mixed_mainland_and_hk_consumer_uses_industry_or_official_evidence(self):
        rows = [{'code': '000651', 'name': '名称无关', 'weight_pct': 15,
                 'instrument_type': 'stock', 'tag_status': 'ok', 'tags': ['家用电器']},
                self.official_row('00288', 20, True, False, board='overseas_hugangshen_consumer'),
                {'code': '600036', 'name': '名称无关2', 'weight_pct': 5,
                 'instrument_type': 'stock', 'tag_status': 'ok', 'tags': ['银行']}]
        result = rh.verify_board(disclosed(rows), 'overseas_hugangshen_consumer', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['matched_disclosed_pct'], 87.5)
        self.assertEqual(result['matched_weight_pct'], 35)

    def test_trusted_mobile_industry_stays_usable_when_concept_endpoint_fails(self):
        row = {'code': '000651', 'name': '名称无关', 'weight_pct': 20,
            'instrument_type': 'stock', 'tag_status': 'unknown', 'tags': [],
            'industry_tags': ['家用电器'], 'tag_evidence': [{'kind': 'industry',
                'security_code': '000651', 'tags': ['家用电器'],
                'source_url': 'https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?FCODE=123456'}]}
        result = rh.verify_board(disclosed([row]), 'sector_home_appliances', '2026-10-30')
        self.assertEqual(result['status'], 'matched')
        row['tag_evidence'][0]['security_code'] = '000652'
        self.assertEqual(rh.verify_board(disclosed([row]), 'sector_home_appliances', '2026-10-30')['status'], 'unknown')

    def test_documented_lookthrough_keeps_all_twenty_rows_in_denominator(self):
        import research_etf_evidence as etf
        period = '2026-09-30'
        def positions(start, theme):
            return {'report_date': period, 'target_code': None,
                'source_url': etf.mobile_url('159730'), 'rows': [
                    {'code': str(start + index), 'name': '股票' + str(index), 'weight_pct': 5,
                     'instrument_type': 'stock', 'tag_status': 'ok', 'tags': [theme]}
                    for index in range(10)]}
        direct = positions(600001, '银行')
        direct['target_code'] = '159730'
        article = 'AN202610271830984400'
        investment = {'report_date': period, 'target_code': '159730', 'target_weight_pct': 80,
            'market_value': 1000000, 'article_id': article,
            'source_url': f'https://fund.eastmoney.com/gonggao/021480,{article}.html',
            'content_source_url': etf.announcement_url(article)}
        holdings = etf.build_lookthrough('021480', direct, positions(600101, '家用电器'), investment)
        self.assertEqual(rh.holdings_row_limit(holdings), 20)
        result = rh.verify_board({'holdings': holdings}, 'sector_home_appliances', '2026-10-30')
        self.assertEqual(len(result['stock_evidence']), 20)
        self.assertEqual(result['disclosed_weight_pct'], 90)
        self.assertAlmostEqual(result['matched_disclosed_pct'], 40 / 90 * 100)
        self.assertEqual(result['status'], 'mismatch')
        holdings['lookthrough'].pop('market_value')
        self.assertEqual(rh.holdings_row_limit(holdings), 10)
        self.assertEqual(rh.verify_board({'holdings': holdings}, 'sector_home_appliances', '2026-10-30')['status'], 'unknown')

    @patch('research_holdings.fetch_holdings')
    def test_collection_fetches_membership_once_and_marks_only_attempted_funds(self, fetch):
        fetch.side_effect = [{**disclosed()['holdings'], 'scope': '公开股票披露'}, ValueError('upstream')]
        history = [{'date': '2026-09-30', 'nav': 1.0}]
        snapshot = {'funds': [{'code': '000001', 'history': history},
            {'code': '000002', 'history': history}, {'code': '000003', 'fund_type': '货币型', 'history': history}]}
        result = rh.collect_holdings(snapshot)
        self.memberships.assert_called_once_with(refresh=False)
        self.assertTrue(all(fund.get('holdings_checked_at') for fund in result['funds'][:2]))
        self.assertNotIn('holdings_checked_at', result['funds'][2])
        self.assertNotIn('market_membership', result['funds'][0]['holdings']['rows'][0])

    def test_compact_membership_keeps_positive_and_complete_negative_only(self):
        positive = self.official_row()['market_membership']
        board = 'overseas_hang_seng_technology'
        source = positive['memberships'][board]['sources'][0]
        context = {'code': '00700', 'region': 'hk', 'memberships': {
            'positive': {'sources': [{**source, 'matched': True}]},
            'negative': {'sources': [{**source, 'matched': False, 'complete': True}]},
            'partial': {'sources': [{**source, 'matched': None, 'complete': False}]},
            'unsafe_partial_false': {'sources': [{**source, 'matched': False, 'complete': False}]}}}
        compact = rh.compact_membership_evidence(context)
        self.assertEqual(set(compact['memberships']), {'positive', 'negative'})
        self.assertLess(len(json.dumps(compact)), len(json.dumps(context)))
        self.assertIsNone(rh.compact_membership_evidence({'code': '600519', 'memberships': {
            board: {'sources': [{**source, 'matched': None}]}}}))
        negative = self.official_row('09999', matched=False)
        negative['market_membership'] = rh.compact_membership_evidence(negative['market_membership'])
        self.assertEqual(rh.verify_board(disclosed([negative]), board, '2026-10-30')['status'], 'mismatch')
        partial = self.official_row('09999', matched=None, complete=False)
        partial['market_membership'] = rh.compact_membership_evidence(partial['market_membership'])
        self.assertEqual(rh.verify_board(disclosed([partial]), board, '2026-10-30')['status'], 'unknown')

    @patch('research_holdings.fetch_security_tags', return_value={'tag_status': 'unknown', 'tags': []})
    @patch('research_holdings._fetch')
    def test_mobile_holdings_is_preferred_and_retains_explicit_industry(self, fetch, classifier):
        payload = {'Success': True, 'ErrCode': 0, 'Expansion': '2026-09-30',
            'Datas': {'fundStocks': [{'GPDM': '000651', 'GPJC': '名称无关', 'JZBL': '20', 'INDEXNAME': '家用电器'}]}}
        fetch.return_value = json.dumps(payload)
        holdings = rh.fetch_holdings('021480')
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('FundMNInverstPosition', fetch.call_args.args[0])
        self.assertEqual(holdings['rows'][0]['industry_tags'], ['家用电器'])
        self.assertEqual(rh.verify_board({'holdings': holdings}, 'sector_home_appliances', '2026-10-30')['status'], 'matched')

    def test_official_membership_does_not_turn_reit_into_stock(self):
        row = self.official_row('00823', board='overseas_hk_dividend')
        row['name'] = 'LINK REIT'
        result = rh.verify_board(disclosed([row]), 'overseas_hk_dividend', '2026-10-30')
        self.assertEqual(result['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
