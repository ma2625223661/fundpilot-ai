import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research_ai_cache import AIEvidenceCache, semantic_fingerprint, CACHE_TTL_SECONDS


class SemanticFingerprintTests(unittest.TestCase):
    def evidence(self):
        return {'as_of': '2026-10-31T09:10:00+08:00', 'revision': 'a',
                'quote': {'as_of': '2026-10-30T15:00:00+08:00', 'price': 20, 'trade_date': '2026-10-30'},
                'sources': [{'id': 'quote', 'status': 'ok', 'fetched_at': '2026-10-31T09:10:00+08:00'}],
                'company': {'ann_date': '2026-10-30', 'roe': 20, 'membership': 'PCB'},
                'score': 65, 'risk': 'high', 'news': [{'summary': '真实公告', 'published_at': '2026-10-30T17:00:00+08:00'}]}

    def test_collection_noise_is_ignored_without_mutating_evidence(self):
        original = self.evidence()
        changed = copy.deepcopy(original)
        changed.update(as_of='2026-10-31T14:30:00+08:00', revision='b', checked_at='new', calculated_at='new')
        changed['sources'][0].update(fetched_at='new', observed_at='new')
        self.assertEqual(semantic_fingerprint('model', 'prompt', original),
                         semantic_fingerprint('model', 'prompt', changed))
        self.assertEqual(original, self.evidence())

    def test_material_evidence_model_prompt_and_day_changes_invalidate(self):
        original = self.evidence()
        fingerprint = semantic_fingerprint('model', 'prompt', original)
        variants = []
        for key, value in [('score', 64), ('risk', 'low'), ('as_of', '2026-11-01T09:10:00+08:00')]:
            changed = copy.deepcopy(original); changed[key] = value; variants.append(changed)
        for group, key, value in [('quote', 'price', 21), ('quote', 'trade_date', '2026-10-31'),
                                  ('company', 'ann_date', '2026-10-31'), ('company', 'membership', 'CPO')]:
            changed = copy.deepcopy(original); changed[group][key] = value; variants.append(changed)
        changed = copy.deepcopy(original); changed['sources'][0]['status'] = 'error'; variants.append(changed)
        changed = copy.deepcopy(original); changed['news'][0]['summary'] = '新的公告'; variants.append(changed)
        for changed in variants:
            self.assertNotEqual(semantic_fingerprint('model', 'prompt', changed), fingerprint)
        self.assertNotEqual(semantic_fingerprint('other', 'prompt', original), fingerprint)
        self.assertNotEqual(semantic_fingerprint('model', 'new prompt', original), fingerprint)

    def test_dictionary_order_is_stable_and_nonfinite_values_are_rejected(self):
        self.assertEqual(semantic_fingerprint('m', 's', {'a': 1, 'b': 2}),
                         semantic_fingerprint('m', 's', {'b': 2, 'a': 1}))
        with self.assertRaises(ValueError):
            semantic_fingerprint('m', 's', {'score': float('nan')})


class EvidenceCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'cache.sqlite3'
        self.now = 1793409000.0
        self.cache = AIEvidenceCache(self.path, clock=lambda: self.now)
        self.key = semantic_fingerprint('model', 'prompt', {'quote': 20})

    def test_result_round_trip_restart_detachment_and_original_time(self):
        value = {'reason': '财务与走势支持研究', 'evidence_ids': ['quote'], 'risks': ['风险']}
        self.assertTrue(self.cache.put('sector', self.key, value))
        value['reason'] = 'changed'
        restored = AIEvidenceCache(self.path, clock=lambda: self.now + 60)
        result = restored.get('sector', self.key)
        self.assertEqual(result['value']['reason'], '财务与走势支持研究')
        self.assertEqual(datetime.fromisoformat(result['created_at']).timestamp(), self.now)
        result['value']['reason'] = 'changed'
        self.assertEqual(restored.get('sector', self.key)['value']['reason'], '财务与走势支持研究')
        self.assertIsNone(restored.get('events', self.key))

    def test_expired_future_and_oversized_results_are_misses(self):
        self.assertTrue(self.cache.put('sector', self.key, {'reason': 'ok'}))
        self.now += CACHE_TTL_SECONDS
        self.assertIsNone(self.cache.get('sector', self.key))
        self.now -= CACHE_TTL_SECONDS + 1
        self.assertIsNone(self.cache.get('sector', self.key))
        self.assertFalse(self.cache.put('sector', self.key, {'reason': '大' * 30000}))
        self.assertFalse(self.cache.put('sector', self.key, {'score': float('nan')}))

    def test_size_bound_cleanup(self):
        with patch('research_ai_cache.MAX_CACHE_ENTRIES', 2):
            for index in range(4):
                key = semantic_fingerprint('m', 'p', index)
                self.assertTrue(self.cache.put('sector', key, {'index': index}))
                self.now += 1
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM evidence_results').fetchone()[0], 2)
        self.assertIsNone(self.cache.get('sector', semantic_fingerprint('m', 'p', 0)))

    def test_attempt_cooldown_survives_restart_and_changes_get_new_slot(self):
        self.assertFalse(self.cache.recent_attempt('sector', self.key))
        self.assertTrue(self.cache.mark_attempt('sector', self.key))
        restored = AIEvidenceCache(self.path, clock=lambda: self.now)
        self.assertTrue(restored.recent_attempt('sector', self.key))
        self.assertFalse(restored.mark_attempt('sector', self.key))
        other = semantic_fingerprint('m', 'p', 'new evidence')
        self.assertTrue(restored.mark_attempt('sector', other))
        self.now += 1800
        self.assertFalse(restored.recent_attempt('sector', self.key))
        self.assertTrue(restored.mark_attempt('sector', self.key))

    def test_concurrent_process_equivalent_instances_admit_only_one_attempt(self):
        def mark(_):
            return AIEvidenceCache(self.path, clock=lambda: self.now).mark_attempt('sector', self.key)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(mark, range(16)))
        self.assertEqual(sum(results), 1)

    def test_corrupt_store_misses_results_but_blocks_new_attempts(self):
        self.path.write_bytes(b'broken database; do not overwrite')
        self.assertIsNone(self.cache.get('sector', self.key))
        self.assertFalse(self.cache.put('sector', self.key, {'reason': 'ok'}))
        self.assertTrue(self.cache.recent_attempt('sector', self.key))
        self.assertFalse(self.cache.mark_attempt('sector', self.key))
        self.assertEqual(self.path.read_bytes(), b'broken database; do not overwrite')

    def test_invalid_inputs_fail_closed_and_payload_is_never_stored(self):
        self.assertFalse(self.cache.mark_attempt('sector', 'invalid'))
        self.assertTrue(self.cache.recent_attempt('sector', 'invalid'))
        self.assertFalse(self.cache.put('sector', 'invalid', {}))
        self.assertIsNone(self.cache.get('sector', 'invalid'))
        self.assertFalse(self.cache.mark_attempt('sector', self.key, seconds=0))
        secret_evidence = 'sensitive input that must not be stored'
        key = semantic_fingerprint('m', 'p', {'input': secret_evidence})
        self.assertTrue(self.cache.mark_attempt('sector', key))
        self.assertTrue(self.cache.put('sector', key, {'reason': 'validated output'}))
        self.assertNotIn(secret_evidence.encode(), self.path.read_bytes())

    def test_datetime_clock_is_supported(self):
        now = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        cache = AIEvidenceCache(self.path, clock=lambda: now)
        self.assertTrue(cache.put('sector', self.key, {'reason': 'ok'}))
        self.assertEqual(cache.get('sector', self.key)['created_at'], '2026-10-31T08:00:00+08:00')


if __name__ == '__main__':
    unittest.main()
