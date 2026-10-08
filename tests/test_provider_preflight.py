import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx
from course_llm import CourseClient, Budget, AdapterError
from tools.provider_preflight import run_checks, main, strict_json, valid_model, write_receipt

CORE = ['READY', '{"ready":true,"course":"llm-security"}', '{"risk":"hardcoded_secret","is_safe":false,"mitigation":"use_secret_store"}']

class SetupTests(unittest.TestCase):
    def setUp(self):
        e=patch.dict(os.environ,{'LLM_OFFLINE':'0'});e.start();self.addCleanup(e.stop)
    def client(self, outputs, provider='openrouter', model='liquid/lfm-2.5-2.6b:free'):
        values=iter(outputs);self.sent=[]
        def handler(req):
            self.sent.append(req)
            v=next(values)
            if isinstance(v,int):return httpx.Response(v,json={'error':{'message':'private-test-key'}})
            if isinstance(v,tuple):v,finish=v
            else:finish='stop'
            return httpx.Response(200,json={'model':model,'choices':[{'message':{'content':v},'finish_reason':finish}]})
        c=CourseClient(provider,model,'private-test-key',max_retries=0,budget=Budget(max_attempts=7),http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(c.close)
        return c
    def test_core_ready_is_three_calls_not_full(self):
        c=self.client(CORE);r,reason=run_checks(c)
        self.assertTrue(r['CORE_READY']);self.assertFalse(r['FULL_READY']);self.assertIsNone(reason)
        self.assertEqual(len(self.sent),3)
        for req in self.sent:
            body=json.loads(req.content)
            self.assertEqual(body['model'],'liquid/lfm-2.5-2.6b:free')
            self.assertTrue(body['provider']['allow_fallbacks'])
            self.assertTrue(body['provider']['require_parameters'])
            self.assertEqual(body['max_tokens'],256)
        self.assertIsNone(c.records[0]['estimated_cost_usd'])
    def test_actual_agent_cycle_and_context_make_full(self):
        c=self.client(CORE+['{"marker":"COURSE_CONTEXT_42"}', '{"tool":{"name":"calc","args":{"expr":"15+27"}}}', '{"answer":"42","citations":[],"safety":"safe","rationale":"Calculated with the allowed tool."}'])
        r,reason=run_checks(c,full=True)
        self.assertTrue(r['FULL_READY'],reason);self.assertEqual(len(self.sent),6)
        self.assertGreater(len(json.loads(self.sent[3].content)['messages'][0]['content']),16384)
    def test_failed_optional_preserves_core(self):
        r,reason=run_checks(self.client(CORE+['{}']),full=True)
        self.assertTrue(r['CORE_READY']);self.assertFalse(r['FULL_READY'])
        self.assertEqual(r['long_context_status'],'FAIL');self.assertEqual(r['tool_status'],'NOT RUN')
    def test_auth_failure_stops_no_retry_or_key_in_receipt(self):
        r,reason=run_checks(self.client([401]))
        self.assertEqual(len(self.sent),1);self.assertEqual(reason,'AUTH_401')
        self.assertFalse(r['CORE_READY']);self.assertNotIn('private-test-key',json.dumps(r))
    def test_json_failure_blocks_security_and_no_coercion(self):
        for bad in ['```json\n{}\n```','{"ready":1,"course":"llm-security"}','{"ready":true,"ready":false}']:
            r,_=run_checks(self.client(['READY',bad]))
            self.assertEqual(r['json_status'],'FAIL');self.assertEqual(r['security_case_status'],'NOT RUN')
    def test_strict_parser_rejects_nonfinite_and_duplicate(self):
        for raw in ['{"x":NaN}','{"x":1,"x":2}']:
            with self.assertRaises(ValueError):strict_json(raw)
    def test_receipt_allowlist_and_no_overwrite(self):
        r,_=run_checks(self.client(CORE))
        expected={'provider','model_id','requested_model','timestamp','environment_status','credential_status','connectivity_status','model_status','json_status','security_case_status','long_context_status','tool_status','returned_model','serving_backend','serving_backends','latency_seconds','prompt_tokens','completion_tokens','reasoning_tokens','cost_usd','finish_reason','CORE_READY','FULL_READY'}
        self.assertEqual(set(r),expected)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'receipt.json';write_receipt(p,r)
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):write_receipt(p,r)
    def test_offline_and_go_do_not_read_keys_or_call(self):
        for provider,offline_value,model in [('nvidia','1','openai/gpt-oss-20b'),('opencode-go','0','glm-5.3-flash')]:
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LLM_OFFLINE':offline_value}),patch('dotenv.dotenv_values',side_effect=AssertionError('No key lookup')),contextlib.redirect_stdout(io.StringIO()) as out:
                code=main(['--provider',provider,'--model',model,'--receipt',d+'/r.json'])
                self.assertEqual(code,2);self.assertIn('BLOCKED',out.getvalue())
                self.assertFalse(json.loads(Path(d+'/r.json').read_text())['CORE_READY'])
    def test_compatible_endpoint_and_alibaba_no_thinking(self):
        c=self.client(['READY'],provider='alibaba',model='qwen-plus');c.complete([{'role':'user','content':'test'}])
        self.assertEqual(str(self.sent[0].url),'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions')
        self.assertIs(json.loads(self.sent[0].content)['enable_thinking'],False)
    def test_model_ids_accept_paid_and_free_but_reject_credentials(self):
        for model in ['deepseek/deepseek-v4.1-flash','deepseek/deepseek-v4-flash-0731:free']:
            self.assertTrue(valid_model('openrouter',model))
            CourseClient('openrouter',model,'test').close()
        for secret in ['sk-private-secret','sk-or-private-secret','nvapi-private-secret','deepseek/sk-or-private-secret']:
            self.assertFalse(valid_model('openrouter',secret))
    def test_model_identity_mismatch_cannot_pass(self):
        c=self.client(CORE)
        original=c.complete
        def wrong(*args,**kwargs):
            response=original(*args,**kwargs)
            response.metadata['returned_model_id']='different/model'
            return response
        c.complete=wrong
        r,reason=run_checks(c)
        self.assertFalse(r['CORE_READY']);self.assertEqual(reason,'MODEL_NOT_FOUND')
        self.assertEqual(len(self.sent),1)
    def test_secret_like_model_rejected_without_receipt(self):
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):main(['--provider','nvidia','--model','sk-private-secret','--receipt',d+'/r.json'])
            self.assertFalse(Path(d+'/r.json').exists())
    def test_malformed_provider_envelope_returns_failure(self):
        c=CourseClient('openrouter','liquid/lfm-2.5-2.6b:free','test',max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=['bad']))))
        self.addCleanup(c.close)
        r,reason=run_checks(c)
        self.assertEqual(reason,'UNKNOWN_PROVIDER_ERROR');self.assertFalse(r['CORE_READY'])
    def test_cloudflare_account_not_in_receipt(self):
        with patch.dict(os.environ,{'CLOUDFLARE_ACCOUNT_ID':'a'*32}):
            c=self.client(CORE,provider='cloudflare',model='@cf/meta/llama-3.1-8b-instruct-fp8-fast');r,_=run_checks(c)
            self.assertTrue(r['CORE_READY']);self.assertNotIn('a'*32,json.dumps(r))
            self.assertIn('/accounts/'+'a'*32+'/ai/v1/chat/completions',str(self.sent[0].url))

    def test_truncation_retries_once_with_512_and_reports_exhaustion(self):
        c=self.client([('','length')]+CORE)
        r,reason=run_checks(c)
        self.assertTrue(r['CORE_READY'],reason)
        self.assertEqual([json.loads(req.content)['max_tokens'] for req in self.sent],[256,512,256,256])
        c=self.client([('','length'),('','length')])
        r,reason=run_checks(c)
        self.assertEqual(reason,'OUTPUT_TRUNCATED')
        self.assertEqual(r['connectivity_status'],'FAIL')

    def test_safe_openrouter_metadata_in_receipt(self):
        outputs=iter(CORE)
        def handler(_):
            return httpx.Response(200,json={
                'model':'deepseek/deepseek-v4.1-flash','provider':'InferenceNet',
                'usage':{'prompt_tokens':30,'completion_tokens':12,'cost':0.0001,
                         'completion_tokens_details':{'reasoning_tokens':7}},
                'choices':[{'message':{'content':next(outputs),'reasoning':'private-thought'},
                            'finish_reason':'stop'}]})
        c=CourseClient('openrouter','deepseek/deepseek-v4.1-flash','private-test-key',max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(c.close)
        r,reason=run_checks(c)
        self.assertTrue(r['CORE_READY'],reason)
        self.assertEqual(r['serving_backend'],'InferenceNet')
        self.assertEqual(r['serving_backends'],['InferenceNet'])
        self.assertEqual(r['reasoning_tokens'],21)
        self.assertAlmostEqual(r['cost_usd'],0.0003)
        self.assertNotIn('private-thought',json.dumps(r))
        self.assertNotIn('private-test-key',json.dumps(r))

    def test_direct_script_and_module_work_without_pythonpath(self):
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env.pop('PYTHONPATH',None)
        env['LLM_OFFLINE']='1'
        with tempfile.TemporaryDirectory() as folder:
            for command in ([sys.executable,'tools/provider_preflight.py'],
                            [sys.executable,'-m','tools.provider_preflight']):
                receipt=Path(folder)/(str(len(list(Path(folder).glob('*.json'))))+'.json')
                result=subprocess.run(command+['--provider','openrouter','--model','deepseek/deepseek-v4.1-flash',
                                          '--receipt',str(receipt)],cwd=root,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertIn('OFFLINE_BLOCKED',result.stdout)
                self.assertTrue(receipt.exists())
                self.assertNotIn('Traceback',result.stderr)

    def test_missing_dependency_is_friendly(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            receipt=Path(folder)/'missing.json'
            env=os.environ.copy();env.pop('PYTHONPATH',None)
            result=subprocess.run([sys.executable,'-S','tools/provider_preflight.py','--provider','openrouter',
                                   '--model','deepseek/deepseek-v4.1-flash','--receipt',str(receipt)],
                                  cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertIn('DEPENDENCY_MISSING',result.stdout)
            self.assertNotIn('Traceback',result.stderr)

if __name__=='__main__':unittest.main()
