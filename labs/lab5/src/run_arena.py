#!/usr/bin/env python3
"""Frozen paired arena with atomic results, durable reservations and exact route identity."""
import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from arena import (LAB, MODEL, MODES, SCHEMA, blank, evaluate, fixture, input_block,
                   messages, metrics, scenarios)
from course_llm.client import AdapterError, Budget, CourseClient, load_course_env

SMOKE = ('LLM05-A1', 'LLM06-B1')
DECODING = {'max_output_tokens': 2048, 'temperature': 0,
            'response_format': {'type': 'json_object'}, 'reasoning_effort': 'low'}
SAFE_METADATA = ('provider', 'model_id', 'returned_model_id', 'serving_backend',
    'timestamp', 'attempt', 'case_id', 'prompt_sha256', 'input_tokens', 'output_tokens',
    'reasoning_tokens', 'cost_usd', 'budget_reserved_usd', 'latency_seconds',
    'category', 'truncated', 'model_refusal', 'http_status', 'finish_reason', 'request_id')


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fingerprint():
    paths = sorted((LAB/'src').glob('*.py')) + sorted((LAB/'data').glob('*'))
    paths += [ROOT/'course_llm/client.py']
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


class DurableBudget(Budget):
    def __init__(self, state, path):
        super().__init__(limit_usd=state['budget_limit_usd'], accounted_usd=state['accounted_usd'],
                         attempts=state['attempts'], max_attempts=100)
        self.state, self.path = state, path

    def save(self):
        self.state.update(accounted_usd=self.accounted_usd, attempts=self.attempts)
        atomic(self.path, self.state)

    def reserve(self, amount):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError('Invalid reservation')
        super().reserve(amount)
        self.save()  # durable BEFORE network dispatch, including automatic retries

    def settle(self, reserved, measured):
        super().settle(reserved, measured)
        self.save()  # unknown billing retains reservation even after interruption


def smoke_healthy(state):
    rows = state['rows']
    needed = {f'{s}:{m}' for s in SMOKE for m in MODES}
    if not needed <= set(rows):
        return False
    return all(rows[k]['evaluation_valid'] and rows[k]['schema_valid'] is True and
               rows[k]['model_called'] and not rows[k]['output_truncated'] and
               (state['offline'] or rows[k]['returned_model'] == state['model']) and
               rows[k]['latency_ms'] is not None and rows[k]['latency_ms'] < 120000
               for k in needed) and state['accounted_usd'] < state['budget_limit_usd']


def export(state, directory):
    rows = list(state['rows'].values())
    document = {'format_version': 1, 'evidence_type': 'synthetic_fixture' if state['offline'] else 'live_inference',
        'run_id': state['run_id'], 'fingerprint': state['fingerprint'], 'rows': rows,
        'metrics': metrics(rows), 'budget': {'limit_usd': state['budget_limit_usd'],
            'accounted_usd': state['accounted_usd'], 'remaining_usd': state['budget_limit_usd']-state['accounted_usd'],
            'requests': state['attempts']}, 'smoke_healthy': smoke_healthy(state)}
    atomic(directory/'results.json', document)
    if rows:
        target = directory/'results.csv'
        tmp = target.with_suffix('.csv.tmp')
        with tmp.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                safe = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
                # Spreadsheet formula injection protection; CSV is still plain data.
                for key, value in safe.items():
                    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                        safe[key] = "'" + value
                writer.writerow(safe)
        os.replace(tmp, target)
    return document


