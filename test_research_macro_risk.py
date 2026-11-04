import unittest
from unittest.mock import patch
from research_macro_risk import parse_pmi, collect_macro_risk, LIST_URL

NOW='2026-10-31T14:00:00+08:00'
URL='https://www.stats.gov.cn/sj/zxfb/202610/t20261031_1965718.html'
HTML='''<meta name="ArticleTitle" content="2026年10月中国采购经理指数运行情况">
<meta name="PubDate" content="2026/10/31 09:30">
<p>制造业采购经理指数（PMI）为49.3%，新订单指数为49.4%，综合PMI产出指数为49.7%。</p>'''


class MacroRiskTests(unittest.TestCase):
    def test_parse_real_official_fields_and_deterministic_risk(self):
        result=parse_pmi(HTML,URL,NOW)
        self.assertEqual(result['values'],{'manufacturing':49.3,'new_orders':49.4,'composite':49.7})
        self.assertAlmostEqual(result['risk_score'],55.65)

    def test_no_future_release_wrong_host_future_period_or_invalid_values(self):
        for text,url,now in [(HTML,URL,'2026-10-31T09:10:00+08:00'),(HTML,URL,'2027-02-01T00:00:00+08:00'),
            (HTML,'https://www.stats.gov.cn.attacker.test/fake',NOW),
            (HTML.replace('2026年10月','2026年11月'),URL,NOW),
            (HTML.replace('49.4%','999%'),URL,NOW),(HTML.replace('新订单指数','缺项'),URL,NOW)]:
            with self.assertRaises(ValueError):parse_pmi(text,url,now)

    def test_script_text_cannot_supply_missing_official_values(self):
        text=HTML.replace('新订单指数为49.4%，','')+'<script>新订单指数为49.4%</script>'
        with self.assertRaises(ValueError):parse_pmi(text,URL,NOW)

    def test_collector_publishes_source_and_can_skip_a_future_release(self):
        listing='<a href="'+URL+'">2026年10月中国采购经理指数运行情况</a>'
        with patch('research_macro_risk.fetch_text',side_effect=[listing,HTML]):
            result,source=collect_macro_risk(NOW)
        self.assertEqual(result['status'],'ok');self.assertEqual(source['count'],3)
        previous=URL.replace('20261031','20260930')
        listing+='<a href="'+previous+'">2026年9月中国采购经理指数运行情况</a>'
        older=HTML.replace('2026年10月','2026年9月').replace('2026/10/31','2026/09/30')
        with patch('research_macro_risk.fetch_text',side_effect=[listing,HTML,older]):
            result,source=collect_macro_risk('2026-10-31T09:10:00+08:00')
        self.assertEqual(result['status'],'ok');self.assertIn('9月',result['title'])

    def test_network_failure_stays_unavailable(self):
        with patch('research_macro_risk.fetch_text',side_effect=TimeoutError('timeout')):
            result,source=collect_macro_risk(NOW)
        self.assertIsNone(result['risk_score']);self.assertEqual(source['status'],'error')


if __name__=='__main__':unittest.main()
