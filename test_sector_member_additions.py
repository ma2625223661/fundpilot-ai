"""Identity and parsing guards for the five added A-share member lists."""
import unittest
from unittest.mock import MagicMock, patch

import research_public_data as data


class AddedSectorMembershipTests(unittest.TestCase):
    CASES = (
        ('sector_energy_storage', '931747', '中证储能主题指数', '中证储能'),
        ('sector_power', 'H30199', '中证全指电力公用事业指数', '电力指数'),
        ('sector_grid_equipment', '931994', '中证电网设备主题指数', '电网设备主题'),
        ('sector_real_estate', '931775', '中证全指房地产指数', '房地产'),
        ('sector_construction_machinery', '931752', '中证工程机械主题指数', '工程机械主题'),
        ('sector_cxo', '931750', '中证医药研发服务主题指数', 'CXO'),
        ('sector_medical', '399989', '中证医疗指数', '中证医疗'),
        ('sector_consumer_electronics', '931494', '中证消费电子主题指数', '消费电子'),
        ('index_dual50', '931643', '中证科创创业50指数', '科创创业50'),
    )

    def test_each_mapping_is_exact_and_only_requested_sectors_are_added(self):
        for identity, code, title, short_name in self.CASES:
            with self.subTest(identity=identity):
                refs = data.reference_memberships([{'id': identity}])
                self.assertEqual(set(refs), {identity})
                self.assertEqual(refs[identity], {
                    'code': code, 'title': title, 'aliases': [title, short_name]})
        self.assertEqual(data.reference_memberships([]), {})

    def test_dated_members_accept_official_short_name_and_reject_adjacent_identity(self):
        sheet = MagicMock(ncols=9, nrows=2)
        sheet.cell_value.return_value = '成份券代码Constituent Code'
        workbook = MagicMock()
        workbook.sheet_by_index.return_value = sheet
        for identity, code, title, short_name in self.CASES:
            with self.subTest(identity=identity), patch('xlrd.open_workbook', return_value=workbook):
                ref = data.reference_memberships([{'id': identity}])[identity]
                row = ['20261030', code, short_name, '', '000001', '样本公司', '', '深圳证券交易所', '']
                sheet.row_values.return_value = row
                members = data.parse_members(b'xls', ref, '2026-10-31T09:00:00+08:00')
                self.assertEqual(members[0]['index_code'], code)
                self.assertEqual(members[0]['member_date'], '2026-10-30')
                self.assertEqual(members[0]['ts_code'], '000001.SZ')
                sheet.row_values.return_value = [*row[:2], '无关宽基指数', *row[3:]]
                with self.assertRaises(ValueError):
                    data.parse_members(b'xls', ref, '2026-10-31T09:00:00+08:00')


if __name__ == '__main__':
    unittest.main()
