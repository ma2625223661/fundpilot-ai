"""Issue #7: official CPI/PPI/credit releases, cycle signals, relative reference
and overseas closes. Fixtures only; no network or real data directory."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import research_long_wave_data as lw
import research_overseas_references as refs
from research_cycle import macro_signals, phase_for
from research_data import CHINA
from research_review import price_review
from test_overseas_references import payload as index_payload
from test_research_review import sector

AS_OF = '2026-11-21T10:00:00+08:00'
CPI_URL = 'https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965795.html'
PPI_URL = 'https://www.stats.gov.cn/sj/zxfb/202611/t20261109_1965794.html'
PBC_URL = 'https://www.pbc.gov.cn/diaochatongjisi/116219/116225/2026111317040354319/index.html'


def page(title, stamp, body):
    return ('<html><head><meta name="ArticleTitle" content="%s"><meta name="PubDate" content="%s"></head>'
            '<body><script>var x=1;</script><p>%s</p></body></html>' % (title, stamp, body))


CPI = page('2026年10月份居民消费价格同比上涨0.7%', '2026/11/09 09:30',
           '2026年10月份，全国居民消费价格同比上涨0.7%。其中，城市上涨0.7%。')
PPI = page('2026年10月份工业生产者出厂价格同比下降1.2% 环比上涨0.7%', '2026/11/09 09:30',
           '2026年10月份，全国工业生产者出厂价格同比下降1.2%，环比上涨0.7%。工业生产者购进价格同比下降2.0%，环比上涨1.1%。')
CREDIT = page('2026年10月金融统计数据报告', '2026-11-13',
              '一、社会融资规模存量同比增长7.2% 初步统计，2026年10月末社会融资规模存量为469.16万亿元，同比增长7.2%。'
              '10月末，广义货币（M2）余额359.06万亿元，同比增长7.1%。')
FAI_URL = 'https://www.stats.gov.cn/sj/zxfb/202611/t20261116_1965841.html'
INDUSTRY_URL = 'https://www.stats.gov.cn/sj/zxfb/202611/t20261116_1965842.html'
ANNUAL_URL = 'https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html'
FAI = page('2026年1—10月份全国固定资产投资基本情况', '2026/11/16 10:00',
           '1—10月份，全国固定资产投资（不含农户）364824亿元，同比下降8.1%（按可比口径计算）。'
           '其中，知识产权产品投资同比增长9.2%。工业投资同比下降3.6%。其中，制造业投资下降2.9%。')
INDUSTRY = page('2026年10月份规模以上工业增加值增长4.8%', '2026/11/16 10:00',
                '10月份，规模以上工业增加值同比实际增长4.8%（扣除价格因素）。1—10月份，规模以上工业增加值同比增长5.3%。')
ANNUAL = page('中华人民共和国2025年国民经济和社会发展统计公报', '2026/02/28 09:30',
              '全员劳动生产率[4]为184413元/人，比上年提高6.1%。'
              '全年研究与试验发展（R&amp;D）经费支出39262亿元，比上年增长8.1%，与国内生产总值之比为2.80%。')


class ParserTests(unittest.TestCase):
    def test_official_values_keep_period_publication_and_sign(self):
        cpi = lw.parse_cpi(CPI, CPI_URL, AS_OF)
        self.assertEqual((cpi['period'], cpi['values']['cpi_yoy']), ('2026-10', 0.7))
        self.assertEqual(cpi['published_at'], '2026-11-09T09:30:00+08:00')
        ppi = lw.parse_ppi(PPI, PPI_URL, AS_OF)
        self.assertEqual(ppi['values'], {'ppi_yoy': -1.2, 'purchase_yoy': -2.0})
        credit = lw.parse_credit(CREDIT, PBC_URL, AS_OF)
        self.assertEqual(credit['values'], {'social_financing_stock': 469.16, 'social_financing_yoy': 7.2,
                                            'm2_balance': 359.06, 'm2_yoy': 7.1})
        self.assertIn('不含债务负担', credit['scope'])

    def test_productivity_releases_monthly_and_annual(self):
        fai = lw.parse_fai(FAI, FAI_URL, AS_OF)
        self.assertEqual(fai['values'], {'fai_yoy': -8.1, 'manufacturing_yoy': -2.9, 'intellectual_property_yoy': 9.2})
        industry = lw.parse_industry(INDUSTRY, INDUSTRY_URL, AS_OF)
        self.assertEqual(industry['values'], {'value_added_yoy': 4.8, 'value_added_ytd_yoy': 5.3})
        annual = lw.parse_annual(ANNUAL, ANNUAL_URL, AS_OF)
        self.assertEqual((annual['period'], annual['frequency']), ('2025', 'annual'))
        self.assertEqual(annual['values'], {'labour_productivity': 184413.0, 'labour_productivity_growth': 6.1,
                                            'rd_spending': 39262.0, 'rd_growth': 8.1, 'rd_intensity': 2.8})
        # A bulletin is valid until roughly the next one, not for 62 days; too old is rejected.
        with self.assertRaises(ValueError):
            lw.parse_annual(ANNUAL, ANNUAL_URL, '2027-06-30T10:00:00+08:00')
        with self.assertRaises(ValueError):
            lw.parse_fai(FAI.replace('制造业投资下降2.9%', ''), FAI_URL, AS_OF)

    def test_wrong_host_future_stale_or_missing_values_are_rejected(self):
        cases = [
            (lw.parse_cpi, CPI, 'https://example.com/t.html', AS_OF),
            (lw.parse_cpi, CPI, CPI_URL, '2026-11-08T10:00:00+08:00'),
            (lw.parse_cpi, CPI, CPI_URL, '2027-01-20T10:00:00+08:00'),
            (lw.parse_cpi, CPI.replace('全国居民消费价格同比上涨0.7%', ''), CPI_URL, AS_OF),
            (lw.parse_ppi, PPI.replace('购进价格', '采购价格'), PPI_URL, AS_OF),
            (lw.parse_credit, CREDIT, CPI_URL, AS_OF),
            (lw.parse_credit, CREDIT.replace('2026-11-13', '2027-03-13'), PBC_URL, '2027-03-14T10:00:00+08:00'),
        ]
        for parser, document, url, as_of in cases:
            with self.subTest(parser=parser.__name__, url=url, as_of=as_of), self.assertRaises(ValueError):
                parser(document, url, as_of)

    def test_collection_reads_list_once_and_caches_outside_data(self):
        listing_nbs = ('<a href="./202611/t20261109_1965795.html">2026年10月份居民消费价格同比上涨0.7%</a>'
                       '<a href="./202611/t20261109_1965794.html">2026年10月份工业生产者出厂价格同比下降1.2% 环比上涨0.7%</a>'
                       '<a href="./202611/t20261116_1965841.html">2026年1—10月份全国固定资产投资基本情况</a>'
                       '<a href="./202611/t20261116_1965842.html">2026年10月份规模以上工业增加值增长4.8%</a>')
        listing_pbc = '<a href="/diaochatongjisi/116219/116225/2026111317040354319/index.html">2026年10月金融统计数据报告</a>'
        listing_annual = '<a href="https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html">2025年</a>'
        pages = {lw.NBS_LIST_URL: listing_nbs, lw.PBC_LIST_URL: listing_pbc, lw.ANNUAL_LIST_URL: listing_annual,
                 CPI_URL: CPI, PPI_URL: PPI, PBC_URL: CREDIT, FAI_URL: FAI, INDUSTRY_URL: INDUSTRY, ANNUAL_URL: ANNUAL}
        calls = []

        def fetch(url, *args):
            calls.append(url)
            return pages[url]
        with tempfile.TemporaryDirectory() as folder, patch.object(lw, 'CACHE_PATH', Path(folder) / 'cache.json'), \
                patch.object(lw, 'fetch_text', side_effect=fetch), patch.object(lw, 'now_iso', return_value=AS_OF):
            evidence, sources = lw.collect_long_wave_evidence(AS_OF)
            self.assertEqual(calls.count(lw.NBS_LIST_URL), 1)
            self.assertEqual({k: v['status'] for k, v in evidence.items()},
                             {k: 'ok' for k in ('cpi', 'ppi', 'credit', 'fai', 'industry', 'annual')})
            self.assertEqual([s['id'] for s in sources], ['macro:nbs_cpi', 'macro:nbs_ppi', 'macro:pbc_credit',
                                                          'macro:nbs_fai', 'macro:nbs_industry', 'macro:nbs_annual'])
            calls.clear()
            again, _ = lw.collect_long_wave_evidence('2026-11-21T11:00:00+08:00')
            self.assertEqual(calls, [])
            self.assertTrue(again['cpi']['cache_used'])
        with patch.object(lw, 'fetch_text', side_effect=OSError('offline')), \
                patch.object(lw, 'load_record', return_value=None):
            evidence, sources = lw.collect_long_wave_evidence(AS_OF)
        self.assertTrue(all(v['status'] == 'unavailable' for v in evidence.values()))
        self.assertTrue(all(s['status'] == 'error' for s in sources))


def report_with(evidence):
    now = datetime(2026, 11, 21, 10, tzinfo=CHINA)
    sources = [{'id': lw._source(kind)['id'], 'status': 'ok', 'as_of': item['published_at'], 'url': item['url']}
               for kind, item in evidence.items()]
    return {'strategy': {'long_wave_evidence': evidence}, 'snapshot': {'sources': sources}}, now


class CycleSignalTests(unittest.TestCase):
    def evidence(self):
        return {'cpi': lw.parse_cpi(CPI, CPI_URL, AS_OF), 'ppi': lw.parse_ppi(PPI, PPI_URL, AS_OF),
                'credit': lw.parse_credit(CREDIT, PBC_URL, AS_OF)}

    def test_inflation_and_credit_ready_with_dates_and_productivity_stays_missing(self):
        report, now = report_with(self.evidence())
        signals = {s['id']: s for s in macro_signals(report, now)}
        self.assertEqual(signals['inflation']['status'], 'ready')
        self.assertEqual(signals['inflation']['value'], 0.7)
        self.assertEqual(signals['inflation']['as_of'], '2026-11-09T09:30:00+08:00')
        self.assertIn('统计期 2026 年 10 月', signals['inflation']['scope'])
        self.assertEqual(signals['credit']['value'], 7.2)
        self.assertIn('M2', signals['credit']['detail'])
        self.assertEqual(signals['productivity']['status'], 'missing')
        self.assertIn('不用估计值填补', signals['productivity']['detail'])
        phase = phase_for(list(signals.values()))
        self.assertEqual(phase['phase_label'], '长期阶段待验证')
        self.assertIn('生产率与投资', phase['phase_detail'])

    def test_unmatched_source_or_foreign_host_is_not_ready(self):
        evidence = self.evidence()
        report, now = report_with(evidence)
        report['snapshot']['sources'][0]['as_of'] = '2026-10-15T09:30:00+08:00'
        evidence['credit'] = dict(evidence['credit'], url='https://example.com/x.html')
        signals = {s['id']: s for s in macro_signals(report, now)}
        self.assertEqual(signals['inflation']['status'], 'missing')
        self.assertIn('CPI', signals['inflation']['detail'])
        self.assertEqual(signals['credit']['status'], 'missing')

    def test_conditional_scenario_only_when_all_five_are_ready(self):
        ready = [{'id': i, 'title': i, 'status': 'ready', 'as_of': '2026-11-09', 'period': '2026-10', 'scope': 's'}
                 for i in ('demand', 'funding', 'inflation', 'credit', 'productivity')]
        phase = phase_for(ready)
        self.assertEqual(phase['phase'], 'conditional')
        self.assertEqual(len(phase['phase_basis']), 5)
        self.assertIn('不构成投资建议', phase['phase_detail'])
        self.assertEqual(phase_for(ready[:4] + [dict(ready[4], status='missing')])['phase'], 'unverified')


class RelativeReferenceTests(unittest.TestCase):
    def market(self, history):
        return {'snapshot': {'market': [{'code': 'sh000300', 'name': '沪深300', 'source_id': 'market_tencent',
                                         'history': history}]}}

    def test_official_csi300_is_preferred_when_every_date_is_present(self):
        index = [{'date': r['date'], 'close': r['value']} for r in sector('index_csi300')['custom_index']['history']]
        review = price_review(sector(), None, '2026-10-30', report=self.market(index))
        self.assertEqual(review['status'], 'completed')
        self.assertIn('官方价格指数', review['reference_label'])
        self.assertIn('market_tencent', review['source_ids'])

    def test_missing_dates_are_named_and_company_sample_is_fallback(self):
        index = [{'date': r['date'], 'close': r['value']} for r in sector('index_csi300')['custom_index']['history']]
        index.pop(-2)
        review = price_review(sector(), sector('index_csi300'), '2026-10-30', report=self.market(index))
        self.assertEqual(review['status'], 'completed')
        self.assertIn('公司样本', review['reference_label'])
        sample = sector('index_csi300')
        sample['custom_index']['history'].pop(-2)
        review = price_review(sector(), sample, '2026-10-30', report=self.market(index))
        self.assertEqual(review['status'], 'partial')
        self.assertIn('2026-10-29', review['reason'])
        self.assertNotIn('待补', review['reason'])


class OverseasCloseTests(unittest.TestCase):
    def test_missing_final_bar_is_taken_from_the_closing_quote_and_labelled(self):
        spec = refs.REFERENCES['overseas_in_equity']
        p = index_payload(spec)
        result = p['chart']['result'][0]
        close = result['meta']['regularMarketTime']
        result['timestamp'] = result['timestamp'][:-1]
        result['indicators']['quote'][0]['close'] = result['indicators']['quote'][0]['close'][:-1]
        result['meta']['regularMarketPrice'] = 500.0
        rows, meta = refs.parse_index(p, spec, '2026-10-31T13:15:00+08:00')
        self.assertEqual(rows[-1], {'date': '2026-10-30', 'close': 500.0})
        self.assertEqual(meta['_close_from_quote'], '2026-10-30')
        result['meta']['regularMarketTime'] = close - 3600
        with self.assertRaisesRegex(ValueError, '2026-10-30'):
            refs.parse_index(p, spec, '2026-10-31T13:15:00+08:00')

    def test_weekday_holiday_keeps_the_last_session_current(self):
        # Brazil closed on Friday 2026-11-20; the source still named Thursday's session.
        zone = 'America/Sao_Paulo'
        quote = {'score_scope': 'reference_trend', 'reference_session_completed': True, 'market': 'BR',
                 'reference_timezone': zone, 'as_of': '2026-11-19', 'reference_latest_completed_date': '2026-11-19',
                 'reference_session_end': '2026-11-19T17:00:00-03:00',
                 'reference_observed_at': '2026-11-21T22:30:00+08:00'}
        self.assertTrue(refs.reference_quote_fresh(quote, '2026-11-21T22:31:00+08:00'))
        # Seen on Thursday evening only, Friday's close would have been required.
        early = dict(quote, reference_observed_at='2026-11-20T05:00:00+08:00')
        self.assertFalse(refs.reference_quote_fresh(early, '2026-11-21T08:00:00+08:00'))

    def test_composite_names_each_missing_market_and_reason(self):
        def collected(key, as_of):
            if key == 'reference_br_equity':
                raise ValueError('来源会话已结束但缺少对应收盘日线（2026-11-20）')
            raise ValueError('other')
        with patch.object(refs, '_collect', side_effect=collected):
            quotes, sources, _ = refs.collect_overseas_references([{'id': 'overseas_em_equity'}], AS_OF)
        self.assertFalse(quotes)
        error = next(s['error'] for s in sources if s['id'] == 'overseas_reference:overseas_em_equity')
        self.assertIn('巴西IBOVESPA指数', error)
        self.assertIn('2026-11-20', error)
        self.assertNotIn('reference_br_equity', error)

    def test_us_equity_and_healthcare_have_verifiable_references(self):
        self.assertEqual(refs.COMPOSITES['overseas_us_equity']['members'], ['overseas_sp500', 'overseas_nasdaq'])
        health = refs.REFERENCES['overseas_healthcare']
        self.assertEqual((health['symbol'], health['instrument']), ('XLV', 'ETF'))
        p = index_payload(health)
        p['chart']['result'][0]['meta']['instrumentType'] = 'ETF'
        rows, _ = refs.parse_index(p, health, '2026-10-31T13:15:00+08:00')
        self.assertEqual(rows[-1]['date'], '2026-10-30')
        p['chart']['result'][0]['meta']['instrumentType'] = 'INDEX'
        with self.assertRaises(ValueError):
            refs.parse_index(p, health, '2026-10-31T13:15:00+08:00')


if __name__ == '__main__':
    unittest.main()
