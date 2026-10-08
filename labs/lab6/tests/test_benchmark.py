import copy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import common as c
import run_benchmark as b
import audit_prices as prices


def quote():
    return {'observed_at':datetime.now(timezone.utc).isoformat(),'source':prices.BASE+'/models',
            'models':{m:{'status':'CATALOG_AVAILABLE','ceilings_usd_per_million':{'prompt':1,'completion':2}}
                      for m in c.MODELS}}


def state(offline=False):
    return {'run_id':'mock-benchmark','fingerprint':c.fingerprint(),'frozen_lab5':c.verify_frozen(),
            'offline':offline,'budget_limit_usd':5,'accounted_usd':0,'reservations':[],
            'attempt_records':[],'rows':{},'pending':None,'execution_order':c.execution_order(),'price_audit':quote()}


class BenchmarkTests(unittest.TestCase):
    def test_frozen_hashes(self):self.assertEqual(len(c.verify_frozen()['sha256']),8)

    def test_exact_four_models(self):
        self.assertEqual(c.MODELS,('deepseek/deepseek-v4.1-flash','z-ai/glm-5.3','moonshotai/kimi-k3','xiaomi/mimo-v2.5-pro'))

    def test_160_unique_rotating_conditions(self):
        order=c.execution_order();self.assertEqual(len(order),160);self.assertEqual(len({c.row_key(r) for r in order}),160)
        for i in range(0,160,4):
            group=order[i:i+4];self.assertEqual({r['model'] for r in group},set(c.MODELS))
            self.assertEqual(len({(r['scenario_id'],r['mode']) for r in group}),1)
        self.assertNotEqual(order[0]['model'],order[4]['model'])

    def test_smoke_rows_prioritized(self):
        self.assertTrue(all(r['scenario_id'] in c.lab5.SMOKE for r in c.execution_order()[:16]))
        self.assertTrue(all(r['scenario_id'] not in c.lab5.SMOKE for r in c.execution_order()[16:]))

    def test_same_application_corpus_schemas_and_policy(self):
        self.assertEqual(c.lab5.DECODING,{'max_output_tokens':2048,'temperature':0,'response_format':{'type':'json_object'},'reasoning_effort':'low'})
        self.assertIs(c.lab5.messages,c.arena.messages)
        self.assertEqual(c.arena.VULNERABLE_SCHEMA,c.arena.HARDENED_SCHEMA)
        self.assertEqual(json.loads((c.arena.LAB/'data/response_schema.json').read_text()),c.arena.SCHEMA)

    def test_pricing_stale_or_future_rejected(self):
        for delta in (timedelta(days=-2),timedelta(days=1)):
            q=quote();q['observed_at']=(datetime.now(timezone.utc)+delta).isoformat()
            with self.assertRaises(ValueError):prices.validate_quote(q)

    def test_pricing_invalid_ceiling(self):
        for value in (-1,float('nan'),float('inf'),True):
            q=quote();q['models'][c.MODELS[0]]['ceilings_usd_per_million']['prompt']=value
            with self.assertRaises(ValueError):prices.validate_quote(q)

    def test_endpoint_review_and_overrides(self):
        eps=[{'status':0,'provider_name':'Local Fixture','supported_parameters':list(prices.REQUIRED_PARAMETERS),
              'pricing':{'prompt':'0.000001','completion':'0.000002','overrides':[{'completion':'0.000003'}]}}]
        result=prices.analyze_model({'pricing':eps[0]['pricing']},eps)
        self.assertEqual(result['ceilings_usd_per_million'],{'prompt':1,'completion':3})
        eps[0]['status']=-5
        self.assertEqual(prices.analyze_model({},eps)['status'],'MODEL_UNAVAILABLE')

    def test_global_cap_durable_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=state();p=Path(tmp)/'state.json';budget=b.RunBudget(s,p);budget.reserve(4.9)
            self.assertEqual(json.loads(p.read_text())['accounted_usd'],4.9)
            with self.assertRaises(b.AdapterError):budget.reserve(.2)
            budget.settle(4.9,None);self.assertEqual(s['accounted_usd'],4.9)

    def test_invalid_global_budget_cli(self):
        for value in ('0','-1','5.01','inf','nan'):
            with self.assertRaises(SystemExit):b.main(['--offline','--budget',value])

    def exercise(self, model, *, returned=None, finish='stop', cost=.001):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)/'state.json';s=state()
        item={'model':model,'scenario_id':'LLM06-B1','mode':'hardened'};s['pending']=c.row_key(item)
        case=next(x for x in c.arena.scenarios() if x['id']==item['scenario_id']);seen=[]
        def handler(req):
            seen.append(json.loads(req.content))
            return httpx.Response(200,json={'model':returned or model,'provider':'Fixture Backend',
                'choices':[{'finish_reason':finish,'message':{'content':c.arena.fixture(case),'reasoning':'HIDDEN THOUGHT TEXT'}}],
                'usage':{'prompt_tokens':20,'completion_tokens':30,'completion_tokens_details':{'reasoning_tokens':10},'cost':cost}})
        def factory(provider,model,key,**kwargs):
            return b.PricedClient(provider,model,'fake-benchmark-key',http_client=httpx.Client(transport=httpx.MockTransport(handler)),**kwargs)
        with patch.dict(os.environ,{'LLM_OFFLINE':'0'}):row=b.execute(s,item,b.RunBudget(s,p),p,client_type=factory)
        return row,s,p,seen

    def test_four_model_wire_parity_and_identity(self):
        bodies=[]
        for model in c.MODELS:
            row,_,_,seen=self.exercise(model);self.assertEqual(row['returned_model'],model)
            body=seen[0];self.assertEqual(body.pop('model'),model);self.assertNotIn('tools',body)
            self.assertNotEqual(body.get('response_format',{}).get('type'),'json_schema');bodies.append(body)
        self.assertTrue(all(x==bodies[0] for x in bodies))

    def test_mismatch_for_every_model(self):
        for model in c.MODELS:
            row,_,_,_=self.exercise(model,returned='wrong/model')
            self.assertEqual(row['error_category'],'model_identity_unverified');self.assertFalse(row['evaluation_valid'])

    def test_backend_usage_cost_and_ceiling(self):
        row,s,_,seen=self.exercise(c.MODELS[0]);self.assertEqual(row['serving_backend'],'Fixture Backend')
        self.assertEqual(row['reasoning_tokens'],10);self.assertAlmostEqual(s['accounted_usd'],.001)
        self.assertEqual(seen[0]['provider']['max_price'],{'prompt':1,'completion':2,'request':0})
        self.assertTrue(seen[0]['provider']['allow_fallbacks'])

    def test_reasoning_and_secret_excluded(self):
        _,_,p,_=self.exercise(c.MODELS[0]);text=''.join(f.read_text() for f in p.parent.rglob('*.json'))
        self.assertNotIn('HIDDEN THOUGHT TEXT',text);self.assertNotIn('fake-benchmark-key',text)
        self.assertNotIn('raw_text',text)

    def test_same_bounded_truncation(self):
        for model in c.MODELS:
            row,_,_,seen=self.exercise(model,finish='length')
            self.assertEqual([x['max_tokens'] for x in seen],[2048,4096])
            self.assertTrue(row['output_truncated']);self.assertFalse(row['evaluation_valid'])
            self.assertAlmostEqual(row['cost_usd'],.002)

    def test_unknown_billing_is_reserved(self):
        row,s,_,_=self.exercise(c.MODELS[0],cost=None)
        self.assertIsNone(row['cost_usd']);self.assertGreater(s['accounted_usd'],0)
        self.assertAlmostEqual(row['reserved_cost_usd'],s['accounted_usd'])

    def test_partial_retry_billing_preserves_known_and_unknown_costs(self):
        row,s,p,_=self.exercise(c.MODELS[3])
        known=s['attempt_records'][0]
        missing=copy.deepcopy(known);missing['number']=0
        missing['metadata'].update(cost_usd=None,budget_reserved_usd=.01,category='transport_error')
        s['attempt_records'].insert(0,missing)
        s['reservations'].append({'number':0,'row_key':s['pending'],'reserved_usd':.01,'cost_usd':None,'settled':True})
        s['accounted_usd']+=.01
        b.event_totals(row,[missing['metadata'],known['metadata']]);b.save_row(s,row,p)
        report=b.export(s,p.parent)
        self.assertIsNone(row['cost_usd']);self.assertEqual(row['request_count'],2)
        self.assertAlmostEqual(report['billing_by_model'][c.MODELS[3]]['actual_cost_usd'],.001)
        self.assertAlmostEqual(report['budget']['accounted_usd'],.011)
        self.assertEqual(report['budget']['unknown_cost_attempts'],1)
        self.assertIsNone(report['model_metrics'][c.MODELS[3]]['hardened']['cost_per_successful_benign_task_usd'])

    def test_receipt_recovers_completed_row_without_repay(self):
        row,s,p,_=self.exercise(c.MODELS[0]);before=len(s['reservations']);b.recover(s,p)
        self.assertEqual(len(s['reservations']),before);self.assertEqual(len(s['rows']),1)
        self.assertTrue(next(iter(s['rows'].values()))['benign_task_success'])

    def test_uncertain_dispatch_skipped_preserving_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=state();p=Path(tmp)/'state.json';s['pending']=c.row_key(s['execution_order'][0]);b.RunBudget(s,p).reserve(.02)
            b.recover(s,p);r=next(iter(s['rows'].values()))
            self.assertEqual(r['status'],'interrupted_not_repaid');self.assertFalse(r['evaluation_valid'])
            self.assertEqual(s['accounted_usd'],.02);self.assertIsNone(r['cost_usd'])

    def test_resume_160_offline_and_no_model_differences(self):
        with tempfile.TemporaryDirectory() as tmp,patch('builtins.print'):
            self.assertEqual(b.main(['--offline','--smoke','--output',tmp]),0)
            self.assertEqual(b.main(['--offline','--resume','--output',tmp]),0)
            before=json.loads((Path(tmp)/'state.json').read_text());b.main(['--offline','--resume','--output',tmp])
            after=json.loads((Path(tmp)/'state.json').read_text());self.assertEqual(before,after)
            self.assertEqual(len(after['rows']),160);self.assertEqual(after['reservations'],[])
            doc=json.loads((Path(tmp)/'benchmark.json').read_text())
            for model in c.MODELS:
                self.assertEqual(doc['model_metrics'][model]['vulnerable']['attack_success']['numerator'],16)
                self.assertEqual(doc['model_metrics'][model]['hardened']['attack_success']['numerator'],0)

    def test_original_result_schema(self):
        row,_,_,_=self.exercise(c.MODELS[0]);schema=json.loads((c.arena.LAB/'data/result_schema.json').read_text())
        c.arena.jsonschema.validate(row,schema)

    def test_failure_denominators_and_cost_per_benign(self):
        row,_,_,_=self.exercise(c.MODELS[0]);bad=copy.deepcopy(row);b.failed(bad,'transport_error')
        bad.update(benign_task_success=False,cost_usd=None,reserved_cost_usd=.01)
        m=c.comparison([row,bad])[c.MODELS[0]]['hardened']
        self.assertEqual(m['benign_task_success']['denominator'],1)
        self.assertIsNone(m['cost_per_successful_benign_task_usd'])
        self.assertEqual(m['failure_rows'],1)


if __name__=='__main__':unittest.main()
