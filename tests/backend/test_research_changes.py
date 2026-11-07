import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_changes as changes


def sector(sector_id='semi', score=50.0, tier=('pending', '待完成评估'), severity='normal', signal='neutral', risk='高风险'):
    return {'id': sector_id, 'title': sector_id, 'score': score, 'severity': severity, 'signal': signal, 'risk': risk,
            'research_tier': {'id': tier[0], 'label': tier[1]} if tier else None}


def report(as_of, *sectors):
    return {'as_of': as_of, 'sector_analysis': list(sectors)}


# Treat every date as a trading day unless a test says otherwise.
ALWAYS_OPEN = patch.object(changes, '_trading_day', lambda day: True)


class SnapshotTests(unittest.TestCase):
    def test_china_date_and_only_backend_fields(self):
        snap = changes.snapshot(report('2026-11-04T23:30:00+00:00', sector(score=41.1, severity='critical')))
        self.assertEqual(snap['date'], '2026-11-05')
        self.assertEqual(snap['sectors']['semi'], {'title': 'semi', 'score': 41.1, 'tier_id': 'pending',
            'tier_label': '待完成评估', 'critical': True, 'strong': False, 'risk': '高风险'})

    def test_missing_time_or_bad_score_is_not_invented(self):
        self.assertIsNone(changes.snapshot(report(None, sector())))
        snap = changes.snapshot(report('2026-11-05T10:00:00+08:00', sector(score=float('nan'))))
        self.assertIsNone(snap['sectors']['semi']['score'])


@ALWAYS_OPEN
class ChangeTests(unittest.TestCase):
    def test_no_baseline_says_so_without_items(self):
        result = changes.changes(report('2026-11-05T10:00:00+08:00', sector()), [])
        self.assertEqual(result['status'], 'no_baseline')
        self.assertEqual(result['items'], {})
        self.assertIn('不构成投资建议', result['note'])

    def test_previous_day_is_the_baseline_not_an_earlier_run_today(self):
        rows = [changes.snapshot(report('2026-11-03T15:00:00+08:00', sector(score=40))),
                changes.snapshot(report('2026-11-04T15:00:00+08:00', sector(score=45))),
                changes.snapshot(report('2026-11-05T09:30:00+08:00', sector(score=49)))]
        result = changes.changes(report('2026-11-05T11:00:00+08:00', sector(score=50.5)), rows)
        self.assertEqual(result['baseline_date'], '2026-11-04')
        self.assertEqual(result['items']['semi']['score_delta'], 5.5)
        self.assertTrue(result['items']['semi']['notable'])

    def test_tier_markers_and_risk_changes_are_listed(self):
        before = changes.snapshot(report('2026-11-04T15:00:00+08:00',
            sector(score=60, tier=('neutral', '中性'), risk='常规波动', signal='trend_excellent')))
        now = report('2026-11-05T15:00:00+08:00',
            sector(score=61, tier=('optimistic', '乐观'), severity='critical', risk='高风险'))
        item = changes.changes(now, [before])['items']['semi']
        self.assertEqual(item['tier'], {'before': '中性', 'now': '乐观'})
        self.assertEqual(item['flags'], ['新增特大风险', '趋势优消失'])
        self.assertEqual(item['risk'], {'before': '常规波动', 'now': '高风险'})
        self.assertTrue(item['notable'])

    def test_small_moves_are_kept_but_not_notable_and_missing_scores_get_no_delta(self):
        before = changes.snapshot(report('2026-11-04T15:00:00+08:00', sector(score=50), sector('bond', score=None)))
        result = changes.changes(report('2026-11-05T15:00:00+08:00', sector(score=51), sector('bond', score=55)), [before])
        self.assertEqual(result['items']['semi']['score_delta'], 1.0)
        self.assertFalse(result['items']['semi']['notable'])
        self.assertNotIn('bond', result['items'])

    def test_a_new_sector_without_history_is_skipped(self):
        before = changes.snapshot(report('2026-11-04T15:00:00+08:00', sector()))
        result = changes.changes(report('2026-11-05T15:00:00+08:00', sector(), sector('new', score=70)), [before])
        self.assertNotIn('new', result['items'])


class BaselineTests(unittest.TestCase):
    def test_one_snapshot_per_date_and_at_most_five_dates(self):
        rows = []
        for day in range(1, 9):
            for hour in ('10', '15'):
                rows = changes.remember(rows, changes.snapshot(report(f'2026-11-0{day}T{hour}:00:00+08:00', sector(score=day))))
        self.assertEqual([row['date'] for row in rows], [f'2026-11-0{d}' for d in range(4, 9)])
        self.assertTrue(rows[-1]['as_of'].startswith('2026-11-08T15'))

    def test_a_weekend_report_is_skipped_when_a_trading_day_exists(self):
        rows = [changes.snapshot(report('2026-11-06T15:00:00+08:00', sector(score=40))),
                changes.snapshot(report('2026-11-07T15:00:00+08:00', sector(score=42)))]
        with patch.object(changes, '_trading_day', lambda day: day != '2026-11-07'):
            base = changes.baseline_for(rows, '2026-11-09')
        self.assertEqual(base['date'], '2026-11-06')

    def test_apply_writes_the_file_and_survives_a_corrupt_one(self):
        with tempfile.TemporaryDirectory() as folder, ALWAYS_OPEN:
            state = Path(folder) / 'sector-report.json'
            (Path(folder) / changes.FILE_NAME).write_text('{not json', encoding='utf-8')
            first = changes.apply_changes(report('2026-11-04T15:00:00+08:00', sector(score=40)), state)
            self.assertEqual(first['sector_changes']['status'], 'no_baseline')
            second = changes.apply_changes(report('2026-11-05T15:00:00+08:00', sector(score=44)), state)
            self.assertEqual(second['sector_changes']['items']['semi']['score_delta'], 4.0)
            saved = json.loads((Path(folder) / changes.FILE_NAME).read_text(encoding='utf-8'))
            self.assertEqual([row['date'] for row in saved], ['2026-11-04', '2026-11-05'])

    def test_apply_never_raises(self):
        with patch.object(changes, 'changes', side_effect=RuntimeError('boom')):
            result = changes.apply_changes(report('2026-11-05T15:00:00+08:00', sector()), None)
        self.assertEqual(result['sector_changes']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
