"""Import the frozen Lab 5 application, never copy or specialize its experiment."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / 'labs/lab6'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'labs/lab5/src'))
import arena
import run_arena as lab5

MODELS = ('deepseek/deepseek-v4.1-flash', 'z-ai/glm-5.3',
          'moonshotai/kimi-k3', 'xiaomi/mimo-v2.5-pro')
NAMES = ('DeepSeek V4.1 Flash', 'GLM 5.3', 'Kimi K3', 'MiMo V2.5 Pro')


def verify_frozen():
    frozen = json.loads((LAB/'data/frozen_lab5.json').read_text())
    changed = [name for name, digest in frozen['sha256'].items()
               if not (ROOT/name).is_file() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
    if changed:
        raise ValueError('Frozen Lab 5 experiment differs: ' + ', '.join(changed))
    return frozen


def fingerprint():
    verify_frozen()
    paths = sorted((LAB/'src').glob('*.py')) + [LAB/'data/frozen_lab5.json']
    digest = hashlib.sha256()
    for p in paths:
        digest.update(p.name.encode()); digest.update(p.read_bytes())
    return digest.hexdigest()


def execution_order():
    rows = []
    for ci, (case, mode) in enumerate((c, m) for c in arena.scenarios() for m in arena.MODES):
        rotation = MODELS[ci % 4:] + MODELS[:ci % 4]
        rows.extend({'scenario_id': case['id'], 'mode': mode, 'model': model} for model in rotation)
    # Smoke first, with the same rotation. Those 16 conditions are reused, never repaid.
    return [r for r in rows if r['scenario_id'] in lab5.SMOKE] + [r for r in rows if r['scenario_id'] not in lab5.SMOKE]


def row_key(item):
    return '|'.join(item[k] for k in ('model', 'scenario_id', 'mode'))


def comparison(rows):
    """Preserve Lab 5 metrics; add only cross-model cost/reliability summaries."""
    result = {}
    for model in MODELS:
        selected = [r for r in rows if r['requested_model'] == model]
        groups = arena.metrics(selected)
        for mode, group in groups.items():
            rs = selected if mode == 'all' else [r for r in selected if r['mode'] == mode]
            calls = [r for r in rs if r['model_called']]
            n = sum(r['application_outcome'] == 'provider_error' for r in calls)
            group['provider_error'] = {'numerator': n, 'denominator': len(calls), 'rate': n/len(calls) if calls else None}
            successes = sum(r['benign_task_success'] for r in rs)
            group['cost_per_successful_benign_task_usd'] = (
                group['actual_cost_usd']/successes if successes and not group['unknown_cost_rows'] else None)
            # Total experiment cost / successful benign task, NOT isolated benign-call cost.
            group['backend_distribution_rows'] = {b: sum(r['serving_backend'] == b for r in rs)
                for b in sorted({r['serving_backend'] for r in rs if r['serving_backend']})}
        result[model] = groups
    return result
