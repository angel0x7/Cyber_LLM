"""Offline cost, identity, and bounded output contracts for the paid course route."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from course_llm import CourseClient, Budget, AdapterError
from course_llm.client import valid_model_identifier, load_course_env

MODEL = 'deepseek/deepseek-v4.1-flash'

class OpenRouterAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'LLM_OFFLINE':'0'});self.env.start();self.addCleanup(self.env.stop)
    def client(self,handler,**kw):
        return CourseClient('openrouter',MODEL,'fake-secret',http_client=httpx.Client(transport=httpx.MockTransport(handler)),max_retries=0,**kw)
    def body(self,finish='stop',cost=.00001):
        return {'model':MODEL,'provider':'Fixture Backend','choices':[{'finish_reason':finish,'message':{'content':'{"ok":true}','reasoning':'PRIVATE THOUGHT'}}], 'usage':{'prompt_tokens':10,'completion_tokens':20,'completion_tokens_details':{'reasoning_tokens':12},'cost':cost}}
    def test_cost_backend_and_routing(self):
        seen=[]
        c=self.client(lambda req:(seen.append(json.loads(req.content)) or httpx.Response(200,json=self.body())))
        r=c.complete([{'role':'user','content':'x'}])
        self.assertEqual(seen[0]['model'],MODEL)
        self.assertIs(seen[0]['stream'], False)
        self.assertEqual(seen[0]['usage'],{'include':True})
        self.assertTrue(seen[0]['provider']['allow_fallbacks'])
        self.assertEqual(seen[0]['provider']['max_price'],{'prompt':.45,'completion':1.8,'request':0})
        self.assertNotIn('models',seen[0]); self.assertEqual(r.metadata['serving_backend'],'Fixture Backend')
        self.assertEqual(r.metadata['reasoning_tokens'],12)
        self.assertAlmostEqual(c.budget.accounted_usd,.00001)
        self.assertNotIn('PRIVATE THOUGHT',json.dumps(c.records))
    def test_opt_in_backend_metadata(self):
        def handler(req):
            self.assertEqual(req.headers['X-OpenRouter-Metadata'],'enabled')
            body=self.body();body.pop('provider')
            body['openrouter_metadata']={'endpoints':{'available':[
                {'provider':'Unused','selected':False}, {'provider':'Selected','selected':True}]}}
            return httpx.Response(200,json=body)
        c=self.client(handler)
        r=c.complete([{'role':'user','content':'x'}])
        self.assertEqual(r.metadata['serving_backend'],'Selected')
    def test_cap_stops_before_network(self):
        c=self.client(lambda _:self.fail('No dispatch'),budget=Budget(limit_usd=.00000001))
        with self.assertRaises(AdapterError) as raised:c.complete([{'role':'user','content':'x'}])
        self.assertEqual(raised.exception.category,'budget_blocked');self.assertEqual(c.budget.attempts,0)
    def test_unknown_cost_keeps_reservation(self):
        c=self.client(lambda _:httpx.Response(200,json=self.body(cost=None)))
        r=c.complete([{'role':'user','content':'x'}])
        self.assertIsNone(r.metadata['cost_usd'])
        self.assertEqual(c.budget.accounted_usd,r.metadata['budget_reserved_usd'])
    def test_truncated_then_success_has_exactly_one_expansion(self):
        caps=[]
        def handler(req):
            caps.append(json.loads(req.content)['max_tokens'])
            return httpx.Response(200,json=self.body('length' if len(caps)==1 else 'stop'))
        c=self.client(handler)
        c.complete_bounded([{'role':'user','content':'x'}],max_output_tokens=256,retry_max_output_tokens=512)
        self.assertEqual(caps,[256,512]);self.assertIsNone(c.records[0]['json_parse_result'])
    def test_permanent_truncation_never_parsed(self):
        c=self.client(lambda _:httpx.Response(200,json=self.body('length')))
        with self.assertRaises(AdapterError) as raised:c.generate_content(model=MODEL,contents='x')
        self.assertEqual(raised.exception.category,'output_truncated')
        self.assertEqual(len(c.records),2)
        self.assertTrue(all(r['json_parse_result'] is None for r in c.records))
    def test_model_identifiers(self):
        for model in [MODEL,'deepseek/deepseek-v4-flash-0731:free','openai/gpt-oss-20b']:
            self.assertTrue(valid_model_identifier('openrouter',model))
        for model in ['sk-or-SECRET','vendor/sk-SECRET','nvapi-SECRET','gsk_SECRET','hf_SECRET','openrouter/free','a//b','a/b\n']:
            self.assertFalse(valid_model_identifier('openrouter',model))
    def test_dotenv_exported_empty_value_wins(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.env').write_text('OPENROUTER_API_KEY=local-fake\nMODEL_ID='+MODEL+'\n')
            with patch('course_llm.client.__file__',str(root/'course_llm/client.py')), patch.dict(os.environ,{'OPENROUTER_API_KEY':''},clear=True):
                load_course_env()
                self.assertEqual(os.environ['OPENROUTER_API_KEY'],'')
                self.assertEqual(os.environ['MODEL_ID'],MODEL)

    def test_dripping_response_stops_at_total_deadline(self):
        clock = [0.0]
        class Drip(httpx.SyncByteStream):
            def __iter__(self):
                yield b'{'
                clock[0] = 121.0
                yield b'"ok":true}'
        c = self.client(lambda _: httpx.Response(200, stream=Drip()))
        with patch('course_llm.client.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(AdapterError) as raised:
                c.complete([{'role':'user','content':'x'}], max_output_tokens=512)
        self.assertEqual(raised.exception.category, 'transport_error')
        self.assertEqual(c.records[0]['error_message'], 'ReadTimeout')
        self.assertEqual(c.budget.attempts, 1)

    def test_response_body_is_bounded_before_json_parse(self):
        c = self.client(lambda _: httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 1)))
        with self.assertRaises(AdapterError) as raised:
            c.complete([{'role':'user','content':'x'}])
        self.assertEqual(raised.exception.category, 'response_too_large')
        self.assertIsNone(c.records[0]['raw_text'])

    def test_http_error_body_is_never_read_or_recorded(self):
        class ForbiddenBody(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError('HTTP error body must remain unread')
                yield b''
        c = self.client(lambda _: httpx.Response(401, stream=ForbiddenBody()))
        with self.assertRaises(AdapterError) as raised:
            c.complete([{'role':'user','content':'x'}])
        self.assertEqual(raised.exception.category, 'authentication_error')
        self.assertNotIn('fake-secret', json.dumps(c.records))

if __name__=='__main__':unittest.main()
