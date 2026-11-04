import json
import tempfile
import unittest
from pathlib import Path

from research_data_config import DataConfigStore

TOKEN = 'offline-tushare-secret-token-5a91'


def crypt(value):
    return bytes(byte ^ 0xA5 for byte in value)


def probe(_):
    return {'capabilities': {name: {'status': 'available', 'count': 1, 'message': 'ok'}
                             for name in ('daily', 'daily_basic', 'index_classify', 'index_member_all', 'fina_indicator', 'trade_cal')}}


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'private' / 'tushare.json'

    def store(self, **options):
        return DataConfigStore(self.path, encrypt=crypt, decrypt=crypt, probe=options.get('probe', probe))

    def test_token_encrypted_and_public_status_detached_and_nonsecret(self):
        store = self.store()
        store.configure(TOKEN)
        status = store.verify()
        self.assertEqual(status['verification'], 'verified')
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertNotIn(TOKEN.encode(), self.path.read_bytes())
        self.assertNotIn('token', json.loads(self.path.read_text(encoding='utf-8')))
        self.assertEqual(status, self.store().status())
        self.assertEqual(store.snapshot()['token'], TOKEN)
        status['capabilities'].clear()
        self.assertEqual(len(store.status()['capabilities']), 6)

    def test_blank_preserves_and_changed_token_invalidates(self):
        store = self.store()
        store.configure(TOKEN)
        previous = store.verify()
        self.assertEqual(store.configure(''), previous)
        self.assertEqual(store.configure(), previous)
        self.assertEqual(store.configure(TOKEN + '-new')['verification'], 'unverified')
        self.assertEqual(store.status()['capabilities'], {})

    def test_probe_error_or_payload_cannot_expose_arbitrary_secrets(self):
        def bad_probe(_):
            raise RuntimeError(TOKEN)
        store = self.store(probe=bad_probe)
        store.configure(TOKEN)
        result = store.verify()
        self.assertEqual(result['verification'], 'failed')
        self.assertNotIn(TOKEN, str(result))
        store._probe = lambda _: {'capabilities': {'daily': {'status': 'permission', 'count': 0, 'message': TOKEN}}}
        self.assertNotIn(TOKEN, str(store.verify()))

    def test_empty_success_does_not_grant_verified_status(self):
        store = self.store(probe=lambda _: {'capabilities': {'daily': {'status': 'empty', 'count': 0}}})
        store.configure(TOKEN)
        self.assertEqual(store.verify()['verification'], 'failed')

    def test_delayed_verification_cannot_validate_replaced_token(self):
        store = self.store()
        store.configure(TOKEN)
        def replace(_):
            store.configure(TOKEN + '-replacement')
            return probe(None)
        store._probe = replace
        self.assertEqual(store.verify()['verification'], 'unverified')
        self.assertEqual(store.snapshot()['token'], TOKEN + '-replacement')

    def test_clear_and_corrupted_storage_do_not_restore_plaintext(self):
        store = self.store()
        store.configure(TOKEN)
        store.clear()
        self.assertFalse(self.path.exists())
        self.path.write_text(json.dumps({'version': 1, 'token': TOKEN}), encoding='utf-8')
        restored = self.store()
        self.assertFalse(restored.status()['configured'])
        self.assertNotIn(TOKEN, str(restored.status()))


if __name__ == '__main__':
    unittest.main()
