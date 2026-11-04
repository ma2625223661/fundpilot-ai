"""Asynchronous health state for the optional, credential-free BaoStock API."""
from __future__ import annotations

import threading

from research_data import now_iso
from research_free_data import capability_snapshot, probe_baostock, provider_status


CAPABILITIES = (
    ('industry', '行业成分与行业标签'),
    ('daily', '代表公司日线行情'),
    ('financial', '公司财务指标'),
)


class FreeDataConfigStore:
    """Installation, connection and endpoint evidence are independent states."""

    def __init__(self, probe=None, on_complete=None):
        self._probe = probe or probe_baostock
        self._on_complete = on_complete
        self._lock = threading.RLock()
        self._worker = None
        self._generation = 0
        self._state = {'verification': 'unverified', 'last_verified_at': None,
                       'last_checked_at': None, 'error': '', 'capabilities': {}}

    def _base(self):
        with self._lock:
            installation = provider_status()
            installed = installation.get('status') == 'available'
            verification = self._state['verification'] if installed else 'not_installed'
            evidence = dict(self._state.get('capabilities', {}))
            for key, row in capability_snapshot().items():
                previous = evidence.get(key)
                if not previous or str(row.get('checked_at') or '') > str(previous.get('checked_at') or ''):
                    evidence[key] = row
            capabilities = []
            for key, label in CAPABILITIES:
                row = dict(evidence.get(key) or {})
                row.setdefault('status', 'unverified')
                row.setdefault('count', 0)
                row.setdefault('checked_at', None)
                row.setdefault('note', '未请求；板块研究时按需采集' if key != 'industry' else '尚未取得行业样本')
                if not installed:
                    row.update(status='not_installed', note='BaoStock 客户端未安装')
                elif row['status'] != 'available':
                    if verification == 'checking':
                        row.update(status='checking', note='正在独立检查本项接口的真实样本')
                    elif key == 'industry' and verification == 'timeout' and not row.get('checked_at'):
                        row.update(status='timeout', note='行业查询超时，可稍后重试')
                    elif key == 'industry' and verification == 'failed' and not row.get('checked_at'):
                        row.update(status='error', note='行业连接未通过，可稍后重试')
                capabilities.append({**row, 'id': key, 'label': label})
            industry_available = capabilities[0]['status'] == 'available'
            if verification == 'unverified' and industry_available:
                verification = 'partial'
            if verification in {'partial', 'verified'}:
                verification = 'verified' if all(r['status'] == 'available' for r in capabilities) else 'partial'
            message = {
                'verified': '行业成分、公司日线和财务接口的真实样本均已核验。',
                'partial': '部分接口已取得真实样本，请查看各项检查结果。',
                'checking': '正在分别核验行业成分、公司日线和财务接口。',
                'timeout': '本次连接检查超时，请查看各项接口原因与缓存日期。',
                'failed': '本次连接检查未通过，请查看各项接口原因。',
            }.get(verification, installation.get('message', ''))
            return {**installation, 'provider': 'baostock', 'status': verification,
                    'message': message,
                    'provider_status': installation.get('status'), 'installed': installed,
                    'configured': installed and industry_available, 'verification': verification,
                    'capabilities': capabilities,
                    'last_verified_at': self._state['last_verified_at'],
                    'last_checked_at': self._state['last_checked_at'],
                    'error': self._state['error']}

    def status(self):
        return self._base()

    def snapshot(self):
        return self._base()

    def configure(self, **_ignored):
        # No account, token, points or payment information needs persistence.
        return self._base()

    def verify(self):
        with self._lock:
            installation = provider_status()
            if installation.get('status') != 'available':
                self._state.update(verification='not_installed', error=installation.get('message', '未安装 BaoStock'))
                return self._base()
            if self._worker and self._worker.is_alive():
                return self._base()
            self._state.update(verification='checking', error='')
            generation = self._generation

            def work():
                try:
                    outcome = self._probe()
                except TimeoutError:
                    outcome = {'verification': 'timeout', 'error': 'BaoStock 查询超时；客户端已安装，可稍后重试'}
                except Exception:
                    outcome = {'verification': 'failed', 'error': 'BaoStock 数据连接检查失败，可稍后重试'}
                with self._lock:
                    if generation != self._generation:
                        return
                    verification = outcome.get('verification', 'failed')
                    if verification not in {'partial', 'verified', 'timeout', 'failed', 'not_installed', 'unverified'}:
                        verification = 'failed'
                    capabilities = outcome.get('capabilities') or {}
                    if isinstance(capabilities, list):
                        capabilities = {r['id']: r for r in capabilities if isinstance(r, dict) and r.get('id')}
                    self._state.update(verification=verification,
                                       error=str(outcome.get('error') or '')[:240],
                                       capabilities=capabilities if isinstance(capabilities, dict) else {},
                                       last_checked_at=now_iso())
                    if verification in {'partial', 'verified'}:
                        self._state['last_verified_at'] = now_iso()
                if verification in {'partial', 'verified'} and self._on_complete:
                    try:
                        self._on_complete()
                    except Exception:
                        # A refresh failure must not rewrite an actual successful
                        # provider response as a connection or install failure.
                        pass

            self._worker = threading.Thread(target=work, name='baostock-health-check', daemon=True)
            # Produce the initial response before the worker may finish, and never
            # wait for the public network from a request handler.
            response = self._base()
            self._worker.start()
            return response

    def clear(self):
        with self._lock:
            self._generation += 1
            self._state.update(verification='unverified', last_verified_at=None,
                               last_checked_at=None, error='', capabilities={})
            return self._base()


__all__ = ['FreeDataConfigStore']
