"""Promptfoo adapter for deterministic fixtures; no model client is constructed."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from arena import MODEL, blank, evaluate, fixture, input_block, scenarios


def call_api(prompt, options, context):
    variables = context['vars']
    case = next(c for c in scenarios() if c['id'] == variables['scenario_id'])
    mode = variables['mode']
    row = blank(case, mode, 'promptfoo-fixture', 'openrouter', MODEL, True)
    control = input_block(case, mode)
    if control:
        row.update(application_outcome='locally_blocked', locally_blocked=True, control=control)
    else:
        row.update(model_called=True, latency_ms=0, returned_model='synthetic-fixture')
        evaluate(case, mode, fixture(case), row)
    return {'output': json.dumps(row)}
