#!/usr/bin/env python3
"""Bounded provider checks for the course's shared LLM client.

The receipt contains only capability status and selected usage metadata. It
never contains credentials, prompts, responses, remote errors, or account IDs.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A fresh Python environment may not have the small preflight profile yet.
# Keep --help and the setup error usable without printing a traceback.
try:
    from course_llm.client import (AdapterError, Budget, CourseClient, ROUTES,
                                   load_course_env, offline, valid_model_identifier)
    _MISSING_DEPENDENCY = None
except ModuleNotFoundError as error:
    _MISSING_DEPENDENCY = error.name

PROVIDERS = ('nvidia', 'alibaba', 'cloudflare', 'openrouter', 'opencode-go')
STATUS_FIELDS = ('connectivity_status', 'model_status', 'json_status',
                 'security_case_status', 'long_context_status', 'tool_status')
ERRORS = {
    'DEPENDENCY_MISSING': ('A preflight dependency is missing.',
                           'Install runtime/requirements-preflight.lock in the course .venv.'),
    'KEY_MISSING': ('The selected provider credential is unavailable.',
                    'Set the documented key in the course-root .env or export it in this shell.'),
    'AUTH_401': ('The provider rejected the credential.',
                 'Check the selected provider key and its account permissions.'),
    'FORBIDDEN_403': ('The provider denied access to this route.',
                      'Check model access and account permissions with the provider.'),
    'MODEL_NOT_FOUND': ('The requested model is unavailable or its identity was not verified.',
                        'Check the exact provider/model ID and its availability.'),
    'RATE_LIMIT_429': ('The provider rate or quota limit was reached.',
                       'Wait for the provider limit to reset or check account quota.'),
    'TIMEOUT': ('The provider did not respond within the request timeout.',
                'Check the connection and retry the bounded preflight later.'),
    'OUTPUT_TRUNCATED': ('The response exhausted its output budget.',
                         'Try a model route with enough completion capacity for this check.'),
    'INVALID_JSON': ('The response was not a strict JSON object.',
                     'Check JSON-object support for this model route.'),
    'SCHEMA_ERROR': ('The response did not satisfy the expected capability check.',
                     'Check this model route before using it for course exercises.'),
    'PROVIDER_5XX': ('The provider returned a server error.',
                      'Retry after the provider service recovers.'),
    'UNKNOWN_PROVIDER_ERROR': ('The provider check failed.',
                                'Check the provider status and retry; keep the receipt for diagnosis.'),
    'OFFLINE_BLOCKED': ('Live inference is disabled by LLM_OFFLINE.',
                        'Unset LLM_OFFLINE before running a provider check.'),
    'ROUTE_UNVALIDATED': ('This route has no validated course API preflight.',
                          'Select a documented provider route for live course work.'),
}
ADAPTER_ERRORS = {
    'credentials_unavailable': 'KEY_MISSING',
    'authentication_error': 'AUTH_401',
    'permission_denied': 'FORBIDDEN_403',
    'model_unavailable': 'MODEL_NOT_FOUND',
    'model_identity_unverified': 'MODEL_NOT_FOUND',
    'quota_or_rate_limit': 'RATE_LIMIT_429',
    'server_error': 'PROVIDER_5XX',
    'transport_error': 'TIMEOUT',
    'timeout': 'TIMEOUT',
    'output_truncated': 'OUTPUT_TRUNCATED',
}


class PreflightFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def valid_model(provider, model):
    """Compatibility wrapper; the client owns the identifier policy."""
    return valid_model_identifier(provider, model)


def blank_receipt(provider, model):
    return dict(provider=provider, model_id=model, requested_model=model,
                timestamp=datetime.now(timezone.utc).isoformat(),
                environment_status='NOT RUN', credential_status='NOT RUN',
                **{key: 'NOT RUN' for key in STATUS_FIELDS},
                returned_model=None, serving_backend=None, serving_backends=[], latency_seconds=None,
                prompt_tokens=None, completion_tokens=None, reasoning_tokens=None,
                cost_usd=None, finish_reason=None, CORE_READY=False, FULL_READY=False)


def strict_json(text):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError('Duplicate JSON key')
            obj[key] = value
        return obj
    def invalid(_):
        raise ValueError('Non-finite JSON number')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


@contextmanager
def project_imports():
    old_path = sys.path[:]
    previous = {k: v for k, v in sys.modules.items() if k == 'src' or k.startswith('src.')}
    for key in previous:
        del sys.modules[key]
    sys.path.insert(0, str(ROOT / 'project'))
    try:
        yield
    finally:
        for key in list(sys.modules):
            if key == 'src' or key.startswith('src.'):
                del sys.modules[key]
        sys.modules.update(previous)
        sys.path[:] = old_path


def tool_check(client):
    """Exercise the course's JSON tool protocol through the actual Agent app."""
    with project_imports(), tempfile.TemporaryDirectory(prefix='llm-sec-preflight-') as folder:
        from src.agent.app import run
        old_log = os.environ.get('LLM_LOG_PATH')
        os.environ['LLM_LOG_PATH'] = str(Path(folder) / 'synthetic-agent.jsonl')
        try:
            trace = {}
            result = run('Use the calc tool to calculate 15 + 27.', client=client,
                         model=client.model_id, max_steps=3, trace=trace)
            return (trace.get('event') == 'accepted' and result.get('safety') == 'safe'
                    and '42' in result.get('answer', '')
                    and any(t.get('tool') == 'calc' and t.get('args', {}).get('expr', '').replace(' ', '') == '15+27'
                            and t.get('result') == '42' for t in result.get('steps', []))
                    and any(t.get('name') == 'calc' and t.get('executed') and t.get('allowed')
                            for t in trace.get('tools', [])))
        finally:
            if old_log is None:
                os.environ.pop('LLM_LOG_PATH', None)
            else:
                os.environ['LLM_LOG_PATH'] = old_log


