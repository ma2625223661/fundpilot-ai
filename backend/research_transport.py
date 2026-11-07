"""HTTP requests with a wall-clock deadline and a bounded response.

An isolated, short-lived worker owns DNS, connection, headers and body reads.
The caller terminates and reaps it at the deadline, including slow streams.
Credentials are passed through stdin, never process arguments or error text.
"""
import sys as _sys
from pathlib import Path as _Path

# The bundled Windows runtime (runtime/python315._pth) does not put a started
# script's own folder on the import path, so a script run directly adds backend/.
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

import base64
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def source_error(error, context):
    """Describe a public-source failure without copying URLs or response bodies."""
    if isinstance(error, urllib.error.HTTPError):
        return 'HTTP ' + str(error.code) + '：' + context
    if isinstance(error, TimeoutError):
        return '请求超时：' + context
    if isinstance(error, urllib.error.URLError):
        return '连接失败：' + context
    if isinstance(error, ValueError):
        return str(error)[:180]
    return type(error).__name__ + '：' + context


def _origin(url):
    value = urlsplit(url)
    return value.scheme.lower(), value.hostname, value.port or (443 if value.scheme == 'https' else 80)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        before, after = _origin(request.full_url), _origin(newurl)
        if before[0] == 'https' and after[0] != 'https':
            raise urllib.error.HTTPError(request.full_url, code, '拒绝 HTTPS 降级跳转', {}, None)
        redirected = super().redirect_request(request, response, code, message, headers, newurl)
        if redirected is not None and before != after:
            for name in list(redirected.headers):
                if name.lower() in {'authorization', 'proxy-authorization', 'cookie', 'cookie2', 'x-api-key', 'api-key', 'apikey'}:
                    redirected.remove_header(name)
        return redirected


def fetch_response(request, *, timeout=8, max_bytes=4_000_000, responses_stream=False):
    if not isinstance(request, urllib.request.Request):
        request = urllib.request.Request(request)
    if (type(responses_stream) is not bool or not 0 < timeout <= (600 if responses_stream else 180)
            or not 0 < max_bytes <= 32_000_000):
        raise ValueError('HTTP 采集边界无效')
    document = {'url': request.full_url, 'method': request.get_method(),
                'headers': dict(request.header_items()),
                'data': base64.b64encode(request.data).decode('ascii') if request.data is not None else None,
                'timeout': timeout, 'max_bytes': max_bytes, 'responses_stream':responses_stream}
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        output, _ = process.communicate(json.dumps(document).encode('utf-8'), timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise TimeoutError('HTTP 采集总时间超限') from None
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode != 0:
        raise urllib.error.URLError('HTTP 采集进程未完成')
    try:
        result = json.loads(output)
        if result.get('error') == 'http':
            raise urllib.error.HTTPError(request.full_url, int(result['status']),
                                         '公开来源 HTTP 响应错误', {}, None)
        if result.get('error') == 'size':
            raise ValueError('数据响应超过大小限制')
        if result.get('error') == 'timeout':
            raise TimeoutError('HTTP 采集总时间超限')
        if result.get('error'):
            raise urllib.error.URLError('HTTP 连接失败或响应无效')
        body = base64.b64decode(result['body'], validate=True)
        if len(body) > max_bytes:
            raise ValueError('数据响应超过大小限制')
        return body, result['url']
    except (KeyError, json.JSONDecodeError) as error:
        raise urllib.error.URLError('HTTP 采集响应格式无效') from error


def fetch_bytes(request, *, timeout=8, max_bytes=4_000_000, responses_stream=False):
    return fetch_response(request, timeout=timeout, max_bytes=max_bytes,
                          responses_stream=responses_stream)[0]


class _ResponsesTerminal:
    """Recognize complete SSE terminal events without trusting partial deltas."""
    endings = re.compile(br'\r\n|\r|\n')
    types = frozenset(('response.completed','response.incomplete','response.failed','error'))

    def __init__(self):
        self.pending, self.data = bytearray(), []
        self.offset, self.first_line, self.skip_lf = 0, True, False

    def feed(self, chunk):
        if self.skip_lf:
            self.skip_lf = False
            if chunk.startswith(b'\n'):
                self.offset += 1
                chunk = chunk[1:]
        self.pending.extend(chunk)
        while True:
            match = self.endings.search(self.pending)
            if not match:
                return None
            # CR is itself a valid SSE line ending. If its LF arrives in the
            # next chunk it belongs to this ending, not a new blank line.
            self.skip_lf = match.group() == b'\r' and match.end() == len(self.pending)
            line = bytes(self.pending[:match.start()])
            self.offset += match.end()
            del self.pending[:match.end()]
            if self.first_line:
                line = line.removeprefix(b'\xef\xbb\xbf')
                self.first_line = False
            if line:
                if line.startswith(b'data:'):
                    self.data.append(line[5:].removeprefix(b' '))
                continue
            data, self.data = b'\n'.join(self.data), []
            if not data or data == b'[DONE]':
                continue
            try:
                event = json.loads(data)
            except (ValueError, UnicodeError):
                continue
            if isinstance(event,dict) and event.get('type') in self.types:
                return self.offset


def _read_responses_stream(response, max_bytes):
    # read(n) can wait for EOF or all n bytes even after response.completed.
    # read1(n) returns available HTTP body data; the caller's process deadline
    # still bounds DNS, headers, stalled reads and endless nonterminal streams.
    body, terminal = bytearray(), _ResponsesTerminal()
    while len(body) <= max_bytes:
        chunk = response.read1(min(65536,max_bytes+1-len(body)))
        if not chunk:
            break
        body.extend(chunk)
        end = terminal.feed(chunk)
        if end is not None:
            return bytes(body[:end])
    return bytes(body)


def decompress_gzip(body, *, max_bytes=32_000_000):
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
        result = stream.read(max_bytes + 1)
    if len(result) > max_bytes:
        raise ValueError('解压后的数据响应超过大小限制')
    return result


def _worker():
    # Worker output is a private structured IPC response; never return upstream
    # error bodies, exception messages, request headers or credential values.
    try:
        args = json.load(sys.stdin)
        request = urllib.request.Request(args['url'],
            data=base64.b64decode(args['data']) if args['data'] is not None else None,
            headers=args['headers'], method=args['method'])
        opener = urllib.request.build_opener(SafeRedirectHandler())
        with opener.open(request, timeout=args['timeout']) as response:
            body = (_read_responses_stream(response,args['max_bytes']) if args.get('responses_stream') is True
                    else response.read(args['max_bytes'] + 1))
            result = ({'error': 'size'} if len(body) > args['max_bytes'] else
                      {'body': base64.b64encode(body).decode('ascii'), 'url': response.geturl()})
    except urllib.error.HTTPError as error:
        result = {'error': 'http', 'status': error.code}
    except TimeoutError:
        result = {'error': 'timeout'}
    except Exception:
        result = {'error': 'network'}
    sys.stdout.buffer.write(json.dumps(result).encode('utf-8'))


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    _worker()
