"""Explicit live settings. Offline replay supplies a client and never reads dotenv."""
import os
from course_llm.client import load_course_env as load_dotenv

DEAD_MODELS = {'gemini-3-pro-preview', 'gemini-2.0-flash'}

def validate_model(model):
    if not model or not isinstance(model, str):
        raise ValueError('MODEL_ID is required; select it in Phase 1B')
    if model.startswith(('google:', 'openrouter:')):
        raise ValueError('MODEL_ID must be a bare model ID, without a promptfoo provider prefix')
    if model in DEAD_MODELS:
        raise ValueError('MODEL_ID is a quarantined retired model')
    return model

def live_client():
    if os.getenv('LLM_OFFLINE') == '1':
        raise RuntimeError('LLM_OFFLINE=1: live inference and dotenv loading are disabled')
    load_dotenv()
    model = validate_model(os.getenv('MODEL_ID'))
    from course_llm import client_from_env

    return client_from_env(default_max_output_tokens=2048), model
