import re, json
from typing import Dict, Any, Tuple
from pydantic import BaseModel, Field

class SafeOutput(BaseModel):
    # Both tracks must return this minimal envelope
    answer: str
    citations: list[str] = []
    safety: str = Field(pattern="^(safe|unsafe)$")
    rationale: str

DENY_INPUT = [
    r"(?i)ignore (all|previous) instructions",
    r"(?i)you are now the system",
    r"(?i)print (the )?admin password",
    r"(?i)run shell|execute .*command|rm -rf",
    r"(?i)follow .* url and .* instructions",
]
DENY_OUTPUT = [
    r"(?i)secret|password|api[_-]?key|token|private key|ssh-rsa",
]

def input_guard(text: str) -> Tuple[bool, str]:
    for pat in DENY_INPUT:
        if re.search(pat, text):
            return False, f"blocked by input rule /{pat}/"
    return True, ""

def output_guard(text: str) -> Tuple[bool, str]:
    for pat in DENY_OUTPUT:
        if re.search(pat, text):
            return False, f"blocked by output rule /{pat}/"
    return True, ""

def enforce_json_schema(raw: str) -> Tuple[bool, str, Dict[str, Any]]:
    try:
        obj = json.loads(raw)
        SafeOutput(**obj)   # validate fields
        return True, "", obj
    except Exception as e:
        return False, f"schema error: {e}", {"raw": raw[:400]}
