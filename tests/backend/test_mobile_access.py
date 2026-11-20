"""Phone admission must advertise usable LAN links without opening settings."""
import http.client
import json
import tempfile
import threading
import unittest
from functools import partial
from unittest.mock import patch

import server


class MobileAccessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.service = server.BoundedThreadingHTTPServer(
            ('127.0.0.1', 0), partial(server.Handler, directory=self.folder.name))
        self.host = f'127.0.0.1:{self.service.server_port}'
        self.service.allowed_hosts = {self.host}
        self.addCleanup(self.service.server_close)
        threading.Thread(target=self.service.serve_forever, daemon=True).start()
        self.addCleanup(self.service.shutdown)

    def get(self, path='/api/access', host=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.service.server_port, timeout=3)
        self.addCleanup(connection.close)
        headers = {'Host': host or self.host}
        if body is not None:
            headers['Origin'] = f'http://{host or self.host}'
            headers['Content-Type'] = 'application/json'
        connection.request('GET' if body is None else 'POST', path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_only_private_assigned_addresses_are_advertised(self):
        with patch('server.socket.gethostbyname_ex', return_value=('pc', [], [
                '10.0.0.5', '10.0.0.5', '192.168.1.2', '127.0.0.1', '0.0.0.0',
                '169.254.1.2', '8.8.8.8', '::1', 'invalid', '224.0.0.1'])):
            self.assertEqual(server.lan_addresses(), ['10.0.0.5', '192.168.1.2'])
        with patch('server.socket.gethostbyname_ex', side_effect=OSError('offline')):
            self.assertEqual(server.lan_addresses(), [])

    def test_access_returns_local_admission_and_no_credentials_or_side_effects(self):
        with patch('server.lan_addresses', return_value=['10.0.0.5']):
            status, value = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(value, {'can_manage_settings': True, 'scope': 'same_network', 'local_only': False,
            'lan_urls': [f'http://10.0.0.5:{self.service.server_port}/index.html']})

    def test_lan_can_read_entry_but_cannot_mutate_ai_or_data(self):
        with patch.object(server.Handler, 'local_client', return_value=False), patch('server.lan_addresses', return_value=[]):
            self.assertFalse(self.get()[1]['can_manage_settings'])
            for path in ('/api/ai/config', '/api/ai/test', '/api/data/config', '/api/data/public/test'):
                self.assertEqual(self.get(path, body='{}')[0], 403, path)

    def test_dhcp_change_is_accepted_only_for_an_actual_private_interface(self):
        with patch('server.lan_addresses', return_value=['10.0.0.8']):
            port = self.service.server_port
            self.assertEqual(self.get(host=f'10.0.0.8:{port}')[0], 200)
            self.assertEqual(self.get(host=f'10.0.0.9:{port}')[0], 403)
            self.assertEqual(self.get(host=f'evil.example:{port}')[0], 403)
            self.assertEqual(self.get(host=f'10.0.0.8.evil.example:{port}')[0], 403)


if __name__ == '__main__':
    unittest.main()