def _safe_metadata(receipt, metadata):
    """Copy numeric and checked identifier fields only; never copy provider blobs."""
    returned = metadata.get('returned_model_id')
    requested = receipt['requested_model']
    if isinstance(returned, str) and (returned == requested or
            (requested.endswith(':free') and returned == requested.removesuffix(':free'))):
        receipt['returned_model'] = returned
    backend = metadata.get('serving_backend')
    if isinstance(backend, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9 ._-]{0,63}', backend):
        receipt['serving_backend'] = backend
        if backend not in receipt['serving_backends']:
            receipt['serving_backends'].append(backend)
    for target, source in (('latency_seconds', 'latency_seconds'),
                           ('prompt_tokens', 'input_tokens'),
                           ('completion_tokens', 'output_tokens'),
                           ('reasoning_tokens', 'reasoning_tokens')):
        value = metadata.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1e9:
            receipt[target] = (receipt[target] or 0) + value
    value = metadata.get('cost_usd', metadata.get('estimated_cost_usd'))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1000:
        receipt['cost_usd'] = (receipt['cost_usd'] or 0) + value
    finish = metadata.get('finish_reason')
    if isinstance(finish, str) and re.fullmatch(r'[A-Za-z_]{1,32}', finish):
        receipt['finish_reason'] = finish


def _truncated(metadata):
    finish = str(metadata.get('finish_reason') or '').upper()
    return metadata.get('truncated') is True or any(word in finish for word in ('LENGTH', 'MAX_TOKENS'))


def _parse_object(text):
    try:
        value = strict_json(text)
    except (ValueError, TypeError):
        raise PreflightFailure('INVALID_JSON') from None
    if not isinstance(value, dict):
        raise PreflightFailure('SCHEMA_ERROR')
    return value


