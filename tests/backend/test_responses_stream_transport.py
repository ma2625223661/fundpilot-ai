"""Local SSE fixtures; never contact a model or read application credentials."""
import json
import subprocess
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import research_transport as transport
from research_responses import (ProviderError, build_payload, decode_wire,
                                send_provider, RESPONSES_MODEL)


def fixture_response(status='completed'):
    return {'status':status,'output':[{'type':'message','content':[
        {'type':'output_text','text':'{"中文":"证据"}'}]}],
        'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}}


class StreamSource(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'

    def log_message(self,*args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length','0')))
        self.server.calls.append(self.path)
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream; charset=utf-8')
        self.end_headers()
        try:
            if self.path=='/nonterminal':
                while not self.server.release.wait(.03):
                    self.wfile.write(b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n')
                    self.wfile.flush()
                return
            status=self.path.removeprefix('/') if self.path in ('/incomplete','/failed') else 'completed'
            event=({'type':'error','message':'synthetic-private-response-body'} if self.path=='/error'
                   else {'type':'response.'+status,'response':fixture_response(status)})
            body=('event: '+event['type']+'\r\ndata: '+json.dumps(event,ensure_ascii=False)+'\r\n\r\n').encode()
            # Deliberately split UTF-8 and CRLF boundaries into separate writes.
            for index in range(0,len(body),7):
                self.wfile.write(body[index:index+7]);self.wfile.flush()
            # A completed SSE response need not close its HTTP connection.
            self.server.release.wait(timeout=5)
        except (OSError,ConnectionError):
            pass
        finally:
            self.close_connection=True


class ResponsesStreamTransportTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),StreamSource)
        self.server.daemon_threads=True
        self.server.release=threading.Event();self.server.calls=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.release.set();self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path='/responses'):
        return urllib.request.Request(self.base+path,data=b'{}',headers={'Authorization':'Bearer synthetic-fixture-key'})

    def test_terminal_event_returns_before_connection_closes_and_worker_is_reaped(self):
        processes=[];original=subprocess.Popen
        def start(*args,**kwargs):
            process=original(*args,**kwargs);processes.append(process);return process
        with patch.object(transport.subprocess,'Popen',side_effect=start):
            started=time.monotonic()
            raw=transport.fetch_bytes(self.request(),timeout=2,responses_stream=True,max_bytes=2000000)
        self.assertLess(time.monotonic()-started,1.8)
        self.assertFalse(self.server.release.is_set())
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(json.loads(decode_wire(raw)['choices'][0]['message']['content']),{'中文':'证据'})
        self.assertEqual(self.server.calls,['/responses'])

    def test_responses_adapter_accepts_completed_stream_without_eof_and_no_retry(self):
        config={'model':RESPONSES_MODEL,'key':'synthetic-fixture-key','responses_base_url':self.base,
                'reasoning_effort':'xhigh'}
        legacy=Mock();started=time.monotonic()
        result=send_provider(config,build_payload(config,[]),75,legacy)
        self.assertLess(time.monotonic()-started,1.8)
        self.assertEqual(result['usage']['total_tokens'],150)
        legacy.assert_not_called();self.assertEqual(self.server.calls,['/responses'])

    def test_incomplete_failed_and_error_terminal_events_do_not_wait_or_claim_success(self):
        for path in ('/incomplete','/failed','/error'):
            with self.subTest(path=path):
                raw=transport.fetch_bytes(self.request(path),timeout=2,responses_stream=True)
                if path=='/error':
                    with self.assertRaises(ProviderError) as caught:decode_wire(raw)
                    self.assertNotIn('synthetic-private',str(caught.exception))
                else:
                    result=decode_wire(raw)
                    self.assertEqual(result['choices'][0]['finish_reason'],'length')
                    self.assertEqual(result['usage']['total_tokens'],150)
        self.assertEqual(len(self.server.calls),3)

    def test_nonterminal_stream_still_hits_hard_deadline_and_reaps_worker(self):
        processes=[];original=subprocess.Popen
        def start(*args,**kwargs):
            process=original(*args,**kwargs);processes.append(process);return process
        with patch.object(transport.subprocess,'Popen',side_effect=start):
            started=time.monotonic()
            with self.assertRaises(TimeoutError):
                transport.fetch_bytes(self.request('/nonterminal'),timeout=.6,responses_stream=True)
        self.assertLess(time.monotonic()-started,2)
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(self.server.calls,['/nonterminal'])

    def test_byte_limit_and_long_deadline_are_restricted_to_responses_mode(self):
        with self.assertRaisesRegex(ValueError,'大小限制'):
            transport.fetch_bytes(self.request(),timeout=2,responses_stream=True,max_bytes=32)
        with self.assertRaisesRegex(ValueError,'边界无效'):
            transport.fetch_bytes(self.request(),timeout=181)
        with self.assertRaisesRegex(ValueError,'边界无效'):
            transport.fetch_bytes(self.request(),timeout=601,responses_stream=True)
        raw=transport.fetch_bytes(self.request(),timeout=600,responses_stream=True)
        self.assertEqual(decode_wire(raw)['choices'][0]['finish_reason'],'stop')

    def test_parser_handles_arbitrary_boundaries_comments_multiline_and_all_sse_line_endings(self):
        for ending in (b'\n',b'\r\n',b'\r'):
            with self.subTest(ending=ending):
                event=json.dumps({'type':'response.completed','response':fixture_response()},ensure_ascii=False).encode()
                # JSON whitespace can span multiple SSE data lines.
                marker=event.index(b'"response"')
                body=b'\xef\xbb\xbf: keepalive'+ending+b'data: '+event[:marker]+ending+b'data: '+event[marker:]+ending+ending
                parser=transport._ResponsesTerminal();found=None
                for byte in body:
                    end=parser.feed(bytes([byte]))
                    if end is not None:found=end;break
                self.assertEqual(found,len(body) if ending!=b'\r\n' else len(body)-1)
                self.assertEqual(decode_wire(body[:found])['choices'][0]['finish_reason'],'stop')
        parser=transport._ResponsesTerminal()
        self.assertIsNone(parser.feed(b'data: {"type":"response.output_text.delta","delta":"response.completed"}\n\ndata: [DONE]\n\n'))


if __name__=='__main__':
    unittest.main()
