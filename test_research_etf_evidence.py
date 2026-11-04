import copy
import json
import unittest
from unittest.mock import patch

import research_etf_evidence as evidence

DAY = '2026-10-30'
PERIOD = '2026-09-30'
ARTICLE = 'AN202610271830984400'


def position(rows=None, target=None, period=PERIOD):
    return {'Success': True, 'ErrCode': 0, 'Expansion': period, 'Datas': {
        'fundStocks': rows or [], 'ETFCODE': target}}


def stock(code='600001', weight='10', industry='家用电器'):
    return {'GPDM': code, 'GPJC': '合成股票' + code, 'JZBL': weight, 'INDEXNAME': industry}


def announcement(weight='94.23', body=None):
    text = body or f'''合成联接基金2026年第3季度报告
    2026 年 9 月 30 日
    基金主代码 021480
    投资策略：本基金将不低于净值90%的资产投资于目标ETF。
    2.1.1 目标基金基本情况
    基金名称 合成目标基金
    基金主代码 159730
    2.1.2 目标基金产品说明
    本基金名称不构成任何行业证据。
    5.2 期末投资目标基金明细
    序号 基金名称 公允价值 占基金资产净
    值比例（%）
    1 合成目标基金 指数型基金 30,663,405.90 {weight}
    5.3 报告期末按行业分类的股票投资组合
    无。
    '''
    return {'success': 1, 'data': {'art_code': ARTICLE,
        'security': [{'stock': '021480'}, {'stock': '021481'}], 'notice_content': text}}


def listing():
    return {'ErrCode': 0, 'Data': [{'FUNDCODE': '021480', 'NEWCATEGORY': '3',
        'PUBLISHDATEDesc': '2026-10-27', 'ID': ARTICLE}]}


