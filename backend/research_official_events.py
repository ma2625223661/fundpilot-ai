"""Bounded public company-announcement and official-policy evidence collection.

No model calls, paid data calls, fund collection or TLS verification bypass.
Only an actually extracted document body is marked complete enough to assess.
"""
import copy
import hashlib
import html
import io
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from research_data import CHINA, now_iso
from research_transport import fetch_response

CNINFO_URL = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
CNINFO_REFERER = 'https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search'
POLICY_SOURCES = (
    ('policy_ndrc_notice', '国家发展改革委 · 通知', 'https://www.ndrc.gov.cn/xxgk/zcfb/tz/'),
    ('policy_ndrc_rules', '国家发展改革委 · 规范性文件', 'https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/'),
)
CACHE_SECONDS = 900
MAX_BYTES = 4_000_000
MAX_DOCUMENTS = 12
MAX_TEXT = 30_000
MAX_PAGES = 8
TOTAL_BUDGET = 60
HTTP_TIMEOUT = 8
_cache = {}
_cache_lock = threading.Lock()

IMPORTANT = re.compile('业绩|季度报告|年度报告|半年度报告|中标|重大合同|订单|减持|增持|回购|违约|处罚|立案|审批|获批|注册证|诉讼|停产|复产|重整|债务|收购|重组|关联交易|风险提示|盈利预测|预亏|亏损|利润|营收')
ROUTINE = re.compile('股东会|股东大会|监事会|董事会决议|法律意见|会议资料|会议通知|业绩说明会|国债逆回购|债券逆回购|制度|议事规则|核查意见|工作细则|章程|独立董事|募集资金存放|投资者关系活动|内控评价')
PRODUCT = re.compile('ETF|LOF|公募REIT|基金份额|基金净值|基金合同|基金招募|基金收益|基金管理人', re.I)
STOCK = re.compile(r'(?:000|001|002|003|300|301|600|601|603|605|688|689|430|83\d|87\d|88\d|92\d)\d{3}\Z')


def _stamp(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=CHINA) if value.tzinfo is None else value.astimezone(CHINA)
    text = str(value or '').strip().replace('Z', '+00:00').replace('/', '-')
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed.astimezone(CHINA)
    except ValueError:
        return None


