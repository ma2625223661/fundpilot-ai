"""Independent, offline checks of redirects and worker cleanup."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

from research_transport import fetch_bytes


class RedirectCredentialTests(unittest.TestCase):
    def setUp(self):
        outer = self
        class Target(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = json.dumps({key: self.headers.get(key) for key in
                    ('Authorization', 'Cookie', 'Proxy-Authorization', 'X-Api-Key')}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.target = self.start(Target)
        class Redirect(Target):
            def do_GET(self):
                if self.path == '/same':
                    location = '/received'
                elif self.path == '/other':
                    location = f'http://127.0.0.1:{outer.target.server_port}/received'
                else:
                    return super().do_GET()
                self.send_response(302)
                self.send_header('Location', location)
                self.send_header('Content-Length', '0')
                self.end_headers()
        self.source = self.start(Redirect)
        self.headers = {'Authorization': 'Bearer synthetic-private-key',
                        'Cookie': 'synthetic-session=value',
                        'Proxy-Authorization': 'Basic synthetic-proxy',
                        'X-Api-Key': 'synthetic-api-key'}

    def start(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def get(self, path):
        request = urllib.request.Request(f'http://127.0.0.1:{self.source.server_port}{path}',
                                         headers=self.headers)
        return json.loads(fetch_bytes(request, timeout=3))

    def test_same_origin_redirect_retains_required_credentials(self):
        self.assertEqual(self.get('/same')['Authorization'], self.headers['Authorization'])

    def test_cross_origin_redirect_never_forwards_request_credentials(self):
        self.assertTrue(all(value is None for value in self.get('/other').values()))


if __name__ == '__main__':
    unittest.main()