class EtfEvidenceTests(unittest.TestCase):
    def parse(self, payload=None, **kwargs):
        return evidence.parse_target_investment(payload or announcement(), ARTICLE,
            kwargs.get('code', '021480'), kwargs.get('target', '159730'),
            kwargs.get('period', PERIOD), kwargs.get('as_of', DAY))

    def test_mobile_source_binds_stock_codes_and_industry_without_product_titles(self):
        result = evidence.parse_mobile_position(position([stock()]), '021480', DAY)
        self.assertEqual(result['report_date'], PERIOD)
        self.assertEqual(result['rows'][0]['tags'], ['家用电器'])
        self.assertEqual(result['rows'][0]['industry_tags'], ['家用电器'])
        self.assertEqual(result['rows'][0]['tag_evidence'][0]['source_field'], 'INDEXNAME')
        self.assertEqual(result['rows'][0]['instrument_type'], 'stock')
        self.assertEqual(result['rows'][0]['weight_pct'], 10)
        self.assertIn('FCODE=021480', result['rows'][0]['tag_source_url'])

    def test_unknown_mobile_industry_preserves_stock_in_denominator(self):
        for industry in ('', '--', None):
            row = stock(industry=industry)
            result = evidence.parse_mobile_position(position([row]), '021480', DAY)
            self.assertEqual(result['rows'][0]['weight_pct'], 10)
            self.assertEqual(result['rows'][0]['tag_status'], 'unknown')
            self.assertEqual(result['rows'][0]['tags'], [])

    def test_mobile_invalid_weights_duplicate_and_nonstock_rows_are_rejected(self):
        for weight in ('--', '-2', 'nan', float('inf'), True, 0, 101):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                evidence.parse_mobile_position(position([stock(weight=weight)]), '021480', DAY)
        for rows in ([stock(), stock()], [dict(stock(), GPJC='目标ETF')], [dict(stock(), GPDM='oops')],
                     [stock(str(600000 + i)) for i in range(11)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evidence.parse_mobile_position(position(rows), '021480', DAY)

    def test_mobile_missing_or_bad_report_period_and_success_are_rejected(self):
        for period in (None, '2026-12-31', '2025-01-01'):
            with self.subTest(period=period), self.assertRaises(ValueError):
                evidence.parse_mobile_position(position([stock()], period=period), '021480', DAY)
        for changes in ({'Success': False}, {'ErrCode': 4}, {'Datas': []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                evidence.parse_mobile_position({**position([stock()]), **changes}, '021480', DAY)

    def test_actual_report_target_row_overrides_contract_minimum(self):
        actual = self.parse(announcement('64.23'))
        self.assertEqual(actual['target_weight_pct'], 64.23)
        self.assertEqual(actual['target_code'], '159730')
        self.assertEqual(actual['report_date'], PERIOD)
        self.assertEqual(actual['market_value'], 30663405.90)
        self.assertIn(ARTICLE, actual['source_url'])
        with self.assertRaises(ValueError):
            self.parse(announcement(body=announcement()['data']['notice_content'].split('5.2')[0]))

    def test_split_column_headers_and_wrapped_names_are_supported(self):
        text = announcement()['data']['notice_content'].replace(
            '序号 基金名称 公允价值 占基金资产净\n    值比例（%）',
            '基                       占基金\n金                       资产净\n基金名称 公允价值（元）\n类                       值比例\n型                       （%）')
        self.assertEqual(self.parse(announcement(body=text))['target_weight_pct'], 94.23)

    def test_report_fund_target_article_and_period_must_all_match(self):
        for mode in ('fund', 'article', 'target', 'date', 'success'):
            payload = announcement()
            if mode == 'fund': payload['data']['security'] = [{'stock': '999999'}]
            elif mode == 'article': payload['data']['art_code'] = 'AN999999999999999'
            elif mode == 'target': payload['data']['notice_content'] = payload['data']['notice_content'].replace('159730', '159731')
            elif mode == 'date': payload['data']['notice_content'] = payload['data']['notice_content'].replace('2026 年 9 月 30 日', '2026 年 6 月 30 日')
            else: payload['success'] = 0
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.parse(payload)

    def test_no_multiple_targets_wrong_weight_basis_or_invalid_weight(self):
        original = announcement()['data']['notice_content']
        for body in (original.replace('5.3', '2 第二个目标基金 1,000.00 1.0\n    5.3'),
                     original.replace('占基金资产净', '占基金资产总'),
                     original.replace('94.23', '190.23')):
            with self.subTest(body=body), self.assertRaises(ValueError): self.parse(announcement(body=body))

    def test_lookthrough_scales_actual_weight_and_merges_same_stock(self):
        direct = evidence.parse_mobile_position(position([stock(weight='1')], target='159730'), '021480', DAY)
        target = evidence.parse_mobile_position(position([stock(weight='20'), stock('600002', '10', '银行')]), '159730', DAY)
        result = evidence.build_lookthrough('021480', direct, target, self.parse(announcement('80')))
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['rows'][0]['weight_pct'], 17)
        self.assertEqual(result['rows'][1]['weight_pct'], 8)
        self.assertEqual(result['disclosed_weight_pct'], 25)
        self.assertEqual(len(result['rows'][0]['lookthrough_components']), 2)
        self.assertEqual(result['lookthrough']['target_weight_pct'], 80)
        self.assertIn('不是完整或实时持仓', result['scope'])

    def test_direct_plus_indirect_rows_are_preserved_above_ten(self):
        direct = evidence.parse_mobile_position(position([stock(f'{600001+i}', '0.5') for i in range(10)], target='159730'), '021480', DAY)
        target = evidence.parse_mobile_position(position([stock(f'{600101+i}', '8') for i in range(10)]), '159730', DAY)
        result = evidence.build_lookthrough('021480', direct, target, self.parse(announcement('80')))
        self.assertEqual(len(result['rows']), 20)
        self.assertAlmostEqual(result['disclosed_weight_pct'], 69)
        self.assertEqual(result['lookthrough']['row_limit'], 20)

    def test_lookthrough_rejects_different_periods_and_nested_target(self):
        direct = evidence.parse_mobile_position(position(target='159730'), '021480', DAY)
        target = evidence.parse_mobile_position(position([stock()]), '159730', DAY)
        for altered in ({**target, 'report_date': '2026-06-30'}, {**target, 'target_code': '159731'}):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                evidence.build_lookthrough('021480', direct, altered, self.parse())

    def test_bounded_fetch_pipeline_keeps_provenance_and_unknown_tags(self):
        documents = {evidence.mobile_url('021480'): position(target='159730'),
                     evidence.mobile_url('159730'): position([stock(weight='20'), stock('600002', '10', '')]),
                     evidence.periodic_url('021480'): listing(), evidence.announcement_url(ARTICLE): announcement('80')}
        calls=[]
        def fetch(url): calls.append(url); return json.dumps(documents[url])
        result = evidence.fetch_holdings_evidence('021480', as_of=DAY, fetcher=fetch)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['disclosed_weight_pct'], 24)
        self.assertEqual(result['source_id'], 'holdings:021480')
        self.assertEqual(len(result['source_urls']), 3)
        self.assertEqual(result['rows'][1]['tag_status'], 'unknown')

    def test_direct_mobile_fallback_and_classifier_combine_explicit_sources(self):
        before = position([stock()])
        original=copy.deepcopy(before)
        result = evidence.fetch_holdings_evidence('021480', as_of=DAY,
            fetcher=lambda _:json.dumps(before), security_classifier=lambda *args, **kwargs:{
                'tag_status':'ok', 'tags':['机器人'], 'tag_source_url':'https://example.test/classification'})
        self.assertEqual(result['rows'][0]['tags'], ['家用电器', '机器人'])
        self.assertEqual(result['rows'][0]['industry_tags'], ['家用电器'])
        self.assertEqual(result['rows'][0]['tag_evidence'][0]['security_code'], '600001')
        self.assertIn('fundmobapi.eastmoney.com', result['rows'][0]['tag_evidence'][0]['source_url'])
        self.assertNotIn('lookthrough', result)
        self.assertEqual(before, original)

    def test_missing_report_cannot_use_contract_or_unknown_weight(self):
        documents = {evidence.mobile_url('021480'): position(target='159730'),
                     evidence.periodic_url('021480'): {'ErrCode':0,'Data':[]}}
        with self.assertRaises(ValueError):
            evidence.fetch_holdings_evidence('021480', as_of=DAY, fetcher=lambda url:json.dumps(documents[url]))


if __name__ == '__main__':
    unittest.main()
