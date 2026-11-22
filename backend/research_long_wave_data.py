"""Date-checked official price and credit releases for the long-wave workspace.

Issue #7: CPI and PPI come from the National Bureau of Statistics release list,
social financing stock growth and M2 from the PBOC financial statistics report.
Each value keeps its statistical period, publication date, source URL and scope.
Nothing is estimated: a release that cannot be verified is reported as missing.

Issue #10 adds the productivity and investment group: monthly fixed-asset
investment and industrial value added, plus the annual statistical bulletin
(overall labour productivity, R&D spending and intensity), which is published
once a year and is marked as such.
"""
import html
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from research_data import CHINA, fetch_text, now_iso
from research_evidence_cache import load_record, save_record

NBS_LIST_URL = 'https://www.stats.gov.cn/sj/zxfb/'
PBC_LIST_URL = 'https://www.pbc.gov.cn/diaochatongjisi/116219/116225/index.html'
ANNUAL_LIST_URL = 'https://www.stats.gov.cn/sj/tjgb/ndtjgb/'
ANNUAL_MAX_AGE_DAYS = 460
DASH = '[—－-]'
CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'macro-long-wave-cache.json'
MAX_AGE_DAYS = 62
CACHE_SECONDS = 6 * 3600

LINK = re.compile(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>', re.S | re.I)
SIGNED = r'(上涨|下降|增长|提高|降低|减少|持平)([\d.]+)?%?'

SPECS = {
    'cpi': {
        'name': '国家统计局 · 居民消费价格指数（CPI）',
        'host': 'www.stats.gov.cn', 'list': NBS_LIST_URL,
        'title': re.compile(r'(\d{4})年(\d{1,2})月份居民消费价格同比(?:上涨|下降|持平)[\d.]*%?'),
        'scope': '全国居民消费价格同比，月度数据；只反映当月价格水平变化，不是长期通胀趋势或实际利率。',
    },
    'ppi': {
        'name': '国家统计局 · 工业生产者价格指数（PPI）',
        'host': 'www.stats.gov.cn', 'list': NBS_LIST_URL,
        'title': re.compile(r'(\d{4})年(\d{1,2})月份工业生产者出厂价格同比(?:上涨|下降|持平)[\d.]*%?\s*环比(?:上涨|下降|持平)[\d.]*%?'),
        'scope': '全国工业生产者出厂及购进价格同比，月度数据；反映工业品价格，不代表企业利润或长期通胀趋势。',
    },
    'credit': {
        'name': '中国人民银行 · 金融统计数据报告',
        'host': 'www.pbc.gov.cn', 'list': PBC_LIST_URL,
        'title': re.compile(r'(\d{4})年(\d{1,2}月|一季度|上半年|前三季度)?金融统计数据报告'),
        'scope': '社会融资规模存量与广义货币（M2）同比，月末存量；反映信用总量增速，不含债务负担、偿债能力或信用利差。',
    },
    'fai': {
        'name': '国家统计局 · 全国固定资产投资',
        'host': 'www.stats.gov.cn', 'list': NBS_LIST_URL,
        'title': re.compile(r'(\d{4})年1' + DASH + r'(\d{1,2})月份全国固定资产投资基本情况'),
        'scope': '年初至当月累计同比（不含农户），按国家统计局可比口径；反映投资规模变化，不等于资本回报或生产率。',
    },
    'industry': {
        'name': '国家统计局 · 规模以上工业增加值',
        'host': 'www.stats.gov.cn', 'list': NBS_LIST_URL,
        'title': re.compile(r'(\d{4})年(\d{1,2})月份规模以上工业增加值(?:增长|下降)[\d.]*%?'),
        'scope': '规模以上工业增加值同比实际增速（扣除价格因素）；只覆盖规模以上工业，不代表全要素生产率。',
    },
    'annual': {
        'name': '国家统计局 · 国民经济和社会发展统计公报',
        'host': 'www.stats.gov.cn', 'list': ANNUAL_LIST_URL,
        'title': re.compile(r'中华人民共和国(\d{4})年国民经济和社会发展统计公报'),
        # The bulletin list page names each release by its year only.
        'list_title': re.compile(r'(?:中华人民共和国)?\d{4}年(?:国民经济和社会发展统计公报)?'),
        'scope': '年度数据，每年约 2 月底发布一次：全员劳动生产率（按从业人员计算）与研究与试验发展（R&D）经费；不是月度变化。',
    },
}


def _now(as_of):
    value = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    return value.replace(tzinfo=CHINA) if value.tzinfo is None else value


def _visible(document):
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', document, flags=re.S | re.I)
    return re.sub(r'\s+', '', html.unescape(re.sub('<[^>]+>', ' ', text)))


def _meta(document, name):
    match = re.search(r'<meta\s+name="' + name + r'"\s+content="([^"]+)"', document)
    return match[1].strip() if match else None


def _signed(verb, number):
    if verb == '持平':
        return 0.0
    if number is None:
        raise ValueError('官方数值缺失')
    value = float(number)
    return -value if verb in ('下降', '降低', '减少') else value


def _check_dates(year, month, published, now):
    if not 1 <= month <= 12 or (year, month) >= (published.year, published.month):
        raise ValueError('统计期尚未结束或身份异常')
    if (published.year * 12 + published.month) - (year * 12 + month) > 2:
        raise ValueError('统计期过旧')
    if not 0 <= (now - published).total_seconds() <= MAX_AGE_DAYS * 86400:
        raise ValueError('公告尚未发布或已超过 62 天')


def _result(kind, url, title, published, year, month, values, now):
    return {'status': 'ok', 'kind': kind, 'title': title, 'url': url,
            'period': '%04d-%02d' % (year, month), 'published_at': published.isoformat(),
            'observed_at': now_iso(), 'values': values, 'scope': SPECS[kind]['scope']}


def parse_cpi(document, url, as_of):
    if urlparse(url).hostname != 'www.stats.gov.cn':
        raise ValueError('CPI 必须来自国家统计局')
    title, stamp = _meta(document, 'ArticleTitle'), _meta(document, 'PubDate')
    period = SPECS['cpi']['title'].fullmatch(title or '')
    if not period or not stamp:
        raise ValueError('CPI 公告身份缺失')
    published = datetime.strptime(stamp, '%Y/%m/%d %H:%M').replace(tzinfo=CHINA)
    year, month = map(int, period.groups())
    _check_dates(year, month, published, _now(as_of))
    match = re.search(r'%d年%d月份，全国居民消费价格同比' % (year, month) + SIGNED, _visible(document))
    if not match:
        raise ValueError('CPI 真实数值缺失')
    value = _signed(match[1], match[2])
    if not -30 <= value <= 30:
        raise ValueError('CPI 数值超出合理范围')
    return _result('cpi', url, title, published, year, month, {'cpi_yoy': value}, _now(as_of))


def parse_ppi(document, url, as_of):
    if urlparse(url).hostname != 'www.stats.gov.cn':
        raise ValueError('PPI 必须来自国家统计局')
    title, stamp = _meta(document, 'ArticleTitle'), _meta(document, 'PubDate')
    period = SPECS['ppi']['title'].fullmatch(title or '')
    if not period or not stamp:
        raise ValueError('PPI 公告身份缺失')
    published = datetime.strptime(stamp, '%Y/%m/%d %H:%M').replace(tzinfo=CHINA)
    year, month = map(int, period.groups())
    _check_dates(year, month, published, _now(as_of))
    visible = _visible(document)
    output = re.search(r'%d年%d月份，全国工业生产者出厂价格同比' % (year, month) + SIGNED, visible)
    purchase = re.search(r'工业生产者购进价格同比' + SIGNED, visible)
    if not output or not purchase:
        raise ValueError('PPI 真实数值缺失')
    values = {'ppi_yoy': _signed(output[1], output[2]), 'purchase_yoy': _signed(purchase[1], purchase[2])}
    if not all(-50 <= v <= 50 for v in values.values()):
        raise ValueError('PPI 数值超出合理范围')
    return _result('ppi', url, title, published, year, month, values, _now(as_of))


def parse_credit(document, url, as_of):
    if urlparse(url).hostname != 'www.pbc.gov.cn':
        raise ValueError('信用数据必须来自中国人民银行')
    title, stamp = _meta(document, 'ArticleTitle'), _meta(document, 'PubDate')
    if not SPECS['credit']['title'].fullmatch(title or '') or not stamp:
        raise ValueError('金融统计数据报告身份缺失')
    published = datetime.strptime(stamp, '%Y-%m-%d').replace(tzinfo=CHINA)
    visible = _visible(document)
    stock = re.search(r'(\d{4})年(\d{1,2})月末社会融资规模存量为([\d.]+)万亿元，同比' + SIGNED, visible)
    money = re.search(r'广义货币\(M2\)余额([\d.]+)万亿元，同比' + SIGNED, visible.replace('（', '(').replace('）', ')'))
    if not stock or not money:
        raise ValueError('社会融资规模或 M2 数值缺失')
    year, month = int(stock[1]), int(stock[2])
    # The statistical period in the body must agree with the report title.
    if not str(title).startswith('%d年' % year):
        raise ValueError('报告标题与统计期不一致')
    _check_dates(year, month, published, _now(as_of))
    values = {'social_financing_stock': float(stock[3]), 'social_financing_yoy': _signed(stock[4], stock[5]),
              'm2_balance': float(money[1]), 'm2_yoy': _signed(money[2], money[3])}
    if not (0 < values['social_financing_stock'] < 10000 and -50 <= values['social_financing_yoy'] <= 50
            and 0 < values['m2_balance'] < 10000 and -50 <= values['m2_yoy'] <= 50):
        raise ValueError('信用数值超出合理范围')
    return _result('credit', url, title, published, year, month, values, _now(as_of))


def _nbs_page(document, url, kind):
    if urlparse(url).hostname != 'www.stats.gov.cn':
        raise ValueError(SPECS[kind]['name'] + ' 必须来自国家统计局')
    title, stamp = _meta(document, 'ArticleTitle'), _meta(document, 'PubDate')
    period = SPECS[kind]['title'].fullmatch(title or '')
    if not period or not stamp:
        raise ValueError(SPECS[kind]['name'] + ' 公告身份缺失')
    return title, period, datetime.strptime(stamp, '%Y/%m/%d %H:%M').replace(tzinfo=CHINA), _visible(document)


def _rate(pattern, visible, required=True):
    match = re.search(pattern + SIGNED, visible)
    if not match:
        if required:
            raise ValueError('官方数值缺失')
        return None
    value = _signed(match[1], match[2])
    if not -100 <= value <= 100:
        raise ValueError('官方数值超出合理范围')
    return value


def parse_fai(document, url, as_of):
    title, period, published, visible = _nbs_page(document, url, 'fai')
    year, month = map(int, period.groups())
    _check_dates(year, month, published, _now(as_of))
    head = '1' + DASH + r'%d月份，全国固定资产投资（不含农户）[\d.]+亿元，同比' % month
    values = {'fai_yoy': _rate(head, visible), 'manufacturing_yoy': _rate('制造业投资', visible)}
    # High-tech investment is not in every release; it is shown only when published.
    for key, pattern in (('intellectual_property_yoy', '知识产权产品投资同比'), ('high_tech_yoy', '高技术产业投资(?:同比)?')):
        value = _rate(pattern, visible, required=False)
        if value is not None:
            values[key] = value
    return _result('fai', url, title, published, year, month, values, _now(as_of))


def parse_industry(document, url, as_of):
    title, period, published, visible = _nbs_page(document, url, 'industry')
    year, month = map(int, period.groups())
    _check_dates(year, month, published, _now(as_of))
    values = {'value_added_yoy': _rate('%d月份，规模以上工业增加值同比实际' % month, visible)}
    cumulative = _rate('1' + DASH + '%d月份，规模以上工业增加值同比' % month, visible, required=False)
    if cumulative is not None:
        values['value_added_ytd_yoy'] = cumulative
    return _result('industry', url, title, published, year, month, values, _now(as_of))


def parse_annual(document, url, as_of):
    title, period, published, visible = _nbs_page(document, url, 'annual')
    year, now = int(period[1]), _now(as_of)
    if published.year != year + 1:
        raise ValueError('年度公报统计年份与发布年份不符')
    if not 0 <= (now - published).total_seconds() <= ANNUAL_MAX_AGE_DAYS * 86400:
        raise ValueError('年度公报尚未发布或已过期')
    labour = re.search(r'全员劳动生产率(?:\[\d+\])?为([\d.]+)元/人，比上年' + SIGNED, visible)
    rd = re.search(r'研究与试验发展（R&D）经费支出([\d.]+)亿元，比上年' + SIGNED + r'，与国内生产总值之比为([\d.]+)%', visible)
    if not labour or not rd:
        raise ValueError('全员劳动生产率或 R&D 经费数值缺失')
    values = {'labour_productivity': float(labour[1]), 'labour_productivity_growth': _signed(labour[2], labour[3]),
              'rd_spending': float(rd[1]), 'rd_growth': _signed(rd[2], rd[3]), 'rd_intensity': float(rd[4])}
    if not (0 < values['labour_productivity'] < 10_000_000 and 0 < values['rd_spending'] < 10_000_000
            and 0 < values['rd_intensity'] < 20 and -50 <= values['labour_productivity_growth'] <= 50
            and -50 <= values['rd_growth'] <= 50):
        raise ValueError('年度数值超出合理范围')
    result = _result('annual', url, title, published, year, 12, values, now)
    result.update(period=str(year), frequency='annual')
    return result


PARSERS = {'cpi': parse_cpi, 'ppi': parse_ppi, 'credit': parse_credit,
           'fai': parse_fai, 'industry': parse_industry, 'annual': parse_annual}
SOURCE_IDS = {'cpi': 'macro:nbs_cpi', 'ppi': 'macro:nbs_ppi', 'credit': 'macro:pbc_credit',
              'fai': 'macro:nbs_fai', 'industry': 'macro:nbs_industry', 'annual': 'macro:nbs_annual'}


def candidates(kind, listing):
    spec, found = SPECS[kind], []
    for link, title in LINK.findall(listing):
        title = re.sub('<[^>]+>', '', title).strip()
        if spec.get('list_title', spec['title']).fullmatch(title):
            url = urljoin(spec['list'], link)
            if urlparse(url).hostname == spec['host']:
                found.append(url)
    # Both list pages put the newest release first; keep that order and try two.
    return list(dict.fromkeys(found))[:2]


def _source(kind):
    return {'id': SOURCE_IDS[kind], 'name': SPECS[kind]['name'],
            'url': SPECS[kind]['list'], 'status': 'error', 'count': 0, 'as_of': None,
            'fetched_at': now_iso(), 'scope': SPECS[kind]['scope']}


def _from_cache(kind, as_of):
    record = load_record(CACHE_PATH, kind)
    if not isinstance(record, dict):
        return None
    try:
        # Reparse the stored official page rather than trusting stored values.
        result = PARSERS[kind](record['document'], record['url'], as_of)
        fetched = _now(record['fetched_at'])
        if fetched > _now(as_of):
            return None
        result.update(observed_at=record['fetched_at'], cache_used=True)
        return result, record['fetched_at']
    except (KeyError, TypeError, ValueError):
        return None


def collect_one(kind, as_of, listings, *, use_cache=True):
    source = _source(kind)
    cached = _from_cache(kind, as_of) if use_cache else None
    if cached and 0 <= (_now(as_of) - _now(cached[1])).total_seconds() < CACHE_SECONDS:
        result, fetched = cached
        source.update(status='ok', url=result['url'], count=len(result['values']), as_of=result['published_at'],
                      fetched_at=fetched, cache_used=True, note='使用 6 小时内已核验的官方公告缓存；保留原发布时间。')
        return result, source
    try:
        listing = listings(SPECS[kind]['list'])
        urls = candidates(kind, listing)
        if not urls:
            raise ValueError('列表页未找到对应官方公告')
        result = None
        for url in urls:
            try:
                document = fetch_text(url)
                result = PARSERS[kind](document, url, as_of)
                break
            except ValueError:
                continue
        if result is None:
            raise ValueError('未取得截至报告时点有效的官方公告')
        source.update(status='ok', url=result['url'], count=len(result['values']), as_of=result['published_at'])
        if use_cache:
            save_record(CACHE_PATH, kind, {'document': document, 'url': result['url'], 'fetched_at': source['fetched_at']})
        return result, source
    except Exception as error:
        source['error'] = type(error).__name__ + '：' + str(error)[:180]
        if cached:
            result, fetched = cached
            source.update(status='partial', url=result['url'], count=len(result['values']), as_of=result['published_at'],
                          fetched_at=fetched, cache_used=True, note='最新请求失败，使用发布时间仍有效的已核验官方公告。')
            result['latest_request_error'] = source['error']
            return result, source
        return {'status': 'unavailable', 'kind': kind, 'error': source['error']}, source


def collect_long_wave_evidence(as_of, *, use_cache=True):
    """Returns ({cpi, ppi, credit, fai, industry, annual}, sources); each list page is fetched once."""
    pages = {}

    def listing(url):
        if url not in pages:
            pages[url] = fetch_text(url)
        return pages[url]

    evidence, sources = {}, []
    for kind in ('cpi', 'ppi', 'credit', 'fai', 'industry', 'annual'):
        evidence[kind], source = collect_one(kind, as_of, listing, use_cache=use_cache)
        sources.append(source)
    return evidence, sources


def collect_cached_long_wave_evidence(as_of):
    return collect_long_wave_evidence(as_of, use_cache=True)
