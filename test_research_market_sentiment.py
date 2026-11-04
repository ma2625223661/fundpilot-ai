"""Offline checks for the dated, deduplicated A-share sentiment proxy."""
import copy
import unittest
from datetime import date, timedelta

from research_market_sentiment import build_market_sentiment
from research_trading_calendar import is_trading_day, last_closed_trading_day


AS_OF = '2026-10-31T15:22:50+08:00'
QUOTE_TIME = '2026-10-30T16:00:00+08:00'
INDEX_CODES = ('sh000001', 'sz399001', 'sh000300', 'sz399006')


def session_days(as_of=AS_OF):
    day = date.fromisoformat(last_closed_trading_day(as_of))
    days = []
    while len(days) < 20:
        if is_trading_day(day):
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(days))


def company(number, change=0, direction=0, as_of=AS_OF):
    days = session_days(as_of)
    values = [20 + direction * i / 10 for i in range(20)]
    return {
        'ts_code': f'{600000 + number:06d}.SH', 'as_of': QUOTE_TIME,
        'quote': {'trade_date': '2026-10-30', 'close': 20, 'pct_chg': change,
                  'is_intraday': False},
        'price_adjustment': 'forward_adjusted',
        'history': [{'date': day, 'close': value} for day, value in zip(days, values)],
        'source_ids': ['quotes:test', f'leader_history:{number}', 'public:financial:test'],
    }


def report(count=20, as_of=AS_OF):
    return {
        'as_of': as_of,
        'company_evidence': {'sector_leaders': {'test': [company(i, as_of=as_of) for i in range(count)]}},
        'snapshot': {'market': [
            {'code': code, 'change_pct': 0, 'as_of': QUOTE_TIME,
             'source_id': 'market_tencent', 'data_frequency': 'daily'}
            for code in INDEX_CODES
        ]},
        'sector_analysis': [{'id': 'test', 'score': 65}],
    }


def rows(value):
    return value['company_evidence']['sector_leaders']['test']


def components(value):
    return {item['id']: item for item in value['components']}


