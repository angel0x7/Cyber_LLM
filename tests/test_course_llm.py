import json
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import httpx
from course_llm import CourseClient, Budget, AdapterError, client_from_env

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'LLM_OFFLINE':'0'});self.env.start();self.addCleanup(self.env.stop)
    def client(self, handler, **kw):
        return CourseClient('groq','openai/gpt-oss-20b','private-test-key',
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),**kw)
    def success(self, **overrides):
        return {'id':'request-1','model':'openai/gpt-oss-20b','choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':10,'completion_tokens':20,'completion_tokens_details':{'reasoning_tokens':12}},**overrides}
    def test_exact_route_usage_and_no_default_system(self):
        seen=[]
        def handler(req):
            seen.append(json.loads(req.content));self.assertEqual(str(req.url),'https://api.groq.com/openai/v1/chat/completions')
            return httpx.Response(200,json=self.success())
        c=self.client(handler);r=c.generate_content(model=c.model_id,contents='Return JSON')
        self.assertEqual(seen[0]['messages'],[{'role':'user','content':'Return JSON'}])
        self.assertEqual(seen[0]['max_completion_tokens'],512)
        self.assertEqual(r.metadata['reasoning_tokens'],12)
        self.assertAlmostEqual(r.metadata['estimated_cost_usd'],.00000675)
        self.assertEqual(r.metadata['request_id'],'request-1')
    def test_guarded_system_and_json_mode_preserved(self):
        seen=[]
        c=self.client(lambda req:(seen.append(json.loads(req.content)) or httpx.Response(200,json=self.success())))
        c.generate_content(model=c.model_id,contents='x',config={'system_instruction':'policy','response_mime_type':'application/json'})
        self.assertEqual(seen[0]['messages'][0],{'role':'system','content':'policy'})
        self.assertEqual(seen[0]['response_format'],{'type':'json_object'})
    def test_offline_before_credentials_and_after_client_creation(self):
        c=self.client(lambda _:self.fail('Network must not run'))
        with patch.dict(os.environ, {'LLM_OFFLINE':'true'}):
            with self.assertRaises(AdapterError):client_from_env()
            with self.assertRaises(AdapterError):c.complete([{'role':'user','content':'x'}])
    def test_missing_key_and_explicit_route(self):
        with self.assertRaises(AdapterError):CourseClient('mistral','mistral-small-2603',None)
        with patch.dict(os.environ,{},clear=True), patch('course_llm.client.load_course_env'):
            with self.assertRaises(ValueError):client_from_env()
    def test_no_silent_model_substitution(self):
        c=self.client(lambda _:self.fail('No request'))
        with self.assertRaises(ValueError):c.generate_content(model='different-model',contents='x')
    def test_one_retry_and_retry_after(self):
        attempts=[];delays=[]
        def handler(req):
            attempts.append(req)
            return httpx.Response(429,json={'error':{'message':'rate limited'}},headers={'retry-after':'3'}) if len(attempts)==1 else httpx.Response(200,json=self.success())
        c=self.client(handler,sleep=delays.append)
        c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(len(attempts),2);self.assertEqual(delays,[3]);self.assertEqual(c.records[0]['category'],'quota_or_rate_limit')
    def test_persistent_429_stops_after_two(self):
        c=self.client(lambda _:httpx.Response(429,json={'error':{'message':'limit'}}),sleep=lambda _:None)
        with self.assertRaises(AdapterError) as e:c.generate_content(model=c.model_id,contents='x')
        self.assertTrue(e.exception.retry_exhausted);self.assertEqual(len(c.records),2)
    def test_two_retries_use_bounded_exponential_backoff(self):
        statuses=iter([503,502,None]);delays=[]
        def handler(_):
            status=next(statuses)
            return httpx.Response(status,json={'error':{'message':'temporary'}}) if status else httpx.Response(200,json=self.success())
        c=self.client(handler,sleep=delays.append,max_retries=2)
        c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(len(c.records),3)
        self.assertEqual(delays,[2.0,4.0])
    def test_long_retry_after_stops_instead_of_early_retry(self):
        c=self.client(lambda _:httpx.Response(429,json={'error':{'message':'limit'}},headers={'retry-after':'120'}),sleep=lambda _:self.fail('No wait'))
        with self.assertRaises(AdapterError):c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(len(c.records),1)
    def test_authentication_error_redacts_key_no_retry(self):
        c=self.client(lambda _:httpx.Response(401,json={'error':{'message':'bad private-test-key'}}))
        with self.assertRaises(AdapterError) as e:c.generate_content(model=c.model_id,contents='x')
        self.assertNotIn('private-test-key',str(e.exception)+json.dumps(c.records));self.assertEqual(len(c.records),1)
    def test_refusal_and_empty_are_distinct(self):
        for content,refusal,expected in [('',None,False),('', 'cannot comply',True)]:
            body=self.success(choices=[{'message':{'content':content,'refusal':refusal}}])
            c=self.client(lambda _:httpx.Response(200,json=body));r=c.generate_content(model=c.model_id,contents='x')
            self.assertEqual(r.metadata['model_refusal'],expected);self.assertFalse(r.metadata['json_parse_result'])
    def test_unknown_usage_is_not_zero_cost(self):
        c=self.client(lambda _:httpx.Response(200,json=self.success(usage={})))
        r=c.generate_content(model=c.model_id,contents='x')
        self.assertIsNone(r.metadata['estimated_cost_usd']);self.assertGreater(c.budget.accounted_usd,0)
    def test_budget_prevents_dispatch(self):
        c=self.client(lambda _:self.fail('Must not send'),budget=Budget(limit_usd=0))
        with self.assertRaises(AdapterError):c.generate_content(model=c.model_id,contents='x')
        self.assertFalse(c.records)
    def test_mistral_uses_own_endpoint_and_cap(self):
        seen=[]
        def handler(req):
            seen.append((str(req.url),json.loads(req.content)))
            return httpx.Response(200,json=self.success(model='mistral-small-2603'))
        c=CourseClient('mistral','mistral-small-2603','test-mistral',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(seen[0][0],'https://api.mistral.ai/v1/chat/completions');self.assertEqual(seen[0][1]['max_tokens'],512)
        self.assertNotIn('reasoning_effort',seen[0][1])
    def test_gemini_usage_excludes_hidden_text_but_prices_reasoning(self):
        class Fake:
            def generate_content(self,**kw):
                self.kw=kw
                return NS(candidates=[NS(content=NS(parts=[NS(text='hidden',thought=True),NS(text='{"ok":true}',thought=False)]),finish_reason='STOP')],usage_metadata={'prompt_token_count':10,'response_token_count':5,'thoughts_token_count':15,'total_token_count':30},model_version='gemini-3.8-flash',response_id='g1')
        fake=Fake();c=CourseClient('gemini','gemini-3.8-flash','test',gemini_client=NS(models=fake))
        r=c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(r.text,'{"ok":true}');self.assertEqual(r.metadata['billable_output_tokens'],20)
        self.assertNotIn('temperature',fake.kw['config']);self.assertEqual(fake.kw['config']['thinking_config'],{'thinking_level':'low'})
        self.assertAlmostEqual(r.metadata['estimated_cost_usd'],.0000825)
    def test_truncation_is_explicit(self):
        c=self.client(lambda _:httpx.Response(200,json=self.success(choices=[{'message':{'content':'{'},'finish_reason':'length'}])))
        with self.assertRaises(AdapterError) as raised:
            c.generate_content(model=c.model_id,contents='x')
        self.assertEqual(raised.exception.category,'output_truncated')
        self.assertEqual(len(c.records),2)
        self.assertTrue(c.records[-1]['truncated'])
        self.assertIsNone(c.records[-1]['json_parse_result'])
    def test_unsupported_setting_is_a_programming_error(self):
        c=self.client(lambda _:self.fail('No request'))
        with self.assertRaises(ValueError):c.generate_content(model=c.model_id,contents='x',config={'tools':[]})

if __name__=='__main__':unittest.main()
