"""Local synthetic provider for Lab 2's offline pipeline checks.

This provider deliberately echoes each fixture's expected label. It verifies
that Promptfoo can load the prompts and dataset and that result parsing works;
it does not evaluate code or measure prompt quality.
"""

import json
import re
from collections.abc import Mapping


def call_api(prompt, options, context):
    """Return a deterministic JSON fixture without network or filesystem I/O."""
    if isinstance(context, Mapping):
        variables = context.get("vars", {})
    else:
        variables = getattr(context, "vars", {})
    if not isinstance(variables, Mapping):
        raise ValueError("Synthetic Lab 2 provider requires test vars")

    label = str(variables.get("label", "")).strip().lower()
    if label not in {"yes", "no"}:
        raise ValueError("Synthetic Lab 2 provider requires vars.label to be yes or no")

    cwe_hint = str(variables.get("cwe_hint", "")).strip()
    cwe = cwe_hint if label == "yes" and re.fullmatch(r"CWE-\d{1,5}", cwe_hint) else None
    output = {
        "is_vuln": label,
        "cwe": cwe,
        "title": "Synthetic fixture finding" if label == "yes" else "Synthetic fixture safe",
        "rationale": "Deterministic offline fixture derived from the dataset label.",
    }
    return {"output": json.dumps(output, sort_keys=True)}