def run_checks(client, *, full=False):
    """Return (sanitized receipt, failure code), sharing the caller's Budget."""
    receipt = blank_receipt(client.provider, client.model_id)
    receipt['environment_status'] = 'PASS'
    receipt['credential_status'] = 'PASS'
    if not full:
        receipt['long_context_status'] = receipt['tool_status'] = 'NOT REQUESTED'
    stage = 'connectivity_status'
    reason = None
    allowed_models = {client.model_id}
    if client.provider == 'openrouter' and client.model_id.endswith(':free'):
        allowed_models.add(client.model_id.removesuffix(':free'))

    def ask(prompt, *, structured=False):
        for limit in (256, 512):
            response = client.complete([{'role': 'user', 'content': prompt}],
                max_output_tokens=limit,
                response_format={'type': 'json_object'} if structured else None)
            metadata = response.metadata
            _safe_metadata(receipt, metadata)
            if _truncated(metadata):
                if limit == 256:
                    continue
                raise PreflightFailure('OUTPUT_TRUNCATED')
            if metadata.get('model_refusal'):
                raise PreflightFailure('SCHEMA_ERROR')
            if metadata.get('returned_model_id') not in allowed_models:
                receipt['model_status'] = 'FAIL'
                raise PreflightFailure('MODEL_NOT_FOUND')
            receipt['model_status'] = 'PASS'
            return response.text
        raise PreflightFailure('OUTPUT_TRUNCATED')

    try:
        if ask('Reply with exactly READY.').strip() != 'READY':
            raise PreflightFailure('SCHEMA_ERROR')
        receipt[stage] = 'PASS'
        stage = 'json_status'
        value = _parse_object(ask('Return only this JSON object: {"ready":true,"course":"llm-security"}.', structured=True))
        if value != {'ready': True, 'course': 'llm-security'} or type(value.get('ready')) is not bool:
            raise PreflightFailure('SCHEMA_ERROR')
        receipt[stage] = 'PASS'
        stage = 'security_case_status'
        value = _parse_object(ask('Synthetic security exercise. A toy application puts a fixed password in source code. '
            'No real secret is provided. Classify this practice. Return exactly a JSON object with '
            'risk="hardcoded_secret", is_safe=false, and mitigation="use_secret_store".', structured=True))
        if value != {'risk': 'hardcoded_secret', 'is_safe': False, 'mitigation': 'use_secret_store'} or type(value.get('is_safe')) is not bool:
            raise PreflightFailure('SCHEMA_ERROR')
        receipt[stage] = 'PASS'
        receipt['CORE_READY'] = True
        if full:
            stage = 'long_context_status'
            filler = ('A synthetic classroom note contains no private information.\n' * 300)[:16384]
            prompt = 'Read this synthetic document and remember marker COURSE_CONTEXT_42.\n' + filler + '\nReturn only JSON {"marker":"<the marker from the beginning>"}.'
            if _parse_object(ask(prompt, structured=True)) != {'marker': 'COURSE_CONTEXT_42'}:
                raise PreflightFailure('SCHEMA_ERROR')
            receipt[stage] = 'PASS'
            stage = 'tool_status'
            before = len(client.records)
            try:
                tool_passed = tool_check(client)
            finally:
                for record in client.records[before:]:
                    _safe_metadata(receipt, record)
            if not tool_passed:
                if client.records[before:] and client.records[-1].get('truncated'):
                    raise PreflightFailure('OUTPUT_TRUNCATED')
                raise PreflightFailure('SCHEMA_ERROR')
            if any(record.get('model_refusal') for record in client.records[before:]):
                raise PreflightFailure('SCHEMA_ERROR')
            if any(record.get('returned_model_id') not in allowed_models for record in client.records[before:]):
                raise PreflightFailure('MODEL_NOT_FOUND')
            receipt[stage] = 'PASS'
            receipt['FULL_READY'] = True
    except AdapterError as error:
        receipt[stage] = 'FAIL'
        reason = ADAPTER_ERRORS.get(error.category, 'UNKNOWN_PROVIDER_ERROR')
    except PreflightFailure as error:
        receipt[stage] = 'FAIL'
        reason = error.code
    except ModuleNotFoundError:
        receipt[stage] = 'FAIL'
        reason = 'DEPENDENCY_MISSING'
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        receipt[stage] = 'FAIL'
        reason = 'SCHEMA_ERROR'
    return receipt, reason


def write_receipt(path, receipt):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')


