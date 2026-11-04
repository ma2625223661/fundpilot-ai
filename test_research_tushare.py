"""Offline evidence and capability checks; never use an actual credential."""
import copy
import unittest
from unittest.mock import Mock, patch

from research_tushare import (TushareClient, TushareError, _cache,
                              board_ids_for_member, gather_sector_company_evidence,
                              probe_tushare)

TOKEN = 'offline-tushare-token-7e91'


def response(rows):
    fields = list(rows[0]) if rows else ['ts_code']
    return {'code': 0, 'msg': None, 'data': {'fields': fields,
                                          'items': [[row.get(field) for field in fields] for row in rows]}}


class ClientTests(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_fields_are_decoded_and_cache_is_detached_and_scoped_by_token(self):
        transport = Mock(return_value=response([{'ts_code': '000001.SZ', 'close': 12.3}]))
        first = TushareClient(TOKEN, transport)
        rows = first.query('daily', {'trade_date': '20261030'})
        self.assertEqual(transport.call_args.args[0]['token'], TOKEN)
        rows[0]['close'] = 0
        self.assertEqual(first.query('daily', {'trade_date': '20261030'})[0]['close'], 12.3)
        self.assertEqual(transport.call_count, 1)
        second = TushareClient(TOKEN + '-other', transport)
        second.query('daily', {'trade_date': '20261030'})
        self.assertEqual(transport.call_count, 2)

    def test_provider_text_never_leaks_a_token(self):
        for message in ('您没有访问该接口权限 ' + TOKEN, '每分钟访问次数超过上限 ' + TOKEN,
                        '无效token: ' + TOKEN):
            client = TushareClient(TOKEN, lambda _: {'code': 2002, 'msg': message})
            with self.assertRaises(TushareError) as error:
                client.query('daily', ttl=0)
            self.assertNotIn(TOKEN, str(error.exception))
        client = TushareClient(TOKEN, lambda _: response([{'ts_code': TOKEN}]))
        with self.assertRaises(TushareError):
            client.query('daily', ttl=0)

    def test_budget_and_malformed_rows_are_rejected(self):
        client = TushareClient(TOKEN, lambda _: response([]), request_budget=1)
        client.query('daily', ttl=0)
        with self.assertRaises(TushareError) as error:
            client.query('daily', ttl=0)
        self.assertEqual(error.exception.category, 'budget')
        client = TushareClient(TOKEN, lambda _: {'code': 0, 'data': {'fields': ['a'], 'items': [[1, 2]]}})
        with self.assertRaises(TushareError):
            client.query('daily', ttl=0)

    def test_probe_does_not_claim_empty_data_is_permission_success(self):
        client = Mock()
        client.query.side_effect = [[], [{'ts_code': '000001.SZ'}], [], [], [], []]
        result = probe_tushare(TOKEN, lambda _: client)
        self.assertEqual(result['verification'], 'partial')
        self.assertEqual(result['capabilities']['daily']['status'], 'empty')
        client.query.side_effect = TushareError('authentication', '无效凭证')
        result = probe_tushare(TOKEN, lambda _: client)
        self.assertEqual(len(result['capabilities']), 1)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        _cache.clear()

    def test_no_token_means_no_requests(self):
        client = Mock()
        result = gather_sector_company_evidence([], {}, '2026-10-31T09:10:00+08:00', client)
        self.assertEqual(result['status'], 'not_configured')
        client.query.assert_not_called()

    def test_theme_does_not_match_company_display_name(self):
        catalog = [{'id': 'sector_energy_storage'}, {'id': 'sector_insurance'}]
        member = {'name': '储能龙头保险', 'l1_name': '非银金融', 'l2_name': '保险Ⅱ', 'l3_name': '保险Ⅲ'}
        self.assertEqual(board_ids_for_member(member, catalog), ['sector_insurance'])

    def test_membership_daily_timestamp_and_financial_disclosure_are_evidence_bound(self):
        requests = []
        def transport(payload):
            requests.append(copy.deepcopy(payload))
            api = payload['api_name']
            if api == 'trade_cal':
                return response([{'cal_date': '20261030', 'is_open': 1}, {'cal_date': '20261031', 'is_open': 0}])
            if api == 'daily':
                return response([{'ts_code': '601000.SH', 'trade_date': '20261030', 'close': 10, 'pct_chg': 1, 'amount': 500},
                                 {'ts_code': '601001.SH', 'trade_date': '20261030', 'close': 12, 'pct_chg': -1, 'amount': 300}])
            if api == 'daily_basic':
                return response([{'ts_code': '601000.SH', 'total_mv': 100}, {'ts_code': '601001.SH', 'total_mv': 200}])
            if api == 'index_classify':
                return response([{'index_code': '801780.SI', 'industry_name': '非银金融'}])
            if api == 'index_member_all':
                return response([{'ts_code': '601000.SH', 'name': '公司甲', 'l1_name': '非银金融', 'l2_name': '保险Ⅱ',
                                  'l3_name': '保险Ⅲ', 'in_date': '20200101', 'out_date': None, 'is_new': 'Y'},
                                 {'ts_code': '601001.SH', 'name': '公司乙', 'l1_name': '非银金融', 'l2_name': '保险Ⅱ',
                                  'l3_name': '保险Ⅲ', 'in_date': '20270101', 'out_date': None, 'is_new': 'Y'}])
            if api == 'fina_indicator':
                return response([{'ts_code': '601000.SH', 'ann_date': '20261031', 'end_date': '20260930', 'roe': 99},
                                 {'ts_code': '601000.SH', 'ann_date': '20261029', 'end_date': '20260930', 'roe': 8}])
            raise AssertionError(api)
        client = TushareClient(TOKEN, transport)
        result = gather_sector_company_evidence([{'id': 'sector_insurance'}, {'id': 'sector_energy_storage'}],
                                               {'token': TOKEN}, '2026-10-31T14:30:00+08:00', client)
        leader = result['sector_leaders']['sector_insurance'][0]
        self.assertEqual(len(result['sector_leaders']['sector_insurance']), 1)
        self.assertNotIn('sector_energy_storage', result['sector_leaders'])
        self.assertFalse(leader['leader_verified'])
        self.assertFalse(leader['quote']['is_intraday'])
        self.assertEqual(leader['quote']['trade_date'], '20261030')
        self.assertEqual(leader['financials']['roe'], 8)
        self.assertNotIn(TOKEN, str(result))
        self.assertTrue(any(s['id'] == 'tushare:fina_indicator:601000.SH' for s in result['sources']))

    def test_missing_calendar_does_not_guess_a_trading_day(self):
        transport = Mock(return_value=response([]))
        result = gather_sector_company_evidence([], {'token': TOKEN}, '2026-10-31T14:30:00+08:00',
                                               TushareClient(TOKEN, transport))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(transport.call_count, 1)

    def test_verified_calendar_capability_requests_full_year_and_registers_only_validated_data(self):
        calendar = [{'exchange': 'SSE', 'cal_date': '20261030', 'is_open': 1}]
        transport = Mock(side_effect=lambda p: response(calendar if p['api_name'] == 'trade_cal' else []))
        config = {'token': TOKEN, 'capabilities': {'trade_cal': {'status': 'available'}}}
        with patch('research_trading_calendar.register_trade_calendar', side_effect=ValueError('partial')) as register:
            output = gather_sector_company_evidence([], config, '2026-10-31T09:10:00+08:00',
                                                   TushareClient(TOKEN, transport))
        self.assertEqual(transport.call_args_list[0].args[0]['params']['start_date'], '20260101')
        self.assertEqual(transport.call_args_list[0].args[0]['params']['end_date'], '20261231')
        register.assert_called_once()
        self.assertNotIn('calendar_registered_year', output)
        self.assertTrue(any('年度交易日历返回不完整' in text for text in output['warnings']))

    def test_full_year_calendar_never_selects_a_future_trading_day_after_close(self):
        calendar = [{'exchange': 'SSE', 'cal_date': '20261030', 'is_open': 1},
                    {'exchange': 'SSE', 'cal_date': '20261231', 'is_open': 1}]
        transport = Mock(side_effect=lambda p: response(calendar if p['api_name'] == 'trade_cal' else []))
        with patch('research_trading_calendar.register_trade_calendar', side_effect=ValueError('partial')):
            gather_sector_company_evidence([], {'token': TOKEN, 'capabilities': {'trade_cal': {'status': 'available'}}},
                                           '2026-10-31T20:00:00+08:00', TushareClient(TOKEN, transport))
        daily = [call.args[0] for call in transport.call_args_list if call.args[0]['api_name'] == 'daily']
        self.assertEqual(daily[0]['params']['trade_date'], '20261030')


if __name__ == '__main__':
    unittest.main()
