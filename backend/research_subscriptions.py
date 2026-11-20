"""Administrator-issued website credits for shared, completed sector AI reports.

These credits are access rights, never a user's provider balance. Reads do not
start upstream requests. Debit and unlock commit together in one transaction.
"""
import hashlib
import json
import math
import re
import secrets
from datetime import datetime, timedelta, timezone

from research_accounts import AccountError

# Personal AI calls are limited per Beijing calendar day and month.
BEIJING = timezone(timedelta(hours=8))
MAX_DAILY_CALLS = 1000
MAX_MONTHLY_CALLS = 30000


CREDIT_COSTS = {'medium': 1, 'xhigh': 1.5}
_CREDIT_SCHEMA_VERSION = 2
NARRATIVE_FIELDS = ('ai_reason', 'ai_analysis', 'ai_risks', 'ai_invalidation',
                    'ai_advice', 'ai_research_status', 'ai_reused',
                    'ai_generated_at', 'ai_reasoning_effort', 'ai_variant_version', 'evidence_ids', 'ai_live_retained')


def without_narrative(sector):
    return {k:v for k,v in sector.items() if not k.startswith('ai_') and k != 'evidence_ids'}


def select_interpretation(source, effort):
    """Select only a completed narrative actually generated at this effort."""
    if not effort or source.get('ai_reasoning_effort') == effort:
        return {k:v for k,v in source.items() if k != 'ai_variants'}
    variants = source.get('ai_variants')
    variant = variants.get(effort) if isinstance(variants, dict) else None
    if (isinstance(variant, dict) and variant.get('ai_reasoning_effort') == effort
            and content_identity({**variant, 'id':source.get('id')})):
        return {**without_narrative(source), **{k:variant[k] for k in NARRATIVE_FIELDS if k in variant}}
    return without_narrative(source)


def _points(half_units):
    """Expose human credit points while keeping all stored arithmetic integral."""
    return half_units // 2 if half_units % 2 == 0 else half_units / 2


def _grant_half_units(value):
    if (type(value) not in (int, float) or not 0 <= value <= 100000
            or not math.isfinite(value) or value * 2 != int(value * 2)):
        raise AccountError('额度需为 0～100000 点，最小单位为 0.5 点')
    return int(value * 2)


def interpretation_price(sector):
    """Price the persisted generation provenance, never the current settings.

    Old reports and old cache entries keep their original one-point price.
    Provenance is deliberately excluded from content_identity, so a previously
    unlocked interpretation cannot be charged again after this rollout.
    """
    effort = sector.get('ai_reasoning_effort') if isinstance(sector, dict) else None
    effort = effort if isinstance(effort, str) and effort in CREDIT_COSTS else None
    return {'cost': CREDIT_COSTS.get(effort, 1), 'reasoning_effort': effort,
            'pricing_legacy': effort is None}


def call_period(clock_value):
    """Beijing calendar day and month for a timestamp, as 'YYYY-MM-DD' and 'YYYY-MM'."""
    moment = datetime.fromtimestamp(clock_value, BEIJING)
    return moment.strftime('%Y-%m-%d'), moment.strftime('%Y-%m')