class MarketSentimentTests(unittest.TestCase):
    def test_public_contract_flat_market_and_no_input_mutation(self):
        value = report()
        original = copy.deepcopy(value)
        result = build_market_sentiment(value)
        self.assertEqual(result['score'], 50)
        self.assertEqual(result['label'], '平稳')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['coverage_pct'], 100)
        self.assertEqual(result['sample_count'], 20)
        self.assertEqual(result['candidate_count'], 20)
        self.assertEqual(result['index_count'], 4)
        self.assertEqual(result['sample_date'], '2026-10-30')
        self.assertEqual(result['history_date'], '2026-10-30')
        self.assertEqual(result['as_of'], AS_OF)
        self.assertEqual([c['weight'] for c in result['components']], [.4, .3, .3])
        self.assertEqual(value, original)
        self.assertIn('不代表全市场', result['scope'])

    def test_formula_uses_displayed_component_precision(self):
        value = report(21)
        for i, item in enumerate(rows(value)):
            item['quote']['pct_chg'] = 1 if i < 11 else 0 if i < 16 else -1
            item['history'] = company(i, direction=1 if i < 7 else 0 if i < 14 else -1)['history']
        for index, change in zip(value['snapshot']['market'], [-1, 1, 3, 5]):
            index['change_pct'] = change
        result = build_market_sentiment(value)
        self.assertEqual([c['score'] for c in result['components']], [64.29, 70, 50])
        self.assertEqual(result['score'], 61.72)

    def test_saturated_extremes_and_all_sentiment_label_boundaries(self):
        for change, direction, expected, label in [(20, 1, 100, '过热'), (-20, -1, 0, '低迷')]:
            with self.subTest(expected=expected):
                value = report()
                for i, item in enumerate(rows(value)):
                    item['quote']['pct_chg'] = change
                    item['history'] = company(i, direction=direction)['history']
                for index in value['snapshot']['market']:
                    index['change_pct'] = change
                result = build_market_sentiment(value)
                self.assertEqual(result['score'], expected)
                self.assertEqual(result['label'], label)
        for up, expected, label in [(0, 0, '低迷'), (4, 20, '偏冷'), (8, 40, '平稳'),
                                    (12, 60, '活跃'), (16, 80, '过热')]:
            with self.subTest(expected=expected):
                value = report()
                for i, item in enumerate(rows(value)):
                    item['quote']['pct_chg'] = 1 if i < up else -1
                    item['history'] = company(i, direction=1 if i < up else -1)['history']
                for index in value['snapshot']['market']:
                    index['change_pct'] = (expected - 50) / 10
                result = build_market_sentiment(value)
                self.assertEqual(result['score'], expected)
                self.assertEqual(result['label'], label)

    def test_repeated_company_in_many_sectors_is_counted_once(self):
        value = report()
        expected = build_market_sentiment(value)
        value['company_evidence']['sector_leaders']['another'] = copy.deepcopy(rows(value)) * 3
        self.assertEqual(build_market_sentiment(value), expected)

    def test_same_time_quote_conflicts_are_excluded(self):
        value = report(21)
        duplicate = copy.deepcopy(rows(value)[0])
        duplicate['quote']['pct_chg'] = 1
        rows(value).append(duplicate)
        result = build_market_sentiment(value)
        self.assertEqual(result['sample_count'], 20)
        self.assertEqual(result['candidate_count'], 21)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any('1只同一时点报价冲突' in text for text in result['missing']))

    def test_latest_quote_wins_independent_of_row_order(self):
        value = report()
        original = rows(value)[0]
        original['as_of'] = '2026-10-30T15:01:00+08:00'
        original['quote']['pct_chg'] = -1
        newer = copy.deepcopy(original)
        newer['as_of'] = QUOTE_TIME
        newer['quote']['pct_chg'] = 1
        rows(value).append(newer)
        first = build_market_sentiment(value)
        rows(value).reverse()
        self.assertEqual(build_market_sentiment(value), first)
        self.assertEqual(components(first)['breadth']['score'], 52.5)

    def test_conflicting_history_in_partial_duplicate_is_excluded(self):
        value = report(21)
        duplicate = copy.deepcopy(rows(value)[0])
        duplicate['history'] = duplicate['history'][-1:]
        duplicate['history'][0]['close'] = 99
        rows(value).append(duplicate)
        result = build_market_sentiment(value)
        self.assertEqual(components(result)['ma20_participation']['count'], 20)
        self.assertTrue(any('1只历史冲突' in text for text in result['missing']))

    def test_incomplete_duplicates_cannot_be_joined_into_a_history_window(self):
        value = report()
        extra = []
        for item in rows(value):
            duplicate = copy.deepcopy(item)
            duplicate['history'] = duplicate['history'][10:]
            item['history'] = item['history'][:10]
            extra.append(duplicate)
        rows(value).extend(extra)
        self.assertEqual(components(build_market_sentiment(value))['ma20_participation']['count'], 0)

    def test_a_share_only_filter_excludes_overseas_funds_bonds_and_indices(self):
        value = report()
        for code in ['00700.HK', 'AAPL.US', '510300.SH', '000001.SH', 'sh000001', '113001.SH', '123001.SZ']:
            item = copy.deepcopy(rows(value)[0])
            item['ts_code'] = code
            rows(value).append(item)
        self.assertEqual(build_market_sentiment(value)['candidate_count'], 20)
        for code in ['688001.SH', '689001.SH', '000001.SZ', '300001.SZ', '301001.SZ', '302132.SZ', '920001.BJ']:
            item = copy.deepcopy(rows(value)[0])
            item['ts_code'] = code
            rows(value).append(item)
        self.assertEqual(build_market_sentiment(value)['candidate_count'], 27)

    def test_minimum_sample_count_is_twenty(self):
        result = build_market_sentiment(report(19))
        self.assertIsNone(result['score'])
        self.assertEqual(result['coverage_pct'], 30)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(build_market_sentiment(report(20))['status'], 'ok')

    def test_minimum_indices_and_partial_source_coverage(self):
        for count, ready in [(0, False), (1, False), (2, True), (3, True), (4, True)]:
            with self.subTest(count=count):
                value = report()
                value['snapshot']['market'] = value['snapshot']['market'][:count]
                result = build_market_sentiment(value)
                item = components(result)['index_strength']
                self.assertEqual(item['score'] is not None, ready)
                self.assertEqual(item['coverage_pct'], count * 25)
                self.assertEqual(result['score'], 50)
                self.assertEqual(result['status'], 'ok' if count == 4 else 'partial')
                self.assertEqual(result['coverage_pct'], 100 if ready else 70)

    def test_missing_thirty_percent_is_renormalized_but_sixty_percent_cannot_publish(self):
        value = report()
        for item in rows(value):
            item['history'] = []
            item['quote']['pct_chg'] = 1
        result = build_market_sentiment(value)
        self.assertEqual(result['score'], 78.57)
        self.assertEqual(result['coverage_pct'], 70)
        self.assertEqual(result['status'], 'partial')
        value = report()
        for item in rows(value):
            item['quote'] = {}
        result = build_market_sentiment(value)
        self.assertIsNone(result['score'])
        self.assertEqual(result['coverage_pct'], 60)

    def test_historical_ma_never_compares_unadjusted_current_price(self):
        value = report()
        for item in rows(value):
            item['quote']['close'] = 2000
        result = build_market_sentiment(value)
        self.assertEqual(components(result)['ma20_participation']['score'], 50)

    def test_history_requires_adjustment_and_every_recent_verified_session(self):
        for invalid in ['unadjusted', 'missing_latest', 'missing_middle', 'zero_close', 'negative_close']:
            with self.subTest(invalid=invalid):
                value = report()
                for item in rows(value):
                    if invalid == 'unadjusted':
                        item['price_adjustment'] = 'unadjusted'
                    elif invalid == 'missing_latest':
                        item['history'].pop()
                    elif invalid == 'missing_middle':
                        item['history'].pop(10)
                    else:
                        item['history'][10]['close'] = 0 if invalid == 'zero_close' else -1
                item = components(build_market_sentiment(value))['ma20_participation']
                self.assertIsNone(item['score'])
                self.assertEqual(item['count'], 0)

    def test_future_history_points_do_not_change_the_completed_session_ma(self):
        value = report()
        for item in rows(value):
            item['history'].append({'date': '2026-11-02', 'close': 1000})
        result = build_market_sentiment(value)
        self.assertEqual(components(result)['ma20_participation']['score'], 50)
        self.assertEqual(result['history_date'], '2026-10-30')

    def test_invalid_stale_or_future_quotes_do_not_contribute(self):
        for when in ['unknown', '2026-10-29T16:00:00+08:00', '2026-11-02T16:00:00+08:00']:
            with self.subTest(when=when):
                value = report()
                for item in rows(value):
                    item['as_of'] = when
                    item['quote'].pop('trade_date')
                result = build_market_sentiment(value)
                self.assertEqual(result['sample_count'], 0)
                self.assertIsNone(result['score'])

    def test_quote_date_disagreement_is_rejected(self):
        value = report()
        for item in rows(value):
            item['quote']['trade_date'] = '2026-10-29'
        self.assertEqual(build_market_sentiment(value)['sample_count'], 0)

    def test_only_same_day_quotes_enter_live_breadth(self):
        current = '2026-11-03T11:05:00+08:00'
        value = report(40, as_of=current)
        for i, item in enumerate(rows(value)):
            today = i < 20
            item['as_of'] = '2026-11-03T11:00:00+08:00' if today else '2026-11-02T16:00:00+08:00'
            item['quote'].update(trade_date='2026-11-03' if today else '2026-11-02', is_intraday=today,
                                 pct_chg=1 if today else -1)
        for index in value['snapshot']['market']:
            index.update(as_of='2026-11-03T11:00:00+08:00', data_frequency='intraday')
        result = build_market_sentiment(value)
        self.assertEqual(result['sample_count'], 20)
        self.assertEqual(result['sample_date'], '2026-11-03')
        self.assertEqual(result['history_date'], '2026-11-02')
        self.assertEqual(components(result)['breadth']['score'], 100)

    def test_known_long_holiday_retains_latest_close_without_using_natural_day_expiry(self):
        value = report(as_of='2026-10-07T14:00:00+08:00')
        for item in rows(value):
            item['as_of'] = '2026-09-30T16:00:00+08:00'
            item['quote']['trade_date'] = '2026-09-30'
        for index in value['snapshot']['market']:
            index['as_of'] = '2026-09-30T16:00:00+08:00'
        result = build_market_sentiment(value)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['history_date'], '2026-09-30')
        self.assertEqual(result['sample_date'], '2026-09-30')

    def test_unknown_calendar_year_never_assumes_a_session(self):
        value = report()
        value['as_of'] = '2027-01-04T16:00:00+08:00'
        result = build_market_sentiment(value)
        self.assertIsNone(result['score'])
        self.assertIsNone(result['history_date'])
        self.assertEqual(result['coverage_pct'], 0)

    def test_index_whitelist_latest_value_and_conflict_rules(self):
        value = report()
        value['snapshot']['market'].append({'code': 'hkHSI', 'change_pct': 100,
            'as_of': QUOTE_TIME, 'source_id': 'overseas', 'data_frequency': 'daily'})
        earlier = copy.deepcopy(value['snapshot']['market'][0])
        earlier.update(as_of='2026-10-30T15:01:00+08:00', change_pct=5)
        value['snapshot']['market'].append(earlier)
        self.assertEqual(components(build_market_sentiment(value))['index_strength']['score'], 50)
        conflict = copy.deepcopy(value['snapshot']['market'][0])
        conflict['change_pct'] = 5
        value['snapshot']['market'].append(conflict)
        result = build_market_sentiment(value)
        self.assertEqual(result['index_count'], 3)
        self.assertEqual(result['status'], 'partial')

    def test_invalid_numbers_and_empty_provenance_do_not_create_data(self):
        for invalid in [True, float('nan'), float('inf'), '1']:
            with self.subTest(invalid=invalid):
                value = report()
                for item in rows(value):
                    item['quote']['pct_chg'] = invalid
                    item['history'][0]['close'] = invalid
                for index in value['snapshot']['market']:
                    index['change_pct'] = invalid
                result = build_market_sentiment(value)
                self.assertIsNone(result['score'])
                self.assertEqual(result['coverage_pct'], 0)
        value = report()
        for item in rows(value):
            item['source_ids'] = ['', '   ', None]
        for index in value['snapshot']['market']:
            index['source_id'] = '   '
        result = build_market_sentiment(value)
        self.assertIsNone(result['score'])
        self.assertEqual(result['source_ids'], [])

    def test_sources_are_trimmed_deduplicated_and_specific_to_each_component(self):
        value = report()
        for item in rows(value):
            item['source_ids'] += ['', '   ', None, ' quotes:test ', 'public:business:test']
        result = build_market_sentiment(value)
        parts = components(result)
        self.assertEqual(parts['breadth']['source_ids'], ['quotes:test'])
        self.assertTrue(all('history' in sid for sid in parts['ma20_participation']['source_ids']))
        self.assertEqual(parts['index_strength']['source_ids'], ['market_tencent'])
        self.assertTrue(all(sid == sid.strip() and sid for sid in result['source_ids']))

    def test_empty_or_malformed_report_is_unavailable_without_invented_timestamp(self):
        for value in [None, [], {}, {'snapshot': [], 'company_evidence': []},
                      {'as_of': 'unknown', 'snapshot': {'market': [None]}}]:
            with self.subTest(value=value):
                result = build_market_sentiment(value)
                self.assertIsNone(result['score'])
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['source_ids'], [])
                self.assertIn(result['as_of'], ['', 'unknown'])
        value = report()
        for item in rows(value):
            item['quote'] = []
        self.assertEqual(build_market_sentiment(value)['sample_count'], 0)

    def test_news_events_and_ai_outputs_do_not_modify_sentiment(self):
        value = report()
        expected = build_market_sentiment(value)
        value['snapshot']['news'] = [{'title': '重大利好' * 1000}]
        value['events'] = [{'impact_score': 100, 'direction': 'bullish'}]
        value['ai_research'] = {'sentiment_score': 100}
        self.assertEqual(build_market_sentiment(value), expected)


if __name__ == '__main__':
    unittest.main()
