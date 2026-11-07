"""Validate AI evidence reasoning against this batch, never certify world truth."""
import hashlib
import json
import re
from urllib.parse import urlsplit

VERSION = 'source_reasoning_v1'
LABELS = {'cross_checked':'本批交叉印证', 'single_source':'单一来源陈述',
          'disputed':'证据存在冲突', 'insufficient':'真实性待核验'}
NOTE = 'AI只核对本批已采集原文及相反证据，不能保证新闻真实，也不代表已完成全网事实调查；官方披露同样可能存在偏差。'


def clean(value, maximum=1200):
    return value.strip()[:maximum] if isinstance(value, str) else ''


def excerpt_in(value, source):
    """Only accept an exact contiguous quotation from the cited document."""
    text = clean(value, 600)
    normalized = re.sub(r'\s+', '', text)
    summary = re.sub(r'\s+', '', str(source.get('summary') or ''))
    return text if len(normalized) >= 12 and normalized in summary else ''


def signature(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def publisher(source):
    """An exchange aggregator is not an independent issuer."""
    codes = source.get('stock_codes') or []
    if codes:
        return 'company:' + ','.join(sorted({str(c).split('.')[0] for c in codes}))
    if source.get('company_name'):
        return 'company:' + clean(source['company_name'])
    host = (urlsplit(str(source.get('url') or '')).hostname or '').lower()
    # Unknown issuers on an announcement aggregator cannot corroborate each other.
    return 'publisher:' + (host if host else str(source.get('source_id') or 'unknown'))


def decode_verification(value, source, candidates):
    """Downgrade unsupported certainty; retain both supporting and contrary facts."""
    fallback = {'version':VERSION, 'status':'insufficient', 'label':LABELS['insufficient'],
                'claim_type':'unknown', 'claim_excerpt':'', 'reason':'本条消息尚未完成来源与相反证据研判。',
                'inference':'', 'uncertainties':['缺少有效的结构化核验结果。'], 'links':[], 'note':NOTE}
    if not isinstance(value, dict):
        return fallback
    quote = excerpt_in(value.get('claim_excerpt'), source)
    verdict, kind = value.get('verdict'), value.get('claim_type')
    reason = clean(value.get('reason'))
    uncertainties = [clean(v, 400) for v in (value.get('uncertainties') or [])[:5]
                     if isinstance(v, str) and clean(v)] if isinstance(value.get('uncertainties'), list) else []
    if (not quote or verdict not in LABELS or kind not in ('fact','forecast','opinion')
            or len(reason) < 15 or not uncertainties):
        return fallback
    lookup = {r['id']:r for r in candidates}
    links, seen = [], set()
    for proposed in value.get('links', [])[:6] if isinstance(value.get('links'), list) else []:
        if not isinstance(proposed, dict):
            continue
        other = lookup.get(proposed.get('event_id'))
        relation = proposed.get('relation')
        if (not other or other['id'] == source['id'] or other['id'] in seen
                or other.get('url') == source.get('url') or relation not in ('supports','contradicts')):
            continue
        # Reprints/identical documents are not independent evidence.
        if re.sub(r'\s+','',str(other.get('summary') or '')) == re.sub(r'\s+','',str(source.get('summary') or '')):
            continue
        fact, why = excerpt_in(proposed.get('fact_excerpt'), other), clean(proposed.get('reason'),600)
        if not fact or len(why) < 12:
            continue
        own_codes = {str(c).split('.')[0] for c in source.get('stock_codes', [])}
        other_codes = {str(c).split('.')[0] for c in other.get('stock_codes', [])}
        independent = publisher(other) != publisher(source) and not own_codes.intersection(other_codes)
        links.append({'event_id':other['id'], 'relation':relation, 'fact_excerpt':fact,
            'reason':why, 'independent':independent, 'title':other.get('title'), 'url':other.get('url'),
            'source_name':other.get('source_name'), 'published_at':other.get('published_at'),
            'signature':signature(other)})
        seen.add(other['id'])
    conflict = any(r['relation'] == 'contradicts' for r in links)
    supported = any(r['relation'] == 'supports' and r['independent'] for r in links)
    status = ('disputed' if conflict or verdict == 'disputed' else
              'insufficient' if verdict == 'insufficient' else
              'cross_checked' if verdict == 'cross_checked' and supported and kind == 'fact' else 'single_source')
    if verdict == 'cross_checked' and status == 'single_source':
        uncertainties.append('缺少不同发布主体的有效交叉证据，已降为单一来源陈述。')
    if kind != 'fact':
        uncertainties.append('该内容属于预测或观点，尚不能视为已经发生的事实。')
    return {'version':VERSION, 'status':status, 'label':LABELS[status], 'claim_type':kind,
            'claim_excerpt':quote, 'reason':reason, 'inference':clean(value.get('inference')),
            'uncertainties':uncertainties, 'links':links, 'note':NOTE}


def revalidate_verification(value, source, candidates):
    """Recheck cross references when a retained document changes or expires."""
    if not isinstance(value, dict):
        return decode_verification(None, source, candidates)
    signatures = {r['id']:signature(r) for r in candidates}
    links = [r for r in value.get('links', []) if isinstance(r, dict)
             and signatures.get(r.get('event_id')) == r.get('signature')]
    return decode_verification({**value, 'verdict':value.get('status'), 'links':links}, source, candidates)
