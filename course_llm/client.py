"""Gemini and compatible chat transports, plus a narrow legacy generate_content seam."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from pathlib import Path
import os
import re
import time
from types import SimpleNamespace

import httpx

ROUTES = {
    'gemini': ('https://generativelanguage.googleapis.com/v1beta', 'GEMINI_API_KEY'),
    'groq': ('https://api.groq.com/openai/v1', 'GROQ_API_KEY'),
    'mistral': ('https://api.mistral.ai/v1', 'MISTRAL_API_KEY'),
    'nvidia': ('https://integrate.api.nvidia.com/v1', 'NVIDIA_API_KEY'),
    'alibaba': ('https://dashscope-intl.aliyuncs.com/compatible-mode/v1', 'DASHSCOPE_API_KEY'),
    'cloudflare': ('https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1', 'CLOUDFLARE_API_TOKEN'),
    'openrouter': ('https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY'),
}
STUDENT_ROUTES = {'nvidia', 'alibaba', 'cloudflare', 'openrouter'}
PRICES = {  # September 2026 Phase1B standard uncached USD per million.
    # OpenRouter endpoint ceiling audited 2026-09-29, also enforced in provider.max_price.
    ('openrouter', 'deepseek/deepseek-v4.1-flash'): (.45, 1.8),
    ('groq', 'openai/gpt-oss-20b'): (.075, .30),
    ('groq', 'openai/gpt-oss-120b'): (.15, .60),
    ('gemini', 'gemini-3.8-flash'): (.75, 3.75),
    ('mistral', 'mistral-small-2603'): (.15, .60),
}

def valid_model_identifier(provider, model):
    """Exact provider IDs only; reject credential-like components without echoing them."""
    if not isinstance(model, str) or not re.fullmatch(r'@?[A-Za-z0-9][A-Za-z0-9_./:@-]{0,159}', model):
        return False
    if any(re.match(r'(?i)(?:sk-|nvapi-|gsk_|hf_|AIza|AKIA|ASIA|gh[pousr]_|xox[baprs]-|Bearer)', part)
           for part in re.split(r'[/@:]', model)):
        return False
    if '..' in model or '//' in model or model.endswith(('/', ':', '@')):
        return False
    if provider == 'openrouter':
        return model.count('/') == 1 and not model.startswith(('openrouter/', 'auto/'))
    return True


def load_course_env():
    """Load only this course's local file; exported values (even empty) win."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False, interpolate=False)


def offline():
    return os.getenv('LLM_OFFLINE', '').strip().lower() in {'1', 'true', 'yes', 'on'}

class AdapterError(httpx.TransportError):
    """Sanitized, classified failure; callers must not multiply transport retries."""
    retry_exhausted = True
    def __init__(self, category, message, *, status_code=None, record=None):
        super().__init__(message)
        self.category, self.status_code, self.record = category, status_code, record

@dataclass
class Budget:
    limit_usd: float = 1.0
    accounted_usd: float = 0.0
    attempts: int = 0
    max_attempts: int = 600

    def reserve(self, amount):
        if self.attempts >= self.max_attempts or self.accounted_usd + amount > self.limit_usd:
            raise AdapterError('budget_blocked', 'Bounded replay budget would be exceeded')
        self.accounted_usd += amount
        self.attempts += 1

    def settle(self, reserved, measured):
        # Unknown usage keeps reservation as budget accounting, not claimed billing.
        if measured is not None:
            self.accounted_usd += measured - reserved


