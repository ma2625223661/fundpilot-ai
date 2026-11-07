import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

import launch
from cloud_server import create_cloud_server
from research_frontend import LEGACY, LEGACY_PUBLIC, REACT, resolve_frontend
from server import ROOT
from test_cloud_accounts import PASSWORD, TEST_CAPTCHA, install_test_captcha

INDEX = '<!doctype html><html><head><script type="module" src="/index-AAA.js"></script></head><body></body></html>'
MANIFEST = {
    'index.html': {'file': 'index-AAA.js', 'src': 'index.html', 'isEntry': True,
                   'imports': ['_theme-CCC.js'], 'css': ['index-AAA.css']},
    'login.html': {'file': 'login-BBB.js', 'src': 'login.html', 'isEntry': True, 'imports': ['_theme-CCC.js']},
    '_theme-CCC.js': {'file': 'theme-CCC.js', 'css': ['theme-CCC.css'], 'imports': ['_vendor-DDD.js']},
    '_vendor-DDD.js': {'file': 'vendor-DDD.js'},
}


def build_react(root, manifest=MANIFEST):
    folder = Path(root) / 'web' / 'dist-react'
    (folder / '.vite').mkdir(parents=True)
    (folder / 'index.html').write_text(INDEX, encoding='utf-8')
    (folder / 'login.html').write_text('<!doctype html><title>login</title>' + 'x' * 100, encoding='utf-8')
    for name in ('index-AAA.js', 'index-AAA.css', 'login-BBB.js', 'theme-CCC.js', 'theme-CCC.css', 'vendor-DDD.js', 'qq-support.png'):
        (folder / name).write_text('/* ' + name + ' */', encoding='utf-8')
    (folder / '.vite' / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return folder


class ResolveFrontendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_legacy_stays_the_default_and_keeps_its_fixed_public_files(self):
        frontend = resolve_frontend(ROOT, {})
        self.assertEqual((frontend.kind, frontend.folder), (LEGACY, ROOT / 'dist'))
        self.assertEqual(frontend.public, LEGACY_PUBLIC)
        self.assertTrue(frontend.injects_cloud_scripts)
        self.assertIn('sector-research.js', frontend.assets)
        self.assertEqual(resolve_frontend(ROOT, {'FUNDPILOT_FRONTEND': ' Legacy '}).kind, LEGACY)

    def test_unknown_choice_and_missing_build_explain_the_fix(self):
        with self.assertRaisesRegex(RuntimeError, 'legacy 或 react'):
            resolve_frontend(self.root, {'FUNDPILOT_FRONTEND': 'vue'})
        with self.assertRaisesRegex(RuntimeError, 'npm run build'):
            resolve_frontend(self.root, {'FUNDPILOT_FRONTEND': 'react'})
        folder = build_react(self.root)
        (folder / '.vite' / 'manifest.json').write_text('not json', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, '构建清单'):
            resolve_frontend(self.root, {'FUNDPILOT_FRONTEND': 'react'})

    def test_login_page_and_everything_it_loads_are_public_but_the_main_page_is_not(self):
        frontend = resolve_frontend(build_react(self.root).parent.parent, {'FUNDPILOT_FRONTEND': 'react'})
        self.assertEqual(frontend.kind, REACT)
        self.assertFalse(frontend.injects_cloud_scripts)
        self.assertEqual(frontend.public, {'login.html', 'login-BBB.js', 'theme-CCC.js', 'theme-CCC.css',
                                           'vendor-DDD.js', 'qq-support.png'})
        self.assertNotIn('index-AAA.js', frontend.public)
        self.assertIn('index-AAA.js', frontend.assets)

    def test_home_screen_manifest_and_icons_are_public_assets(self):
        folder = build_react(self.root)
        for name in ('manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png', 'favicon.svg'):
            (folder / name).write_text('x', encoding='utf-8')
        frontend = resolve_frontend(self.root, {'FUNDPILOT_FRONTEND': 'react'})
        for name in ('manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png', 'favicon.svg'):
            self.assertIn(name, frontend.assets)
            self.assertIn(name, frontend.public)

    def test_manifest_without_a_login_entry_is_rejected(self):
        build_react(self.root, {'index.html': MANIFEST['index.html']})
        with self.assertRaisesRegex(RuntimeError, 'login.html'):
            resolve_frontend(self.root, {'FUNDPILOT_FRONTEND': 'react'})

    def test_hot_reload_notices_a_react_rebuild(self):
        build_react(self.root)
        before = launch.watched_files(self.root)
        self.assertIn('web/dist-react/index-AAA.js', before)
        folder = self.root / 'web' / 'dist-react'
        (folder / 'index-AAA.js').rename(folder / 'index-EEE.js')
        self.assertEqual(launch.changed_files(before, launch.watched_files(self.root)),
                         ['web/dist-react/index-AAA.js', 'web/dist-react/index-EEE.js'])


class ReactCloudHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / 'site'
        build_react(root)
        frontend = resolve_frontend(root, {'FUNDPILOT_FRONTEND': 'react'})
        self.server = create_cloud_server(port=0, state_dir=str(Path(self.tmp.name) / 'state'),
                                          development=True, environ={}, frontend=frontend)
        install_test_captcha(self.server)
        self.server.auto_engine = Mock()
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join()))
        self.origin = self.server.public_url

    def request(self, path, body=None, cookie=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {'Origin': self.origin}
        if cookie:
            headers['Cookie'] = cookie
        if body is not None:
            headers['Content-Type'] = 'application/json'
        connection.request('POST' if body is not None else 'GET', path,
                           body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def sign_in(self):
        challenge = json.loads(self.request('/api/auth/captcha')[1])
        status, body, headers = self.request('/api/auth/setup', {
            'username': 'owner', 'password': PASSWORD, 'role': 'admin',
            'captcha_id': challenge['captcha_id'], 'captcha_code': TEST_CAPTCHA})
        self.assertEqual(status, 200, body)
        return headers['Set-Cookie'].split(';')[0]

    def test_logged_out_visitor_gets_the_whole_login_page_and_nothing_else(self):
        for path in ('/login.html', '/login-BBB.js', '/theme-CCC.js', '/theme-CCC.css', '/vendor-DDD.js', '/qq-support.png'):
            self.assertEqual(self.request(path)[0], 200, path)
        for path in ('/index.html', '/', '/index-AAA.js', '/index-AAA.css'):
            status, _, headers = self.request(path)
            self.assertEqual((status, headers.get('Location')), (302, '/login.html'), path)
        for path in ('/session-context.js', '/api/auth/me', '/api/access'):
            self.assertEqual(self.request(path)[0], 401, path)
        for path in ('/.vite/manifest.json', '/../cloud_server.py'):
            self.assertNotEqual(self.request(path)[0], 200, path)

    def test_signed_in_user_gets_the_built_page_unchanged(self):
        cookie = self.sign_in()
        status, html, headers = self.request('/index.html', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(html.decode('utf-8'), INDEX)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(self.request('/index-AAA.js', cookie=cookie)[0], 200)
        access = json.loads(self.request('/api/access', cookie=cookie)[1])
        self.assertEqual(access['scope'], 'cloud')
        context = self.request('/session-context.js', cookie=cookie)[1].decode()
        self.assertTrue(context.startswith('window.FundPilotCloud='))


if __name__ == '__main__':
    unittest.main()
