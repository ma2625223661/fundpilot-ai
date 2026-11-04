"""Production service exposes sectors and retires the fund endpoints."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import server


class SectorServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.root_patch = patch('server.ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        # Legacy collector/retired-endpoint contract; account boundary has its own HTTP tests.
        self.service = server.create_server(0, require_login=False)
        self.addCleanup(self.service.server_close)
        self.addCleanup(self.service.auto_engine.close)
        self.origin = f'http://127.0.0.1:{self.service.server_port}'
        threading.Thread(target=self.service.serve_forever, daemon=True).start()
        self.addCleanup(self.service.shutdown)

    def test_health_has_no_fund_defaults_and_engine_uses_sector_runners(self):
        with urllib.request.urlopen(self.origin + '/api/health') as response:
            value = json.load(response)
        self.assertEqual(value['research_scope'], 'sectors')
        self.assertEqual(value['defaults'], [])
        self.assertEqual(value['version'], 6)
        self.assertEqual(self.service.auto_engine.runner.__name__, 'run_sector_research')
        self.assertEqual(self.service.auto_engine.ai_runner.__name__, 'enrich_sector_report')
        self.assertEqual(self.service.auto_engine.state_path.name, 'sector-report.json')

    def test_fund_endpoints_are_gone_without_upstream_research(self):
        requests = [urllib.request.Request(self.origin + '/api/research?codes=000001'),
                    urllib.request.Request(self.origin + '/api/analyze', data=b'{"codes":["000001"]}',
                                            headers={'Origin': self.origin, 'Content-Type': 'application/json'})]
        with patch('server.run_research', side_effect=AssertionError('fund upstream')):
            for request in requests:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                with error.exception as response:
                    self.assertEqual(response.code, 410)
                    self.assertEqual(json.load(response)['research_scope'], 'sectors')

    def test_second_connection_is_independent_and_real_probe_runs_asynchronously(self):
        with patch('research_public_config.capability_snapshot', return_value={}):
            with urllib.request.urlopen(self.origin + '/api/data/config') as response:
                value = json.load(response)
            self.assertEqual(value['config']['provider'], 'baostock')
            self.assertEqual(value['supplemental']['provider'], 'public_multisource')
            self.assertNotEqual(value['supplemental']['verification'], 'verified')
            self.service.public_data_config._probe = lambda: {'verification': 'failed', 'error': 'offline'}
            req = urllib.request.Request(self.origin + '/api/data/public/test', data=b'{}',
                headers={'Origin': self.origin, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(json.load(response)['supplemental']['verification'], 'checking')
            self.service.public_data_config._worker.join(1)
            self.assertEqual(self.service.public_data_config.status()['verification'], 'failed')
            # Existing origin restrictions must also protect the new endpoint.
            req = urllib.request.Request(self.origin + '/api/data/public/test', data=b'{}')
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()

    def test_active_fund_state_is_archived_and_paid_schedule_preserved(self):
        (self.root / 'data').mkdir(exist_ok=True)
        (self.root / 'config').mkdir(exist_ok=True)
        old_report = self.root / 'data' / 'automatic-report.json'
        old_report.write_text('{"funds":["000001"]}', encoding='utf-8')
        old_schedule = self.root / 'data' / 'automatic-report.schedule.json'
        old_schedule.write_text('{"next_run_at":"2026-10-31T15:30:00+08:00"}', encoding='utf-8')
        members = self.root / 'config' / 'board-candidates.json'
        members.write_text('["000001"]', encoding='utf-8')
        credential = self.root / 'data' / 'deepseek-config.dpapi.json'
        credential.write_text('synthetic-encrypted-credential', encoding='utf-8')
        server.archive_legacy_fund_state(self.root)
        self.assertFalse(old_report.exists())
        self.assertFalse(old_schedule.exists())
        self.assertFalse(members.exists())
        self.assertIn('2026-10-31', (self.root / 'data' / 'sector-report.schedule.json').read_text())
        self.assertEqual(credential.read_text(), 'synthetic-encrypted-credential')
        self.assertEqual(len(list((self.root / 'backups').glob('*/automatic-report.json'))), 1)


if __name__ == '__main__':
    unittest.main()
