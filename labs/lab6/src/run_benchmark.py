#!/usr/bin/env python3
"""One frozen application, four exact models, rotating execution and a shared $5 cap."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import fcntl
import json
import math
import os
from pathlib import Path
import sys
import uuid

from common import LAB, MODELS, arena, lab5, comparison, execution_order, fingerprint, row_key, verify_frozen
from audit_prices import validate_quote
from course_llm.client import AdapterError, Budget, CourseClient, load_course_env


class PricedClient(CourseClient):
    """The certified transport unchanged; inject only audited model reservation rates."""
    def __init__(self, *args, quote, **kwargs):
        self.quote = quote
        super().__init__(*args, **kwargs)

    def _rates(self):
        if self.provider != 'openrouter' or self.model_id not in MODELS:
            raise AdapterError('unpriced_model', 'Exact benchmark model required')
        rates = self.quote['models'][self.model_id]['ceilings_usd_per_million']
        return rates['prompt'], rates['completion']


class RunBudget(Budget):
    def __init__(self, state, path):
        super().__init__(limit_usd=state['budget_limit_usd'], accounted_usd=state['accounted_usd'],
                         attempts=len(state['reservations']), max_attempts=640)
        self.state, self.path = state, path

    def save(self):
        self.state['accounted_usd'] = self.accounted_usd
        lab5.atomic(self.path, self.state)

    def reserve(self, amount):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError('Invalid reservation')
        super().reserve(amount)
        self.state['reservations'].append({'number': self.attempts, 'row_key': self.state['pending'],
            'reserved_usd': amount, 'cost_usd': None, 'settled': False})
        self.save()  # before every network dispatch, including shared-adapter retries

    def settle(self, reserved, measured):
        super().settle(reserved, measured)
        self.state['reservations'][-1].update(cost_usd=measured, settled=True)
        self.save()


def event_totals(row, events):
    row['request_count'] = len(events)
    row['cost_usd'] = sum(e['cost_usd'] for e in events) if events and all(e['cost_usd'] is not None for e in events) else None
    row['reserved_cost_usd'] = sum(e['budget_reserved_usd'] for e in events if e['cost_usd'] is None)
    row['latency_ms'] = sum((e.get('latency_seconds') or 0)*1000 for e in events) if events else None
    for dest, source in [('prompt_tokens','input_tokens'), ('completion_tokens','output_tokens'), ('reasoning_tokens','reasoning_tokens')]:
        values = [e[source] for e in events if e.get(source) is not None]
        row[dest] = sum(values) if values else None
    if events:
        row.update(returned_model=events[-1].get('returned_model_id'), serving_backend=events[-1].get('serving_backend'),
                   model_refusal=bool(events[-1].get('model_refusal')))
    return row


def failed(row, category):
    outcome = ('output_truncated' if category == 'output_truncated' else 'transport_error'
               if category == 'transport_error' else 'evaluation_error'
               if category.startswith('interrupted') else 'provider_error')
    row.update(application_outcome=outcome, error_category=category, evaluation_valid=False,
               output_truncated=outcome=='output_truncated', transport_error=outcome=='transport_error')
    return row


def new_row(state, item):
    case = next(c for c in arena.scenarios() if c['id'] == item['scenario_id'])
    return case, arena.blank(case, item['mode'], state['run_id'], 'openrouter', item['model'], state['offline'])


def execute(state, item, budget, path, client_type=PricedClient):
    case, row = new_row(state, item)
    control = arena.input_block(case, item['mode'])
    if control:
        row.update(application_outcome='locally_blocked', locally_blocked=True, control=control, cost_usd=0)
        row['false_positive_block'] = case['kind'] == 'benign'
        return row
    row['model_called'] = True
    if state['offline']:
        row.update(returned_model='synthetic-fixture', latency_ms=0)
        return arena.evaluate(case, item['mode'], arena.fixture(case), row)
    events = []
    def observe(record):
        event = {k: record.get(k) for k in lab5.SAFE_METADATA}
        events.append(event)
        candidate = None
        if record['category'] == 'api_success' and not record.get('truncated'):
            candidate = event_totals(dict(row), events)
            if record.get('returned_model_id') != item['model']:
                failed(candidate, 'model_identity_unverified')
            else:
                arena.evaluate(case, item['mode'], record.get('raw_text'), candidate)
        number = state['reservations'][-1]['number']
        receipt = {'number': number, 'row_key': row_key(item), 'metadata': event, 'evaluated_row': candidate}
        # Only normalized application-visible output survives; raw output/hidden reasoning do not.
        target = path.parent/'attempts'/f'{number:04d}.json'
        if target.exists():
            raise RuntimeError('Immutable attempt receipt already exists')
        lab5.atomic(target, receipt)
        state['attempt_records'].append(receipt)
        lab5.atomic(path, state)
    client = client_type('openrouter', item['model'], os.getenv('OPENROUTER_API_KEY',''), quote=state['price_audit'],
        budget=budget, observer=observe, run_id=state['run_id'], case_id=row_key(item), max_retries=1)
    try:
        response = client.complete_bounded(arena.messages(case), **lab5.DECODING)
        event_totals(row, events)
        if response.metadata.get('returned_model_id') != item['model']:
            return failed(row, 'model_identity_unverified')
        return arena.evaluate(case, item['mode'], response.text, row)
    except AdapterError as exc:
        return failed(event_totals(row, events), exc.category)
    finally:
        client.close()


def save_row(state, row, path):
    key = row['requested_model']+'|'+row['scenario_id']+'|'+row['mode']
    index = next(i for i,r in enumerate(state['execution_order']) if row_key(r) == key)
    target = path.parent/'rows'/f'{index:03d}.json'
    if target.exists():
        if json.loads(target.read_text()) != row:
            raise ValueError('Immutable row already exists with different evidence')
    else:
        lab5.atomic(target, row)
    state['rows'][key] = row
    state['pending'] = None
    lab5.atomic(path, state)


def recover(state, path):
    """Recover receipts/rows after disconnect; never replay an uncertain paid request."""
    receipts = [json.loads(p.read_text()) for p in sorted((path.parent/'attempts').glob('*.json'))]
    state['attempt_records'] = receipts
    for p in (path.parent/'rows').glob('*.json'):
        r = json.loads(p.read_text())
        state['rows'][r['requested_model']+'|'+r['scenario_id']+'|'+r['mode']] = r
    key = state['pending']
    if key and key not in state['rows']:
        item = next(r for r in state['execution_order'] if row_key(r) == key)
        observed = [r for r in receipts if r['row_key'] == key]
        reserved = [r for r in state['reservations'] if r['row_key'] == key]
        if observed and observed[-1]['evaluated_row'] is not None and len(observed) == len(reserved):
            row = observed[-1]['evaluated_row']
        elif not reserved:
            # No reservation means no request could have been sent. Safe to continue this row.
            state['pending'] = None
            lab5.atomic(path, state)
            return
        else:
            _, row = new_row(state, item)
            row['model_called'] = True
            event_totals(row, [r['metadata'] for r in observed])
            failed(row, 'interrupted_unconfirmed')
            row.update(status='interrupted_not_repaid', request_count=len(reserved),
                cost_usd=sum(r['cost_usd'] for r in reserved) if all(r['cost_usd'] is not None for r in reserved) else None,
                reserved_cost_usd=sum(r['reserved_usd'] for r in reserved if r['cost_usd'] is None))
        save_row(state, row, path)
    state['pending'] = None
    lab5.atomic(path, state)


def admission(state):
    answer = {}
    for model in MODELS:
        keys = [row_key(r) for r in state['execution_order'] if r['model'] == model and r['scenario_id'] in lab5.SMOKE]
        rows = [state['rows'][k] for k in keys if k in state['rows']]
        unavailable = any(r['error_category'] in {'model_unavailable','authentication_error','permission_denied','quota_or_rate_limit'} for r in rows)
        healthy = state['accounted_usd'] < state['budget_limit_usd'] and len(rows)==4 and all(r['evaluation_valid'] and r['schema_valid'] and r['model_called'] and
            not r['output_truncated'] and (state['offline'] or r['returned_model']==model) and
            r['cost_usd'] is not None and r['latency_ms'] is not None and r['latency_ms'] < 120000 for r in rows)
        answer[model] = {'status': 'ADMITTED' if healthy else 'MODEL_UNAVAILABLE' if unavailable else
                          'MODEL_INCOMPATIBLE' if len(rows)==4 else 'PENDING', 'rows':len(rows),
                         'failures':[r['error_category'] or ('latency_gate' if r['latency_ms'] is None or r['latency_ms'] >= 120000 else 'contract_identity_or_cost_gate') for r in rows
                                      if not r['evaluation_valid'] or not r['schema_valid'] or r['cost_usd'] is None or r['latency_ms'] is None or r['latency_ms'] >= 120000 or (not state['offline'] and r['returned_model'] != model)] + (['budget_exhausted'] if state['accounted_usd'] >= state['budget_limit_usd'] else [])}
    return answer


def export(state, directory):
    rows = list(state['rows'].values())
    receipts = state['attempt_records']
    billing = {m:{'requests':sum(r['metadata']['model_id']==m for r in receipts),
                  'actual_cost_usd':sum(r['metadata']['cost_usd'] for r in receipts if r['metadata']['model_id']==m and r['metadata']['cost_usd'] is not None),
                  'backend_distribution_attempts':dict(Counter(r['metadata']['serving_backend'] or 'unknown' for r in receipts if r['metadata']['model_id']==m))}
               for m in MODELS}
    document = {'format_version':1, 'run_id':state['run_id'],
        'evidence_type':'synthetic_fixture' if state['offline'] else 'live_inference',
        'label':'SYNTHETIC / NOT BENCHMARK EVIDENCE' if state['offline'] else 'CLASSROOM BENCHMARK / NOT UNIVERSAL RANKING',
        'fingerprint':state['fingerprint'], 'frozen_lab5':state['frozen_lab5'],
        'rows':rows, 'model_metrics':comparison(rows), 'billing_by_model':billing,
        'admission':admission(state), 'execution_order':state['execution_order'],
        'price_audit':state.get('price_audit'),
        'budget':{'limit_usd':state['budget_limit_usd'], 'accounted_usd':state['accounted_usd'],
                  'remaining_usd':state['budget_limit_usd']-state['accounted_usd'],
                  'actual_cost_usd':sum(m['actual_cost_usd'] for m in billing.values()),
                  'confirmed_attempts':len(receipts), 'dispatch_reservations':len(state['reservations']),
                  'unknown_cost_attempts':sum(r['cost_usd'] is None for r in state['reservations'])}}
    lab5.atomic(directory/'benchmark.json', document)
    if rows:
        temp = directory/'benchmark.csv.tmp'
        with temp.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader()
            for row in rows:
                values={k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()}
                values={k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in values.items()}
                writer.writerow(values)
        os.replace(temp,directory/'benchmark.csv')
    return document


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true');parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--budget',type=float,default=5)
    parser.add_argument('--prices',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    if not math.isfinite(args.budget) or not 0<args.budget<=5:
        parser.error('Global budget must be finite and in (0, $5]')
    frozen=verify_frozen();digest=fingerprint()
    directory=(args.output or LAB/'reports'/('offline' if args.offline else 'live')).resolve();directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('Another process owns this benchmark; do not launch a duplicate')
        path=directory/'state.json'
        if path.exists():
            if not args.resume:parser.error('Existing evidence: use --resume, never overwrite a run')
            state=json.loads(path.read_text())
            if state['fingerprint']!=digest or state['offline']!=args.offline or state['budget_limit_usd']!=args.budget:
                parser.error('Frozen source, mode or budget differs from the persisted experiment')
            recover(state,path)
        else:
            if args.resume:parser.error('No benchmark to resume')
            state={'run_id':str(uuid.uuid4()),'fingerprint':digest,'frozen_lab5':frozen,'offline':args.offline,
                   'budget_limit_usd':args.budget,'accounted_usd':0,'reservations':[],'attempt_records':[],
                   'rows':{},'pending':None,'execution_order':execution_order(),'price_audit':None}
        if not args.offline:
            quote=json.loads(args.prices.read_text()) if args.prices else state['price_audit']
            if quote is None:parser.error('Run audit_prices.py and pass --prices before paid smoke')
            try:validate_quote(quote)
            except ValueError as exc:parser.error(str(exc))
            if state['price_audit'] and quote!=state['price_audit']:
                for m in MODELS:
                    if any(quote['models'][m]['ceilings_usd_per_million'][k]>state['price_audit']['models'][m]['ceilings_usd_per_million'][k] for k in ('prompt','completion')):
                        parser.error('Prices increased above frozen reservation ceilings; preserve run and ask instructor')
                state.setdefault('price_refreshes',[]).append(quote)
            else:state['price_audit']=quote
            load_course_env()
            if not os.getenv('OPENROUTER_API_KEY'):parser.error('Configure the local OpenRouter key through Provider Setup')
            if not args.smoke and not all(x['status']=='ADMITTED' for x in admission(state).values()):
                parser.error('All four model smoke gates must pass before full benchmark')
        lab5.atomic(path,state);budget=RunBudget(state,path)
        for item in state['execution_order']:
            if args.smoke and item['scenario_id'] not in lab5.SMOKE:continue
            key=row_key(item)
            if key in state['rows']:continue
            state['pending']=key;lab5.atomic(path,state)
            try:row=execute(state,item,budget,path)
            except Exception as exc:
                print('Interrupted:',type(exc).__name__,'— reservations preserved; use --resume.',file=sys.stderr);return 2
            save_row(state,row,path);document=export(state,directory)
            print(json.dumps({'row':key,'outcome':row['application_outcome'],'completed':len(state['rows']),**document['budget']}),flush=True)
            if row['error_category'] in {'budget_blocked','authentication_error','permission_denied','model_identity_unverified'}:
                print('Stopped:',row['error_category'],'— do not substitute models or erase billing.');return 2
        document=export(state,directory)
        print(json.dumps({'completed_rows':len(state['rows']),'admission':document['admission'],'budget':document['budget']},indent=2))
        if args.smoke and not all(x['status']=='ADMITTED' for x in document['admission'].values()):return 2
        return 0


if __name__=='__main__':raise SystemExit(main())
