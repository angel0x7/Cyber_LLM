import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/'src'))
import arena as a
import run_arena as runner
from course_llm.client import AdapterError
from course_llm.client import CourseClient


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.cases = a.scenarios()

    def case(self, id):
        return next(c for c in self.cases if c['id'] == id)

    def row(self, id, mode='vulnerable', value=None):
        c = self.case(id)
        row = a.blank(c, mode, 'test', 'openrouter', a.MODEL, True)
        row.update(model_called=True, latency_ms=0)
        return a.evaluate(c, mode, json.dumps(value) if value else a.fixture(c), row)

    def test_unique_twenty(self):
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(len({c['id'] for c in self.cases}), 20)

    def test_sixteen_plus_four(self):
        self.assertEqual(sum(c['kind']=='adversarial' for c in self.cases), 16)
        self.assertEqual(sum(c['kind']=='benign' for c in self.cases), 4)

    def test_family_counts(self):
        for f in ('LLM01', 'LLM02', 'LLM05', 'LLM06'):
            cases = [c for c in self.cases if c['owasp_id']==f]
            self.assertEqual(len(cases), 5)
            self.assertEqual(sum(c['kind']=='adversarial' for c in cases), 4)

    def test_required_dataset_fields_and_no_private_notes(self):
        for c in self.cases:
            self.assertLessEqual({'id','owasp_id','family','title','kind','target_component',
                'user_input','synthetic_context','security_property','success_definition'}, set(c))
            self.assertNotIn('notes_private', c)

    def test_identical_schema(self):
        self.assertEqual(a.VULNERABLE_SCHEMA, a.HARDENED_SCHEMA)
        self.assertEqual(json.loads((LAB/'data/response_schema.json').read_text()), a.SCHEMA)

    def test_canonical_inputs_unchanged(self):
        original = copy.deepcopy(self.cases)
        for c in self.cases:
            before = a.messages(c)
            for mode in a.MODES:
                a.input_block(c, mode)
                self.row(c['id'], mode)
                self.assertEqual(before, a.messages(c))
        self.assertEqual(self.cases, original)

    def test_successful_override_is_not_labeled_safe(self):
        row=self.row('LLM01-A1')
        self.assertTrue(row['attack_success'])
        self.assertEqual(row['application_outcome'],'model_unsafe_decision')

    def test_canary_literal_all_locations(self):
        for n in range(1,5):
            self.assertTrue(self.row(f'LLM02-A{n}')['canary_leak'])
            guarded = self.row(f'LLM02-A{n}', 'hardened')
            self.assertFalse(guarded['canary_leak'])
            self.assertTrue(guarded['model_canary_emitted'])

    def test_canary_action_arguments(self):
        value = {'decision':'answer','response':'ok','action':{'tool':'shell','arguments':{'x':a.CANARY}}}
        row = self.row('LLM02-A1', 'hardened', value)
        self.assertIsNone(row['tool_receipt'])
        self.assertFalse(row['canary_leak'])

    def test_denied_tools_no_real_execution(self):
        with (patch('subprocess.run', side_effect=AssertionError('Must not execute')),
              patch('os.system', side_effect=AssertionError('Must not execute'))):
            for tool in a.DENIED:
                for mode in a.MODES:
                    receipt = a.dispatch({'tool':tool,'arguments':{}}, mode)
                    self.assertFalse(receipt['real_side_effect'])
                    self.assertEqual(receipt['blocked'], mode=='hardened')

    def test_unauthorized_request_vs_virtual_dispatch(self):
        for n in range(1,5):
            v, h = self.row(f'LLM06-A{n}'), self.row(f'LLM06-A{n}', 'hardened')
            self.assertTrue(v['unauthorized_tool_requested'] and h['unauthorized_tool_requested'])
            self.assertTrue(v['unauthorized_tool_executed'])
            self.assertFalse(h['unauthorized_tool_executed'])
            self.assertTrue(h['locally_blocked'])

    def test_allowed_calculator(self):
        self.assertEqual(a.calculator('2+3*4'), 14)
        for expression in ('__import__("os")', '2**100', '1/0', '9'*100):
            with self.assertRaises((ValueError, ZeroDivisionError)):
                a.calculator(expression)

    def test_allowed_search(self):
        self.assertIn('18:00', a.dispatch({'tool':'search_corpus','arguments':{'query':'hours'}}, 'hardened')['result'])

    def test_step_cap(self):
        self.assertTrue(a.dispatch({'tool':'calculator','arguments':{'expression':'2+3'}}, 'hardened', 1)['blocked'])

    def test_unsafe_output_handling(self):
        for n in range(1,5):
            v, h = self.row(f'LLM05-A{n}'), self.row(f'LLM05-A{n}', 'hardened')
            self.assertTrue(v['unsafe_output_accepted'])
            self.assertTrue(h['unsafe_output_blocked'])
            self.assertNotIn('<script>', h['visible_response'])

    def test_benign_controls(self):
        for c in self.cases:
            if c['kind']=='benign':
                for mode in a.MODES:
                    row = self.row(c['id'], mode)
                    self.assertTrue(row['benign_task_success'])
                    self.assertFalse(row['false_positive_block'])

    def test_schema_invalid_is_not_defense(self):
        row = self.row('LLM01-A1', value={'decision':'safe'})
        self.assertEqual(row['application_outcome'], 'schema_error')
        self.assertFalse(row['evaluation_valid'])
        self.assertFalse(row['locally_blocked'])

    def test_metrics_denominators(self):
        good, bad = self.row('LLM01-A1'), self.row('LLM01-A1', value={'bad':True})
        m = a.metrics([good,bad])['all']
        self.assertEqual(m['attack_success'], {'numerator':1,'denominator':1,'rate':1})
        self.assertEqual(m['failure_rows'], 1)
        self.assertIsNone(m['benign_task_success']['rate'])
        self.assertIsNone(a.metrics([])['all']['latency_p95_ms'])

    def test_cost_aggregation_unknown(self):
        rows = [self.row('LLM01-A1'), self.row('LLM01-A2')]
        rows[0]['cost_usd'] = .01; rows[1]['cost_usd'] = None; rows[1]['reserved_cost_usd'] = .02
        m = a.metrics(rows)['all']
        self.assertEqual(m['actual_cost_usd'], .01)
        self.assertEqual(m['reserved_cost_usd'], .02)
        self.assertEqual(m['unknown_cost_rows'], 1)

    def test_durable_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            s = {'budget_limit_usd':.01,'accounted_usd':0,'attempts':0}
            b = runner.DurableBudget(s,path); b.reserve(.007); b.settle(.007,None)
            self.assertEqual(json.loads(path.read_text())['accounted_usd'], .007)
            with self.assertRaises(AdapterError): b.reserve(.004)
            b.settle(.007,.002)
            self.assertAlmostEqual(json.loads(path.read_text())['accounted_usd'], .002)

    def test_budget_invalid_cli(self):
        for amount in ('nan','inf','-1','1.01'):
            with self.assertRaises(SystemExit): runner.main(['--offline','--budget',amount])

    def test_exact_model(self):
        with self.assertRaises(SystemExit): runner.main(['--offline','--model','other/model'])

    def test_no_raw_output_or_hidden_reasoning_metadata(self):
        self.assertTrue(set(runner.SAFE_METADATA).isdisjoint({'raw_text','reasoning','reasoning_content','api_key','messages','headers'}))

    def test_offline_resume_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ['--offline','--output',tmp]
            with patch('builtins.print'):
                self.assertEqual(runner.main(args+['--smoke']), 0)
                self.assertEqual(runner.main(args+['--resume']), 0)
                before = json.loads((Path(tmp)/'state.json').read_text())
                self.assertEqual(runner.main(args+['--resume']), 0)
            after = json.loads((Path(tmp)/'state.json').read_text())
            self.assertEqual(before, after)
            self.assertEqual(len(after['rows']), 40)
            self.assertEqual(after['attempts'], 0)
            self.assertFalse(any('key' in k.lower() for k in after))

    def test_interrupted_resume_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ['--offline','--output',tmp]
            with patch('builtins.print'): runner.main(args+['--smoke'])
            path=Path(tmp)/'state.json'; s=json.loads(path.read_text()); s['pending']='LLM01-A1:vulnerable'; runner.atomic(path,s)
            with self.assertRaises(SystemExit): runner.main(args+['--resume'])

    def test_changed_source_resume_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=['--offline','--output',tmp]
            with patch('builtins.print'): runner.main(args+['--smoke'])
            with patch.object(runner,'fingerprint',return_value='changed'):
                with self.assertRaises(SystemExit): runner.main(args+['--resume'])

    def test_fixture_count_and_common_schema(self):
        fixtures=json.loads((LAB/'data/offline_responses.json').read_text())
        self.assertEqual(set(fixtures), {c['id'] for c in self.cases})
        for value in fixtures.values(): a.jsonschema.validate(value,a.SCHEMA)

    def test_result_schema(self):
        schema=json.loads((LAB/'data/result_schema.json').read_text())
        for c in self.cases:
            for mode in a.MODES: a.jsonschema.validate(self.row(c['id'],mode),schema)

    def live_fixture(self, *, returned=a.MODEL, finish='stop', cost=.001):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            state={'budget_limit_usd':1, 'accounted_usd':0, 'attempts':0, 'attempt_records':[],
                   'run_id':'mock-only', 'provider':'openrouter', 'model':a.MODEL, 'offline':False}
            case=self.case('LLM05-B1')
            body={'model':returned,'provider':'Fixture Backend','choices':[{'finish_reason':finish,
                  'message':{'content':a.fixture(case),'reasoning':'HIDDEN-REASONING-MUST-NOT-PERSIST'}}],
                  'usage':{'prompt_tokens':100,'completion_tokens':80,'cost':cost,
                           'completion_tokens_details':{'reasoning_tokens':20}}}
            def factory(provider,model,key,**kwargs):
                return CourseClient(provider,model,'fake-private-key',
                    http_client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body))),**kwargs)
            with patch.dict(os.environ,{'LLM_OFFLINE':'0'}), patch.object(runner,'CourseClient',factory):
                row=runner.execute(case,'hardened',state,runner.DurableBudget(state,path),path)
            persisted=''.join(p.read_text() for p in Path(tmp).rglob('*.json'))
            return row,state,persisted

    def test_live_boundary_usage_and_secrets(self):
        row,state,persisted=self.live_fixture()
        self.assertEqual(row['returned_model'],a.MODEL)
        self.assertEqual(row['serving_backend'],'Fixture Backend')
        self.assertEqual(row['reasoning_tokens'],20)
        self.assertAlmostEqual(row['cost_usd'],.001)
        self.assertNotIn('HIDDEN-REASONING-MUST-NOT-PERSIST',persisted)
        self.assertNotIn('fake-private-key',persisted)
        self.assertTrue(row['benign_task_success'])

    def test_live_model_mismatch_is_provider_error(self):
        row,_,_=self.live_fixture(returned='wrong/model')
        self.assertEqual(row['error_category'],'model_identity_unverified')
        self.assertFalse(row['evaluation_valid'])
        self.assertEqual(row['application_outcome'],'provider_error')

    def test_live_truncation_is_not_defense(self):
        row,state,_=self.live_fixture(finish='length')
        self.assertEqual(row['request_count'],2)
        self.assertAlmostEqual(row['cost_usd'],.002)
        self.assertTrue(row['output_truncated'])
        self.assertFalse(row['evaluation_valid'])
        self.assertFalse(row['locally_blocked'])

    def test_live_unknown_cost_preserved(self):
        row,state,_=self.live_fixture(cost=None)
        self.assertIsNone(row['cost_usd'])
        self.assertGreater(row['reserved_cost_usd'],0)
        self.assertEqual(state['accounted_usd'],row['reserved_cost_usd'])


if __name__ == '__main__': unittest.main()
