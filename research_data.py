"""Public market research collectors with explicit provenance and partial failure.

No credentials, HTML/JS execution, TLS bypass, or generated market observations.
Provider feeds are public site interfaces, not guaranteed SLA APIs.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import html
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from research_transport import fetch_bytes

CHINA = timezone(timedelta(hours=8))
DEFAULT_CODES = ['110020', '110026', '000216', '070009']
CACHE_TTL = 300
TIMEOUT = 8
MAX_BYTES = 4_000_000
MARKET_URL = 'https://qt.gtimg.cn/q=sh000001,sz399001,sh000300,sz399006'
NEWS_URL = 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=60&page=1'
POLICY_URL = 'https://www.csrc.gov.cn/csrc/c100028/common_list.shtml'
_cache = {}
_cache_lock = threading.Lock()


def now_iso():
    return datetime.now(CHINA).isoformat(timespec='seconds')


def clean_text(value, limit=3000):
    text = re.sub(r'<[^>]+>', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()[:limit]


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def fetch_text(url, encoding='utf-8-sig'):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 FundPilotLocalResearch/1.0',
        'Referer': 'https://fundf10.eastmoney.com/',
        'Accept': 'application/json,text/plain,text/html,*/*',
    })
    return fetch_bytes(request, timeout=TIMEOUT, max_bytes=MAX_BYTES).decode(encoding)


def assignment(text, name, required=True):
    """Decode only a JSON value following a JS variable assignment. Never eval."""
    match = re.search(r'\bvar\s+' + re.escape(name) + r'\s*=\s*', text)
    if not match:
        if required:
            raise ValueError(f'数据源缺少字段 {name}')
        return None
    try:
        return json.JSONDecoder().raw_decode(text[match.end():])[0]
    except (ValueError, TypeError) as error:
        raise ValueError(f'字段 {name} 格式已变化') from error


def parse_fund(text, code):
    name = assignment(text, 'fS_name')
    received_code = assignment(text, 'fS_code')
    if str(received_code) != code or not isinstance(name, str):
        raise ValueError('基金代码与响应不一致')
    values = assignment(text, 'Data_netWorthTrend')
    if not isinstance(values, list):
        raise ValueError('未提供单位净值历史；暂不支持该基金类型')
    history = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        nav, timestamp = number(entry.get('y')), number(entry.get('x'))
        if nav is None or nav <= 0 or timestamp is None:
            continue
        try:
            day = datetime.fromtimestamp(timestamp / 1000, CHINA).date().isoformat()
        except (OSError, ValueError, OverflowError):
            continue
        history[day] = {'date': day, 'nav': nav, 'return_pct': number(entry.get('equityReturn')),
                        'distribution_note': clean_text(entry.get('unitMoney'), 150)}
    history = [history[day] for day in sorted(history)][-320:]
    if not history:
        raise ValueError('没有有效净值记录')
    source = f'https://fund.eastmoney.com/{code}.html'
    rate = assignment(text, 'fund_Rate', required=False)
    holdings = assignment(text, 'stockCodesNew', required=False)
    return {'code': code, 'name': clean_text(name, 120), 'nav': history[-1]['nav'],
            'nav_date': history[-1]['date'], 'history': history, 'source_url': source,
            'source_id': f'nav:{code}', 'return_method': '每日收益率使用来源 equityReturn（百分比）；缺失时不以单位净值变化替代分红调整收益。',
            'expense_note': f'平台显示申购费率 {rate}%；实际费率、赎回费及持有期以交易平台和基金公告为准。' if number(rate) is not None else '费率未取得，请核对基金公告。',
            'holdings_codes': holdings[:20] if isinstance(holdings, list) else [],
            'holdings_note': '来源披露持仓代码，仅作行业核验线索，未获得对应报告期，不视为实时持仓。'}


def parse_market(text):
    records = []
    for match in re.finditer(r'v_([a-z]{2}\d{6})="([^"]+)"', text):
        fields = match.group(2).split('~')
        if len(fields) < 33:
            continue
        price, change = number(fields[3]), number(fields[32])
        if price is None or change is None:
            continue
        try:
            as_of = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=CHINA).isoformat()
        except ValueError:
            as_of = None
        records.append({'code': match.group(1), 'name': fields[1], 'last': price,
                        'change_pct': change, 'as_of': as_of,
                        'source_url': f'https://gu.qq.com/{match.group(1)}/zs',
                        'source_id': 'market_tencent'})
    if not records:
        raise ValueError('行情源未返回有效指数记录')
    return records


def timestamp_iso(value):
    try:
        return datetime.fromtimestamp(float(value), CHINA).isoformat(timespec='seconds')
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def safe_url(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(value)
    parsed = urllib.parse.urlparse(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else ''


def parse_news(data):
    items = data.get('result', {}).get('data', [])
    if not isinstance(items, list):
        raise ValueError('财经新闻源结构变化')
    result, seen = [], set()
    terms = re.compile(r'股|基金|指数|债|央行|利率|通胀|通缩|黄金|原油|期货|证券|市场|货币|金融|贸易|经济|投资|科技|半导体|新能源|出口|进口|银行|财政|政策|能源|关税|机器人|医药|消费')
    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get('title'), 200)
        url = safe_url(item.get('url'))
        if not title or not url or url in seen or not terms.search(title):
            continue
        if re.search(r'索赔|律师|股民维权|登记赔偿|股民.*起诉|投资者.*起诉', title):
            continue
        seen.add(url)
        result.append({'title': title, 'url': url, 'published_at': timestamp_iso(item.get('ctime')),
                       'source': clean_text(item.get('media_name') or '新浪财经', 100),
                       'publisher': '新浪财经', 'source_id': 'news_sina', 'category': '财经新闻',
                       'summary': clean_text(item.get('intro'), 700), 'content_scope': '新闻源摘要，未读取全文'})
    return result[:24]


def parse_announcements(data, code):
    if data.get('ErrCode') != 0 or not isinstance(data.get('Data'), list):
        raise ValueError('基金公告接口未返回有效列表')
    categories = {'1': '发行运作', '2': '分红送配', '3': '定期报告', '4': '人事调整', '5': '基金销售', '6': '其他公告'}
    result = []
    for item in data['Data'][:4]:
        article_id = str(item.get('ID', ''))
        if not re.fullmatch(r'AN\d+', article_id):
            continue
        date = str(item.get('PUBLISHDATEDesc') or '')[:10]
        result.append({'title': clean_text(item.get('TITLE'), 250),
                       'url': f'https://fund.eastmoney.com/gonggao/{code},{article_id}.html',
                       'published_at': date if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else None,
                       'source': '基金公告（天天基金转载）', 'source_id': f'announcements_{code}',
                       'category': '基金公告', 'fund_code': code, 'article_id': article_id,
                       'summary': f"公告分类：{categories.get(str(item.get('NEWCATEGORY')), '其他')}。",
                       'content_scope': '标题与发布日期，正文未读取'})
    return result


def announcement_excerpt(content):
    """Include the opening and named risk/operation sections; expose excerpt scope."""
    text = clean_text(content, 100000)
    if not text:
        return ''
    excerpts = [text[:450]]
    for keyword in ('投资策略和运作分析', '报告期内基金的投资策略', '风险收益特征', '重大事项', '暂停申购', '限额'):
        start = text.find(keyword, 450)
        if start >= 0:
            fragment = text[max(0, start - 20):start + 650]
            if all(fragment not in prior for prior in excerpts):
                excerpts.append(fragment)
        if len(excerpts) >= 4:
            break
    return ' […] '.join(excerpts)[:2500]


def fetch_announcements(code):
    url = f'https://api.fund.eastmoney.com/f10/JJGG?fundcode={code}&pageIndex=1&pageSize=4&type=0'
    items = parse_announcements(json.loads(fetch_text(url)), code)
    if items:
        first = items[0]
        detail_url = f'https://np-cnotice-fund.eastmoney.com/api/content/ann?client_source=web_fund&show_all=1&art_code={first["article_id"]}'
        try:
            detail = json.loads(fetch_text(detail_url))
            excerpt = announcement_excerpt(detail.get('data', {}).get('notice_content'))
            if excerpt:
                first['summary'] = excerpt
                first['content_scope'] = '公告正文节选：开头及风险/投资运作等相关段落；非完整报告'
        except Exception:
            # List remains valid, but do not pretend to have read the document.
            first['content_scope'] = '标题与发布日期，公告正文暂未取得'
    return items


def fetch_policy():
    text = fetch_text(POLICY_URL)
    records = []
    # CSRC rendered list items include link and date; unknown dates remain unknown.
    for row in re.findall(r'<li\b[^>]*>(.*?)</li>', text, re.S | re.I):
        link = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', row, re.S | re.I)
        date = re.search(r'\b20\d{2}-\d{2}-\d{2}\b', row)
        if not link or not date:
            continue
        title = clean_text(link.group(2), 250)
        url = urllib.parse.urljoin(POLICY_URL, link.group(1))
        if title and urllib.parse.urlparse(url).hostname == 'www.csrc.gov.cn':
            records.append({'title': title, 'url': url, 'published_at': date.group(0), 'source': '中国证监会',
                            'source_id': 'policy_csrc', 'category': '监管发布', 'summary': '', 'content_scope': '官方列表标题，正文未读取'})
    if not records:
        raise ValueError('监管发布页未解析到有日期的新闻记录')
    return records[:6]


def explain_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return f'数据提供方返回 HTTP {error.code}'
    message = str(error)
    if 'CERTIFICATE_VERIFY_FAILED' in message:
        return 'HTTPS 证书验证失败；未绕过证书验证'
    if isinstance(error, TimeoutError) or 'timed out' in message:
        return '数据源请求超时'
    if isinstance(error, urllib.error.URLError):
        return '暂时无法连接数据源'
    return clean_text(message, 180) or '数据源暂不可用'


def collect_research(codes=None, refresh=False, market_only=False, include_common=True):
    selected = [] if market_only else list(dict.fromkeys(codes or DEFAULT_CODES))
    if (not market_only and not 1 <= len(selected) <= 8) or any(not isinstance(code, str) or not re.fullmatch(r'\d{6}', code) for code in selected):
        raise ValueError('请提供 1–8 个六位基金代码')
    cache_key = (tuple(selected), bool(include_common))
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and not refresh and time.monotonic() - cached[0] < CACHE_TTL:
            result = deepcopy(cached[1])
            result['cache_hit'] = True
            return result
    collected_at = now_iso()
    result = {'as_of': collected_at, 'funds': [], 'market': [], 'news': [], 'sources': [], 'warnings': [], 'cache_hit': False,
              'scope': '公开数据源自动采集；基金净值通常在收盘后更新，新闻/公告范围不代表全市场完整覆盖。'}
    jobs = []
    for code in selected:
        nav_url = f'https://fund.eastmoney.com/pingzhongdata/{code}.js'
        jobs.append((f'nav:{code}', f'基金 {code} 净值', nav_url, 'funds', lambda code=code, url=nav_url: parse_fund(fetch_text(url), code)))
        ann_url = f'https://fundf10.eastmoney.com/jjgg_{code}.html'
        jobs.append((f'announcements_{code}', f'基金 {code} 公告', ann_url, 'news', lambda code=code: fetch_announcements(code)))
    if include_common:
        jobs += [
        ('market_tencent', '腾讯财经 · 四大指数行情', MARKET_URL, 'market', lambda: parse_market(fetch_text(MARKET_URL, 'gbk'))),
        ('news_sina', '新浪财经 · 市场新闻', NEWS_URL, 'news', lambda: parse_news(json.loads(fetch_text(NEWS_URL)))),
        ('policy_csrc', '中国证监会 · 监管发布', POLICY_URL, 'news', fetch_policy),
        ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(job[4]): job for job in jobs}
        for future in as_completed(futures):
            source_id, name, url, target, _ = futures[future]
            source = {'id': source_id, 'name': name, 'status': 'ok', 'url': url, 'as_of': None, 'fetched_at': now_iso()}
            try:
                value = future.result()
                if target == 'funds':
                    result[target].append(value)
                    source['as_of'] = value['nav_date']
                    source['count'] = len(value['history'])
                    missing = sum(row['return_pct'] is None for row in value['history'])
                    if missing:
                        source['status'] = 'partial'
                        source['error'] = f'{missing} 条净值缺少来源日收益率，不推算分红调整收益'
                else:
                    result[target].extend(value)
                    source['count'] = len(value)
                    dates = [row.get('as_of') or row.get('published_at') for row in value if row.get('as_of') or row.get('published_at')]
                    source['as_of'] = max(dates) if dates else None
                    if not value:
                        source['status'] = 'partial'
                        source['error'] = '本次返回空列表；不能据此断定没有相关新闻/公告'
            except Exception as error:
                source.update(status='error', error=explain_error(error), count=0)
                result['warnings'].append(f'{name}：{source["error"]}')
            result['sources'].append(source)
    rank = {code: i for i, code in enumerate(selected)}
    result['funds'].sort(key=lambda row: rank[row['code']])
    result['market'].sort(key=lambda row: row['code'])
    result['sources'].sort(key=lambda row: row['id'])
    seen = set()
    news = []
    for row in sorted(result['news'], key=lambda row: row.get('published_at') or '', reverse=True):
        if row['url'] not in seen:
            seen.add(row['url'])
            news.append(row)
    result['news'] = news
    today = datetime.now(CHINA).date()
    for fund in result['funds']:
        age = (today - datetime.strptime(fund['nav_date'], '%Y-%m-%d').date()).days
        if age > 7:
            result['warnings'].append(f'{fund["name"]} 最新净值距今 {age} 个自然日；暂停基金级行动建议直至更新。')
        if age < 0:
            result['warnings'].append(f'{fund["name"]} 净值日期晚于当前日期，数据时间需核验。')
            source = next((item for item in result['sources'] if item['id'] == fund['source_id']), None)
            if source:
                source.update(status='partial', error='净值日期晚于当前日期，数据时间需核验')
    result['warnings'].append('新闻使用财经源摘要，基金公告仅最新一条读取正文节选；未读取全文的记录已单独标注，不能视为完成全面尽调。')
    result['warnings'].append('交易情绪只能由指数涨跌与新闻文本等公开代理指标估计，不等同于真实资金流或投资者全体情绪。')
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), deepcopy(result))
        if len(_cache) > 20:
            oldest = min(_cache, key=lambda key: _cache[key][0])
            del _cache[oldest]
    return result
