"""Explicit account-owned sector AI jobs with durable, atomic credit settlement.

Only POST admission starts a worker. Polling, report projection, preferences and
watchlist changes never request a model. Public scheduled AI uses its own runner.
"""
import copy
import hashlib
import json
import secrets
import threading
from contextlib import nullcontext

from research_accounts import AccountError
from research_ai_cache import semantic_fingerprint
from research_responses import cache_identity, is_responses
from research_sector_ai import SYSTEM, _batch_evidence, _eligible, _enrich_sector_report, _sources, has_detailed_advice
from research_subscriptions import CREDIT_COSTS, NARRATIVE_FIELDS, content_identity, select_interpretation


def configuration_identity(config):
    # Never persist the provider credential or endpoint in the account database.
    material = [config.get('model'), config.get('responses_base_url'),
                config.get('revision', config.get('generation')),
                bool(config.get('requested_enabled',config.get('enabled'))),
                hashlib.sha256(str(config.get('key') or '').encode()).hexdigest()]
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class ManualSectorResearch:
    def __init__(self, accounts, engine_provider, config_provider, requester=None, connection_checker=None,
                 configuration_lock=None):
        self.accounts, self.subscriptions = accounts, accounts.subscriptions
        self.engine_provider, self.config_provider, self.requester = engine_provider, config_provider, requester
        self.connection_checker = connection_checker
        self.configuration_lock = (configuration_lock if configuration_lock is not None else
                                   getattr(getattr(config_provider,'__self__',None),'_lock',None))
        self._lock, self._active_keys, self._workers = threading.Lock(), set(), set()
        # A single server process owns these jobs. A restart releases reservations;
        # committed results/unlocks survive and are reused by the next click.
        with accounts.connection() as db:
            db.execute("UPDATE ai_manual_jobs SET status='failed',reserved_units=0,updated=?,"
                       "error='服务已重启，请重新点击推理；已完成的解读不会重复扣点。' WHERE status='running'",
                       (accounts.clock(),))

    def overlay(self, report, historical=False, user_id=None):
        if not isinstance(report, dict) or not isinstance(report.get('as_of'), str):
            return report
        snapshot = historical and report.get('_personal_record_snapshot') is True
        if '_personal_record_snapshot' in report:
            report = {key:value for key,value in report.items() if key!='_personal_record_snapshot'}
        config = self.config_provider()
        signature = configuration_identity(config)
        with self.accounts.connection() as db:
            rows = db.execute('SELECT sector_id,reasoning_effort,narrative,configuration FROM ai_manual_narratives '
                              'WHERE report_id=? ORDER BY updated', (report['as_of'],)).fetchall()
            user = db.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone() if historical and user_id else None
            owned = {row['content_id'] for row in db.execute('SELECT content_id FROM ai_unlocks WHERE user_id=?',
                                                            (user_id,))} if user and user['role']!='admin' else set()
        if not rows:
            return report
        output = copy.deepcopy(report)
        by_id = {row.get('id'):row for row in output.get('sector_analysis', [])}
        personal = historical and user is not None and user['role']!='admin'
        frozen = historical and snapshot and user is not None and user['role']=='admin'
        # The personal snapshot is the exact paid completion. It wins over a
        # newer shared narrative generated under somebody else's configuration.
        pinned = {(sector['id'],effort) for sector in output.get('sector_analysis',[]) for effort in CREDIT_COSTS
                  if (personal and content_identity(select_interpretation(sector,effort)) in owned)
                  or (frozen and content_identity(select_interpretation(sector,effort)))}
        priorities = {}
        for saved in rows:
            if not historical and saved['configuration'] != signature:
                continue
            sector = by_id.get(saved['sector_id'])
            if sector is None:
                continue
            narrative = json.loads(saved['narrative'])
            evidence_key = narrative.pop('_evidence_key',None)
            historical_key = narrative.pop('_historical_evidence_key',None)
            evidence, _ = _batch_evidence(report,[saved['sector_id']])
            if historical_key and historical_key != semantic_fingerprint('historical-sector-evidence','',evidence):
                continue
            if not historical:
                current_key = semantic_fingerprint(cache_identity({**config,'reasoning_effort':saved['reasoning_effort']}), SYSTEM,evidence)
                if evidence_key != current_key:
                    continue
            identity = content_identity({**narrative, 'id':sector['id']})
            if not identity:
                continue
            choice=(saved['sector_id'],saved['reasoning_effort'])
            if choice in pinned:
                continue
            if personal:
                priority=2 if identity in owned else 1
                if priority < priorities.get(choice,0):
                    continue
                priorities[choice]=priority
            if sector.get('ai_reasoning_effort') == saved['reasoning_effort']:
                for key in NARRATIVE_FIELDS:
                    sector.pop(key, None)
                sector.update(narrative)
            else:
                sector.setdefault('ai_variants', {})[saved['reasoning_effort']] = narrative
        return output

    @staticmethod
    def _validate(sector_id, report_id, effort):
        if (not isinstance(sector_id, str) or not 1 <= len(sector_id) <= 100
                or not isinstance(report_id, str) or not 1 <= len(report_id) <= 64
                or not isinstance(effort, str) or effort not in CREDIT_COSTS):
            raise AccountError('请提供当前板块、报告版本及中度或极高推理')

    def _reserve(self, user_id, report_id, sector_id, effort, identity):
        now = self.accounts.clock()
        with self.accounts.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT disabled FROM users WHERE id=?', (user_id,)).fetchone()
            if not user or user['disabled']:
                raise AccountError('账号不可用', 403)
            active = db.execute("SELECT * FROM ai_manual_jobs WHERE user_id=? AND status='running' ORDER BY created DESC LIMIT 1",
                                (user_id,)).fetchone()
            if active:
                if (active['report_id'],active['sector_id'],active['reasoning_effort']) == (report_id,sector_id,effort):
                    return active['id'], False
                raise AccountError('已有一份 AI 推理正在生成，请完成后再发起下一份', 409)
            summary = self.subscriptions._summary(db, user_id)
            already = identity and db.execute('SELECT 1 FROM ai_unlocks WHERE user_id=? AND content_id=?',
                                              (user_id, identity)).fetchone()
            free = summary['status'] == 'admin' or already and summary['status'] != 'paused'
            units = 0 if free else int(CREDIT_COSTS[effort] * 2)
            if not free and (not summary['can_unlock'] or summary['credits_remaining'] < CREDIT_COSTS[effort]):
                raise AccountError('订阅未开通、已暂停、已到期或研究点数不足，未扣减额度', 403)
            db.execute('INSERT INTO ai_research_preferences VALUES (?,?,?) ON CONFLICT(user_id) '
                       'DO UPDATE SET reasoning_effort=excluded.reasoning_effort,updated=excluded.updated',
                       (user_id,effort,now))
            job_id = secrets.token_hex(16)
            db.execute('INSERT INTO ai_manual_jobs(id,user_id,report_id,sector_id,reasoning_effort,status,reserved_units,created,updated) '
                       "VALUES (?,?,?,?,?,'running',?,?,?)", (job_id,user_id,report_id,sector_id,effort,units,now,now))
            db.execute("DELETE FROM ai_manual_jobs WHERE status!='running' AND updated<?", (now-7*86400,))
            # Personal historical reports still need their generated text after
            # the short-lived polling jobs expire. Follow report retention.
            db.execute('DELETE FROM ai_manual_narratives WHERE updated<? AND report_id NOT IN (SELECT id FROM reports)',
                       (now-7*86400,))
            return job_id, True

    def start(self, user_id, sector_id, report_id, effort):
        self._validate(sector_id, report_id, effort)
        engine, config = self.engine_provider(), dict(self.config_provider() or {})
        state = engine.status(include_report=True)
        report = state.get('report')
        if (not isinstance(report, dict) or report.get('as_of') != report_id
                or state.get('report_stale') or report.get('report_stale')
                or report.get('research_scope') != 'sectors'):
            raise AccountError('研究报告已更新或过期，请刷新后重新点击推理，未扣减额度', 409)
        report = self.overlay(report)
        source = next((row for row in report.get('sector_analysis', []) if row.get('id') == sector_id), None)
        if source is None:
            raise AccountError('当前报告中没有此板块', 404)
        if (not config.get('key') or not config.get('requested_enabled',config.get('enabled'))
                or not is_responses(config) or not config.get('enabled') and self.connection_checker is None):
            raise AccountError('AI 服务暂未就绪，请联系管理员检查模型连接，未扣减额度', 503)
        signature = configuration_identity(config)
        selected = select_interpretation(source, effort)
        identity = content_identity(selected)
        if identity and not has_detailed_advice(selected,report):
            identity = None
        shared_meta = report.get('ai_research') or {}
        # A current public interpretation at this actual level can be unlocked
        # immediately. An old configuration cannot authorize new paid access.
        if identity and (shared_meta.get('status') == 'stale'
                or shared_meta.get('revision') not in (None, config.get('revision', config.get('generation')))):
            identity = None
        if not _eligible(source, _sources(report)):
            raise AccountError('本板块尚缺有效行情或公司证据，暂不能生成可靠解读，未扣减额度', 409)
        evidence, _ = _batch_evidence(report, [sector_id])
        key = semantic_fingerprint(cache_identity({**config,'reasoning_effort':effort}), SYSTEM, evidence)
        with self._lock:
            # Same-account retries find their existing job even while that exact
            # evidence is being processed. Different jobs never send it twice.
            with self.accounts.connection() as db:
                active = db.execute("SELECT id FROM ai_manual_jobs WHERE user_id=? AND report_id=? AND sector_id=? AND reasoning_effort=? AND status='running'",
                                    (user_id,report_id,sector_id,effort)).fetchone()
            if active:
                return self.status(user_id, active['id'])
            if key in self._active_keys:
                raise AccountError('相同证据和推理档位正在生成，请稍后再点击；未扣减额度', 409)
            if len(self._workers) >= 2:
                raise AccountError('AI 推理服务繁忙，请稍后再试；未扣减额度', 429)
            job_id, fresh = self._reserve(user_id, report_id, sector_id, effort, identity)
            if not fresh:
                return self.status(user_id, job_id)
            self._phase(job_id,'researching' if config.get('enabled') else 'connecting')
            self._active_keys.add(key)
            worker = threading.Thread(target=self._run,
                args=(job_id,user_id,report,sector_id,effort,config,signature,key,selected if identity else None),
                name='manual-sector-ai', daemon=True)
            self._workers.add(worker)
            try:
                worker.start()
            except Exception:
                self._workers.discard(worker); self._active_keys.discard(key)
                self._fail(job_id, '推理任务未能启动，请稍后重试；未扣减额度')
                raise AccountError('推理任务未能启动，请稍后重试；未扣减额度', 503)
        return self.status(user_id, job_id)

    def _evidence_current(self, report_id, sector_id, effort, key, config):
        """Check the published report, not the worker's original snapshot.

        An as_of match alone is insufficient: a scan can replace evidence under
        the same report ID, and freshness is carried by the engine's status.
        """
        state = self.engine_provider().status(include_report=True)
        report = state.get('report')
        if (not isinstance(report, dict) or report.get('as_of') != report_id
                or state.get('report_stale') or report.get('report_stale')
                or report.get('research_scope') != 'sectors'):
            return False
        source = next((row for row in report.get('sector_analysis', []) if row.get('id') == sector_id), None)
        if not _eligible(source, _sources(report)):
            return False
        evidence, _ = _batch_evidence(report, [sector_id])
        current_key = semantic_fingerprint(cache_identity({**config,'reasoning_effort':effort}), SYSTEM, evidence)
        return current_key == key

    def _current(self, user_id, signature, report_id, sector_id, effort, key, *, require_ready=True):
        config = self.config_provider()
        if (not config.get('requested_enabled',config.get('enabled'))
                or require_ready and not config.get('enabled') or configuration_identity(config) != signature):
            return False
        if not self._evidence_current(report_id, sector_id, effort, key, config):
            return False
        with self.accounts.connection() as db:
            user = db.execute('SELECT disabled FROM users WHERE id=?', (user_id,)).fetchone()
            summary = self.subscriptions._summary(db, user_id)
        return bool(user and not user['disabled'] and (summary['status']=='admin'
                    or summary['status']=='active' and summary['credits_remaining'] >= CREDIT_COSTS[effort]))

    def _run(self, job_id, user_id, report, sector_id, effort, config, signature, key, existing):
        try:
            engine = self.engine_provider()
            current = lambda:self._current(user_id,signature,report['as_of'],sector_id,effort,key)
            admitted = lambda:self._current(user_id,signature,report['as_of'],sector_id,effort,key,require_ready=False)
            if not admitted():
                raise AccountError('账号、模型设置或板块证据已变化，请刷新后重新推理；本次未扣减额度', 409)
            if not config.get('enabled'):
                if self.connection_checker is None:
                    raise AccountError('AI 服务暂未就绪，请联系管理员检查模型连接；本次未扣减额度', 503)
                self._phase(job_id,'connecting')
                try:
                    config = dict(self.connection_checker(config.get('revision',config.get('generation')), admitted))
                except RuntimeError as error:
                    raise AccountError(str(error)+'；本次未扣减额度',503) from None
            self._phase(job_id,'researching')
            if not current():
                raise AccountError('账号、模型设置或板块证据已变化，请刷新后重新推理；本次未扣减额度', 409)
            reused = existing is not None
            if existing is None:
                targeted = copy.deepcopy(report)
                targeted['sector_analysis'] = [row for row in targeted['sector_analysis'] if row['id'] == sector_id]
                settings = {**config, 'reasoning_effort':effort,
                    '_cost_guard':getattr(engine, '_ai_cost_guard', None),
                    '_evidence_cache':getattr(engine, '_ai_evidence_cache', None),
                    '_cost_config_provider':lambda:{**self.config_provider(), 'reasoning_effort':effort},
                    '_require_detailed_advice':True}
                result = _enrich_sector_report(targeted, config=settings, requester=self.requester,
                    is_current=current, can_start_request=current)
                existing = next((row for row in result.get('sector_analysis', [])
                                 if row.get('id') == sector_id and content_identity(row)
                                 and row.get('ai_reasoning_effort') == effort), None)
                if existing is None:
                    if not current():
                        raise AccountError('账号、模型设置或板块证据已变化，请刷新后重新推理；本次未扣减额度', 409)
                    raise AccountError(result.get('ai_research',{}).get('error') or
                                       '未取得有效 AI 解读，请稍后重试；未扣减额度', 503)
                reused = bool(existing.get('ai_reused'))
            narrative = {key:copy.deepcopy(existing[key]) for key in NARRATIVE_FIELDS if key in existing}
            narrative['_evidence_key'] = key
            evidence,_ = _batch_evidence(report,[sector_id])
            narrative['_historical_evidence_key'] = semantic_fingerprint('historical-sector-evidence','',evidence)
            if (existing.get('ai_reasoning_effort') != effort or not content_identity(existing)
                    or not has_detailed_advice(existing,report)):
                raise AccountError('未取得所选档位的有效解读，未扣减额度', 409)
            # The narrative, debit, unlock and completed job are one SQLite
            # transaction. A page reload or a lost response cannot charge twice.
            now = self.accounts.clock()
            # Coordinate with the engine's report publication lock so a scan
            # cannot replace valid evidence between this check and the debit.
            publication_lock = getattr(engine,'_lock',None)
            publication_guard = publication_lock if hasattr(publication_lock,'__enter__') else nullcontext()
            configuration_guard = self.configuration_lock if self.configuration_lock is not None else nullcontext()
            # Engine internals also acquire their publication lock before
            # reading the configuration. Commit before releasing either guard.
            with publication_guard, configuration_guard, self.accounts.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                user = db.execute('SELECT disabled FROM users WHERE id=?', (user_id,)).fetchone()
                current_config = self.config_provider()
                if (not user or user['disabled'] or not current_config.get('enabled')
                        or configuration_identity(current_config) != signature):
                    raise AccountError('账号或模型设置已变化，结果未扣减额度，请刷新后重试', 409)
                if not self._evidence_current(report['as_of'],sector_id,effort,key,current_config):
                    raise AccountError('研究报告或板块证据已更新，请刷新后重新推理；本次未扣减额度', 409)
                generated_report = {**report, 'sector_analysis':[existing]}
                settled = self.subscriptions._unlock(db,user_id,generated_report,sector_id,content_identity(existing),
                                                     reasoning_effort=effort,reservation_id=job_id)
                db.execute('INSERT OR REPLACE INTO ai_manual_narratives VALUES (?,?,?,?,?,?)',
                           (report['as_of'],sector_id,effort,signature,json.dumps(narrative,ensure_ascii=False),now))
                saved_report=copy.deepcopy(report)
                saved_sector=next(row for row in saved_report['sector_analysis'] if row['id']==sector_id)
                if saved_sector.get('ai_reasoning_effort') == effort:
                    for field in NARRATIVE_FIELDS:saved_sector.pop(field,None)
                    saved_sector.update({field:copy.deepcopy(existing[field]) for field in NARRATIVE_FIELDS if field in existing})
                else:
                    saved_sector.setdefault('ai_variants',{})[effort]={
                        field:copy.deepcopy(existing[field]) for field in NARRATIVE_FIELDS if field in existing}
                self.accounts._remember_report(db,user_id,saved_report)
                value = {**settled, 'status':'completed', 'job_id':job_id, 'sector_id':sector_id,
                         'reasoning_effort':effort, 'sector':select_interpretation(existing,effort),
                         'report_id':report['as_of'], 'reused':reused,
                         'saved':True,
                         '_configuration':signature, '_evidence_key':key}
                value.pop('subscription',None)
                db.execute("UPDATE ai_manual_jobs SET status='completed',reserved_units=0,result=?,updated=?,error='' WHERE id=?",
                           (json.dumps(value,ensure_ascii=False,allow_nan=False),now,job_id))
        except AccountError as error:
            self._fail(job_id, str(error))
        except Exception:
            self._fail(job_id, 'AI 推理服务暂时不可用，请稍后重试；未扣减额度')
        finally:
            with self._lock:
                self._active_keys.discard(key)
                self._workers.discard(threading.current_thread())

    def _fail(self, job_id, message):
        with self.accounts.connection() as db:
            db.execute("UPDATE ai_manual_jobs SET status='failed',reserved_units=0,error=?,updated=? WHERE id=? AND status='running'",
                       (str(message)[:500],self.accounts.clock(),job_id))

    def _phase(self, job_id, phase):
        with self.accounts.connection() as db:
            db.execute("UPDATE ai_manual_jobs SET result=?,updated=? WHERE id=? AND status='running'",
                       (json.dumps({'phase':phase}),self.accounts.clock(),job_id))

    def status(self, user_id, job_id):
        if not isinstance(job_id,str) or len(job_id) != 32:
            raise AccountError('推理任务不存在', 404)
        with self.accounts.connection() as db:
            row = db.execute('SELECT * FROM ai_manual_jobs WHERE id=? AND user_id=?', (job_id,user_id)).fetchone()
        if row is None:
            raise AccountError('推理任务不存在', 404)
        value = {'job_id':job_id,'status':row['status'],'sector_id':row['sector_id'],
                 'report_id':row['report_id'],'reasoning_effort':row['reasoning_effort'],
                 'charged':False,'charged_cost':0}
        if row['status']=='running':
            value['phase'] = json.loads(row['result']).get('phase','researching')
        if row['status'] == 'completed':
            value.update(json.loads(row['result']))
            signature, key = value.pop('_configuration',None), value.pop('_evidence_key',None)
            config = self.config_provider()
            valid = (config.get('enabled') and signature == configuration_identity(config)
                     and self._evidence_current(row['report_id'],row['sector_id'],row['reasoning_effort'],key,config))
            value.update(stale=not valid, applicable=bool(valid))
            if valid:
                projected = self.subscriptions.project_report({'as_of':row['report_id'],
                    'sector_analysis':[value['sector']]}, user_id, reasoning_effort=row['reasoning_effort'])
                value['sector'] = projected['sector_analysis'][0]
            else:
                # Preserve the committed payment facts, but an old completion
                # must not reinstall expired text into the current report.
                value.pop('sector',None)
                value['stale_reason'] = '此任务已完成，但报告、证据或模型设置已更新；请刷新当前研究后重新推理。'
        elif row['status'] == 'failed':
            value['error'] = row['error']
        value['subscription'] = self.subscriptions.summary(user_id)
        return value

    def pending(self, user_id):
        with self.accounts.connection() as db:
            rows = db.execute("SELECT id FROM ai_manual_jobs WHERE user_id=? AND status='running' ORDER BY created DESC LIMIT 2",(user_id,)).fetchall()
        return {'jobs':[self.status(user_id,row['id']) for row in rows]}
