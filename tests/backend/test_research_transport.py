import gzip
import json
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import urllib.error
import urllib.request

import research_transport as transport


class Source(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        try:
            if self.path == '/slow-headers':
                for byte in b'HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok':
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(.04)
                return
            status = 403 if self.path == '/error' else 200
            self.send_response(status)
            self.send_header('Content-Length', '60' if self.path == '/slow-body' else '2')
            self.end_headers()
            if self.path == '/slow-body':
                for _ in range(60):
                    self.wfile.write(b'x')
                    self.wfile.flush()
                    time.sleep(.04)
            else:
                self.wfile.write(b'ok')
        except (OSError, ConnectionError):
            pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'method': 'POST', 'body': body.decode(),
                                    'authorization': self.headers.get('Authorization')}).encode())


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Source)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_get_post_headers_and_final_url(self):
        self.assertEqual(transport.fetch_response(self.url, timeout=3), (b'ok', self.url))
        request = urllib.request.Request(self.url, data=b'body', headers={'Authorization': 'Bearer synthetic-value'})
        value = json.loads(transport.fetch_bytes(request, timeout=3))
        self.assertEqual(value, {'method': 'POST', 'body': 'body', 'authorization': 'Bearer synthetic-value'})

    def test_continuous_body_and_header_drips_have_total_deadline_and_reaped_worker(self):
        created = []
        original = subprocess.Popen
        def record(*args, **kwargs):
            process = original(*args, **kwargs)
            created.append(process)
            return process
        for path in ('/slow-body', '/slow-headers'):
            with self.subTest(path=path), patch.object(transport.subprocess, 'Popen', side_effect=record):
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    transport.fetch_bytes(self.url + path, timeout=.5)
                self.assertLess(time.monotonic() - started, 2)
                self.assertIsNotNone(created[-1].poll())

    def test_body_limit_and_safe_http_error(self):
        with self.assertRaisesRegex(ValueError, '大小限制'):
            transport.fetch_bytes(self.url, timeout=3, max_bytes=1)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            transport.fetch_bytes(self.url + '/error', timeout=3)
        self.assertEqual(caught.exception.code, 403)
        self.assertNotIn('synthetic', str(caught.exception))
        caught.exception.close()

    def test_source_error_retains_http_status_without_url_body_or_credentials(self):
        secret='synthetic-private-source-token'
        error=urllib.error.HTTPError('https://example.test/?key='+secret,429,secret,{},None)
        message=transport.source_error(error,'公司历史数据未取得')
        self.assertEqual(message,'HTTP 429：公司历史数据未取得')
        self.assertNotIn(secret,message)
        self.assertNotIn('429',transport.source_error(urllib.error.URLError(secret),'日线未取得'))
        self.assertEqual(transport.source_error(TimeoutError(secret),'日线未取得'),'请求超时：日线未取得')
        error.close()

    def test_credentials_are_sent_via_stdin_not_process_arguments(self):
        original = subprocess.Popen
        calls = []
        def record(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)
        request = urllib.request.Request(self.url, headers={'Authorization': 'Bearer synthetic-private-key'})
        with patch.object(transport.subprocess, 'Popen', side_effect=record):
            transport.fetch_bytes(request, timeout=3)
        self.assertNotIn('synthetic-private-key', repr(calls))
        self.assertIs(calls[0][1]['stderr'], subprocess.DEVNULL)

    def test_gzip_expansion_is_bounded(self):
        data = gzip.compress(b'x' * 5000)
        with self.assertRaisesRegex(ValueError, '大小限制'):
            transport.decompress_gzip(data, max_bytes=100)
        self.assertEqual(transport.decompress_gzip(data, max_bytes=5000), b'x' * 5000)


if __name__ == '__main__':
    unittest.main()