def execute(case, mode, state, budget, path):
    row = blank(case, mode, state['run_id'], state['provider'], state['model'], state['offline'])
    control = input_block(case, mode)
    if control:
        row.update(application_outcome='locally_blocked', locally_blocked=True, control=control, cost_usd=0)
        row['false_positive_block'] = case['kind'] == 'benign'
        return row
    if state['offline']:
        row.update(model_called=True, latency_ms=0, returned_model='synthetic-fixture')
        return evaluate(case, mode, fixture(case), row)
    observed = []
    def observe(record):
        clean = {k: record.get(k) for k in SAFE_METADATA}
        # No raw model output, reasoning text, prompts, headers or credentials persisted.
        observed.append(clean)
        state['attempt_records'].append(clean)
        atomic(path, state)
        receipt = path.parent/'attempts'/f"{len(state['attempt_records']):04d}.json"
        if receipt.exists():
            raise RuntimeError('Immutable attempt receipt already exists')
        atomic(receipt, clean)
    client = CourseClient(state['provider'], state['model'], os.environ.get('OPENROUTER_API_KEY', ''),
                          budget=budget, observer=observe, run_id=state['run_id'],
                          case_id=case['id']+':'+mode, max_retries=1)
    response = None
    try:
        row['model_called'] = True
        response = client.complete_bounded(messages(case), **DECODING)
        if response.metadata.get('returned_model_id') != state['model']:
            raise AdapterError('model_identity_unverified', 'Exact model identity failed')
    except AdapterError as exc:
        outcome = ('output_truncated' if exc.category == 'output_truncated' else
                   'transport_error' if exc.category == 'transport_error' else 'provider_error')
        row.update(application_outcome=outcome, evaluation_valid=False,
                   output_truncated=outcome=='output_truncated', transport_error=outcome=='transport_error',
                   error_category=exc.category)
    finally:
        client.close()
        row['request_count'] = len(observed)
        row['cost_usd'] = sum(r['cost_usd'] for r in observed) if observed and all(r['cost_usd'] is not None for r in observed) else None
        row['reserved_cost_usd'] = sum(r['budget_reserved_usd'] for r in observed if r['cost_usd'] is None)
        row['latency_ms'] = sum((r.get('latency_seconds') or 0)*1000 for r in observed) if observed else None
        for dest, src in [('prompt_tokens', 'input_tokens'), ('completion_tokens', 'output_tokens'), ('reasoning_tokens', 'reasoning_tokens')]:
            values = [r[src] for r in observed if r[src] is not None]
            row[dest] = sum(values) if values else None
        if observed:
            row.update(returned_model=observed[-1]['returned_model_id'], serving_backend=observed[-1]['serving_backend'],
                       model_refusal=bool(observed[-1]['model_refusal']))
    if response is not None and row['evaluation_valid']:
        return evaluate(case, mode, response.text, row)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--provider', choices=['openrouter'], default='openrouter')
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--budget', type=float, default=1)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--owasp', choices=['LLM01', 'LLM02', 'LLM05', 'LLM06'])
    parser.add_argument('--mode', choices=MODES)
    parser.add_argument('--scenario')
    args = parser.parse_args(argv)
    if not math.isfinite(args.budget) or not 0 < args.budget <= 1:
        parser.error('Budget must be finite, positive and at most $1.00')
    if args.model != MODEL:
        parser.error('Lab 5 uses the single certified exact model; Lab 6 is upcoming')
    all_cases = scenarios()
    if args.scenario and args.scenario not in {c['id'] for c in all_cases}:
        parser.error('Unknown canonical scenario')
    directory = (args.output or LAB/'reports'/('offline' if args.offline else 'live')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another runner owns this run directory')
        path = directory/'state.json'
        identity = dict(provider=args.provider, model=args.model, offline=args.offline, fingerprint=fingerprint())
        if path.exists():
            if not args.resume:
                parser.error('Existing evidence: use --resume or choose a NEW --output directory')
            state = json.loads(path.read_text())
            if any(state[k] != v for k, v in identity.items()) or state['budget_limit_usd'] != args.budget:
                parser.error('Resume identity, source, dataset, or budget differs; preserve evidence and use a new run')
            if state['pending']:
                parser.error('Interrupted in-flight row: reservation preserved; no automatic repayment. Inspect state.json with instructor.')
        else:
            if args.resume:
                parser.error('No run to resume; start with --smoke')
            state = dict(identity, run_id=str(uuid.uuid4()), budget_limit_usd=args.budget,
                         accounted_usd=0, attempts=0, attempt_records=[], rows={}, pending=None)
            atomic(path, state)
        if not args.offline:
            load_course_env()
            if not os.getenv('OPENROUTER_API_KEY'):
                parser.error('OPENROUTER_API_KEY missing; configure it locally using Provider Setup')
        if not args.offline and not args.smoke and not smoke_healthy(state):
            parser.error('Smoke gate missing or unhealthy. Run --smoke in this directory, then --resume.')
        selected = [c for c in all_cases if (not args.smoke or c['id'] in SMOKE)
                    and (not args.owasp or c['owasp_id'] == args.owasp)
                    and (not args.scenario or c['id'] == args.scenario)]
        budget = DurableBudget(state, path)
        for case in selected:
            for mode in ([args.mode] if args.mode else MODES):
                key = case['id']+':'+mode
                if key in state['rows']:
                    continue
                state['pending'] = key
                atomic(path, state)
                try:
                    row = execute(case, mode, state, budget, path)
                except Exception as exc:
                    # Preserve pending and reservation; never print an unsanitized exception.
                    print('Run stopped:', type(exc).__name__, '— evidence and reservations preserved.', file=sys.stderr)
                    return 2
                state['rows'][key] = row
                state['pending'] = None
                atomic(path, state)
                document = export(state, directory)
                remaining_rows = 40-len(state['rows'])
                actual = document['metrics']['all']['actual_cost_usd']
                estimated = (state['accounted_usd']/state['attempts']*remaining_rows) if state['attempts'] else None
                print(json.dumps({'row': key, 'outcome': row['application_outcome'], 'attack_success': row['attack_success'],
                      'actual_spent_usd': actual, 'accounted_usd': state['accounted_usd'],
                      'remaining_usd': args.budget-state['accounted_usd'], 'requests': state['attempts'],
                      'estimated_remaining_matrix_usd': estimated}), flush=True)
                if row['error_category'] in {'authentication_error', 'permission_denied', 'model_identity_unverified',
                                             'budget_blocked', 'credentials_unavailable', 'quota_or_rate_limit'}:
                    print('Route stopped:', row['error_category'], 'Inspect budget/provider setup; do not relabel as a defense.')
                    return 2
        document = export(state, directory)
        print(f"Rows: {len(state['rows'])}/40; smoke: {'healthy' if document['smoke_healthy'] else 'not healthy'}; results: {directory/'results.json'}")
        if args.smoke and not document['smoke_healthy']:
            print('Smoke failed: require four valid exact-model responses under 120 seconds each; inspect outcome/error_category.')
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
