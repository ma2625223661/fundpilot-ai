"""Public sector reports upgrade sentiment without mutating saved evidence."""
import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from research_auto import AutoResearchEngine
from research_data import CHINA, now_iso
from test_sector_engine import sector_report


def sentiment_result():
    return {
        'score': 42.5, 'label': '平稳', 'status': 'ok', 'coverage_pct': 100,
        'as_of': now_iso(), 'sample_date': '2026-10-30',
        'history_date': '2026-10-30', 'sample_count': 300,
        'candidate_count': 300, 'index_count': 4,
        'components': [
            {'id': 'breadth', 'label': '样本上涨广度', 'weight': .4,
             'score': 40, 'count': 300, 'status': 'ok', 'source_ids': ['quotes']},
        ],
        'source_ids': ['quotes'], 'missing': [],
        'method': '去重样本规则化计算', 'scope': 'A股样本代理',
        'summary': '当前去重样本情绪平稳。',
    }


class MarketSentimentIntegrationTests(unittest.TestCase):
    def make_engine(self, config=None):
        engine = AutoResearchEngine(
            research_scope='sectors',
            runner=lambda **_: sector_report(),
            ai_runner=lambda report, **_: report,
            config_provider=lambda: config if config is not None else {'enabled': False},
        )
        self.addCleanup(engine.close)
        engine._state.update(
            status='ready', report=sector_report(), completed_at=now_iso())
        return engine

    def test_legacy_report_gets_computed_sentiment_without_modifying_raw_report(self):
        engine = self.make_engine()
        original = copy.deepcopy(engine._state['report'])
        self.assertNotIn('market_sentiment', original)
        with patch('research_auto.build_market_sentiment',
                   return_value=sentiment_result()) as build:
            public = engine.status()['report']
        build.assert_called_once()
        self.assertIsNot(build.call_args.args[0], engine._state['report'])
        self.assertEqual(public['market_sentiment']['score'], 42.5)
        self.assertEqual(public['market_sentiment']['sample_count'], 300)
        self.assertEqual(engine._state['report'], original)
        self.assertEqual(public['sector_analysis'], original['sector_analysis'])
        self.assertEqual(public['strategy'], original['strategy'])

    def test_summary_heartbeat_does_not_run_sentiment_calculation(self):
        engine = self.make_engine()
        with patch('research_auto.build_market_sentiment',
                   side_effect=AssertionError('heartbeat must not calculate sentiment')):
            first = engine.status(include_report=False)
            second = engine.status(include_report=False)
        self.assertTrue(first['has_report'])
        self.assertIsNone(first['report'])
        self.assertIsNone(second['report'])
        self.assertEqual(first['report_version'], second['report_version'])

    def test_public_cache_computes_once_and_caller_changes_do_not_leak(self):
        engine = self.make_engine()
        with patch('research_auto.build_market_sentiment',
                   side_effect=lambda _: sentiment_result()) as build:
            first = engine.status()
            first['report']['market_sentiment']['score'] = 100
            first['report']['market_sentiment']['components'][0]['score'] = 100
            engine._progress('继续扫描', {'deep_done': 1})
            engine.status(include_report=False)
            second = engine.status()
        build.assert_called_once()
        self.assertEqual(second['report']['market_sentiment']['score'], 42.5)
        self.assertEqual(second['report']['market_sentiment']['components'][0]['score'], 40)
        self.assertNotIn('market_sentiment', engine._state['report'])
        self.assertEqual(second['stage'], '继续扫描')

    def test_stale_report_clears_current_sentiment_score_and_keeps_raw_evidence(self):
        engine = self.make_engine()
        engine._state['report']['market_sentiment'] = sentiment_result()
        original = copy.deepcopy(engine._state['report'])
        engine._state['completed_at'] = (
            datetime.now(CHINA) - timedelta(hours=3)).isoformat()
        with patch('research_auto.build_market_sentiment',
                   return_value=sentiment_result()):
            public = engine.status()
        self.assertTrue(public['report_stale'])
        sentiment = public['report']['market_sentiment']
        self.assertIsNone(sentiment['score'])
        self.assertEqual(sentiment['status'], 'stale')
        self.assertEqual(sentiment['label'], '待更新')
        self.assertRegex(sentiment['summary'], '历史|过期|等待|待更新')
        self.assertEqual(engine._state['report'], original)

    def test_ai_configuration_change_rebuilds_view_without_invalidating_market_data(self):
        config = {'enabled': False, 'revision': 'one'}
        engine = self.make_engine(config)
        with patch('research_auto.build_market_sentiment',
                   side_effect=lambda _: sentiment_result()) as build:
            first = engine.status()
            config['revision'] = 'two'
            second = engine.status()
        self.assertEqual(build.call_count, 2)
        self.assertNotEqual(first['report_version'], second['report_version'])
        self.assertFalse(second['report_stale'])
        self.assertEqual(second['report']['market_sentiment']['score'], 42.5)


if __name__ == '__main__':
    unittest.main()
