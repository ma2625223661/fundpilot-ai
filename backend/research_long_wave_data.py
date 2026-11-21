"""Date-checked official price and credit releases for the long-wave workspace.

Issue #7: CPI and PPI come from the National Bureau of Statistics release list,
social financing stock growth and M2 from the PBOC financial statistics report.
Each value keeps its statistical period, publication date, source URL and scope.
Nothing is estimated: a release that cannot be verified is reported as missing.
Productivity and capital expenditure have no official monthly series here and
stay unconnected.
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
CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'macro-long-wave-cache.json'
MAX_AGE_DAYS = 62
CACHE_SECONDS = 6 * 3600

LINK = re.compile(r'<a\b[^>]*href=["\x27]([^"\x27]+)["\x27][^>]*>(.*?)</a>', re.S | re.I)
SIGNED = r'(上涨|下降|增长|持平)([\d.]+)?%?'

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
    return -value if verb == '下降' else value


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


PARSERS = {'cpi': parse_cpi, 'ppi': parse_ppi, 'credit': parse_credit}


def candidates(kind, listing):
    spec, found = SPECS[kind], []
    for link, title in LINK.findall(listing):
        title = re.sub('<[^>]+>', '', title).strip()
        if spec['title'].fullmatch(title):
            url = urljoin(spec['list'], link)
            if urlparse(url).hostname == spec['host']:
                found.append(url)
    # Both list pages put the newest release first; keep that order and try two.
    return list(dict.fromkeys(found))[:2]


def _source(kind):
    return {'id': 'macro:' + ('pbc_credit' if kind == 'credit' else 'nbs_' + kind), 'name': SPECS[kind]['name'],
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
    """Returns ({cpi, ppi, credit}, sources); one list page is fetched once."""
    pages = {}

    def listing(url):
        if url not in pages:
            pages[url] = fetch_text(url)
        return pages[url]

    evidence, sources = {}, []
    for kind in ('cpi', 'ppi', 'credit'):
        evidence[kind], source = collect_one(kind, as_of, listing, use_cache=use_cache)
        sources.append(source)
    return evidence, sources


def collect_cached_long_wave_evidence(as_of):
    return collect_long_wave_evidence(as_of, use_cache=True)
