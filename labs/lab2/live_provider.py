"""Promptfoo bridge to the shared course LLM adapter for Lab 2."""

import json
import os
from collections.abc import Mapping


LABEL_PROVENANCE = "PROVISIONAL_GROUND_TRUTH"


def _messages(prompt):
    if isinstance(prompt, str):
        try:
            prompt = json.loads(prompt)
        except (TypeError, ValueError):
            if not prompt.strip():
                raise ValueError("Live Lab 2 requires a non-empty prompt")
            # Preserve the two canonical text variants without adding instructions.
            return [{"role": "user", "content": prompt}]
    if not isinstance(prompt, list) or not prompt:
        raise ValueError("Live Lab 2 requires a non-empty JSON chat message list")

    messages = []
    for message in prompt:
        if not isinstance(message, Mapping):
            raise ValueError("Live Lab 2 prompt messages must be objects")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise ValueError("Live Lab 2 prompt messages require supported roles and text content")
        messages.append({"role": role, "content": content})
    return messages


def call_api(prompt, options, context):
    """Return model text and adapter metadata; dataset labels remain provisional."""
    if os.getenv("LLM_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("LLM_OFFLINE blocks live Lab 2 evaluation")

    from course_llm.client import load_course_env as load_dotenv

    load_dotenv()
    from course_llm import client_from_env

    client = client_from_env(default_max_output_tokens=1024)
    try:
        completion = client.complete_bounded(messages=_messages(prompt), max_output_tokens=1024, retry_max_output_tokens=2048,
            reasoning_effort='low' if client.provider in {'gemini', 'groq', 'openrouter'} else None)
    finally:
        client.close()
    metadata = {
        "provider": client.provider,
        "model": client.model_id,
        "label_provenance": LABEL_PROVENANCE,
        "adapter": completion.metadata,
    }
    return {"output": completion.text or "", "metadata": metadata}