def _limit(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise AccountError(f'{label}需为 0～{maximum} 的整数')
    return value


def quota_message(quota):
    """Why a personal AI call cannot start, naming both remaining counts; '' when it can."""
    if quota.get('unlimited'):
        return ''
    if not quota.get('configured'):
        return '管理员尚未设置你的每日和每月 AI 调用次数，未发起请求，也未扣减次数'
    remaining = f"今日剩余 {quota['daily_remaining']} 次，本月剩余 {quota['monthly_remaining']} 次"
    if quota['daily_remaining'] <= 0 and quota['monthly_remaining'] <= 0:
        return f'今日和本月的 AI 调用次数都已用完（{remaining}），未发起请求'
    if quota['monthly_remaining'] <= 0:
        return f'本月 AI 调用次数已用完（{remaining}），下月 1 日北京时间 0 点恢复，未发起请求'
    if quota['daily_remaining'] <= 0:
        return f'今日 AI 调用次数已用完（{remaining}），北京时间次日 0 点恢复，未发起请求'
    return ''


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


def content_identity(sector):
    if (not isinstance(sector, dict) or sector.get('ai_research_status') != 'completed'
            or not str(sector.get('ai_reason') or sector.get('ai_analysis') or '').strip()):
        return None
    content = {key: sector.get(key) for key in (
        'id', 'ai_reason', 'ai_analysis', 'ai_risks', 'ai_invalidation',
        'ai_advice', 'ai_generated_at', 'evidence_ids')}
    # New independently generated variants must have distinct unlock identities,
    # even if two valid upstream responses happen to use identical wording.
    if sector.get('ai_variant_version') == 1:
        content['variant_effort'] = sector.get('ai_reasoning_effort')
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class SubscriptionStore:
    def __init__(self, accounts):
        self.accounts = accounts
        with accounts.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS ai_subscriptions (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                enabled INTEGER NOT NULL, credits INTEGER NOT NULL CHECK(credits>=0),
                expires REAL NOT NULL, updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS ai_unlocks (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content_id TEXT NOT NULL, sector_id TEXT NOT NULL, report_id TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(user_id,content_id));
              CREATE TABLE IF NOT EXISTS ai_subscription_ledger (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                actor_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
                delta INTEGER NOT NULL, balance INTEGER NOT NULL, expires REAL NOT NULL,
                note TEXT NOT NULL, created REAL NOT NULL, request_id TEXT NOT NULL,
                UNIQUE(actor_id,request_id));
              CREATE INDEX IF NOT EXISTS ai_ledger_user ON ai_subscription_ledger(user_id,created);
              CREATE TABLE IF NOT EXISTS ai_research_preferences (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                reasoning_effort TEXT NOT NULL CHECK(reasoning_effort IN ('medium','xhigh')),
                updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS ai_manual_jobs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                report_id TEXT NOT NULL, sector_id TEXT NOT NULL, reasoning_effort TEXT NOT NULL,
                status TEXT NOT NULL, reserved_units INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, updated REAL NOT NULL, result TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '');
              CREATE INDEX IF NOT EXISTS ai_manual_user ON ai_manual_jobs(user_id,status,updated);
              CREATE TABLE IF NOT EXISTS ai_call_limits (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                daily_limit INTEGER NOT NULL CHECK(daily_limit>=0),
                monthly_limit INTEGER NOT NULL CHECK(monthly_limit>=0), updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS ai_call_usage (
                job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                day TEXT NOT NULL, month TEXT NOT NULL, created REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS ai_call_usage_user ON ai_call_usage(user_id,month,day);
              CREATE TABLE IF NOT EXISTS ai_manual_narratives (
                report_id TEXT NOT NULL, sector_id TEXT NOT NULL, reasoning_effort TEXT NOT NULL,
                configuration TEXT NOT NULL, narrative TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(report_id,sector_id,reasoning_effort,configuration));
            ''')
            # The old schema stored whole points. SQLite's column name stays
            # stable, but v2 stores half-points in every monetary field. Migrate
            # the balance and its complete audit trail in the same transaction.
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS ai_subscription_schema '
                       '(component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
            marker = db.execute("SELECT version FROM ai_subscription_schema WHERE component='credits'").fetchone()
            if marker is None:
                db.execute('UPDATE ai_subscriptions SET credits=credits*2')
                db.execute('UPDATE ai_subscription_ledger SET delta=delta*2,balance=balance*2')
                db.execute('INSERT INTO ai_subscription_schema VALUES (?,?)', ('credits', _CREDIT_SCHEMA_VERSION))
            elif marker['version'] != _CREDIT_SCHEMA_VERSION:
                raise AccountError('订阅额度版本不兼容，已暂停额度操作', 503)

    def _summary(self, db, user_id):
        user = db.execute('SELECT role,disabled FROM users WHERE id=?', (user_id,)).fetchone()
        if not user:
            raise AccountError('账号不存在', 404)
        preference = db.execute('SELECT reasoning_effort FROM ai_research_preferences WHERE user_id=?', (user_id,)).fetchone()
        held = db.execute("SELECT coalesce(sum(reserved_units),0),coalesce(max(updated),0) FROM ai_manual_jobs WHERE user_id=?", (user_id,)).fetchone()
        personal = {'preferred_reasoning_effort':preference[0] if preference else None,
                    'credits_reserved':_points(held[0]), 'manual_research_revision':held[1]}
        if user['role'] == 'admin':
            personal['call_quota'] = self._call_quota(db, user_id, 'admin')
            return {'status':'admin', 'label':'管理员', 'can_unlock':True,
                    'credits_remaining':None, 'expires_at':None, 'unlocked_count':0,
                    'credit_unit':'点', 'credit_costs':dict(CREDIT_COSTS), **personal}
        personal['call_quota'] = self._call_quota(db, user_id, user['role'])
        row = db.execute('SELECT * FROM ai_subscriptions WHERE user_id=?', (user_id,)).fetchone()
        status = ('unsubscribed' if not row else 'paused' if not row['enabled'] or user['disabled']
                  else 'expired' if row['expires'] <= self.accounts.clock()
                  else 'exhausted' if row['credits'] < 2 else 'active')
        return {'status':status, 'label':{'unsubscribed':'未开通', 'paused':'已暂停',
            'expired':'已到期', 'exhausted':'额度不足', 'active':'服务已开通'}[status],
            'can_unlock':status == 'active', 'credits_remaining':_points(row['credits']) if row else 0,
            'credit_unit':'点', 'credit_costs':dict(CREDIT_COSTS), **personal,
            'expires_at':iso(row['expires']) if row else None,
            'unlocked_count':db.execute('SELECT count(*) FROM ai_unlocks WHERE user_id=?', (user_id,)).fetchone()[0]}

    def _call_quota(self, db, user_id, role):
        """Today's and this month's personal AI calls against the administrator's limits.

        Counts come from ai_call_usage, which records only completed calls that
        actually asked the model; failures and reused interpretations never count.
        Changing a limit applies at once and never rewrites the recorded usage.
        """
        day, month = call_period(self.accounts.clock())
        daily_used = db.execute('SELECT count(*) FROM ai_call_usage WHERE user_id=? AND day=?', (user_id, day)).fetchone()[0]
        monthly_used = db.execute('SELECT count(*) FROM ai_call_usage WHERE user_id=? AND month=?', (user_id, month)).fetchone()[0]
        base = {'day':day, 'month':month, 'daily_used':daily_used, 'monthly_used':monthly_used, 'timezone':'Asia/Shanghai'}
        if role == 'admin':
            return {**base, 'unlimited':True, 'configured':True, 'daily_limit':None, 'monthly_limit':None,
                    'daily_remaining':None, 'monthly_remaining':None, 'can_call':True}
        row = db.execute('SELECT daily_limit,monthly_limit FROM ai_call_limits WHERE user_id=?', (user_id,)).fetchone()
        if not row:
            return {**base, 'unlimited':False, 'configured':False, 'daily_limit':None, 'monthly_limit':None,
                    'daily_remaining':0, 'monthly_remaining':0, 'can_call':False}
        daily_remaining = max(0, row['daily_limit'] - daily_used)
        monthly_remaining = max(0, row['monthly_limit'] - monthly_used)
        return {**base, 'unlimited':False, 'configured':True, 'daily_limit':row['daily_limit'],
                'monthly_limit':row['monthly_limit'], 'daily_remaining':daily_remaining,
                'monthly_remaining':monthly_remaining, 'can_call':daily_remaining > 0 and monthly_remaining > 0}

    def record_call(self, db, user_id, job_id):
        """Count one completed model call, inside the caller's settlement transaction."""
        now = self.accounts.clock()
        day, month = call_period(now)
        db.execute('INSERT OR IGNORE INTO ai_call_usage VALUES (?,?,?,?,?)', (job_id, user_id, day, month, now))
        # Monthly limits need only the current month; keep about 13 months for the audit.
        db.execute('DELETE FROM ai_call_usage WHERE created<?', (now - 400 * 86400,))

    def summary(self, user_id):
        with self.accounts.connection() as db:
            return self._summary(db, user_id)

    def preference(self, user_id, effort):
        if not isinstance(effort, str) or effort not in CREDIT_COSTS:
            raise AccountError('请选择中度推理或极高推理')
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT disabled FROM users WHERE id=?', (user_id,)).fetchone()
            if not user or user['disabled']:
                raise AccountError('账号不可用', 403)
            db.execute('INSERT INTO ai_research_preferences VALUES (?,?,?) ON CONFLICT(user_id) '
                       'DO UPDATE SET reasoning_effort=excluded.reasoning_effort,updated=excluded.updated',
                       (user_id, effort, self.accounts.clock()))
            return self._summary(db, user_id)

    def research_demand(self):
        """Union watched sectors for active users; selecting never starts I/O."""
        demand = {effort:set() for effort in CREDIT_COSTS}
        with self.accounts.connection() as db:
            rows = db.execute('SELECT u.id,u.watchlist,p.reasoning_effort FROM users u '
                'JOIN ai_research_preferences p ON p.user_id=u.id WHERE u.disabled=0').fetchall()
            for row in rows:
                summary = self._summary(db, row['id'])
                effort = row['reasoning_effort']
                if summary['status'] != 'admin' and (not summary['can_unlock'] or
                        summary['credits_remaining'] < CREDIT_COSTS[effort]):
                    continue
                try:
                    ids = json.loads(row['watchlist'])
                except (ValueError, TypeError):
                    continue
                if isinstance(ids, list):
                    demand[effort].update(value for value in ids if isinstance(value, str))
        return demand

    def ledger(self, user_id):
        with self.accounts.connection() as db:
            self._summary(db, user_id)
            rows = db.execute('SELECT kind,delta,balance,note,created FROM ai_subscription_ledger '
                'WHERE user_id=? ORDER BY created DESC,rowid DESC LIMIT 30', (user_id,)).fetchall()
        return [{**dict(row), 'delta':_points(row['delta']), 'balance':_points(row['balance']),
                 'credit_unit':'点', 'created_at':iso(row['created'])} for row in rows]

    def manage(self, actor_id, user_id, action, request_id, credits=0, days=0, note='',
               daily_limit=None, monthly_limit=None):
        if (not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id)
                or action not in ('grant', 'pause', 'resume', 'limits') or not isinstance(user_id, str)
                or not isinstance(note, str) or len(note) > 200):
            raise AccountError('订阅操作参数无效')
        if action == 'limits':
            return self._set_limits(actor_id, user_id, request_id, daily_limit, monthly_limit, note)
        grant_units = _grant_half_units(credits)
        if type(days) is not int or not 0 <= days <= 3660:
            raise AccountError('有效期需为 0～3660 天的整数')
        if action == 'grant' and credits == days == 0:
            raise AccountError('请填写新增额度或延长天数')
        now = self.accounts.clock()
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = db.execute('SELECT role,disabled FROM users WHERE id=?', (actor_id,)).fetchone()
            if not actor or actor['role'] != 'admin' or actor['disabled']:
                raise AccountError('仅管理员可分配研究额度', 403)
            target = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
            if not target or target['role'] != 'member':
                raise AccountError('请选择普通用户账号', 404)
            previous = db.execute('SELECT user_id FROM ai_subscription_ledger WHERE actor_id=? AND request_id=?',
                                  (actor_id, request_id)).fetchone()
            if previous:
                if previous['user_id'] != user_id:
                    raise AccountError('操作编号已使用，请刷新后重新操作', 409)
                return self._summary(db, user_id)
            row = db.execute('SELECT * FROM ai_subscriptions WHERE user_id=?', (user_id,)).fetchone()
            balance, expires = (row['credits'], row['expires']) if row else (0, 0)
            if action == 'grant':
                balance += grant_units
                if balance > 2000000:
                    raise AccountError('账号剩余额度不能超过 1000000 点')
                expires = max(now, expires) + days * 86400 if days else expires
                if expires <= now or not math.isfinite(expires):
                    raise AccountError('账号尚未开通或已到期，请同时填写延长天数')
                enabled = 1
            else:
                if not row:
                    raise AccountError('该账号尚未开通服务')
                enabled = int(action == 'resume')
            db.execute('INSERT INTO ai_subscriptions VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET '
                'enabled=excluded.enabled,credits=excluded.credits,expires=excluded.expires,updated=excluded.updated',
                (user_id, enabled, balance, expires, now))
            db.execute('INSERT INTO ai_subscription_ledger VALUES (?,?,?,?,?,?,?,?,?,?)',
                (secrets.token_hex(16), user_id, actor_id, action, grant_units if action == 'grant' else 0,
                 balance, expires, note, now, request_id))
            return self._summary(db, user_id)

    def _set_limits(self, actor_id, user_id, request_id, daily_limit, monthly_limit, note):
        daily = _limit(daily_limit, MAX_DAILY_CALLS, '每日调用次数')
        monthly = _limit(monthly_limit, MAX_MONTHLY_CALLS, '每月调用总次数')
        if monthly < daily:
            raise AccountError('每月调用总次数不能少于每日调用次数')
        now = self.accounts.clock()
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            actor = db.execute('SELECT role,disabled FROM users WHERE id=?', (actor_id,)).fetchone()
            if not actor or actor['role'] != 'admin' or actor['disabled']:
                raise AccountError('仅管理员可设置调用次数', 403)
            target = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
            if not target or target['role'] != 'member':
                raise AccountError('请选择普通用户账号', 404)
            previous = db.execute('SELECT user_id FROM ai_subscription_ledger WHERE actor_id=? AND request_id=?',
                                  (actor_id, request_id)).fetchone()
            if previous:
                if previous['user_id'] != user_id:
                    raise AccountError('操作编号已使用，请刷新后重新操作', 409)
                return self._summary(db, user_id)
            db.execute('INSERT INTO ai_call_limits VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET '
                       'daily_limit=excluded.daily_limit,monthly_limit=excluded.monthly_limit,updated=excluded.updated',
                       (user_id, daily, monthly, now))
            row = db.execute('SELECT credits,expires FROM ai_subscriptions WHERE user_id=?', (user_id,)).fetchone()
            balance, expires = (row['credits'], row['expires']) if row else (0, 0)
            # The audit trail records the change; credits and expiry are untouched.
            db.execute('INSERT INTO ai_subscription_ledger VALUES (?,?,?,?,?,?,?,?,?,?)',
                (secrets.token_hex(16), user_id, actor_id, 'limits', 0, balance, expires,
                 (note + '；' if note else '') + f'每日 {daily} 次 · 每月 {monthly} 次', now, request_id))
            return self._summary(db, user_id)

    def unlock(self, user_id, report, sector_id, expected_content):
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._unlock(db, user_id, report, sector_id, expected_content)

    def _unlock(self, db, user_id, report, sector_id, expected_content,
                reasoning_effort=None, reservation_id=None):
        # The manual worker also commits its result and released reservation
        # in this transaction; an interrupted HTTP response cannot double debit.
        source = next((s for s in report.get('sector_analysis', []) if s.get('id') == sector_id), None)
        now = self.accounts.clock()
        summary = self._summary(db, user_id)
        sector = select_interpretation(source, reasoning_effort or summary['preferred_reasoning_effort']) if source else None
        identity = content_identity(sector)
        # Legacy interpretations retain their old access/price; they are
        # explicitly labelled legacy, never advertised as a new effort.
        if not identity and source and interpretation_price(source)['pricing_legacy']:
            sector = {k:v for k,v in source.items() if k != 'ai_variants'}
            identity = content_identity(sector)
        if not identity:
            raise AccountError('所选推理档位尚无有效解读，请点击推理生成后再查看，未扣减额度', 409)
        if expected_content != identity:
            raise AccountError('报告或推理档位已更新，请重新确认，未扣减额度', 409)
        pricing = interpretation_price(sector)
        cost_units = int(pricing['cost'] * 2)
        if summary['status'] == 'admin':
            return {'charged':False, 'charged_cost':0, 'subscription':summary}
        if summary['status'] == 'paused':
            raise AccountError('AI 服务已暂停，请联系客服', 403)
        existing = db.execute('SELECT 1 FROM ai_unlocks WHERE user_id=? AND content_id=?', (user_id, identity)).fetchone()
        if existing:
            return {'charged':False, 'charged_cost':0, 'subscription':summary}
        if not summary['can_unlock']:
            raise AccountError(summary['label'] + '，请联系管理员订阅或续订，未扣减额度', 403)
        row = db.execute('SELECT credits,expires FROM ai_subscriptions WHERE user_id=?', (user_id,)).fetchone()
        held = db.execute("SELECT coalesce(sum(reserved_units),0) FROM ai_manual_jobs WHERE user_id=? AND status='running' AND id!=?", (user_id, reservation_id or '')).fetchone()[0]
        if row['credits'] - held < cost_units:
            raise AccountError('当前余额 ' + str(_points(row['credits'])) + ' 点，本份解读需 '
                               + str(pricing['cost']) + ' 点，未扣减额度', 403)
        balance = row['credits'] - cost_units
        db.execute('UPDATE ai_subscriptions SET credits=?,updated=? WHERE user_id=?', (balance, now, user_id))
        db.execute('INSERT INTO ai_unlocks VALUES (?,?,?,?,?)',
            (user_id, identity, sector_id, str(report.get('as_of') or '')[:64], now))
        db.execute('INSERT INTO ai_subscription_ledger VALUES (?,?,?,?,?,?,?,?,?,?)',
            (secrets.token_hex(16), user_id, user_id, 'unlock', -cost_units, balance, row['expires'],
             '解锁板块 AI 解读：' + str(sector.get('title') or sector_id)[:80] +
             (' · 中度推理' if pricing['reasoning_effort']=='medium' else ' · 极高推理' if pricing['reasoning_effort']=='xhigh' else ' · 旧版'), now, 'unlock-' + identity))
        return {'charged':True, 'charged_cost':pricing['cost'], 'subscription':self._summary(db, user_id)}

    def project_report(self, report, user_id, reasoning_effort=None):
        """Filter before HTTP serialization; never modify the shared report/cache."""
        if not isinstance(report, dict):
            return report
        with self.accounts.connection() as db:
            summary = self._summary(db, user_id)
            if summary['status'] == 'admin' and not summary['preferred_reasoning_effort'] and not reasoning_effort:
                return report
            unlocked = {row[0] for row in db.execute('SELECT content_id FROM ai_unlocks WHERE user_id=?', (user_id,))}
        output = dict(report)
        output['sector_analysis'] = []
        for source in report.get('sector_analysis', []):
            selected = reasoning_effort or summary['preferred_reasoning_effort']
            sector = select_interpretation(source, selected)
            available = [effort for effort in CREDIT_COSTS if content_identity(select_interpretation(source, effort))]
            pending = selected is not None and not content_identity(sector)
            if pending and interpretation_price(source)['pricing_legacy'] and content_identity(source):
                sector = {k:v for k,v in source.items() if k != 'ai_variants'}
            identity = content_identity(sector)
            if identity:
                pricing = interpretation_price(sector)
                allowed = summary['status']=='admin' or identity in unlocked and summary['status'] != 'paused'
                if not allowed:
                    sector = without_narrative(sector)
                sector['ai_access'] = {'status':'unlocked' if allowed else 'locked',
                    'content_id':identity, **pricing,
                    'can_unlock':summary['can_unlock'] and (summary['status']=='admin' or summary['credits_remaining'] >= pricing['cost']),
                    'preferred_reasoning_effort':selected, 'preference_pending':pending, 'available_efforts':available,
                    'subscription_status':summary['status']}
            elif selected or any(k.startswith('ai_') for k in source):
                sector = without_narrative(sector)
                sector['ai_access'] = {'status':'not_ready', 'cost':0, 'preferred_reasoning_effort':selected,
                    'preference_pending':pending, 'available_efforts':available}
            output['sector_analysis'].append(sector)
        return output
