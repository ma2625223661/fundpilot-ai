"""Offline sockets verify finite bodies, bounded workers and HEAD admission."""
import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

from server import BoundedThreadingHTTPServer, Handler


class ServerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        Path(self.directory.name, 'index.html').write_text('local sector page', encoding='utf-8')
        self.service = self.start(Handler)

    def start(self, handler, max_workers=4):
        service = BoundedThreadingHTTPServer(('127.0.0.1', 0), partial(handler, directory=self.directory.name),
                                             max_workers=max_workers, request_read_timeout=.2)
        service.allowed_hosts = {f'127.0.0.1:{service.server_port}'}
        service.research_scope = 'sectors'
        service.auto_engine = Mock()
        service.auto_engine.status.return_value = {'status': 'ready'}
        thread = threading.Thread(target=service.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        self.addCleanup(service.server_close)
        self.addCleanup(service.shutdown)
        return service

    def connect(self, service=None):
        sock = socket.create_connection(('127.0.0.1', (service or self.service).server_port), timeout=2)
        self.addCleanup(sock.close)
        return sock

    def response(self, sock):
        response = http.client.HTTPResponse(sock)
        response.begin()
        self.addCleanup(response.close)
        return response

    def head(self, path, host):
        conn = http.client.HTTPConnection('127.0.0.1', self.service.server_port, timeout=2)
        self.addCleanup(conn.close)
        conn.request('HEAD', path, headers={'Host': host})
        response = conn.getresponse()
        return response.status, response.read(), response.getheader('Allow')

    @unittest.skipUnless(os.name == 'nt', 'Windows socket exclusivity regression')
    def test_windows_rejects_second_instance_without_stealing_live_requests(self):
        port = self.service.server_port
        self.assertFalse(self.service.allow_reuse_address)
        self.assertFalse(self.service.allow_reuse_port)
        self.assertEqual(self.service.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
        for address in ('127.0.0.1', '0.0.0.0'):
            with self.subTest(address=address), self.assertRaises(OSError):
                duplicate = BoundedThreadingHTTPServer((address, port), Handler)
                # Cleanup still runs if a future regression permits the bind.
                self.addCleanup(duplicate.server_close)
        # An old process with SO_REUSEADDR cannot take this same interface.
        with socket.socket() as old_socket:
            old_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                old_socket.bind(('127.0.0.1', port))
                old_socket.listen(1)
        host = next(iter(self.service.allowed_hosts))
        self.assertEqual(self.head('/index.html', host)[0:2], (200, b''))
        self.service.auto_engine.start.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows socket exclusivity regression')
    def test_windows_wildcard_bind_is_exclusive_and_releases_on_close(self):
        first = BoundedThreadingHTTPServer(('0.0.0.0', 0), Handler)
        self.addCleanup(first.server_close)
        port = first.server_port
        for address in ('127.0.0.1', '0.0.0.0'):
            with self.subTest(address=address), self.assertRaises(OSError):
                duplicate = BoundedThreadingHTTPServer((address, port), Handler)
                self.addCleanup(duplicate.server_close)
            # The actual Windows/LAN deployment binds a wildcard; even old
            # instances using SO_REUSEADDR cannot steal any of its interfaces.
            with socket.socket() as old_socket:
                old_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                with self.subTest(legacy_address=address), self.assertRaises(OSError):
                    old_socket.bind((address, port))
                    old_socket.listen(1)
        first.server_close()
        replacement = BoundedThreadingHTTPServer(('0.0.0.0', port), Handler)
        self.addCleanup(replacement.server_close)
        self.assertEqual(replacement.server_port, port)

    def test_partial_body_times_out_with_408_and_never_starts_research(self):
        sock = self.connect()
        host = next(iter(self.service.allowed_hosts))
        request = f'POST /api/auto/refresh HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nContent-Length: 100\r\n\r\n{{'
        started = time.monotonic()
        sock.sendall(request.encode('ascii'))
        response = self.response(sock)
        self.assertEqual(response.status, 408)
        self.assertIn('超时', json.loads(response.read())['error'])
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(sock.recv(1), b'')
        self.service.auto_engine.request_scan.assert_not_called()

    def test_dripping_body_does_not_extend_total_read_deadline(self):
        sock = self.connect()
        host = next(iter(self.service.allowed_hosts))
        sock.sendall(f'POST /api/auto/refresh HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nContent-Length: 100\r\n\r\n'.encode('ascii'))
        stop = threading.Event()
        def drip():
            while not stop.wait(.05):
                try:
                    sock.sendall(b' ')
                except OSError:
                    break
        writer = threading.Thread(target=drip, daemon=True)
        writer.start()
        started = time.monotonic()
        try:
            response = self.response(sock)
            self.assertEqual(response.status, 408)
            response.read()
            self.assertLess(time.monotonic() - started, 1)
        finally:
            stop.set()
            writer.join(1)
        self.service.auto_engine.request_scan.assert_not_called()

    def test_worker_limit_returns_503_and_recovers_after_worker_release(self):
        entered, release = threading.Event(), threading.Event()
        class BlockingHandler(Handler):
            def do_GET(inner):
                if inner.path == '/hold':
                    entered.set()
                    release.wait(2)
                    return inner.reply(200, {'done': True})
                return super().do_GET()
        service = self.start(BlockingHandler, max_workers=1)
        self.addCleanup(release.set)
        first = self.connect(service)
        host = next(iter(service.allowed_hosts))
        first.sendall(f'GET /hold HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('ascii'))
        self.assertTrue(entered.wait(1))
        second = self.connect(service)
        # Admission rejects before reading a request. Avoid sending unread
        # bytes, whose reset-on-close behavior differs between Windows/Linux.
        self.assertEqual(self.response(second).status, 503)
        release.set()
        self.assertEqual(self.response(first).status, 200)
        # Slot release happens after the first response is written.
        deadline = time.monotonic() + 1
        while True:
            sock = self.connect(service)
            sock.sendall(f'GET /api/health HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('ascii'))
            try:
                response = self.response(sock)
            except (ConnectionResetError, ConnectionAbortedError):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
                continue
            if response.status == 200:
                break
            self.assertEqual(response.status, 503)
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)

    def test_head_applies_host_guard_and_api_head_has_no_side_effect(self):
        host = next(iter(self.service.allowed_hosts))
        self.assertEqual(self.head('/index.html', 'attacker.invalid')[0:2], (403, b''))
        self.assertEqual(self.head('/index.html', host)[0:2], (200, b''))
        status, body, allow = self.head('/api/auto/status', host)
        self.assertEqual((status, body), (405, b''))
        self.assertIn('GET', allow)
        self.service.auto_engine.start.assert_not_called()
        self.service.auto_engine.status.assert_not_called()

    def test_lan_can_read_but_configuration_is_rejected_before_body_read(self):
        host = next(iter(self.service.allowed_hosts))
        with patch.object(Handler, 'local_client', return_value=False):
            sock = self.connect()
            sock.sendall(f'GET /api/health HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('ascii'))
            self.assertEqual(self.response(sock).status, 200)
            sock = self.connect()
            sock.sendall(f'POST /api/ai/config HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nContent-Length: 4096\r\n\r\n'.encode('ascii'))
            self.assertEqual(self.response(sock).status, 403)

    def test_duplicate_host_and_body_length_headers_are_rejected(self):
        host = next(iter(self.service.allowed_hosts))
        for request, status in [
            (f'HEAD /index.html HTTP/1.1\r\nHost: {host}\r\nHost: attacker.invalid\r\n\r\n', 403),
            (f'POST /api/auto/refresh HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n', 400),
        ]:
            sock = self.connect()
            sock.sendall(request.encode('ascii'))
            self.assertEqual(self.response(sock).status, status)

    def test_eof_after_short_valid_json_body_is_rejected_without_research(self):
        sock = self.connect()
        host = next(iter(self.service.allowed_hosts))
        sock.sendall(f'POST /api/auto/refresh HTTP/1.1\r\nHost: {host}\r\nOrigin: http://{host}\r\nContent-Length: 20\r\n\r\n{{}}'.encode('ascii'))
        sock.shutdown(socket.SHUT_WR)
        response = self.response(sock)
        self.assertEqual(response.status, 400)
        response.read()
        self.assertEqual(sock.recv(1), b'')
        self.service.auto_engine.request_scan.assert_not_called()

    def test_dripping_requestline_and_headers_have_absolute_deadline_and_release_slot(self):
        service = self.start(Handler, max_workers=1)
        host = next(iter(service.allowed_hosts))
        for prefix in (b'GET /api/', f'GET /api/auto/status HTTP/1.1\r\nHost: {host}\r\nX-Slow: '.encode('ascii')):
            with self.subTest(prefix=prefix):
                sock = self.connect(service)
                sock.sendall(prefix)
                stop = threading.Event()
                def drip():
                    while not stop.wait(.03):
                        try:
                            sock.sendall(b'x')
                        except OSError:
                            break
                writer = threading.Thread(target=drip, daemon=True)
                writer.start()
                started = time.monotonic()
                try:
                    # Buffered read shutdown may reset the socket on Windows;
                    # otherwise the incomplete request returns 400 or 408.
                    try:
                        response = self.response(sock)
                        self.assertIn(response.status, (400, 408))
                        response.read()
                        self.assertEqual(sock.recv(1), b'')
                    except (ConnectionResetError, http.client.RemoteDisconnected):
                        pass
                    self.assertLess(time.monotonic() - started, 1)
                finally:
                    stop.set()
                    writer.join(1)
                deadline = time.monotonic() + 1
                while True:
                    check = self.connect(service)
                    check.sendall(f'GET /api/health HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode('ascii'))
                    status = self.response(check).status
                    if status == 200:
                        break
                    self.assertEqual(status, 503)
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
        service.auto_engine.start.assert_not_called()
        service.auto_engine.status.assert_not_called()


if __name__ == '__main__':
    unittest.main()