def _clean(value, limit=MAX_TEXT):
    text = re.sub(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>', ' ', str(value or ''), flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text))).strip()[:limit]


def _eligible_time(value, reference):
    stamp = _stamp(value)
    return stamp is not None and reference - timedelta(days=7) <= stamp <= reference


def _safe_error(error):
    if isinstance(error, urllib.error.HTTPError):
        return f'公开来源返回 HTTP {error.code}'
    if 'CERTIFICATE_VERIFY_FAILED' in str(error):
        return 'HTTPS 证书验证失败，未绕过验证'
    if isinstance(error, TimeoutError) or 'timed out' in str(error):
        return '公开来源连接或采集预算超时'
    return '公开来源连接失败或响应格式发生变化'


def _read(url, *, data=None, deadline=None):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.cninfo.com.cn', 'static.cninfo.com.cn', 'www.ndrc.gov.cn'):
        raise ValueError('未认可的公开来源')
    timeout = HTTP_TIMEOUT if deadline is None else min(HTTP_TIMEOUT, deadline - time.monotonic())
    if timeout <= 0:
        raise TimeoutError('event collection deadline')
    headers = {'User-Agent': 'Mozilla/5.0 FundPilotSectorResearch/1.0',
               'Accept': 'application/json,text/html,application/pdf,*/*'}
    if data is not None:
        headers.update({'Referer': CNINFO_REFERER, 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'})
    request = urllib.request.Request(url, data=data, headers=headers)
    content, final_url = fetch_response(request, timeout=timeout, max_bytes=MAX_BYTES)
    if urllib.parse.urlparse(final_url).hostname != parsed.hostname:
        raise ValueError('公开来源发生跨域跳转')
    return content


def _leader_codes(leaders):
    result = set()
    def visit(value):
        if len(result) >= 300:
            return
        if isinstance(value, dict):
            for key in ('ts_code', 'code', 'stock_code'):
                code = str(value.get(key) or '').split('.')[0]
                if STOCK.fullmatch(code):
                    result.add(code)
            for key, child in value.items():
                if key not in ('ts_code', 'code', 'stock_code', 'name', 'title', 'summary') and isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value[:500]:
                visit(child)
        elif isinstance(value, str):
            code = value.split('.')[0]
            if STOCK.fullmatch(code):
                result.add(code)
    visit(leaders)
    return result


def _pdf_excerpt(content):
    if not content.startswith(b'%PDF'):
        raise ValueError('公告未返回PDF正文')
    try:
        from pypdf import PdfReader
    except ImportError:
        vendor = Path(__file__).resolve().parent.parent / '.vendor'
        if not (vendor / 'pypdf').is_dir():
            raise RuntimeError('PDF正文解析组件尚未安装') from None
        if str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
        from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted:
        raise ValueError('公告PDF加密，无法提取正文')
    parts, count = [], 0
    for page in reader.pages[:MAX_PAGES]:
        text = _clean(page.extract_text() or '', MAX_TEXT - count)
        parts.append(text)
        count += len(text)
        if count >= MAX_TEXT:
            break
    excerpt = ' '.join(parts).strip()[:MAX_TEXT]
    if len(excerpt) < 80:
        raise ValueError('公告正文不可提取或仅含图片')
    return excerpt


def _document_evidence(event, deadline):
    result = dict(event)
    try:
        excerpt = _pdf_excerpt(_read(event['url'], deadline=deadline))
        result.update(summary=excerpt[:6000], body_excerpt=excerpt,
                      evidence_complete=True, content_scope='已读取PDF前8页、最多30000字符的正文节选；非全文',
                      body_status='extracted')
    except Exception as error:
        result.update(evidence_complete=False, body_status='unavailable',
                      content_scope='仅公告标题与披露日期；PDF正文未取得，不作影响评分',
                      evidence_error='公告正文未取得：' + _safe_error(error))
    return result


def _cninfo_rows(data, reference, leaders):
    raw = data.get('announcements') if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise ValueError('公告列表结构无效')
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code, title = str(item.get('secCode') or ''), _clean(item.get('announcementTitle'), 500)
        if not STOCK.fullmatch(code) or not title or PRODUCT.search(title):
            continue
        if not IMPORTANT.search(title) or (ROUTINE.search(title) and not re.search('重大合同|中标|违约|立案|处罚|风险提示', title)):
            continue
        try:
            published = datetime.fromtimestamp(float(item['announcementTime']) / 1000, CHINA).isoformat()
        except (KeyError, ValueError, OverflowError, TypeError):
            continue
        if not _eligible_time(published, reference):
            continue
        path = str(item.get('adjunctUrl') or '')
        if not re.fullmatch(r'finalpage/\d{4}-\d{2}-\d{2}/[A-Za-z0-9_.-]+\.PDF', path, re.I):
            continue
        url = 'https://static.cninfo.com.cn/' + path
        identity = str(item.get('announcementId') or hashlib.sha256(url.encode()).hexdigest()[:20])
        result.append({'id': 'cninfo:' + identity, 'title': title,
                       'company_name': _clean(item.get('secName'), 100), 'summary': '', 'body_excerpt': '',
                       'published_at': published, 'published_precision': 'disclosure_date',
                       'url': url, 'source_id': 'official_cninfo', 'source_name': '巨潮资讯 · 上市公司公开公告',
                       'stock_codes': [code], 'sector_ids': [], 'event_type': 'company_announcement',
                       'evidence_complete': False, 'leader_related': code in leaders,
                       'content_scope': '公告列表标题，正文尚未读取'})
    return result


def _collect_announcements(reference, leaders, deadline):
    source = {'id': 'official_cninfo', 'name': '巨潮资讯 · 上市公司公开公告', 'url': CNINFO_URL,
              'status': 'ok', 'fetched_at': now_iso(), 'as_of': None, 'count': 0,
              'scope': '沪深公开公告分页样本；优先龙头相关重大公告，最多12份正文节选，非全市场完整覆盖'}
    rows, errors, successful_lists = [], [], 0
    for column in ('szse', 'sse'):
        params = {'pageNum': 1, 'pageSize': 30, 'column': column, 'tabName': 'fulltext', 'plate': '',
                  'stock': '', 'searchkey': '', 'secid': '', 'category': '', 'trade': '',
                  'seDate': (reference - timedelta(days=7)).strftime('%Y-%m-%d') + '~' + reference.strftime('%Y-%m-%d'),
                  'sortName': 'time', 'sortType': 'desc', 'isHLtitle': 'true'}
        try:
            response = json.loads(_read(CNINFO_URL, data=urllib.parse.urlencode(params).encode(), deadline=deadline))
            rows.extend(_cninfo_rows(response, reference, leaders))
            successful_lists += 1
        except Exception as error:
            errors.append(_safe_error(error))
    unique = {row['id']: row for row in rows}
    rows = sorted(unique.values(), key=lambda row: (not row['leader_related'], -_stamp(row['published_at']).timestamp()))[:MAX_DOCUMENTS]
    source['listing_count'] = len(unique)
    events = []
    pool = ThreadPoolExecutor(max_workers=4)
    futures = {pool.submit(_document_evidence, row, deadline): row for row in rows}
    try:
        for future in as_completed(futures, timeout=max(0.1, deadline - time.monotonic())):
            events.append(future.result())
    except TimeoutError:
        errors.append('公开文档正文采集达到60秒总预算')
    finally:
        for future, row in futures.items():
            if not future.done():
                future.cancel()
                events.append(dict(row, body_status='unavailable', evidence_complete=False,
                                   content_scope='仅公告标题；正文采集预算不足，不作影响评分'))
        pool.shutdown(wait=False, cancel_futures=True)
    source.update(count=len(events), content_count=sum(row['evidence_complete'] for row in events),
                  as_of=max((row['published_at'] for row in events), default=None),
                  listing_requests_ok=successful_lists, empty_window=not events and not errors)
    missing_body = any(not row['evidence_complete'] for row in events)
    if errors or missing_body:
        source.update(status='partial' if events or successful_lists else 'error',
                      error='；'.join(dict.fromkeys(errors)) if errors else '部分公告PDF正文未取得，不参与影响评分')
    return {'events': events, 'sources': [source], 'warnings': ([source['error']] if source.get('error') else [])}


class _ArticleBody(HTMLParser):
    def __init__(self):
        super().__init__()
        self.level = 0
        self.active = False
        self.ignore = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div' and not self.active and 'article_con' in attrs.get('class', '').split():
            self.active, self.level = True, 1
        elif self.active and tag == 'div':
            self.level += 1
        if self.active and tag in ('script', 'style'):
            self.ignore += 1

    def handle_endtag(self, tag):
        if self.active and tag in ('script', 'style') and self.ignore:
            self.ignore -= 1
        if self.active and tag == 'div':
            self.level -= 1
            if not self.level:
                self.active = False

    def handle_data(self, text):
        if self.active and not self.ignore:
            self.parts.append(text)


def _policy_rows(document, source_id, source_name, base_url, reference):
    if 'u-list' not in document:
        raise ValueError('政策栏目列表结构无效')
    events = []
    for item in re.findall(r'<li\b[^>]*>.*?</li>', document, re.S | re.I):
        link = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', item, re.S | re.I)
        if not link:
            continue
        url = urllib.parse.urljoin(base_url, html.unescape(link.group(1)))
        stamp = re.search(r'/t(20\d{6})_\d+\.html', url)
        if not stamp or urllib.parse.urlparse(url).hostname != 'www.ndrc.gov.cn':
            continue
        published = datetime.strptime(stamp.group(1), '%Y%m%d').replace(tzinfo=CHINA).isoformat()
        if not _eligible_time(published, reference):
            continue
        title = _clean(link.group(2), 500)
        if not title or PRODUCT.search(title):
            continue
        events.append({'id': source_id + ':' + hashlib.sha256(url.encode()).hexdigest()[:20],
                       'title': title, 'summary': '', 'body_excerpt': '', 'published_at': published,
                       'url': url, 'source_id': source_id, 'source_name': source_name,
                       'stock_codes': [], 'sector_ids': [], 'event_type': 'official_policy',
                       'evidence_complete': False, 'content_scope': '官方栏目标题，正文尚未读取'})
    return events[:6]


def _collect_policy(source_id, name, url, reference, deadline):
    source = {'id': source_id, 'name': name, 'url': url, 'status': 'ok', 'fetched_at': now_iso(),
              'as_of': None, 'count': 0, 'scope': '官方政策栏目近7天公开文件；读取正文节选'}
    events, errors = [], []
    try:
        listing = _read(url, deadline=deadline).decode('utf-8-sig')
        rows = _policy_rows(listing, source_id, name, url, reference)
        for event in rows:
            try:
                document = _read(event['url'], deadline=deadline).decode('utf-8-sig')
                meta = re.search(r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)', document, re.I)
                if meta:
                    stamp = _stamp(meta.group(1))
                    if not stamp or not _eligible_time(stamp, reference):
                        continue
                    event['published_at'] = stamp.isoformat()
                body = _ArticleBody()
                body.feed(document)
                excerpt = _clean(' '.join(body.parts))
                if len(excerpt) < 80:
                    raise ValueError('政策正文未提取')
                event.update(summary=excerpt[:6000], body_excerpt=excerpt,
                             evidence_complete=True, body_status='extracted',
                             content_scope='已读取官方网页正文、最多30000字符的节选；附件未读取')
            except Exception as error:
                errors.append(_safe_error(error))
                event.update(body_status='unavailable', evidence_complete=False,
                             content_scope='仅官方政策标题；正文未取得，不作影响评分')
            events.append(event)
        source.update(count=len(events), content_count=sum(event['evidence_complete'] for event in events),
                      as_of=max((event['published_at'] for event in events), default=None), empty_window=not events)
        if errors:
            source.update(status='partial', error='部分官方政策正文未取得')
    except Exception as error:
        source.update(status='error', error=_safe_error(error), empty_window=False)
    return {'events': events, 'sources': [source], 'warnings': [source['error']] if source.get('error') else []}


def collect_official_events(catalog, leaders=None, as_of=None):
    """Collect official evidence only; leave unknown sector mappings empty."""
    reference = _stamp(as_of or now_iso())
    if reference is None:
        raise ValueError('公开事件研究时间无效')
    leaders = _leader_codes(leaders)
    key = (reference.strftime('%Y-%m-%d'), tuple(sorted(leaders)))
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            result = copy.deepcopy(cached[1])
            result['events'] = [event for event in result['events'] if _eligible_time(event['published_at'], reference)]
            result['cache_hit'] = True
            return result
    deadline = time.monotonic() + TOTAL_BUDGET
    result = {'events': [], 'sources': [], 'warnings': [], 'cache_hit': False}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(_collect_announcements, reference, leaders, deadline)]
        jobs.extend(pool.submit(_collect_policy, source_id, name, url, reference, deadline)
                    for source_id, name, url in POLICY_SOURCES)
        for future in as_completed(jobs):
            try:
                collected = future.result()
                for field in ('events', 'sources', 'warnings'):
                    result[field].extend(collected[field])
            except Exception as error:
                result['warnings'].append('公开事件采集未完成：' + _safe_error(error))
    result['events'] = sorted({row['id']: row for row in result['events']}.values(),
                              key=lambda row: row['published_at'], reverse=True)
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    with _cache_lock:
        _cache.clear()
        _cache[key] = (time.monotonic(), copy.deepcopy(result))
    return result
