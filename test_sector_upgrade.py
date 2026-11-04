"""Classification upgrades must retain evidence and never unlock old buy plans."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_auto import AutoResearchEngine, apply_board_holdings_gate
from research_categories import BOARDS, SCHEMA_VERSION
from research_data import now_iso
from research_selection import build_sections
from research_holdings import HOLDINGS_RULE_VERSION


def report_for(name, kind='股票型'):
    timestamp = now_iso()
    holdings = {'status': 'ok', 'report_date': timestamp[:10], 'rows': [
        {'code': str(600001 + index), 'name': '合成证券', 'weight_pct': 10,
         'instrument_type': 'stock', 'tag_status': 'ok', 'tags': ['银行', '电力']}
        for index in range(4)]}
    return {
        'board_schema_version': 5,
        'board_coverage': [{'id': 'dividend', 'label': '红利与低波'}],
        'snapshot': {'as_of': timestamp, 'funds': [{'code': '000001', 'name': name,
            'fund_type': kind, 'nav_date': timestamp[:10], 'holdings': holdings}]},
        'quant': [{'code': '000001', 'quality': 'ok', 'nav_date': timestamp[:10],
            'score': 95, 'action': '分批配置候选',
            'metrics': {'volatility_annual': 10, 'max_drawdown': -3},
            'thresholds': {'annual_volatility_limit': 15, 'drawdown_limit': 8}}],
        'analysis': {'summary': '', 'funds': [{'code': '000001', 'name': name,
            'action': '7 天以上研究候选', 'operation_plan': {'new_position': '第一批买入',
            'steps': ['第一批买入'], 'entry_conditions': ['按旧规则加仓']}}]},
        'strategy': {'as_of': timestamp, 'panic': {'as_of': timestamp, 'score': 10},
            'regime': {'mode': 'risk_on', 'label': '进攻研究'},
            'candidates': [{'code': '000001', 'name': name}]}}


class SectorUpgradeTests(unittest.TestCase):
    def test_persistence_evicts_large_portfolios_but_keeps_discovery_progress(self):
        report = report_for('显示名称')
        report['analysis']['funds'][0]['board_matches'] = [{'derived': '可重算' * 10000}]
        report['holdings_index'] = [{'code': f'{i:06d}', 'holdings': {'padding': '字' * 1000}}
                                    for i in range(100)]
        report['holdings_check_ledger'] = {f'{i:06d}': now_iso() for i in range(100)}
        before = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as directory, patch('research_auto.MAX_REPORT_BYTES', 12000):
            path = Path(directory) / 'report.json'
            engine = AutoResearchEngine(path)
            engine._persist(report, now_iso())
            self.assertLessEqual(path.stat().st_size, 12000)
            saved = json.loads(path.read_text(encoding='utf-8'))['report']
            self.assertNotIn('board_matches',saved['analysis']['funds'][0])
            self.assertLess(len(saved['holdings_index']), 100)
            self.assertEqual(len(saved['holdings_check_ledger']), 100)
            restored = AutoResearchEngine(path)
            self.assertEqual(restored._state['report']['holdings_check_ledger'], report['holdings_check_ledger'])
            engine.close()
            restored.close()
        self.assertEqual(report, before)

    def test_oversized_evidence_does_not_overwrite_restorable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            engine = AutoResearchEngine(path)
            engine._persist(report_for('显示名称'), now_iso())
            before = path.read_bytes()
            with patch('research_auto.MAX_REPORT_BYTES', 10), self.assertRaises(OSError):
                engine._persist(report_for('新报告'), now_iso())
            self.assertEqual(path.read_bytes(), before)
            engine.close()

    def test_old_match_rechecks_75_percent_rule_without_losing_catalog_or_search_record(self):
        report = report_for('某半导体股票A')
        report['board_schema_version'] = SCHEMA_VERSION - 1
        report['snapshot']['funds'][0]['holdings']['rows'] = [
            {'code': str(600001 + index), 'name': '合成证券', 'weight_pct': 10,
             'instrument_type': 'stock', 'tag_status': 'ok',
             'tags': ['半导体'] if index < 4 else ['银行']}
            for index in range(8)]
        report['board_coverage'] = [{'id': 'sector_semiconductor', 'label': '半导体',
            'catalog_counts_known': True, 'screened_count': 100, 'eligible_count': 70,
            'requires_holdings_match': True, 'deep_count': 1, 'valid_quant_count': 1,
            'matched_holdings_count': 1, 'holdings_unknown_count': 0, 'holdings_mismatch_count': 0,
            'status': 'candidate', 'displayed_count': 1,
            'reason': '每板块最多展示三只；观察不等于买入。',
            'web_search': {'status': 'empty', 'query': '半导体 基金', 'searched_at': now_iso()}}]
        report['universe'] = {'selected_codes': ['000001'], 'coverage': {
            'catalog_count': 12000, 'screened_count': 11000,
            'board_count': 1, 'researched_board_count': 7, 'displayed_board_count': 1}}
        before = copy.deepcopy(report)
        engine = AutoResearchEngine()
        engine._state.update(status='ready', completed_at=now_iso(), report=report)
        try:
            with patch('research_auto.collect_universe', side_effect=AssertionError('no rescan')), \
                 patch('research_auto.discover_public_candidates', side_effect=AssertionError('no search')):
                upgraded = engine.status()['report']
        finally:
            engine.close()
        board = next(item for item in upgraded['board_coverage'] if item['id'] == 'sector_semiconductor')
        self.assertEqual(upgraded['holdings_rule_version'], HOLDINGS_RULE_VERSION)
        self.assertEqual(upgraded['sections'], [])
        self.assertEqual(board['status'], 'unknown')
        self.assertEqual(board['matched_holdings_count'], 0)
        self.assertEqual(board['holdings_mismatch_count'], 0)
        self.assertNotEqual(board['reason'], before['board_coverage'][0]['reason'])
        self.assertIn('持仓', board['reason'])
        self.assertIsNone(board['screened_count'])
        self.assertIsNone(board['eligible_count'])
        coverage = upgraded['universe']['coverage']
        self.assertEqual(coverage['board_count'], len(upgraded['board_coverage']))
        self.assertEqual(coverage['displayed_board_count'], len(upgraded['sections']))
        self.assertEqual(coverage['researched_board_count'],
                         sum(item['deep_count'] > 0 for item in upgraded['board_coverage']))
        self.assertEqual(coverage['catalog_count'], 12000)
        self.assertEqual(coverage['screened_count'], 11000)
        self.assertEqual(board['web_search']['searched_at'], before['board_coverage'][0]['web_search']['searched_at'])
        self.assertEqual(next(b for b in upgraded['board_coverage'] if b['id']=='holdings_unclassified')['research_gap']['examples'][0]['code'], '000001')
        self.assertEqual(report, before)

    def test_saved_old_report_exposes_new_directory_without_fetching_or_writing(self):
        report = report_for('某红利低波指数A')
        measured = copy.deepcopy(report['quant'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            saved = json.dumps({'version': 1, 'completed_at': now_iso(), 'report': report}, ensure_ascii=False)
            path.write_text(saved, encoding='utf-8')
            engine = AutoResearchEngine(path)
            try:
                with patch('research_auto.collect_universe', side_effect=AssertionError('no rescan')), \
                     patch('research_auto.enrich_auto_report', side_effect=AssertionError('no model call')):
                    state = engine.status()
            finally:
                engine.close()
            self.assertEqual(path.read_text(encoding='utf-8'), saved)
        upgraded = state['report']
        self.assertEqual(upgraded['board_schema_version'], SCHEMA_VERSION)
        self.assertEqual({item['id'] for item in upgraded['board_coverage']}, set(BOARDS))
        self.assertTrue(all(item['screened_count'] is None for item in upgraded['board_coverage']))
        self.assertEqual(upgraded['quant'], measured)
        self.assertEqual(upgraded['strategy']['candidates'], [])
        self.assertTrue(upgraded['sections'])
        self.assertNotIn('style_dividend_low_volatility', {s['id'] for s in upgraded['sections']})
        self.assertTrue(all(f['role']=='observation' for s in upgraded['sections'] for f in s['funds']))

    def test_industry_tags_cannot_unlock_new_style_index_or_bond_exposure(self):
        for name, kind in [('某现金流股票A', '股票型'), ('某上证50指数A', '指数型-股票'),
                           ('某中长债债券A', '债券型-长债'), ('某固收+混合A', '混合型-偏债')]:
            with self.subTest(name=name):
                report = report_for(name, kind)
                measured = copy.deepcopy(report['quant'])
                apply_board_holdings_gate(report['snapshot'], report['quant'], report['analysis'], report['strategy'])
                ids = {s['id'] for s in build_sections(report['snapshot'], report['quant'], report['analysis'], report['strategy'])}
                self.assertFalse(ids.intersection({'style_cashflow','index_sse50','long_bond','fixed_income_plus'}))
                self.assertEqual(report['quant'], measured)


if __name__ == '__main__':
    unittest.main()
