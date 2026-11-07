"""Independent async status for the extra credential-free data connection."""
import threading

from research_data import now_iso
from research_public_data import capability_snapshot, probe_public_data
from research_sector_references import VERIFIED_REFERENCES
from research_bond_model import METHOD


class PublicDataConfigStore:
    def __init__(self, on_complete=None, probe=None):
        self._lock = threading.RLock()
        self._worker = None
        self._on_complete = on_complete
        self._probe = probe or probe_public_data
        self._state = {'verification': 'unverified', 'error': '', 'last_checked_at': None, 'capabilities': {}}

    def status(self):
        with self._lock:
            evidence = {**self._state['capabilities'], **capability_snapshot()}
            caps = [{'id': key, 'label': label, **evidence.get(key, {'status': 'unverified', 'count': 0})}
                for key, label in (('industry', '官方指数成分'), ('daily', '代表公司行情'), ('financial', '公司财务指标'))]
            # Mapping/model availability is not the same claim as live data.
            caps.extend([
                {'id': 'mapping', 'label': '官方指标映射配置', 'status': 'available',
                 'count': len(VERIFIED_REFERENCES), 'note': '逐项声明代码与范围；实际行情覆盖请看首页，不代表全部板块已取数'},
                {'id': 'bond_model', 'label': '独立债券趋势模型', 'status': 'available', 'count': 1,
                 'note': '全债与7–10年国债政金债共用债券专用模型；至少61个近期点才评分'},
                {'id': 'convertible_model', 'label': '独立可转债趋势模型', 'status': 'available', 'count': 1,
                 'note': '中证转债独立趋势模型；不套用普通债券模型。评级、转股溢价、到期收益率与赎回条款未接入，不计分'}])
            verification = self._state['verification']
            if verification != 'checking' and any(c['status'] == 'available' for c in caps[:3]):
                verification = 'verified' if all(c['status'] == 'available' for c in caps[:3]) else 'partial'
            return {**self._state, 'provider': 'public_multisource', 'verification': verification,
                    'configured': True, 'installed': True, 'capabilities': caps,
                    'scope': '公开多源连接；真实样本检查通过不代表101个板块全部覆盖'}

    def verify(self):
        with self._lock:
            if self._worker and self._worker.is_alive():
                return self.status()
            self._state.update(verification='checking', error='')
            def work():
                try:
                    outcome = self._probe()
                except Exception:
                    outcome = {'verification': 'failed', 'error': '备用数据检查失败，原连接保留'}
                with self._lock:
                    self._state.update(outcome, last_checked_at=now_iso())
                if outcome.get('verification') in {'verified', 'partial'} and self._on_complete:
                    self._on_complete()
            self._worker = threading.Thread(target=work, name='public-data-check', daemon=True)
            initial = self.status()
            self._worker.start()
            return initial
