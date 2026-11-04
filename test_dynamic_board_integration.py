"""Offline integration for holdings-driven additions and one-board assignment."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_auto as automatic
import research_categories as categories
import research_holdings as holdings
from research_dynamic_boards import merge_dynamic_board_registry
from test_research_dynamic_boards import AS_OF, fund, stock
from test_research_auto import sample_report
from research_data import now_iso


class DynamicBoardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch.dict(categories.BOARDS, copy.deepcopy(categories.BOARDS), clear=True).start()
        patch.dict(holdings.BOARD_TAGS, copy.deepcopy(holdings.BOARD_TAGS), clear=True).start()
        # Any unexpected source/AI access is a failure, never a live test call.
        patch('research_holdings._fetch', side_effect=AssertionError('offline test')).start()
        patch('research_auto.collect_universe', side_effect=AssertionError('offline test')).start()
        patch('research_auto.enrich_auto_report', side_effect=AssertionError('offline test')).start()

    def test_missing_industry_is_registered_and_fund_only_enters_highest_board(self):
        item = fund(rows=[stock(weight=40, industry='光学光电子'), stock('600002', 10, '银行')])
        for row in item['holdings']['rows']:
            row['tags'] = list(row['industry_tags'])
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        self.assertEqual(len(registry), 1)
        identity = registry[0]['id']
        self.assertIn(identity, categories.BOARDS)
        self.assertEqual(holdings.BOARD_TAGS[identity], {'光学光电子'})
        primary = categories.boards_for(item, 'equity_active', AS_OF)
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0]['id'], identity)
        self.assertEqual(primary[0]['board_match']['matched_disclosed_pct'], 80)
        self.assertEqual(primary[0]['board_match']['matched_weight_pct'], 40)
        self.assertEqual(primary[0]['board_match']['disclosed_weight_pct'], 50)

    def test_equal_exposure_prefers_registered_finer_industry_and_only_one_destination(self):
        item = fund(rows=[stock(weight=40, industry='光学元件', industry_level=3), stock('600002', 10, None, tag_status='unknown', tags=[])])
        item['holdings']['rows'][0]['tags'] = ['光学元件', '电子']
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        identity = registry[0]['id']
        all_matches = categories.board_matches_for(item, 'equity_active', AS_OF)
        self.assertEqual(all_matches[0]['id'], identity)
        self.assertIn('sector_technology', [board['id'] for board in all_matches])
        primary = categories.boards_for(item, 'equity_active', AS_OF)
        self.assertEqual([board['id'] for board in primary], [identity])
        self.assertTrue(primary[0]['board_match']['ratio_is_lower_bound'])
        self.assertEqual(primary[0]['board_match']['matched_disclosed_pct'], 80)

    def test_existing_parent_tag_does_not_block_missing_software_board(self):
        self.assertIn('软件开发', holdings.BOARD_TAGS['sector_technology'])
        self.assertFalse(any(board['label'] == '软件开发' for board in categories.BOARDS.values()))
        item = fund(rows=[stock(weight=40, industry='软件开发', industry_level=2), stock('600002', 10, None)])
        item['holdings']['rows'][0]['tags'] = ['软件开发']
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        self.assertEqual([board['label'] for board in registry], ['软件开发'])
        primary = categories.boards_for(item, 'equity_active', AS_OF)
        self.assertEqual(primary[0]['label'], '软件开发')
        self.assertEqual(primary[0]['board_match']['matched_disclosed_pct'], 80)

    def test_repeat_registration_and_json_restoration_preserve_exact_membership(self):
        item = fund(rows=[stock(weight=40, industry='光学元件'), stock('600002', 10, None)])
        item['holdings']['rows'][0]['tags'] = ['光学元件']
        first = automatic._update_dynamic_catalog([item], [], AS_OF)
        second = automatic._update_dynamic_catalog([item], first, AS_OF)
        self.assertEqual([board['id'] for board in second], [board['id'] for board in first])
        restored = json.loads(json.dumps(second, ensure_ascii=False))
        identity = first[0]['id']
        categories.BOARDS.pop(identity)
        holdings.BOARD_TAGS.pop(identity)
        verified = categories.register_dynamic_boards(restored, AS_OF)
        self.assertEqual([board['id'] for board in verified], [identity])
        self.assertEqual(categories.boards_for(item, 'equity_active', AS_OF)[0]['id'], identity)
        self.assertEqual(len([board for board in categories.BOARDS.values() if board.get('dynamic')]), 1)

    def test_broad_medical_biology_never_beats_narrow_medical_at_equal_exposure(self):
        item = fund(rows=[stock(weight=50, industry='医药生物', tags=['医疗服务', '医药生物'])])
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        self.assertEqual([b['label'] for b in registry], ['医药生物'])
        primary = categories.boards_for(item, 'equity_active', AS_OF)[0]
        self.assertEqual(primary['id'], 'sector_medical')
        self.assertEqual(primary['board_match']['matched_disclosed_pct'], 100)
        item['holdings']['rows'].append(stock('600002', 5, '医药生物', tags=['医药生物']))
        # Higher actual exposure still takes priority over a narrower board.
        self.assertEqual(categories.boards_for(item, 'equity_active', AS_OF)[0]['id'], registry[0]['id'])

    def test_broad_electronics_tie_prefers_semiconductor_then_narrow_chip_equipment(self):
        item = fund(rows=[stock(weight=50, industry='电子', tags=['电子','半导体','半导体设备'])])
        automatic._update_dynamic_catalog([item], [], AS_OF)
        self.assertEqual(categories.board_for(item,'equity_active',AS_OF)['id'],'sector_semiconductor_equipment')
        item['holdings']['rows'][0]['tags']=['电子','半导体']
        self.assertEqual(categories.board_for(item,'equity_active',AS_OF)['id'],'sector_semiconductor')

    def test_nav_weights_are_used_instead_of_stock_counts_and_names_do_not_reclassify(self):
        rows = [stock(weight=30, industry='光学元件'),
                stock('600002', 5, '银行'), stock('600003', 5, '银行'), stock('600004', 5, '银行'),
                stock('600005', 5, None, tag_status='unknown')]
        for row in rows:
            row['tags'] = list(row['industry_tags'])
        item = fund(rows=rows)
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        self.assertEqual([board['label'] for board in registry], ['光学元件'])
        before = categories.boards_for(item, 'equity_active', AS_OF)[0]
        self.assertEqual(before['board_match']['matched_disclosed_pct'], 60)
        self.assertEqual(before['board_match']['disclosed_weight_pct'], 50)
        item['name'] = '银行消费科技半导体基金'
        for row in rows:
            row['name'] = '银行科技'
        after = categories.boards_for(item, 'equity_active', AS_OF)[0]
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['board_match']['matched_disclosed_pct'], before['board_match']['matched_disclosed_pct'])

    def test_corrupt_persisted_proposals_are_ignored_without_losing_valid_sector(self):
        item = fund(rows=[stock(weight=50, industry='光学元件')])
        valid = automatic._update_dynamic_catalog([item], [], AS_OF)
        invalid = copy.deepcopy(valid[0])
        invalid['evidence'][0]['matched_disclosed_pct'] = 'bad numeric string'
        registry = merge_dynamic_board_registry([invalid], valid, AS_OF)
        self.assertEqual([board['id'] for board in registry], [valid[0]['id']])
        self.assertEqual(registry[0]['best_matched_disclosed_pct'], 100)

    def test_old_report_status_uses_its_empty_registry_and_restores_new_global_catalog(self):
        item = fund(rows=[stock(weight=50, industry='光学元件', tags=['光学元件'])])
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        identity = registry[0]['id']
        report = sample_report()
        report['snapshot']['funds'][0]['holdings'] = item['holdings']
        report['dynamic_board_registry'] = []
        engine = automatic.AutoResearchEngine()
        self.addCleanup(engine.close)
        engine._state.update(status='ready', report=report, completed_at=now_iso())
        result = engine.status()['report']
        self.assertNotIn(identity, {board['id'] for board in result['board_coverage']})
        self.assertNotIn(identity, {section['id'] for section in result['sections']})
        self.assertEqual(result['sections'], [])
        self.assertIn(identity, categories.BOARDS)
        self.assertIn(identity, holdings.BOARD_TAGS)
        self.assertEqual(categories.boards_for(item, 'equity_active', AS_OF)[0]['id'], identity)

    def test_persisted_report_restores_own_registry_and_does_not_leak_other_new_sector(self):
        item = fund(rows=[stock(weight=50, industry='光学元件', tags=['光学元件'])])
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        identity = registry[0]['id']
        report = sample_report()
        report['snapshot']['funds'][0]['holdings'] = item['holdings']
        report['dynamic_board_registry'] = registry
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dynamic-report.json'
            writer = automatic.AutoResearchEngine(path)
            writer._persist(report, now_iso())
            writer.close()
            categories.BOARDS.pop(identity)
            holdings.BOARD_TAGS.pop(identity)
            other = fund('000002', [stock(weight=50, industry='塑料制品', tags=['塑料制品'])])
            other_registry = automatic._update_dynamic_catalog([other], [], AS_OF)
            other_identity = other_registry[0]['id']
            restored = automatic.AutoResearchEngine(path)
            self.addCleanup(restored.close)
            result = restored.status()['report']
        self.assertIn(identity, {board['id'] for board in result['board_coverage']})
        self.assertEqual([section['id'] for section in result['sections']], [identity])
        self.assertNotIn(other_identity, {board['id'] for board in result['board_coverage']})
        self.assertIn(identity, categories.BOARDS)
        self.assertIn(other_identity, categories.BOARDS)
        self.assertIn(identity, holdings.BOARD_TAGS)
        self.assertIn(other_identity, holdings.BOARD_TAGS)

    def test_catalog_scope_restores_global_even_when_status_rendering_fails(self):
        item = fund(rows=[stock(weight=50, industry='光学元件', tags=['光学元件'])])
        registry = automatic._update_dynamic_catalog([item], [], AS_OF)
        identity = registry[0]['id']
        with self.assertRaisesRegex(RuntimeError, 'failed render'):
            with categories.board_catalog_scope([], AS_OF):
                self.assertNotIn(identity, categories.BOARDS)
                self.assertNotIn(identity, holdings.BOARD_TAGS)
                raise RuntimeError('failed render')
        self.assertIn(identity, categories.BOARDS)
        self.assertIn(identity, holdings.BOARD_TAGS)


if __name__ == '__main__':
    unittest.main()
