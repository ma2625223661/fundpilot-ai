import copy
import unittest

from research_sample_policy import finalize_company_samples, fair_codes, provider_basis, MAX_SAMPLES, VERIFIED_MARK
from research_leader_index import build_indicator
from test_research_leader_index import member, NOW, BOARD


class ExpandedSampleTests(unittest.TestCase):
    def rows(self, count=12):
        rows = [member(f'{600000+i:06d}.SH', daily=.0001*(i+1)) for i in range(count)]
        for i, row in enumerate(rows):
            row['market_metrics'] = {'total_mv': 100-i}
            row['financials'].update(eps=1 if i >= 8 else -1, roe=8 if i >= 8 else -2,
                                     tr_yoy=10 if i >= 8 else -10, netprofit_yoy=20 if i >= 8 else -10)
        return rows

    def test_more_than_three_weighted_samples_and_quality_additions(self):
        original = self.rows()
        company = {'sector_leaders': {'test': copy.deepcopy(original)}}
        finalize_company_samples(company, NOW)
        rows = company['sector_leaders']['test']
        self.assertEqual(len(rows), MAX_SAMPLES)
        self.assertEqual([r['ts_code'] for r in rows[:4]], [r['ts_code'] for r in original[:4]])
        self.assertEqual({r['ts_code'] for r in rows[4:]}, {r['ts_code'] for r in original[8:]})
        bundle = build_indicator(BOARD, rows, NOW)
        self.assertTrue(bundle['meta']['ready'])
        self.assertEqual(len(bundle['meta']['constituents']), 8)
        self.assertAlmostEqual(sum(r['weight_pct'] for r in bundle['meta']['constituents']), 100)
        expected = 100
        for i in range(1, len(rows[0]['history'])):
            expected *= sum(r['history'][i]['close']/r['history'][i-1]['close'] for r in rows)/len(rows)
        self.assertAlmostEqual(bundle['meta']['value'], round(expected, 4))

    def test_missing_finance_history_and_membership_are_pending_not_fabricated(self):
        rows = self.rows(6)
        rows[0]['financials'] = None
        rows[1]['history'] = rows[1]['history'][:-1]
        rows[2]['membership_evidence'] = {}
        company = {'sector_leaders': {'test': rows}}
        finalize_company_samples(company, NOW)
        self.assertEqual(len(company['sector_leaders']['test']), 3)
        pending = company['sample_selection']['test']['pending']
        self.assertEqual(len(pending), 3)
        self.assertIn('财务', pending[0]['reason'])
        self.assertIn('走势', pending[1]['reason'])
        self.assertIn('归属', pending[2]['reason'])
        self.assertTrue(all(all(r['sample_checks'].values()) for r in company['sector_leaders']['test']))

    def test_insufficient_complete_companies_never_yields_ready_basket(self):
        rows = self.rows(2)
        rows[1]['history'] = []
        company = {'sector_leaders': {'test': rows}}
        finalize_company_samples(company, NOW)
        self.assertFalse(build_indicator(BOARD, company['sector_leaders']['test'], NOW)['meta']['ready'])

    def test_reused_samples_do_not_repeat_the_verification_sentence(self):
        company = {'sector_leaders': {'test': self.rows()}}
        finalize_company_samples(company, NOW)
        first = [r['selection_basis'] for r in company['sector_leaders']['test']]
        # A later refresh reuses the selected rows, as the auto research does.
        finalize_company_samples(company, NOW)
        second = [r['selection_basis'] for r in company['sector_leaders']['test']]
        self.assertEqual(first, second)
        self.assertTrue(all(text.count('数据核验通过') == 1 for text in second))

    def test_already_repeated_text_is_cleaned_on_the_next_refresh(self):
        rows = self.rows()
        tail = VERIFIED_MARK + '市值/固定池代表样本；近期61个交易日走势完整。'
        for row in rows:
            row['selection_basis'] = '官方成分市值代表' + tail * 3
        company = {'sector_leaders': {'test': rows}}
        finalize_company_samples(company, NOW)
        for row in company['sector_leaders']['test']:
            self.assertTrue(row['selection_basis'].startswith('官方成分市值代表' + VERIFIED_MARK))
            self.assertEqual(row['selection_basis'].count('数据核验通过'), 1)
        self.assertEqual(provider_basis(None), '')

    def test_round_robin_requests_do_not_starve_sectors_or_truncate_to_180(self):
        pools = {str(i): [{'ts_code': f'{i}-{j}'} for j in range(12)] for i in range(40)}
        codes = fair_codes(pools)
        self.assertEqual(len(codes), 480)
        self.assertEqual(codes[:40], [f'{i}-0' for i in range(40)])
        self.assertEqual(len(fair_codes({'a': [{'ts_code':'same'}], 'b':[{'ts_code':'same'}]})), 1)


if __name__ == '__main__':
    unittest.main()