def _plain(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json', exclude_none=True)
    return value


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and math.isfinite(value) else None


def _category(status):
    return {400:'invalid_request', 401:'authentication_error', 403:'permission_denied',
            404:'model_unavailable', 429:'quota_or_rate_limit'}.get(status, 'server_error' if status and status >= 500 else 'provider_error')


class CourseClient:
    """Explicit route with injectable transports/observer; no auto fallback."""
    def __init__(self, provider, model_id, api_key, *, default_max_output_tokens=512,
                 budget=None, observer=None, http_client=None, gemini_client=None,
                 sleep=time.sleep, max_retries=1, run_id='interactive', case_id='unspecified'):
        if offline():
            raise AdapterError('offline_blocked', 'LLM_OFFLINE blocks live clients')
        if provider not in ROUTES:
            raise ValueError('Unsupported LLM_PROVIDER; choose an explicit documented course route')
        if not valid_model_identifier(provider, model_id):
            raise ValueError('MODEL_ID must be an explicit model identifier, never a credential')
        if not api_key:
            raise AdapterError('credentials_unavailable', ROUTES[provider][1] + ' is unavailable')
        if type(max_retries) is not int or not 0 <= max_retries <= 2:
            raise ValueError('At most two transport retries are allowed')
        self.provider, self.model_id, self.base_url = provider, model_id, ROUTES[provider][0]
        if provider == 'cloudflare':
            account_id = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
            if not re.fullmatch(r'[a-fA-F0-9]{32}', account_id):
                raise AdapterError('configuration_missing', 'Set CLOUDFLARE_ACCOUNT_ID locally')
            self.base_url = self.base_url.format(account_id=account_id)
        self._key = api_key
        self.default_max_output_tokens = default_max_output_tokens
        self.budget = budget if budget is not None else Budget()
        self.observer, self._http, self._gemini = observer, http_client, gemini_client
        self._sleep, self.max_retries = sleep, max_retries
        self.run_id, self.case_id = run_id, case_id
        self.models = self  # preserves the accepted injection seam in existing applications
        self.records = []

    def _redact(self, value):
        if isinstance(value, str):
            return value.replace(self._key, '[REDACTED]') if self._key else value
        if isinstance(value, dict):
            return {k:self._redact(v) for k,v in value.items()}
        if isinstance(value, list):
            return [self._redact(v) for v in value]
        return value

    def _emit(self, record):
        record = self._redact(record)
        self.records.append(record)
        if self.observer:
            self.observer(record)
        return record

    def _rates(self):
        if self.provider == 'openrouter':
            if self.model_id.endswith(':free'):
                return (0, 0)
            rates = PRICES.get((self.provider, self.model_id))
            if rates is None:
                raise AdapterError('unpriced_model', 'This paid model needs audited price ceilings before dispatch')
            return rates
        if self.provider in STUDENT_ROUTES:
            # Quotas/account billing differ. Bound requests, but never invent a USD price.
            return None
        rates = PRICES.get((self.provider, self.model_id))
        if rates is None:
            raise AdapterError('unpriced_model', 'Set explicit audited prices before using another model')
        if self.provider == 'gemini' and datetime.now(timezone.utc).year >= 2027:
            return tuple(x*2 for x in rates)
        return rates

    def complete(self, messages, *, model_id=None, max_output_tokens=None,
                 temperature=None, response_format=None, reasoning_effort=None, top_p=None):
        if offline():
            raise AdapterError('offline_blocked', 'LLM_OFFLINE blocks inference')
        if model_id is not None and model_id != self.model_id:
            raise ValueError('Requested model differs from explicit client route')
        limit = self.default_max_output_tokens if max_output_tokens is None else max_output_tokens
        if type(limit) is not int or not 1 <= limit <= 16384:
            raise ValueError('max_output_tokens must be an integer between 1 and 16384')
        if not messages or any(set(m) != {'role','content'} or m['role'] not in {'system','user','assistant'}
                               or not isinstance(m['content'], str) for m in messages):
            raise ValueError('Only explicit text role/content messages are supported')
        if self.provider == 'gemini' and self.model_id == 'gemini-3.8-flash' and temperature is not None:
            raise ValueError('Gemini3.8 does not support temperature; omit it explicitly')
        if response_format not in (None, {'type':'json_object'}):
            raise ValueError('Initial course adapter supports text or JSON-object mode only')
        if reasoning_effort not in (None, 'low', 'medium', 'high'):
            raise ValueError('Unsupported reasoning effort')
        if self.provider == 'gemini' and reasoning_effort == 'medium':
            raise ValueError('Pinned Gemini SDK supports low/high thinking only')
        if self.provider == 'mistral' and reasoning_effort is not None:
            raise ValueError('Reasoning control not implemented for this Mistral route')
        if top_p is not None and (self.provider != 'nvidia' or isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not 0 < top_p <= 1):
            raise ValueError('Explicit top_p is supported only for NVIDIA, in (0, 1]')
        rates = self._rates()
        pi, po = rates if rates is not None else (0, 0)
        serialized = json.dumps(messages, ensure_ascii=False)
        # UTF-8 bytes + framing is deliberately conservative, not a billed token count.
        input_bound = len(serialized.encode('utf-8')) + 512
        if input_bound + limit > (131072 if self.provider == 'groq' else 256000):
            raise AdapterError('context_budget_blocked', 'Input exceeds the bounded course request allowance')
        reserved = (input_bound*pi + limit*po)/1e6
        for attempt in range(1, self.max_retries+2):
            self.budget.reserve(reserved)
            record = dict(provider=self.provider, base_url=ROUTES[self.provider][0], model_id=self.model_id,
                          returned_model_id=None, request_id=None, run_id=self.run_id, case_id=self.case_id,
                          timestamp=datetime.now(timezone.utc).isoformat(), attempt=attempt,
                          prompt_sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                          settings={'max_output_tokens':limit,'temperature':temperature,
                                    'response_format':response_format,'reasoning_effort':reasoning_effort,
                                    'top_p':top_p,'stream':False,'tools':None},
                          input_tokens=None, output_tokens=None, reasoning_tokens=None,
                          cached_input_tokens=None, billable_output_tokens=None,
                          usage=None, cost_usd=None, serving_backend=None, estimated_cost_usd=None, cost_basis='usage unavailable; not an invoice',
                          budget_reserved_usd=reserved, json_parse_result=None, schema_result=None,
                          model_refusal=None, http_status=None, raw_text=None)
            if rates is None:
                record['cost_basis'] = 'student setup route: price not audited; request cap only, no USD guarantee'
            started = time.monotonic()
            status = None
            retry_after = None
            try:
                if self.provider == 'gemini':
                    result = self._gemini_request(messages, limit, temperature, response_format, reasoning_effort)
                else:
                    result = self._compatible_request(messages, limit, temperature, response_format, reasoning_effort, top_p)
                record.update(result)
                it, ot = record['input_tokens'], record['billable_output_tokens']
                if rates is not None and it is not None and ot is not None:
                    record['estimated_cost_usd'] = (it*pi + ot*po)/1e6
                    record['cost_basis'] = 'returned usage × standard uncached list prices; not charged invoice'
                if record.get('cost_usd') is not None:
                    record['cost_basis'] = 'OpenRouter returned usage.cost in USD credits'
                record['category'] = 'api_success'
                record['truncated'] = any(marker in str(record.get('finish_reason','')).upper() for marker in ('MAX_TOKENS','LENGTH'))
                try:
                    if record['truncated']:
                        raise ValueError('OUTPUT_TRUNCATED; JSON not evaluated')
                    json.loads(record['raw_text'])
                    record['json_parse_result'] = True
                except (ValueError, TypeError):
                    record['json_parse_result'] = None if record['truncated'] else False
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                retry_after = e.response.headers.get('retry-after')
                record.update(category=_category(status), http_status=status,
                              request_id=e.response.headers.get('x-request-id') or e.response.headers.get('request-id'))
                record['error_message'] = 'Provider HTTP error (' + str(status) + ')' 
            except AdapterError as e:
                record.update(category=e.category, error_message=self._redact(str(e))[:600])
            except httpx.TransportError as e:
                record.update(category='transport_error', error_message=type(e).__name__)
            except Exception as e:
                APIError = ()
                if self.provider == 'gemini':
                    from google.genai.errors import APIError
                if not isinstance(e, APIError):
                    # Programming errors must never become safety outcomes.
                    self.budget.settle(reserved, None)
                    record.update(category='adapter_error', error_message=type(e).__name__, latency_seconds=time.monotonic()-started)
                    self._emit(record)
                    raise
                status = getattr(e, 'code', None)
                record.update(category=_category(status), http_status=status,
                              error_message=self._redact(str(getattr(e, 'message', type(e).__name__)))[:600])
                resp = getattr(e, 'response', None)
                if resp is not None:
                    headers = getattr(resp, 'headers', {})
                    retry_after = headers.get('retry-after')
                    record['request_id'] = headers.get('x-request-id') or headers.get('x-goog-request-id')
            record['latency_seconds'] = round(time.monotonic()-started, 6)
            measured = record.get('cost_usd') if self.provider == 'openrouter' else record['estimated_cost_usd']
            self.budget.settle(reserved, measured)
            event = self._emit(record)
            if record['category'] == 'api_success':
                if self.provider == 'openrouter' and event.get('returned_model_id') not in {self.model_id, self.model_id.removesuffix(':free')} :
                    raise AdapterError('model_identity_unverified', 'Returned model differs from the requested exact model', record=event)
                return SimpleNamespace(text=event['raw_text'], metadata=event,
                    prompt_feedback=SimpleNamespace(block_reason='SAFETY' if event['model_refusal'] else None),
                    candidates=[SimpleNamespace(finish_reason=event.get('finish_reason'))])
            transient = status in {429,500,502,503,504} or record['category'] == 'transport_error'
            if not transient or attempt > self.max_retries:
                raise AdapterError(record['category'], record.get('error_message',record['category']), status_code=status, record=event)
            delay = 2.0 * (2 ** (attempt - 1))
            if retry_after:
                try:
                    delay = max(float(retry_after), 0)
                except ValueError:
                    try:
                        delay = max((parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds(),0)
                    except (ValueError,TypeError):
                        delay = 2.0
            if delay > 30:
                raise AdapterError('quota_or_rate_limit', 'Retry-After exceeds bounded 30-second wait; route stopped', status_code=status, record=event)
            self._sleep(delay)

    def _compatible_request(self, messages, limit, temperature, response_format, reasoning_effort, top_p=None):
        if self._http is None:
            self._http = httpx.Client(timeout=60, follow_redirects=False)
        payload = {'model':self.model_id,'messages':messages,'stream':False}
        payload['max_completion_tokens' if self.provider == 'groq' else 'max_tokens'] = limit
        if temperature is not None:
            payload['temperature'] = temperature
        if top_p is not None:
            payload['top_p'] = top_p
        if response_format is not None:
            payload['response_format'] = response_format
        if reasoning_effort is not None:
            if self.provider != 'openrouter':
                payload['reasoning_effort'] = reasoning_effort
        if self.provider == 'alibaba':
            payload['enable_thinking'] = False
        if self.provider == 'openrouter':
            pi, po = self._rates()
            payload['provider'] = {'allow_fallbacks':True, 'require_parameters':True,
                                   'max_price':{'prompt':pi, 'completion':po, 'request':0}}
            payload['reasoning'] = {'effort':reasoning_effort or 'low', 'exclude':True}
            payload['usage'] = {'include':True}
        headers = {'Authorization':'Bearer '+self._key}
        if self.provider == 'openrouter':
            headers['X-OpenRouter-Metadata'] = 'enabled'
        deadline = time.monotonic() + max(120, min(360, limit / 32 + 30))
        with self._http.stream('POST', self.base_url+'/chat/completions', headers=headers, json=payload) as response:
            if time.monotonic() >= deadline:
                raise httpx.ReadTimeout('Response exceeded bounded wall-time deadline', request=response.request)
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() >= deadline:
                    raise httpx.ReadTimeout('Response exceeded bounded wall-time deadline', request=response.request)
                if len(content) + len(chunk) > 2 * 1024 * 1024:
                    raise AdapterError('response_too_large', 'Provider response exceeded the 2 MiB limit')
                content.extend(chunk)
            if time.monotonic() >= deadline:
                raise httpx.ReadTimeout('Response exceeded bounded wall-time deadline', request=response.request)
        try:
            body = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            raise AdapterError('malformed_response', 'Provider returned an invalid JSON response envelope') from None
        if (not isinstance(body, dict) or not isinstance(body.get('choices'), list)
                or not body['choices'] or not isinstance(body['choices'][0], dict)
                or not isinstance(body['choices'][0].get('message'), dict)
                or not isinstance(body.get('usage', {}), (dict, type(None)))):
            raise AdapterError('malformed_response', 'Provider returned an invalid chat response envelope')
        choice = (body.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        text = message.get('content')
        if isinstance(text,list):
            text = ''.join(p.get('text','') for p in text if p.get('type')=='text')
        text = text if isinstance(text,str) else ''
        usage = body.get('usage') or {}
        details = usage.get('completion_tokens_details') or {}
        if not isinstance(details, dict) or not isinstance(usage.get('prompt_tokens_details') or {}, dict):
            raise AdapterError('malformed_response', 'Provider returned invalid usage metadata')
        backend = body.get('provider')
        routing = body.get('openrouter_metadata') or {}
        if not isinstance(backend, str) and isinstance(routing, dict):
            endpoints = routing.get('endpoints') or {}
            available = endpoints.get('available', []) if isinstance(endpoints, dict) else []
            backend = next((x.get('provider') for x in available if isinstance(x, dict) and x.get('selected') is True), None) if isinstance(available, list) else None
        finish = choice.get('finish_reason')
        if '<think' in text.lower() or '</think' in text.lower():
            text = '[INLINE REASONING OMITTED]'
        return dict(raw_text=text, returned_model_id=body.get('model'),
                    serving_backend=backend if isinstance(backend, str) else None,
                    cost_usd=_number(usage.get('cost')),
                    reasoning_fields_present=any(bool(message.get(k)) for k in ('reasoning_content','reasoning','thinking')),
                    native_tool_calls_present=bool(message.get('tool_calls')),
                    request_id=response.headers.get('x-request-id') or response.headers.get('request-id') or body.get('id'),
                    http_status=response.status_code, usage={k:usage[k] for k in ['prompt_tokens','completion_tokens','total_tokens','cost'] if k in usage},
                    input_tokens=_number(usage.get('prompt_tokens')),
                    output_tokens=_number(usage.get('completion_tokens')),
                    billable_output_tokens=_number(usage.get('completion_tokens')),
                    reasoning_tokens=_number(details.get('reasoning_tokens')),
                    cached_input_tokens=_number((usage.get('prompt_tokens_details') or {}).get('cached_tokens')),
                    model_refusal=bool(message.get('refusal')) or finish=='content_filter', finish_reason=finish)

    def _gemini_request(self, messages, limit, temperature, response_format, reasoning_effort):
        if self._gemini is None:
            from google import genai
            from google.genai import types
            self._gemini = genai.Client(api_key=self._key, vertexai=False, http_options=types.HttpOptions(
                base_url='https://generativelanguage.googleapis.com', api_version='v1beta',
                timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))
        config = {'max_output_tokens':limit}
        systems = [m['content'] for m in messages if m['role']=='system']
        if systems:
            config['system_instruction'] = '\n\n'.join(systems)
        if temperature is not None:
            config['temperature'] = temperature
        if response_format is not None:
            config['response_mime_type'] = 'application/json'
        if reasoning_effort is not None:
            config['thinking_config'] = {'thinking_level':reasoning_effort}
        contents = [{'role':'model' if m['role']=='assistant' else 'user','parts':[{'text':m['content']}]} for m in messages if m['role']!='system']
        resp = self._gemini.models.generate_content(model=self.model_id,contents=contents,config=config)
        usage = _plain(getattr(resp,'usage_metadata',None)) or {}
        input_count = _number(usage.get('prompt_token_count'))
        output = _number(usage.get('response_token_count', usage.get('candidates_token_count')))
        reasoning = _number(usage.get('thoughts_token_count'))
        total = _number(usage.get('total_token_count'))
        billed = output + reasoning if output is not None and reasoning is not None else (
            total-input_count if total is not None and input_count is not None and total>=input_count else None)
        candidates = getattr(resp,'candidates',None) or []
        finish = str(getattr(candidates[0],'finish_reason','')) if candidates else None
        feedback = getattr(resp,'prompt_feedback',None)
        block = str(getattr(feedback,'block_reason','') or '')
        refused = (bool(block) and 'UNSPECIFIED' not in block.upper()) or any(s in (finish or '').upper() for s in ['SAFETY','BLOCKLIST','PROHIBITED_CONTENT','RECITATION'])
        # Read final text parts directly to avoid SDK warnings dumping thought metadata.
        text = ''.join(getattr(part,'text','') or '' for c in candidates[:1]
                       for part in (getattr(getattr(c,'content',None),'parts',None) or [])
                       if not getattr(part,'thought',False))
        headers = getattr(getattr(resp,'sdk_http_response',None),'headers',{}) or {}
        return dict(raw_text=text, returned_model_id=getattr(resp,'model_version',None),
                    request_id=headers.get('x-request-id') or headers.get('x-goog-request-id') or getattr(resp,'response_id',None),
                    usage=usage,input_tokens=input_count,output_tokens=output,reasoning_tokens=reasoning,
                    billable_output_tokens=billed,cached_input_tokens=_number(usage.get('cached_content_token_count')),
                    model_refusal=refused,finish_reason=finish,prompt_block_reason=block or None)

    def generate_content(self, *, model, contents, config=None):
        """Only the text shapes used by current labs; unsupported settings fail closed."""
        config = dict(config or {})
        unknown = set(config)-{'system_instruction','response_mime_type','max_output_tokens','temperature'}
        if unknown:
            raise ValueError('Unsupported course generation settings: '+','.join(sorted(unknown)))
        messages=[]
        if config.get('system_instruction'):
            messages.append({'role':'system','content':config['system_instruction']})
        if isinstance(contents,str):
            messages.append({'role':'user','content':contents})
        else:
            for c in contents:
                messages.append({'role':'assistant' if c['role']=='model' else c['role'],
                                 'content':'\n'.join(p['text'] for p in c['parts'])})
        mime = config.get('response_mime_type')
        if mime not in (None,'application/json'):
            raise ValueError('Only JSON MIME mode is supported')
        return self.complete_bounded(messages, model_id=model, max_output_tokens=config.get('max_output_tokens'),
                             temperature=config.get('temperature'),
                             response_format={'type':'json_object'} if mime else None,
                             reasoning_effort='low' if self.provider in {'groq','gemini','openrouter'} else None)

    def complete_bounded(self, messages, *, retry_max_output_tokens=None, **kwargs):
        """One larger completion after length; never interpret truncation as model behavior."""
        first = kwargs.get('max_output_tokens') or self.default_max_output_tokens
        retry = retry_max_output_tokens if retry_max_output_tokens is not None else min(first * 2, 16384)
        if type(retry) is not int or not first <= retry <= 16384:
            raise ValueError('Invalid bounded completion retry cap')
        result = self.complete(messages, **kwargs)
        if result.metadata.get('truncated') and retry > first:
            kwargs['max_output_tokens'] = retry
            result = self.complete(messages, **kwargs)
        if result.metadata.get('truncated'):
            raise AdapterError('output_truncated', 'OUTPUT_TRUNCATED: completion allowance exhausted', record=result.metadata)
        return result

    def close(self):
        if self._http is not None:
            self._http.close()
        if self._gemini is not None and hasattr(self._gemini,'close'):
            self._gemini.close()


def client_from_env(*, default_max_output_tokens=512, **kwargs):
    if offline():
        raise AdapterError('offline_blocked','LLM_OFFLINE blocks live inference and key lookup')
    load_course_env()
    provider = os.getenv('LLM_PROVIDER')
    if provider not in ROUTES:
        raise ValueError('Set LLM_PROVIDER explicitly to a documented course route')
    return CourseClient(provider, os.getenv('MODEL_ID'), os.getenv(ROUTES[provider][1]),
                        default_max_output_tokens=default_max_output_tokens, **kwargs)
