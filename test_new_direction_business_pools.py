"""New directions retain exact company identities and limited business scope."""
import unittest
from unittest.mock import patch

import research_theme_memberships as theme
from research_sample_policy import MAX_SAMPLES
from urllib.parse import urlsplit

NOW = '2026-10-31T12:00:00+08:00'


class NewDirectionBusinessPools(unittest.TestCase):
    EXPECTED = {
        'sector_manufacturing': {'600031.SH', '601100.SH'},
        'sector_lithium_mining': {'002460.SZ', '002466.SZ'},
        'sector_agriculture': {'300498.SZ', '000876.SZ', '000998.SZ'},
        'sector_oil_gas': {'600938.SH', '603619.SH'},
        'gold': {'601899.SH', '600547.SH'},
        'commodities': {'601899.SH', '600938.SH'},
        'sector_brain_computer': {'688626.SH', '301293.SZ'},
        'sector_insurance': {'601601.SH', '601319.SH'},
    }

    def test_seed_companies_are_preserved_and_expanded_pool_evidence_is_explicit(self):
        for identity, expected in self.EXPECTED.items():
            with self.subTest(identity=identity):
                rows = theme.BUSINESS_EVIDENCE[identity]
                codes = {row['ts_code'] for row in rows}
                self.assertTrue(expected <= codes)
                self.assertEqual(len(rows), len(codes))
                self.assertTrue(len(expected) <= len(rows) <= MAX_SAMPLES)
                self.assertTrue(theme.BUSINESS_REFERENCES[identity]['code'].startswith('business:'))
                for row in rows:
                    self.assertRegex(row['ts_code'], r'^\d{6}\.(?:SH|SZ|BJ)$')
                    self.assertTrue(row['name'])
                    self.assertTrue(row['title'])
                    self.assertTrue(row['description'])
                    self.assertGreaterEqual(len(row['required']), 3)
                    self.assertIn(urlsplit(row['url']).scheme, ('http', 'https'))
                    self.assertTrue(urlsplit(row['url']).hostname)
                    self.assertIn('published_date', row)

    def test_hidden_comment_or_script_facts_never_establish_business_membership(self):
        evidence = theme.BUSINESS_EVIDENCE['sector_oil_gas'][0]
        ref = theme.BUSINESS_REFERENCES['sector_oil_gas']
        body = ' '.join(evidence['required'][:-1])
        missing = evidence['required'][-1]
        for hidden in ('<!-- ' + missing + ' -->', '<script>' + missing + '</script>'):
            with self.subTest(hidden=hidden), self.assertRaises(ValueError):
                theme.parse_business_evidence(body + hidden, evidence, ref, NOW, NOW)

    def test_independent_pools_emit_exact_sources_without_adjacent_sectors(self):
        requested = [{'id': key} for key in self.EXPECTED]
        def member(evidence, reference, as_of):
            # Offline public HTML fixture; the production downloader is never used.
            body = '<p>' + ' '.join(evidence['required']) + '</p>'
            return theme.parse_business_evidence(body, evidence, reference, as_of, NOW)
        with patch.object(theme, 'fetch_business_member', side_effect=member), \
             patch('research_public_data._save'):
            result = theme.fetch_theme_memberships(requested, NOW)
        self.assertEqual(set(result['memberships']), set(self.EXPECTED))
        sources = {row['id'] for row in result['sources']}
        for key, expected in self.EXPECTED.items():
            rows = result['memberships'][key][0]
            codes = {row['ts_code'] for row in rows}
            self.assertTrue(expected <= codes)
            self.assertEqual(codes, {row['ts_code'] for row in theme.BUSINESS_EVIDENCE[key]})
            for row in rows:
                self.assertEqual(row['evidence_type'], 'public_business')
                self.assertEqual(row['member_date'], '2026-10-31')
                self.assertEqual(len(row['source_ids']), 1)
                self.assertIn(row['source_ids'][0], sources)

    def test_brain_computer_stays_research_link_and_gold_stays_equity(self):
        evidence = theme.BUSINESS_EVIDENCE['sector_brain_computer'][1]
        row = theme.parse_business_evidence(' '.join(evidence['required']), evidence,
            theme.BUSINESS_REFERENCES['sector_brain_computer'], NOW, NOW)
        self.assertIn('临床研究关联', row['role'])
        self.assertIn('非主题收入', row['role'])
        self.assertEqual(row['published_date'], '2025-04-01')
        self.assertIn('黄金矿业股票', theme.BUSINESS_REFERENCES['gold']['title'])
        for evidence in theme.BUSINESS_EVIDENCE['gold']:
            self.assertRegex(evidence['ts_code'], r'^6\d{5}\.SH$')
            self.assertRegex(evidence['description'], r'金价|黄金现货价格')


if __name__ == '__main__':
    unittest.main()