def _report(receipt, reason, attempts):
    print('FULL READY' if receipt['FULL_READY'] else 'CORE READY' if receipt['CORE_READY'] else 'BLOCKED')
    for label, key in (('ENVIRONMENT', 'environment_status'), ('CREDENTIAL', 'credential_status'),
                       ('CONNECTIVITY', 'connectivity_status'), ('MODEL', 'model_status'),
                       ('JSON', 'json_status'), ('SECURITY CASE', 'security_case_status'),
                       ('LONG CONTEXT', 'long_context_status'), ('TOOLS', 'tool_status')):
        status = receipt[key]
        if status == 'NOT RUN' and key in ('long_context_status', 'tool_status'):
            status = 'NOT REQUESTED' if receipt['CORE_READY'] else 'NOT RUN'
        print(f'{label}: {status}')
    if reason:
        happened, action = ERRORS.get(reason, ERRORS['UNKNOWN_PROVIDER_ERROR'])
        print(f'ERROR: {reason}')
        print(f'WHAT HAPPENED: {happened}')
        print(f'WHAT TO DO NEXT: {action}')
    print('Sanitized local receipt written. Setup requests made: ' + str(attempts))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=PROVIDERS, required=True)
    parser.add_argument('--model', required=True, help='Exact provider model ID')
    parser.add_argument('--full', action='store_true', help='Also check synthetic long context and course Agent tool cycle')
    parser.add_argument('--prompt-key', action='store_true', help='Read a key securely for this process only')
    parser.add_argument('--receipt', type=Path, default=Path('provider_setup_receipt.json'))
    args = parser.parse_args(argv)
    if args.receipt.exists() or args.receipt.is_symlink():
        parser.error('Receipt already exists. Preserve it and select a new --receipt path.')
    # Validate secret-like arguments even before optional packages are installed.
    if (not re.fullmatch(r'@?[A-Za-z0-9][A-Za-z0-9_./:@-]{0,159}', args.model)
            or any(re.match(r'(?i)(?:sk-|nvapi-|gsk_|hf_|AIza|AKIA|ASIA|gh[pousr]_|xox[baprs]-|Bearer)', part)
                   for part in re.split(r'[/@:]', args.model))):
        parser.error('Invalid model identifier. Use a documented provider/model ID, never a credential.')
    receipt = blank_receipt(args.provider, args.model)
    if not args.full:
        receipt['long_context_status'] = receipt['tool_status'] = 'NOT REQUESTED'
    reason = None
    client = None
    if _MISSING_DEPENDENCY:
        receipt['environment_status'] = 'FAIL'
        reason = 'DEPENDENCY_MISSING'
    elif not valid_model(args.provider, args.model):
        # Never echo the supplied value; it could be a credential.
        parser.error('Invalid model identifier. Use a documented provider/model ID, never a credential.')
    elif offline():
        receipt['environment_status'] = 'FAIL'
        reason = 'OFFLINE_BLOCKED'
    elif args.provider == 'opencode-go':
        receipt['environment_status'] = 'PASS'
        reason = 'ROUTE_UNVALIDATED'
    else:
        receipt['environment_status'] = 'PASS'
        try:
            load_course_env()
            key_var = ROUTES[args.provider][1]
            key = os.environ.get(key_var)
            if args.prompt_key and not key:
                key = getpass.getpass(key_var + ' (hidden, not saved): ')
            if not key:
                receipt['credential_status'] = 'FAIL'
                reason = 'KEY_MISSING'
            else:
                receipt['credential_status'] = 'PASS'
                client = CourseClient(args.provider, args.model, key, max_retries=0,
                    budget=Budget(max_attempts=14 if args.full else 6),
                    run_id='student-provider-setup')
                receipt, reason = run_checks(client, full=args.full)
        except AdapterError as error:
            reason = ADAPTER_ERRORS.get(error.category, 'UNKNOWN_PROVIDER_ERROR')
            receipt['credential_status'] = 'FAIL' if reason == 'KEY_MISSING' else receipt['credential_status']
            receipt['connectivity_status'] = 'FAIL' if client else receipt['connectivity_status']
        except ModuleNotFoundError:
            reason = 'DEPENDENCY_MISSING'
            receipt['environment_status'] = 'FAIL'
        except (OSError, ValueError, TypeError):
            reason = 'UNKNOWN_PROVIDER_ERROR'
            receipt['environment_status'] = 'FAIL' if client is None else receipt['environment_status']
        finally:
            if client:
                client.close()
    write_receipt(args.receipt, receipt)
    _report(receipt, reason, len(client.records) if client else 0)
    return 0 if receipt['CORE_READY'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
