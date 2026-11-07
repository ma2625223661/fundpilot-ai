"""Credential-free second connection: publisher members + Tencent + EM finance.

No scraping challenges, account access or TLS bypass. Lists are publisher
snapshots, not historical reconstructions. Only validated dated A-share members
are used; membership and business leadership are distinct claims.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from research_data import CHINA, fetch_text, now_iso
from research_transport import fetch_bytes
from research_sector_references import VERIFIED_REFERENCES

PROVIDER = 'public_multisource'
MEMBER_BASE = 'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/'
FINANCE_BASE = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'public-company-cache.json'
MEMBER_CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'csi-members-last-good.json'
FIXED_SAMPLE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'csi-fixed-samples.json'
MAX_CACHE_BYTES = 64_000_000
_lock = threading.RLock()
_cache = {}
_capabilities = {}
_member_last_good = {}
_member_fetch_status = {}
_fixed_samples = {}
try:
    # Public overseas responses can exceed 15 MB together. Rejecting the whole
    # file at that former limit silently discarded every CSI membership too.
    _doc = json.loads(CACHE_PATH.read_text(encoding='utf-8')) if CACHE_PATH.stat().st_size < MAX_CACHE_BYTES else {}
    _cache.update({k: v for k, v in _doc.get('datasets', {}).items()
                   if isinstance(v, dict) and isinstance(v.get('expires'), (int, float))
                   and isinstance(v.get('fetched_at'), str) and 'data' in v})
except (OSError, ValueError, TypeError, AttributeError):
    pass
try:
    _fixed_doc = json.loads(FIXED_SAMPLE_PATH.read_text(encoding='utf-8')) if FIXED_SAMPLE_PATH.stat().st_size < 1_000_000 else {}
    if _fixed_doc.get('schema') == 'csi_fixed_samples_not_complete_v1' and isinstance(_fixed_doc.get('boards'), dict):
        _fixed_samples.update(_fixed_doc['boards'])
except (OSError, ValueError, TypeError, AttributeError):
    pass
try:
    _member_doc = json.loads(MEMBER_CACHE_PATH.read_text(encoding='utf-8')) if MEMBER_CACHE_PATH.stat().st_size < 12_000_000 else {}
    if _member_doc.get('version') == 1 and isinstance(_member_doc.get('snapshots'), dict):
        _member_last_good.update(_member_doc['snapshots'])
except (OSError, ValueError, TypeError, AttributeError):
    pass


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)


def _remember(key, data, ttl):
    with _lock:
        _cache[key] = {'data': copy.deepcopy(data), 'expires': time.time() + ttl, 'fetched_at': now_iso()}
    return data


def _get(key):
    with _lock:
        row = _cache.get(key)
        return copy.deepcopy(row['data']) if isinstance(row, dict) and row.get('expires', 0) > time.time() else None


def _fetched_at(key):
    with _lock:
        return (_cache.get(key) or {}).get('fetched_at') or now_iso()


def _save():
    with _lock:
        live = {k: v for k, v in _cache.items() if v.get('expires', 0) > time.time()}
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = CACHE_PATH.with_suffix('.tmp')
            encoded = json.dumps({'datasets': live}, ensure_ascii=False)
            if len(encoded.encode('utf-8')) >= MAX_CACHE_BYTES:
                # Preserve the previous readable file; independent CSI last-good
                # snapshots remain safe even if other raw responses grow large.
                return
            temp.write_text(encoded, encoding='utf-8')
            os.replace(temp, CACHE_PATH)
        except OSError:
            pass


def _source(identity, name, url, status='ok', count=0, as_of=None, error=''):
    return {'id': 'public:' + identity, 'name': name, 'url': url, 'status': status,
            'count': count, 'as_of': as_of, 'fetched_at': now_iso(), 'error': error}


def reference_memberships(catalog):
    # Direct references are already explicitly declared by the sector engine.
    from research_sectors import DIRECT_INDICES
    result = {}
    for board in catalog:
        identity = board['id']
        ref = VERIFIED_REFERENCES.get(identity)
        if ref and ref['provider'] == 'csindex' and ref['asset_type'] == 'equity':
            result[identity] = {'code': ref['code'], 'aliases': list(ref['aliases']), 'title': ref['title']}
        elif identity in DIRECT_INDICES:
            symbol, title, _ = DIRECT_INDICES[identity]
            if symbol.startswith(('sh', 'sz')) and re.fullmatch(r'\d{6}', symbol[2:]):
                result[identity] = {'code': symbol[2:], 'aliases': [title], 'title': title}
    # Publisher's current official short names differ from Tencent legacy names.
    for identity, alias in (('sector_consumer', '800消费'), ('sector_healthcare', '800医卫'),
                             ('sector_financial_real_estate', '800金地')):
        if identity in result:
            result[identity]['aliases'].append(alias)
    # Shenzhen publishes this index; do not request an unrelated CSI file.
    result.pop('index_chinext', None)
    # Membership-only identity checked against CSI basic-info, 2026-10-31.
    # The website's custom indicator uses the companies, not this index price.
    if any(row['id'] == 'sector_semiconductor_equipment' for row in catalog):
        result['sector_semiconductor_equipment'] = {
            'code': '931743', 'title': '中证半导体材料设备主题指数',
            'aliases': ['中证半导体材料设备主题指数', '半导体材料设备']}
    # Membership-only mappings: the publisher basic-info and dated cons.xls
    # were checked together on 2026-10-31. No adjacent broad sector substitutes.
    member_only = {
        'sector_energy_storage': ('931747', '中证储能主题指数', '中证储能'),
        'sector_power': ('H30199', '中证全指电力公用事业指数', '电力指数'),
        'sector_grid_equipment': ('931994', '中证电网设备主题指数', '电网设备主题'),
        'sector_real_estate': ('931775', '中证全指房地产指数', '房地产'),
        'sector_construction_machinery': ('931752', '中证工程机械主题指数', '工程机械主题'),
        'sector_cxo': ('931750', '中证医药研发服务主题指数', 'CXO'),
        'sector_medical': ('399989', '中证医疗指数', '中证医疗'),
        'sector_consumer_electronics': ('931494', '中证消费电子主题指数', '消费电子'),
        'index_dual50': ('931643', '中证科创创业50指数', '科创创业50'),
    }
    for board in catalog:
        if board['id'] in member_only:
            code, title, short_name = member_only[board['id']]
            result[board['id']] = {'code': code, 'title': title, 'aliases': [title, short_name]}
    from research_theme_memberships import membership_references
    result.update(membership_references(catalog))
    return result


def parse_members(content, reference, as_of):
    import xlrd
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    if sheet.ncols < 9 or 'Constituent Code' not in str(sheet.cell_value(0, 4)):
        raise ValueError('官方成分文件表头变化')
    now = _stamp(as_of).date()
    result = {}
    for i in range(1, sheet.nrows):
        row = sheet.row_values(i)
        day = datetime.strptime(str(row[0]).split('.')[0], '%Y%m%d').date()
        if day > now or (now - day).days > 45:
            continue
        code = str(row[1]).split('.')[0].zfill(6)
        if code != reference['code'] or str(row[2]).strip() not in reference['aliases']:
            raise ValueError('官方成分指数身份与板块映射不一致')
        exchange = {'上海证券交易所': 'SH', '深圳证券交易所': 'SZ', '北京证券交易所': 'BJ'}.get(str(row[7]))
        stock = str(row[4]).split('.')[0].zfill(6)
        if not exchange or not re.fullmatch(r'\d{6}', stock):
            continue
        ts_code = stock + '.' + exchange
        result[ts_code] = {'ts_code': ts_code, 'name': str(row[5]), 'member_date': day.isoformat(),
                           'index_code': code, 'index_name': str(row[2])}
    if not result:
        raise ValueError('成分文件未提供研究日前45天内有效A股成员')
    return list(result.values())


def fetch_members(reference, as_of):
    key = 'members:' + reference['code']
    cached = _get(key)
    attempted_at = now_iso()
    if cached is not None and _valid_member_rows(cached, reference, as_of, _fetched_at(key)):
        _set_member_fetch_status(reference['code'], 'memory_cache', _fetched_at(key), attempted_at)
        return cached
    with _lock:
        previous = copy.deepcopy(_member_last_good.get(reference['code']))
    fallback = previous if _valid_member_snapshot(previous, reference, as_of) else None
    if fallback and 0 <= (_stamp(as_of) - _stamp(fallback.get('fetched_at') or fallback['verified_at'])).total_seconds() <= 6*3600:
        _set_member_fetch_status(reference['code'], 'persistent_cache', fallback.get('fetched_at'), attempted_at)
        _add_member_recovery_status(reference['code'], fallback)
        return copy.deepcopy(fallback['rows'])
    url = MEMBER_BASE + reference['code'] + 'cons.xls'
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 FundPilot/1.0'})
    try:
        content = fetch_bytes(request, timeout=8, max_bytes=4_000_000)
        fetched_at = now_iso()
        rows = import_member_workbook(content, reference, as_of, fetched_at, url)
        _set_member_fetch_status(reference['code'], 'network', fetched_at, attempted_at)
        return rows
    except Exception as error:
        if not fallback:
            _set_member_fetch_status(reference['code'], 'failed', None, attempted_at, str(error))
            raise
        _set_member_fetch_status(reference['code'], 'last_good_after_failure', fallback['fetched_at'], attempted_at, str(error))
        _add_member_recovery_status(reference['code'], fallback)
        return copy.deepcopy(fallback['rows'])


def _valid_member_rows(rows, reference, as_of, fetched_at):
    """Validate the whole dated list; never salvage a partial or mixed snapshot."""
    try:
        today, fetched = _stamp(as_of), _stamp(fetched_at)
        if (not isinstance(rows, list) or not 0 < len(rows) <= 10000
                or fetched.date() > today.date() or (fetched-today).total_seconds() > 300):
            return False
        codes, dates = set(), set()
        for row in rows:
            day = datetime.fromisoformat(row['member_date']).date()
            code = row['ts_code']
            if (not 0 <= (today.date()-day).days <= 45 or day > fetched.date()
                    or row['index_code'] != reference['code']
                    or row['index_name'] not in reference['aliases']
                    or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code)
                    or code in codes or not isinstance(row.get('name'), str) or not row['name'].strip()):
                return False
            codes.add(code)
            dates.add(day)
        return len(dates) == 1
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _valid_member_snapshot(snapshot, reference, as_of):
    if not isinstance(snapshot, dict):
        return False
    rows = snapshot.get('rows')
    if not isinstance(rows, list):
        return False
    return bool(snapshot.get('version') == 1 and snapshot.get('code') == reference['code']
        and snapshot.get('source_url') == MEMBER_BASE + reference['code'] + 'cons.xls'
        and snapshot.get('parsed_complete') is True
        and snapshot.get('parsed_count') == len(rows)
        and re.fullmatch(r'[a-f0-9]{64}', str(snapshot.get('content_sha256') or ''))
        and _valid_member_rows(rows, reference, as_of, snapshot.get('fetched_at') or snapshot.get('verified_at')))


def _save_member_snapshots():
    with _lock:
        encoded = json.dumps({'version': 1, 'snapshots': _member_last_good}, ensure_ascii=False)
        if len(encoded.encode('utf-8')) >= 12_000_000:
            return
        try:
            MEMBER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp = MEMBER_CACHE_PATH.with_suffix('.tmp')
            temp.write_text(encoded, encoding='utf-8')
            os.replace(temp, MEMBER_CACHE_PATH)
        except OSError:
            pass


def import_member_workbook(content, reference, as_of, fetched_at, source_url=None, filesystem_saved_at=None):
    """Persist only an actually parsed full official workbook with provenance.

    Also supports recovery of saved original XLS bytes. A selected three-company
    report cannot be imported through this entry point as a complete universe.
    """
    source_url = source_url or MEMBER_BASE + reference['code'] + 'cons.xls'
    if source_url != MEMBER_BASE + reference['code'] + 'cons.xls':
        raise ValueError('成分名单来源不是对应的中证官方文件')
    rows = parse_members(content, reference, as_of)
    verified_at = now_iso()
    if not _valid_member_rows(rows, reference, as_of, fetched_at or verified_at):
        raise ValueError('完整成分名单未通过身份、日期和证券校验')
    if fetched_at is None:
        saved = _stamp(filesystem_saved_at)
        if saved.date() < datetime.fromisoformat(rows[0]['member_date']).date() or saved > _stamp(as_of):
            raise ValueError('恢复文件的保存时间无效')
    snapshot = {'version': 1, 'code': reference['code'], 'source_url': source_url,
        'fetched_at': fetched_at, 'rows': copy.deepcopy(rows), 'parsed_complete': True,
        'parsed_count': len(rows), 'content_sha256': hashlib.sha256(content).hexdigest(),
        'verified_at': verified_at, 'filesystem_saved_at': filesystem_saved_at,
        'fetched_at_precision': 'datetime' if fetched_at else 'unknown'}
    with _lock:
        _member_last_good[reference['code']] = snapshot
        if fetched_at:
            _cache['members:' + reference['code']] = {'data': copy.deepcopy(rows),
                'fetched_at': fetched_at, 'expires': _stamp(fetched_at).timestamp() + 6*3600}
    _save_member_snapshots()
    return rows


def _set_member_fetch_status(code, mode, fetched_at, attempted_at, error=''):
    with _lock:
        _member_fetch_status[code] = {'cache_status': mode, 'fetched_at': fetched_at,
            'cache_used': mode in {'memory_cache', 'persistent_cache', 'last_good_after_failure'},
            'last_attempt_at': attempted_at, 'last_attempt_error': error[:300],
            'used_fallback': mode == 'last_good_after_failure'}


def member_fetch_status(code):
    with _lock:
        return copy.deepcopy(_member_fetch_status.get(code) or {})


def _add_member_recovery_status(code, snapshot):
    if snapshot.get('fetched_at') is None:
        with _lock:
            _member_fetch_status[code].update(fetched_at_precision='unknown', verified_at=snapshot.get('verified_at'),
                filesystem_saved_at=snapshot.get('filesystem_saved_at'),
                provenance_note='从先前保存的官方完整工作簿恢复；原HTTP采集时刻未保存，文件保存及本次重新核验时间单独记录。')


def import_fixed_samples_snapshot(content, references, as_of):
    """Recover only prior successfully verified selected samples, never a full list."""
    document = json.loads(content.decode('utf-8'))
    sources = {row.get('id'): row for row in document.get('sources', []) if isinstance(row, dict)}
    recovered = {}
    digest = hashlib.sha256(content).hexdigest()
    for identity, reference in references.items():
        leaders = document.get('sector_leaders', {}).get(identity) or []
        source_id = 'public:members:' + identity
        source = sources.get(source_id) or {}
        if (not 2 <= len(leaders) <= 3 or source.get('status') != 'ok'
                or source.get('url') != MEMBER_BASE + reference['code'] + 'cons.xls'
                or not isinstance(source.get('count'), int) or source['count'] < len(leaders)):
            continue
        members = []
        for leader in leaders:
            evidence = leader.get('membership_evidence') or {}
            name = str(evidence.get('l1_name') or '').removesuffix('（官方指数成分）')
            if (evidence.get('evidence_type') != 'official_index' or source_id not in leader.get('source_ids', [])
                    or evidence.get('snapshot_date') != source.get('as_of') or name not in reference['aliases']):
                break
            members.append({'ts_code': leader.get('ts_code'), 'name': leader.get('name'),
                'member_date': evidence['snapshot_date'], 'index_code': reference['code'], 'index_name': name})
        if len(members) != len(leaders) or not _valid_member_rows(members, reference, as_of, source.get('fetched_at')):
            continue
        recovered[identity] = {'code': reference['code'], 'source_url': source['url'],
            'fetched_at': source['fetched_at'], 'rows': members, 'complete_membership': False,
            'count': len(members), 'original_full_member_count': source['count'], 'original_source_id': source_id,
            'original_snapshot_sha256': digest}
    if not recovered:
        raise ValueError('原报告没有通过日期、身份、成功来源和引用校验的固定公司样本')
    _store_fixed_samples(recovered)
    return copy.deepcopy(recovered)


def _store_fixed_samples(recovered):
    with _lock:
        _fixed_samples.update(copy.deepcopy(recovered))
        encoded = json.dumps({'schema': 'csi_fixed_samples_not_complete_v1', 'boards': _fixed_samples}, ensure_ascii=False)
        FIXED_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = FIXED_SAMPLE_PATH.with_suffix('.tmp')
        temp.write_text(encoded, encoding='utf-8')
        os.replace(temp, FIXED_SAMPLE_PATH)


def import_visible_fixed_samples(content, references, as_of):
    """Validate a saved visible history extraction, without inventing full counts."""
    document = json.loads(content.decode('utf-8'))
    report_time = _stamp(document.get('report_as_of'))
    if report_time > _stamp(as_of) or not isinstance(document.get('method'), str):
        raise ValueError('历史页面恢复时间或方法无效')
    sources = {row.get('url'): row for row in document.get('sources', []) if isinstance(row, dict)}
    digest = hashlib.sha256(content).hexdigest()
    recovered = {}
    for sector in document.get('sectors', []):
        identity = sector.get('id')
        reference = references.get(identity)
        if not reference:
            raise ValueError('历史页面板块不在当前已核验映射中：' + str(identity))
        source_url = MEMBER_BASE + reference['code'] + 'cons.xls'
        source = sources.get(source_url) or {}
        source_name = str(source.get('name') or '').removeprefix('中证官方成分 · ')
        times = re.search(r'数据时间：(\d{4}-\d{2}-\d{2})本次获取：(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})可用', str(source.get('text') or ''))
        samples = sector.get('samples') or []
        evidence_rows = sector.get('company_evidence') or []
        if (source.get('status') != '可用' or source_name not in [reference['title'], *reference['aliases']]
                or not times or not 2 <= len(samples) <= 3 or len(evidence_rows) != len(samples)):
            raise ValueError('历史页面的成功来源、时刻或样本数量不一致：' + identity)
        member_date, fetched_text = times.groups()
        fetched_at = datetime.strptime(fetched_text, '%Y/%m/%d %H:%M:%S').replace(tzinfo=CHINA).isoformat()
        if _stamp(fetched_at) > report_time:
            raise ValueError('历史页面来源采集时间晚于报告：' + identity)
        rows = []
        for sample in samples:
            code, name = sample.get('code'), sample.get('name')
            matches = [row for row in evidence_rows if str(row.get('identity') or '').startswith(str(name)+str(code)+' · ')]
            if len(matches) != 1 or sample.get('membership_date') != member_date:
                raise ValueError('历史页面公司身份或名单日期不一致：' + identity)
            evidence = matches[0]
            if not any(link.get('url') == source_url for link in evidence.get('links', [])):
                raise ValueError('历史页面公司未引用对应官方来源：' + identity)
            membership = re.fullmatch(r'归属依据：(.+)（官方指数成分） → 成分名单日期 (\d{4}-\d{2}-\d{2})', str(evidence.get('membership') or ''))
            if not membership or membership[1] not in reference['aliases'] or membership[2] != member_date:
                raise ValueError('历史页面归属事实与板块不一致：' + identity)
            rows.append({'ts_code': code, 'name': name, 'member_date': member_date,
                         'index_code': reference['code'], 'index_name': membership[1]})
        if not _valid_member_rows(rows, reference, as_of, fetched_at):
            raise ValueError('历史固定样本未通过日期、身份和重复校验：' + identity)
        recovered[identity] = {'code': reference['code'], 'source_url': source_url, 'fetched_at': fetched_at,
            'rows': rows, 'complete_membership': False, 'count': len(rows), 'original_full_member_count': None,
            'original_source_id': 'public:members:' + identity, 'original_snapshot_sha256': digest,
            'recovery_method': document['method'], 'original_report_as_of': document['report_as_of'],
            'original_visible_source_text': source['text']}
    if not recovered:
        raise ValueError('历史页面未提供可恢复的固定样本')
    _store_fixed_samples(recovered)
    return copy.deepcopy(recovered)


def fixed_sample_members(identity, reference, as_of):
    with _lock:
        snapshot = copy.deepcopy(_fixed_samples.get(identity))
    if (not isinstance(snapshot, dict) or snapshot.get('complete_membership') is not False
            or snapshot.get('code') != reference['code']
            or snapshot.get('source_url') != MEMBER_BASE + reference['code'] + 'cons.xls'
            or snapshot.get('original_source_id') != 'public:members:' + identity
            or not re.fullmatch(r'[a-f0-9]{64}', str(snapshot.get('original_snapshot_sha256') or ''))
            or not isinstance(snapshot.get('rows'), list) or not 2 <= len(snapshot['rows']) <= 3
            or snapshot.get('count') != len(snapshot['rows'])
            or (snapshot.get('original_full_member_count') is not None
                and (not isinstance(snapshot['original_full_member_count'], int)
                     or snapshot['original_full_member_count'] < len(snapshot['rows'])))
            or not _valid_member_rows(snapshot['rows'], reference, as_of, snapshot.get('fetched_at'))):
        return [], {}
    rows = snapshot['rows']
    for row in rows:
        row.update(evidence_type='official_fixed_sample', source_ids=[snapshot['original_source_id']],
            source_url=snapshot['source_url'], observed_at=snapshot['fetched_at'],
            role='先前已验证官方归属的固定代表样本（非完整成分池）',
            evidence_description='保留先前已通过官方成分归属验证的固定样本；原名单日期 ' + row['member_date'] + '；当前未重新取得完整成员池。',
            selection_basis='本轮沿用先前已核验的固定2~3家公司；仅在此有限池内按当前市值展示，不代表本轮完整成分池市值排名。')
    metadata = {'cache_status': 'fixed_samples_after_failure', 'cache_used': True, 'used_fallback': True,
        'fetched_at': snapshot['fetched_at'], 'complete_membership': False,
        'original_full_member_count': snapshot['original_full_member_count'],
        'backup_snapshot_sha256': snapshot['original_snapshot_sha256'],
        'recovery_method': snapshot.get('recovery_method', '先前成功研究报告中保留的已核验固定公司样本'),
        'original_report_as_of': snapshot.get('original_report_as_of'),
        'scope': '先前已核验归属的固定2~3家公司样本池；不是完整成员清单，也不代表本轮全池市值排名。'}
    return rows, metadata


def parse_quotes(text, wanted, as_of, received_at=None):
    now = _stamp(as_of)
    if received_at:
        received = _stamp(received_at)
        if 0 <= (received - now).total_seconds() <= 300:
            now = received
            as_of = now.isoformat()
    from research_trading_calendar import is_trading_day, a_share_quote_fresh
    result = {}
    for symbol, value in re.findall(r'v_((?:sh|sz|bj)\d{6})="([^"]+)"', text):
        fields = value.split('~')
        code = symbol[2:] + '.' + symbol[:2].upper()
        if code not in wanted or len(fields) < 49 or fields[2] != symbol[2:]:
            continue
        try:
            stamp = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=CHINA)
        except ValueError:
            continue
        if not a_share_quote_fresh(stamp.isoformat(), as_of):
            continue
        # A stale close must not masquerade as current during later trading days.
        from datetime import timedelta
        live = stamp.date() == now.date() and (stamp.hour > 9 or stamp.hour == 9 and stamp.minute >= 30) and stamp.hour < 15 and now.hour < 15
        # a_share_quote_fresh already pauses the age clock over lunch. A
        # second wall-clock check here used to reject the entire market at noon.
        expected = now.date() if live else now.date() - timedelta(days=1 if now.hour < 15 else 0)
        while expected > stamp.date():
            opened = is_trading_day(expected)
            if opened is None or opened:
                break
            expected -= timedelta(days=1)
        if expected != stamp.date() or not is_trading_day(stamp.date()) or (not live and stamp.hour < 15):
            continue
        close, change, size = number(fields[3]), number(fields[32]), number(fields[45])
        if close is None or close <= 0 or change is None or size is None or size <= 0:
            continue
        result[code] = {'name': fields[1], 'trade_date': stamp.date().isoformat(), 'as_of': stamp.isoformat(),
            'close': close, 'pct_chg': change, 'amount': (number(fields[37]) or 0) * 10000,
            'total_mv': size * 10000, 'turnover_rate': number(fields[38]),
            'pe_ttm': number(fields[39]), 'pb': number(fields[46]),
            'is_intraday': live}
    return result


def fetch_quotes(codes, as_of):
    symbols = [c[-2:].lower() + c[:6] for c in codes]
    url = 'https://qt.gtimg.cn/q=' + ','.join(symbols)
    text = fetch_text(url, 'gbk')
    return parse_quotes(text, set(codes), as_of, received_at=now_iso())


def finance_url(code):
    return FINANCE_BASE + '?' + urlencode({'reportName': 'RPT_LICO_FN_CPD', 'columns': 'ALL',
        'filter': '(SECUCODE="' + code + '")', 'pageSize': 12, 'pageNumber': 1,
        'sortColumns': 'REPORTDATE', 'sortTypes': -1})


def parse_financial(payload, code, as_of):
    if not isinstance(payload, dict) or payload.get('success') is not True:
        raise ValueError('财务接口未返回成功数据')
    now = _stamp(as_of)
    usable = []
    for row in (payload.get('result') or {}).get('data') or []:
        if row.get('SECUCODE') != code:
            continue
        ann, end = str(row.get('NOTICE_DATE') or '')[:10], str(row.get('REPORTDATE') or '')[:10]
        try:
            announced, report = datetime.fromisoformat(ann).date(), datetime.fromisoformat(end).date()
        except ValueError:
            continue
        # Date-only official publication is conservatively usable next day.
        if announced >= now.date() or report > now.date():
            continue
        metrics = {target: number(row.get(source)) for target, source in (
            ('roe', 'WEIGHTAVG_ROE'), ('eps', 'BASIC_EPS'), ('netprofit_yoy', 'SJLTZ'),
            ('tr_yoy', 'YSTZ'), ('grossprofit_margin', 'XSMLL'))}
        if all(v is None for v in metrics.values()):
            continue
        usable.append({'ts_code': code, 'ann_date': ann, 'end_date': end, **metrics})
    return max(usable, key=lambda r: (r['end_date'], r['ann_date'])) if usable else None


def fetch_financial(code, as_of):
    key = 'financial:' + code
    payload = _get(key)
    if payload is None:
        try:
            payload = json.loads(fetch_text(finance_url(code)))
        except (OSError, TimeoutError):
            retained = _get(key + ':last_good')
            if retained and parse_financial(retained, code, as_of):
                return parse_financial(retained, code, as_of)
            raise
        # Empty successful responses must not poison the cache for a full day.
        if parse_financial(payload, code, as_of):
            _remember(key, payload, 24 * 3600)
            _remember(key + ':last_good', payload, 550 * 86400)
    return parse_financial(payload, code, as_of)


def _parallel(items, function, seconds, workers=6):
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(function, item): item for item in items}
    results = {}
    try:
        for future in as_completed(futures, timeout=seconds):
            item = futures[future]
            try:
                results[item] = (future.result(), '')
            except Exception as error:
                results[item] = (None, str(error)[:160])
    except TimeoutError:
        pass
    finally:
        for future, item in futures.items():
            if item not in results:
                future.cancel()
                results[item] = (None, '本轮采集预算用完，下轮继续')
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def capability_snapshot():
    with _lock:
        out = copy.deepcopy(_capabilities)
        for row in out.values():
            if row.get('checked_at') and (_stamp(now_iso()) - _stamp(row['checked_at'])).total_seconds() > 6 * 3600:
                row.update(status='unverified', note='样本检查已超过6小时，等待重新取数')
        return out


def gather_public_company_evidence(catalog, as_of):
    from research_sample_policy import CANDIDATE_LIMIT, SELECTION_METHOD, fair_codes
    result = {'status': 'unavailable', 'provider': PROVIDER, 'sources': [], 'sector_leaders': {},
              'warnings': [], 'request_count': 0,
              'selection_method': SELECTION_METHOD}
    references = reference_memberships(catalog)
    with _lock:
        for ref in references.values():
            _member_fetch_status.pop(ref['code'], None)
    memberships = _parallel(list(references), lambda key: fetch_members(references[key], as_of), 12)
    codes = set()
    for identity, (members, error) in memberships.items():
        ref = references[identity]
        state = member_fetch_status(ref['code'])
        if not members:
            fixed, metadata = fixed_sample_members(identity, ref, as_of)
            if fixed:
                members = fixed
                memberships[identity] = (fixed, error)
                state.update(metadata)
        limited = bool(members and state.get('complete_membership') is False)
        fallback = bool(members and state.get('used_fallback'))
        collection_error = error or state.get('last_attempt_error', '')
        if fallback:
            prefix = ('本轮官方完整成分采集失败，沿用45天内先前已验证归属的固定公司样本池（非完整名单）：'
                      if limited else '本轮官方成分采集失败，沿用仍在45天有效窗口内的完整已核验名单：')
            collection_error = prefix + collection_error
        source_name = ('中证归属已验证固定样本 · ' if limited else '中证官方成分 · ') + ref['title']
        result['sources'].append(_source('members:' + identity, source_name,
            MEMBER_BASE + ref['code'] + 'cons.xls', 'partial' if fallback or state.get('fetched_at_precision') == 'unknown' else 'ok' if members else 'error',
            len(members or []), max((r['member_date'] for r in members or []), default=None), collection_error))
        result['sources'][-1]['fetched_at'] = (state['fetched_at'] if 'fetched_at' in state else _fetched_at('members:' + ref['code'])) if members else now_iso()
        result['sources'][-1].update({key: value for key, value in state.items() if key != 'fetched_at'})
        codes.update(r['ts_code'] for r in members or [])
    from research_theme_memberships import fetch_theme_memberships
    theme = fetch_theme_memberships(catalog, as_of)
    memberships.update(theme['memberships'])
    references.update(theme['references'])
    result['sources'].extend(theme['sources'])
    for members, _ in theme['memberships'].values():
        codes.update(r['ts_code'] for r in members or [])
    batches = [tuple(sorted(codes)[i:i+100]) for i in range(0, len(codes), 100)]
    prices = {}
    for batch, (rows, error) in _parallel(batches, lambda b: fetch_quotes(b, as_of), 45, workers=8).items():
        prices.update(rows or {})
        result['sources'].append(_source('quotes:' + str(batches.index(batch)), '腾讯财经 · 代表公司行情',
            'https://qt.gtimg.cn/q=' + ','.join(c[-2:].lower()+c[:6] for c in batch),
            'ok' if rows else 'error', len(rows or []), max((r['as_of'] for r in (rows or {}).values()), default=None), error))
    selected = {}
    result['selection_universes'] = {}
    for identity, (members, _) in memberships.items():
        rows = [r for r in members or [] if r['ts_code'] in prices and not re.search(r'ST|退', prices[r['ts_code']]['name'], re.I)]
        smallest = references[identity].get('selection_order') == 'smallest_market_cap'
        selected[identity] = sorted(rows, key=lambda r: ((1 if smallest else -1)*prices[r['ts_code']]['total_mv'], r['ts_code']))[:CANDIDATE_LIMIT]
        result['selection_universes'][identity] = {'membership_count': len(members or []),
            'quoted_count': len(rows), 'order': 'smallest_market_cap' if smallest else 'largest_market_cap',
            'verified_member_codes': [r['ts_code'] for r in members or []]}
    fin_codes = fair_codes(selected)
    finances = _parallel(fin_codes, lambda c: fetch_financial(c, as_of), 60, workers=12)
    for code, (fin, error) in finances.items():
        result['sources'].append(_source('financial:' + code, '东方财富 · 公司财务指标', finance_url(code),
            'ok' if fin else 'error' if error else 'partial', 1 if fin else 0,
            fin['ann_date'] if fin else None, error or ('' if fin else '无研究日前已披露且字段有效的报告')))
        result['sources'][-1]['fetched_at'] = _fetched_at('financial:' + code) if fin else now_iso()
    for identity, rows in selected.items():
        leaders = []
        for member in rows:
            code = member['ts_code']
            price = prices[code]
            financials = finances.get(code, (None, ''))[0]
            business = member.get('evidence_type') in {'public_business', 'official_business'}
            fixed_sample = member.get('evidence_type') == 'official_fixed_sample'
            quote_sources = [s['id'] for s in result['sources'] if s['id'].startswith('public:quotes:')
                             and code[-2:].lower()+code[:6] in s['url']]
            leaders.append({'ts_code': code, 'name': price['name'], 'industry': references[identity]['title'],
                'role': member.get('role') or '官方指数成分代表样本（非已核验主营龙头）', 'leader_verified': False,
                'selection_basis': member.get('selection_basis') or result['selection_method'],
                'quote': {**{k: price[k] for k in ('trade_date', 'close', 'pct_chg', 'amount')},
                          'data_kind': 'realtime' if price['is_intraday'] else 'daily_close',
                          'is_intraday': price['is_intraday'], 'units': {'amount': '元'}},
                'market_metrics': {k: price[k] for k in ('total_mv', 'turnover_rate', 'pe_ttm', 'pb')},
                'financials': financials,
                'financials_note': '东方财富公开财务报表，百分比按原值；仅使用研究日前披露的报告，同日披露暂不使用。市值单位万元。',
                'membership_evidence': {'l1_name': member['index_name'] + ('（先前已核验官方归属的固定样本）' if fixed_sample else '（公开业务证据样本池）' if business else '（官方指数成分）'),
                    'l2_name': member.get('evidence_description') or '成分名单日期 ' + member['member_date'],
                    'l3_name': '', 'in_date': '', 'out_date': '', 'snapshot_date': member['member_date'],
                    'evidence_type': member.get('evidence_type', 'official_index'),
                    'published_date': member.get('published_date'), 'observed_at': member.get('observed_at'),
                    'source_url': member.get('source_url')},
                'as_of': price['as_of'], 'source_ids': member.get('source_ids', ['public:members:' + identity]) + quote_sources
                    + (['public:financial:' + code] if financials else [])})
        if leaders:
            result['sector_leaders'][identity] = leaders
    counts = {'industry': sum(len(rows or []) for rows, _ in memberships.values()),
              'daily': len(prices), 'financial': sum(bool(fin) for fin, _ in finances.values())}
    with _lock:
        for key, count in counts.items():
            _capabilities[key] = {'status': 'available' if count else 'unavailable', 'count': count,
                'checked_at': now_iso(), 'note': '真实取数样本，不表示全板块完整覆盖'}
    result['status'] = 'partial' if result['sector_leaders'] else 'unavailable'
    result['request_count'] = len(memberships) + len(batches) + len(finances)
    from research_overseas import gather_overseas_company_evidence, SAMPLES as OVERSEAS_SAMPLES
    if any(row['id'] in OVERSEAS_SAMPLES for row in catalog):
        overseas = gather_overseas_company_evidence(catalog, as_of)
        result['sector_leaders'].update({key: rows for key, rows in overseas['sector_leaders'].items() if rows})
        result['sources'].extend(overseas['sources'])
        result['warnings'].extend(overseas.get('warnings', []))
        result['request_count'] += overseas.get('request_count', 0)
        result['status'] = 'partial' if result['sector_leaders'] else 'unavailable'
    result['coverage'] = {'mapped_sector_count': len(references), 'sampled_sector_count': len(result['sector_leaders']), **counts}
    result['warnings'].append('免费公开接口不承诺稳定性；指数成分是官方快照，不是完整行业或主营龙头认证。缺少专属映射的方向不强行替代。')
    _save()
    return result


def probe_public_data():
    result = gather_public_company_evidence([{'id': 'sector_cloud_computing'}], now_iso())
    caps = capability_snapshot()
    return {'verification': 'verified' if all(caps.get(k, {}).get('count', 0) for k in ('industry','daily','financial')) else 'partial' if result['sector_leaders'] else 'failed',
            'capabilities': caps, 'error': '' if result['sector_leaders'] else '备用公开接口未取得有效样本'}
