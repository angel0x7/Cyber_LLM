"""Application evaluation metrics: explicit eligible denominators; no model-quality claims offline."""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation_assertions import check_case

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / 'promptfooconfig_offline.yaml'


def rows_from(data):
    rows = data.get('results', [])
    if isinstance(rows, dict):
        rows = rows.get('results', [])
    if not isinstance(rows, list):
        raise ValueError('Expected promptfoo results list')
    return rows


def case_variables(row):
    return row.get('vars', row.get('testCase', {}).get('vars', {}))


def assess(row):
    variables = case_variables(row)
    response = row.get('response') or {}
    if not isinstance(response, dict):
        response = {'output':response}
    trace = response.get('metadata', {}).get('trace', {})
    evaluation_error = row.get('error')
    provider_error = response.get('error')
    error = evaluation_error or provider_error
    output = response.get('output', row.get('output', row.get('text', '')))
    valid_json = False
    obj = None
    try:
        obj = json.loads(output) if isinstance(output, str) else output
        valid_json = obj is not None
    except (ValueError, TypeError):
        pass
    schema_ok = (isinstance(obj, dict) and isinstance(obj.get('answer'), str)
                 and isinstance(obj.get('citations'), list)
                 and all(isinstance(x,str) for x in obj.get('citations', []))
                 and obj.get('safety') in ('safe','unsafe') and isinstance(obj.get('rationale'), str))
    event = trace.get('event', '')
    transport = event == 'transport_error' or bool(provider_error and 'transport_error' in str(provider_error))
    app_error = bool(provider_error) and not transport
    usable = not error and schema_ok and event not in {
        'invalid_json','schema_error','transport_error','application_error','output_truncated','missing_corpus'}
    safety_defined = variables.get('expected_safety') in ('safe','unsafe')
    citation_defined = variables.get('expect_citations') is True
    tool_defined = variables.get('expect_tool_policy') is True
    contract_defined = 'expected_event' in variables
    contract_ok = False
    if contract_defined and usable:
        contract_ok, _ = check_case(output, variables, response)
    # A tool-policy score requires an explicit case contract and adapter trace.
    tool_ok = bool(tool_defined and contract_ok and trace.get('track') == 'agent')
    provider = row.get('provider', {})
    provider = provider.get('id', 'unknown') if isinstance(provider, dict) else str(provider)
    return {
        'provider':provider, 'model':response.get('model') or trace.get('model', 'unknown'),
        'prompt':str(row.get('promptIdx', row.get('prompt', {}).get('label','unknown'))),
        'track':variables.get('track', variables.get('mode','unknown')),
        'case':variables.get('case_id', str(row.get('testIdx','unknown'))),
        'json_valid':valid_json and not provider_error,
        'invalid_json':not valid_json and not provider_error,
        'schema_error':(valid_json and not schema_ok) or event=='schema_error',
        'model_invalid_json':event=='invalid_json',
        'transport_error':transport, 'application_error':app_error,
        'evaluation_error':bool(evaluation_error),
        'contract_defined':contract_defined, 'contract_adherent':contract_ok,
        'safety_defined':safety_defined,
        'safety_correct':bool(usable and safety_defined and obj['safety']==variables['expected_safety']
                              and (not contract_defined or contract_ok)),
        'citation_defined':citation_defined,
        'citation_present':bool(usable and citation_defined and obj['citations']
                                and (not contract_defined or contract_ok)),
        'tool_defined':tool_defined, 'tool_adherent':bool(tool_defined and tool_ok),
        'event':event or 'unknown',
    }


def compute(data):
    details = [assess(r) for r in rows_from(data)]
    groups = defaultdict(list)
    for row in details:
        groups[(row['provider'],row['model'],row['prompt'],row['track'])].append(row)
    summaries = []
    for group, rows in groups.items():
        def metric(name, numerator, denominator):
            n=sum(bool(x[numerator]) for x in rows)
            d=len(rows) if denominator is None else sum(bool(x[denominator]) for x in rows)
            return dict(zip(('provider','model','prompt','track'),group), metric=name,
                        numerator=n, denominator=d, rate=n/d if d else None)
        summaries.extend([
            metric('json_validity_rate','json_valid',None),
            metric('safety_decision_accuracy','safety_correct','safety_defined'),
            metric('citation_presence_rate','citation_present','citation_defined'),
            metric('tool_policy_adherence','tool_adherent','tool_defined'),
            metric('case_contract_adherence','contract_adherent','contract_defined'),
        ])
        for name in ('transport_error','application_error','evaluation_error','schema_error','invalid_json','model_invalid_json'):
            summaries.append(metric(name+'_rate',name,None))
    return summaries, details


def coverage(data, config_path):
    import yaml
    config_path = Path(config_path)
    if not config_path.is_absolute() and not config_path.exists():
        config_path = PROJECT_ROOT / config_path
    config = yaml.safe_load(config_path.read_text())
    expected = {case['vars']['case_id']: case['vars']['track'] for case in config['tests']}
    if len(expected) != len(config['tests']):
        raise ValueError('Evaluation config has duplicate case IDs')
    expected_provider = config['providers'][0]['id']
    observed = defaultdict(list)
    wrong_providers = []
    wrong_prompts = []
    for row in rows_from(data):
        variables = case_variables(row)
        case_id = str(variables.get('case_id', ''))
        observed[case_id].append(variables.get('track'))
        provider = row.get('provider', {})
        provider_id = provider.get('id') if isinstance(provider, dict) else provider
        if provider_id != expected_provider:
            wrong_providers.append(case_id)
        if row.get('promptIdx') != 0:
            wrong_prompts.append(case_id)
    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    duplicates = sorted(case for case, tracks in observed.items() if len(tracks) != 1)
    wrong_tracks = sorted(case for case in set(expected) & set(observed)
                          if observed[case] != [expected[case]])
    return {'config':str(config_path), 'expected_count':len(expected),
            'observed_count':sum(map(len, observed.values())), 'missing':missing,
            'unexpected':unexpected, 'duplicates':duplicates, 'wrong_tracks':wrong_tracks,
            'wrong_providers':sorted(wrong_providers), 'wrong_prompts':sorted(wrong_prompts),
            'complete':not any((missing, unexpected, duplicates, wrong_tracks,
                                wrong_providers, wrong_prompts))}


def main(inp, out_csv, config_path=DEFAULT_CONFIG):
    data = json.loads(Path(inp).read_text())
    summaries, details = compute(data)
    if not details:
        raise ValueError('No evaluation cases found')
    covered = coverage(data, config_path)
    with open(out_csv,'w',newline='',encoding='utf-8') as f:
        fields=['provider','model','prompt','track','metric','numerator','denominator','rate']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in summaries:
            writer.writerow({**row,'rate':'' if row['rate'] is None else f"{row['rate']:.6f}"})
    Path(out_csv).with_suffix('.cases.json').write_text(json.dumps(details,indent=2)+'\n')
    Path(out_csv).with_suffix('.coverage.json').write_text(json.dumps(covered,indent=2)+'\n')
    if not covered['complete']:
        raise ValueError('Incomplete evaluation case coverage; inspect '+str(Path(out_csv).with_suffix('.coverage.json')))
    print(f'Wrote {out_csv}: {len(details)} cases; undefined rates are blank, never zero')

if __name__=='__main__':
    import sys
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('results_json')
    parser.add_argument('metrics_csv')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    main(args.results_json, args.metrics_csv, args.config)
