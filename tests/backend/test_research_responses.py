import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from research_ai_config import AIConfigStore
from research_ai_cost import AICostGuard, _reservation
from research_responses import (RESPONSES_MODEL, build_payload, cache_identity,
    decode_wire, normalize_response, send_provider, probe_responses_key, ProviderError, validate_base_url)

KEY='sk-isolated-responses-key-0123456789'
CONFIG={'key':KEY,'model':RESPONSES_MODEL,'responses_base_url':'https://provider.example/v1'}


def response(status='completed'):
    return {'status':status,'output':[{'type':'reasoning','summary':[]},
        {'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}],
        'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150,
                 'input_tokens_details':{'cached_tokens':20},'output_tokens_details':{'reasoning_tokens':30}}}


class ResponsesTests(unittest.TestCase):
    def test_requested_model_medium_wire_format_and_output_budget(self):
        payload=build_payload(CONFIG,[{'role':'user','content':'Return JSON'}])
        self.assertEqual(payload['model'],'gpt-6.1-sol')
        self.assertEqual(payload['reasoning'],{'effort':'medium'})
        self.assertEqual(payload['max_output_tokens'],6500)
        self.assertTrue(payload['stream']);self.assertFalse(payload['store'])
        self.assertNotIn('thinking',payload);self.assertNotIn('max_tokens',payload)
        size,reserved=_reservation(payload);self.assertEqual(reserved,size+6500)

    def test_usage_includes_reasoning_once_and_cache_observations(self):
        normalized=normalize_response(response())
        self.assertEqual(normalized['choices'][0]['finish_reason'],'stop')
        self.assertEqual(normalized['usage']['completion_tokens'],50)
        self.assertEqual(normalized['usage']['total_tokens'],150)
        self.assertEqual(normalized['usage']['prompt_tokens_details']['cached_tokens'],20)

    def test_sse_requires_final_response_and_never_uses_incomplete_text(self):
        raw=('data: '+json.dumps({'type':'response.output_text.delta','delta':'FAKE'})+'\n\n'+
             'data: '+json.dumps({'type':'response.completed','response':response()})+'\n\n').encode()
        self.assertEqual(json.loads(decode_wire(raw)['choices'][0]['message']['content']),{'ok':True})
        self.assertEqual(normalize_response(response('incomplete'))['choices'][0]['finish_reason'],'length')
        with self.assertRaises(ProviderError):decode_wire(b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n')
        refused=response();refused['output']=[{'type':'message','content':[{'type':'refusal','refusal':'x'}]}]
        self.assertEqual(normalize_response(refused)['choices'][0]['finish_reason'],'content_filter')

    def test_endpoint_and_medium_are_covered_by_cache_identity(self):
        self.assertNotEqual(cache_identity(CONFIG),cache_identity({**CONFIG,'responses_base_url':'https://other.example/v1'}))
        self.assertIn('medium',cache_identity(CONFIG))
        self.assertEqual(cache_identity({'model':'deepseek-flash'}),'deepseek-flash')

    @patch('research_responses.fetch_bytes')
    def test_only_one_actual_wire_request_and_guard_settles_actual_usage(self,fetch):
        fetch.return_value=json.dumps(response()).encode();legacy=Mock()
        payload=build_payload(CONFIG,[{'role':'user','content':'JSON'}])
        with tempfile.TemporaryDirectory() as folder:
            guard=AICostGuard(Path(folder)/'cost.sqlite3')
            result=guard.invoke('sector',payload,CONFIG,lambda:send_provider(CONFIG,payload,75,legacy))
            state=guard.summary(CONFIG)
            self.assertEqual(state['requests'],1);self.assertEqual(state['usage']['total_tokens'],150)
        legacy.assert_not_called();fetch.assert_called_once()
        request=fetch.call_args.args[0]
        self.assertEqual(request.full_url,'https://provider.example/v1/responses')
        self.assertEqual(json.loads(request.data)['reasoning']['effort'],'medium')
        self.assertEqual(result['usage']['completion_tokens'],50)
        self.assertEqual(fetch.call_args.kwargs['timeout'],300)
        self.assertTrue(fetch.call_args.kwargs['responses_stream'])

    @patch('research_responses.fetch_bytes')
    def test_xhigh_has_its_own_bounded_ten_minute_deadline_without_retry(self,fetch):
        fetch.return_value=json.dumps(response()).encode()
        payload=build_payload({**CONFIG,'reasoning_effort':'xhigh'},[])
        send_provider(CONFIG,payload,75,Mock())
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs['timeout'],600)
        self.assertTrue(fetch.call_args.kwargs['responses_stream'])

    @patch('research_responses.fetch_bytes')
    def test_model_probe_is_a_get_and_never_generates_tokens(self,fetch):
        fetch.return_value=json.dumps({'data':[{'id':RESPONSES_MODEL}]}).encode()
        self.assertTrue(probe_responses_key(KEY,CONFIG['responses_base_url'])['model_available'])
        self.assertEqual(fetch.call_args.args[0].get_method(),'GET')

    def test_config_secure_persistence_and_no_cross_provider_key_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            store=AIConfigStore(path,encrypt=lambda b:b[::-1],decrypt=lambda b:b[::-1],probe=lambda k,m:{'models':[m]})
            store.configure(key=KEY,model=RESPONSES_MODEL,responses_base_url=CONFIG['responses_base_url'],enabled=True)
            checked=store.verify();self.assertTrue(checked['effective_enabled'])
            self.assertEqual(checked['reasoning_effort'],'xhigh');self.assertNotIn(KEY,json.dumps(checked))
            restored=AIConfigStore(path,encrypt=lambda b:b[::-1],decrypt=lambda b:b[::-1])
            self.assertEqual(restored.snapshot()['responses_base_url'],CONFIG['responses_base_url'])
            self.assertEqual(restored.snapshot()['reasoning_effort'],'xhigh')
            self.assertNotIn(KEY,path.read_text())
            with self.assertRaises(ValueError):store.configure(model='deepseek-flash')
            before=store.status()['revision']
            store.configure(responses_base_url='https://other.example/v1')
            self.assertNotEqual(before,store.status()['revision']);self.assertFalse(store.snapshot()['enabled'])

    def test_urls_reject_embedded_credentials_and_non_http_protocols(self):
        for url in ['file:///x','https://user:secret@provider.example','https://provider.example?key=secret','https://provider.example/#x']:
            with self.assertRaises(ValueError):validate_base_url(url)


if __name__=='__main__':unittest.main()
