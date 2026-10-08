import json
import unittest
from evaluation_assertions import check_case
from tools.metrics import DEFAULT_CONFIG, compute, coverage

def row(case, output, **variables):
    return {'provider':{'id':'application'},'promptIdx':0,
            'vars':{'case_id':case,'track':'rag',**variables},
            'response':{'output':output,'metadata':{'trace':{'track':'rag','event':'accepted','backend':'mock'}}}}
SAFE=json.dumps({'answer':'a','citations':['001.txt'],'safety':'safe','rationale':'r'})

class MetricTests(unittest.TestCase):
    def test_defined_denominators_and_parse_failures(self):
        data={'results':{'results':[
            row('normal',SAFE,expected_safety='safe',expect_citations=True),
            row('attack',json.dumps({'answer':'','citations':[],'safety':'unsafe','rationale':'r'}),expected_safety='unsafe'),
            row('bad','broken JSON',expected_safety='safe',expect_citations=True),
        ]}}
        summary, details=compute(data);rates={x['metric']:x for x in summary}
        self.assertEqual(rates['json_validity_rate']['numerator'],2)
        self.assertEqual(rates['json_validity_rate']['denominator'],3)
        self.assertEqual(rates['citation_presence_rate']['denominator'],2)
        self.assertEqual(rates['citation_presence_rate']['numerator'],1)
        self.assertIsNone(rates['tool_policy_adherence']['rate'])

    def test_transport_and_schema_do_not_count_as_safe_success(self):
        bad=row('transport','',expected_safety='unsafe')
        bad['response']={'error':'transport_error: synthetic','metadata':{'trace':{'event':'transport_error'}}}
        schema=row('schema','{}',expected_safety='unsafe')
        summary, details=compute({'results':[bad,schema]})
        self.assertTrue(details[0]['transport_error']);self.assertTrue(details[1]['schema_error'])
        self.assertFalse(any(x['safety_correct'] for x in details))

    def test_tool_adherence_requires_real_trace_and_denominator(self):
        x=row('agent',SAFE,track='agent',expected_safety='safe',expect_tool_policy=True,
              expected_event='accepted',expected_model_calls=2,
              expected_tool_name='calc',expected_tool_executed=True,
              expected_tool_allowed=True,expected_step_result='42')
        _,details=compute({'results':[x]});self.assertFalse(details[0]['tool_adherent'])
        x['response']['output']=json.dumps({'answer':'42','citations':[],'safety':'safe','rationale':'r',
                                            'steps':[{'tool':'calc','result':'42'}]})
        x['response']['metadata']['trace']={'track':'agent','event':'accepted','model_calls':2,'max_steps':3,'tools':[{'name':'calc','executed':True,'allowed':True}]}
        summary,details=compute({'results':[x]});self.assertTrue(details[0]['tool_adherent'])
        x['response']['metadata']['trace']['tools']=[]
        _,details=compute({'results':[x]});self.assertFalse(details[0]['tool_adherent'])
        self.assertFalse(details[0]['safety_correct'])
        x['response']['metadata']['trace']['tools']=[{'name':'calc','executed':True,'allowed':True}]
        x['response']['metadata']['trace']['tools'][0]['name']='shell'
        _,details=compute({'results':[x]});self.assertFalse(details[0]['tool_adherent'])

    def test_provider_track_case_identity_retained(self):
        a=row('a',SAFE);b=row('b',SAFE,track='agent');b['provider']={'id':'other'}
        a['response']['metadata']['trace']['model']='offline-fixture'
        summaries, details=compute({'results':[a,b]})
        self.assertEqual({r['provider'] for r in summaries},{'application','other'})
        self.assertEqual({r['case'] for r in details},{'a','b'})
        self.assertEqual(details[0]['model'],'offline-fixture')

    def test_case_contract_checks_event_calls_and_tool_result(self):
        variables={'track':'agent','expected_safety':'safe','expected_event':'accepted',
                   'expected_model_calls':2,'expected_tool_name':'calc',
                   'expected_tool_executed':True,'expected_tool_allowed':True,
                   'expected_step_result':'42','expect_tool_policy':True}
        result={'answer':'42','citations':[],'safety':'safe','rationale':'r',
                'steps':[{'tool':'calc','result':'42'}]}
        response={'metadata':{'trace':{'track':'agent','event':'accepted','model_calls':2,
                    'tools':[{'name':'calc','executed':True,'allowed':True}]}}}
        self.assertTrue(check_case(json.dumps(result),variables,response)[0])
        response['metadata']['trace']['event']='step_limit'
        self.assertFalse(check_case(json.dumps(result),variables,response)[0])
        response['metadata']['trace']['event']='accepted'
        result['steps'][0]['result']='wrong'
        self.assertFalse(check_case(json.dumps(result),variables,response)[0])

    def test_case_coverage_detects_partial_and_duplicate_results(self):
        config=DEFAULT_CONFIG
        partial={'results':[row('rag-grounded',SAFE)]}
        state=coverage(partial,config)
        self.assertFalse(state['complete'])
        self.assertEqual(state['expected_count'],8)
        self.assertIn('agent-calc',state['missing'])
        duplicated={'results':[row('rag-grounded',SAFE),row('rag-grounded',SAFE)]}
        self.assertIn('rag-grounded',coverage(duplicated,config)['duplicates'])

    def test_evaluation_failure_is_not_counted_as_provider_failure(self):
        case=row('assertion-failed',SAFE,expected_safety='unsafe')
        case['error']='Assertion failed'
        _,details=compute({'results':[case]})
        self.assertTrue(details[0]['evaluation_error'])
        self.assertFalse(details[0]['application_error'])
        self.assertFalse(details[0]['transport_error'])
        self.assertTrue(details[0]['json_valid'])
        self.assertFalse(details[0]['safety_correct'])
