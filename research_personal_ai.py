"""Public scheduled research; personal narrative generation is explicit.

Preferences and watchlists do not start AI. Public administrator research and
five-day reviews retain their existing schedule and daily cost protection.
"""
import copy
from functools import partial

from research_sector_ai import enrich_sector_report


def personalized_runner(subscriptions):
    return partial(enrich_reviewed_report, subscriptions=subscriptions)


def enrich_reviewed_report(report, config=None, progress=None, is_current=None,
                           can_start_request=None, subscriptions=None,
                           requester=None, event_requester=None, review_requester=None):
    """Review observations persist independently; paid reviews share admission."""
    from research_review import run_scheduled_reviews
    config = dict(config or {})
    current = is_current or (lambda: True)
    store = subscriptions.accounts.reviews
    if current():
        store.capture(report)
    # One compact review batch precedes normal narratives so it cannot starve
    # behind 101 sectors. It never raises the shared request/token limits.
    stats = run_scheduled_reviews(store, report, config, current, can_start_request, review_requester)
    working = copy.deepcopy(report)
    for item in store.items(report, [s['id'] for s in report.get('sector_analysis', []) if s.get('id')]):
        if item['status'] != 'completed':
            continue
        narrative = store.narrative(store.fingerprint(item, config))
        row = next((s for s in working.get('sector_analysis', []) if s['id'] == item['id']), None)
        if row is not None:
            row['review_feedback'] = {'period_end':item['period_end'], 'return_pct':item.get('return_pct'),
                'drawdown_pct':item.get('drawdown_pct'), 'review_kind':item.get('review_kind'),
                'rate_metrics':item.get('rate_metrics'), 'score':item['score'], 'scope':item['scope'],
                'source_ids':item['source_ids'], 'lessons':narrative['lessons'] if narrative else []}
    run_config = {**config, 'enabled':False} if stats['terminal_error'] else config
    output = enrich_personal_report(working, run_config, progress, current, can_start_request,
                                   subscriptions, requester, event_requester)
    for row in output.get('sector_analysis', []):
        row.pop('review_feedback', None)
    meta = output['ai_research']
    if stats['terminal_error']:
        meta.update(status='failed', terminal_error=True, configuration_enabled=bool(config.get('enabled',True)),
                    error=stats['errors'][0]['message'])
    meta['five_day_review'] = copy.deepcopy(stats)
    for key in ('request_count','requests_attempted','requests_succeeded'):
        meta[key] += stats[key]
    for key in meta['usage']:
        meta['usage'][key] += stats['usage'].get(key,0)
    meta['usage_complete'] = meta['usage_complete'] and stats['usage_complete']
    meta['errors'].extend({**e, 'module':'five_day_review'} for e in stats['errors'])
    output.setdefault('automatic',{}).update(paid_api_calls=bool(meta['request_count']), paid_api_call_count=meta['request_count'])
    if current():
        store.capture(output)
    return output


def enrich_personal_report(report, config=None, progress=None, is_current=None,
                           can_start_request=None, subscriptions=None,
                           requester=None, event_requester=None):
    config = dict(config or {})
    current = is_current or (lambda:True)
    output = enrich_sector_report(report, config=config, progress=progress, is_current=current,
        can_start_request=can_start_request, requester=requester, event_requester=event_requester)
    # Personal preferences and watchlists never enqueue paid variants. Only
    # the explicit manual endpoint may generate additional reasoning levels.
    output['ai_research']['personal_variants'] = []
    return output
