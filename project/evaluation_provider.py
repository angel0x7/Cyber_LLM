"""Promptfoo adapter to the REAL application. Fixtures replace only generate_content."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src import app
from src.common.logger import log

class FixtureClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)  # Exhaustion is a fixture/course error, not a provider refusal.
        if isinstance(response, dict) and response.get('_raise') == 'transport':
            import httpx
            raise httpx.ConnectError('Synthetic offline transport failure')
        return SimpleNamespace(text=response if isinstance(response, str) else json.dumps(response))


PROVIDERS = {'gemini', 'groq', 'mistral', 'nvidia', 'alibaba', 'cloudflare', 'openrouter'}
LIVE_BACKENDS = {'live'} | PROVIDERS


def _offline_enabled():
    return os.getenv('LLM_OFFLINE', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _check_provider(backend, provider):
    if provider is None:
        return
    provider = str(provider).strip().lower()
    if provider not in PROVIDERS:
        raise ValueError('Unsupported live application provider')
    if backend != 'live' and backend != provider:
        raise ValueError(f'Backend {backend!r} does not match client provider {provider!r}')


def evaluate_case(variables, *, backend='mock', client=None, model=None):
    if backend != 'mock' and backend not in LIVE_BACKENDS:
        raise ValueError('Unsupported application backend; select live, gemini, groq, mistral or mock')
    trace = {'backend':backend, 'model': 'offline-fixture' if backend == 'mock' else (model or os.getenv('MODEL_ID', 'unselected'))}
    if backend == 'mock':
        if client is None:
            client = FixtureClient(variables.get('mock_responses', []))
        model = 'offline-fixture'
    else:
        if 'mock_responses' in variables:
            raise ValueError('Live cases must not contain fixture responses')
        if _offline_enabled():
            raise RuntimeError('LLM_OFFLINE=1 blocks live evaluation')
        if client is None:
            # Keep client construction and dotenv loading behind the application's
            # local input guard. Validate the configured route when this case reaches
            # the live model boundary.
            question = variables.get('question')
            if isinstance(question, str):
                from src.common.guards import input_guard

                needs_model, _ = input_guard(question)
            else:
                needs_model = True
            if needs_model:
                from course_llm.client import load_course_env as load_dotenv

                load_dotenv()
                selected = os.getenv('LLM_PROVIDER', '').strip().lower()
                if selected not in PROVIDERS:
                    raise ValueError('Set LLM_PROVIDER explicitly to a documented course route')
                _check_provider(backend, selected)
                trace['provider'] = selected
        else:
            _check_provider(backend, getattr(client, 'provider', None))
            trace['provider'] = getattr(client, 'provider', None)
        if client is not None and getattr(client, 'model_id', None):
            model = model or client.model_id
        else:
            model = model or os.getenv('MODEL_ID')
        trace['model'] = model or 'unselected'
    track = variables.get('track', variables.get('mode', 'rag'))
    try:
        result = app.run_application(track, variables['question'], k=int(variables.get('k', 3)),
                                    max_steps=int(variables.get('max_steps', 3)),
                                    client=client, model=model, trace=trace)
    except Exception as error:
        import httpx
        from google.genai import errors
        transport = isinstance(error, (httpx.TransportError, errors.APIError))
        category = ('output_truncated' if getattr(error, 'category', None) == 'output_truncated'
                    else 'transport_error' if transport else 'application_error')
        trace['event'] = category
        log({'track':track, 'phase':category, 'exception_type':type(error).__name__, 'trace':trace})
        return {'error': category+': '+type(error).__name__, 'metadata':{'trace':trace}}
    return {'output':json.dumps(result), 'metadata':{'trace':trace}}


def call_api(prompt, options, context):
    config = (options or {}).get('config', {})
    variables = (context or {}).get('vars', {})
    return evaluate_case(variables, backend=config.get('backend', 'mock'))
