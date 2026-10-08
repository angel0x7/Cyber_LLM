#!/usr/bin/env python3
"""Read-only public OpenRouter catalog audit. No inference and no API credential."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import urllib.request
from common import MODELS, lab5

BASE = 'https://openrouter.ai/api/v1'
REQUIRED_PARAMETERS = {'temperature', 'response_format', 'reasoning', 'max_tokens'}


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def dollars_per_million(value):
    n = float(value)*1e6
    if not math.isfinite(n) or n < 0:
        raise ValueError('Invalid published price')
    return n


def analyze_model(model, endpoints):
    eligible = [e for e in endpoints if e.get('status') == 0 and
                REQUIRED_PARAMETERS <= set(e.get('supported_parameters', [])) and
                float(e.get('pricing', {}).get('request', 0)) == 0]
    if not eligible:
        return {'status': 'MODEL_UNAVAILABLE', 'reason': 'No available endpoint with the unchanged common parameters'}
    prices = [e['pricing'] for e in eligible]
    for p in list(prices):
        prices.extend(p.get('overrides', []))
    ceilings = {k: max(dollars_per_million(p[k]) for p in prices if k in p) for k in ('prompt', 'completion')}
    return {'status': 'CATALOG_AVAILABLE', 'catalog_usd_per_million': {
                k: dollars_per_million(model['pricing'][k]) for k in ('prompt', 'completion')},
            'ceilings_usd_per_million': ceilings, 'eligible_endpoint_count': len(eligible),
            'eligible_backends': sorted({e['provider_name'] for e in eligible}),
            'canonical_slug': model.get('canonical_slug'), 'reasoning': model.get('reasoning'),
            'supported_parameters': model.get('supported_parameters'),
            'catalog_pricing': model['pricing'], 'endpoint_snapshot': endpoints}


def audit():
    catalog = {m['id']: m for m in get_json(BASE+'/models')['data'] if m['id'] in MODELS}
    models = {}
    for id in MODELS:
        if id not in catalog:
            models[id] = {'status': 'MODEL_UNAVAILABLE', 'reason': 'Exact ID absent from catalog'}
        else:
            endpoints = get_json(BASE+'/models/'+id+'/endpoints')['data']['endpoints']
            models[id] = analyze_model(catalog[id], endpoints)
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'source': BASE+'/models',
            'price_units': 'USD per million tokens; actual usage.cost is authoritative',
            'valid_for_hours': 24, 'models': models}


def validate_quote(quote, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(quote['observed_at'])
    if stamp.tzinfo is None or not timedelta(0) <= now-stamp <= timedelta(hours=24):
        raise ValueError('Price audit must be current (within 24 hours); fetch a new snapshot')
    if quote['source'] != BASE+'/models' or set(quote['models']) != set(MODELS):
        raise ValueError('Audit source/model set differs from the canonical benchmark')
    for m in quote['models'].values():
        if m['status'] != 'CATALOG_AVAILABLE':
            raise ValueError('MODEL_UNAVAILABLE: all four exact models must be available before admission')
        for k in ('prompt', 'completion'):
            value = m['ceilings_usd_per_million'][k]
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid reviewed reservation ceiling')
    return quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Preserve the existing audit; choose a NEW output path')
    quote = audit()
    lab5.atomic(args.output, quote)
    for id, data in quote['models'].items():
        print(id, data['status'], 'catalog', data.get('catalog_usd_per_million'),
              'reservation ceilings', data.get('ceilings_usd_per_million'))
    validate_quote(quote)


if __name__ == '__main__':
    main()
