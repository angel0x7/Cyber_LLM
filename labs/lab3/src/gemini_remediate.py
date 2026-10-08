#!/usr/bin/env python3
import os, sys, json
from pathlib import Path
from course_llm.client import load_course_env as load_dotenv

PROMPT = r"""
You are a senior cloud security engineer. From the following static-analysis findings,
produce a JSON array of remediation suggestions. Each item must be:
{
  "tool": "checkov|semgrep",
  "file": "relative/path",
  "issue_id": "CKV_... or semgrep rule id",
  "title": "short title",
  "proposed_fix": "exact changes or YAML/Terraform/Dockerfile snippet to apply",
  "justification": "why this fix addresses the risk with a reference to official docs"
}
Rules:
- Do not invent file paths or IDs. Only use items present in the input.
- Prefer concrete code/config edits over vague advice.
- Keep each 'proposed_fix' under 12 lines.
"""

def main(checkov_json, semgrep_json):
    if os.getenv("LLM_OFFLINE") == "1":
        raise RuntimeError("LLM_OFFLINE=1 blocks Gemini remediation and dotenv loading")
    load_dotenv()
    model = os.getenv("MODEL_ID")
    if not model or model.startswith(("google:", "openrouter:")) or model in {"gemini-3-pro-preview", "gemini-2.0-flash"}:
        raise ValueError("Set MODEL_ID to a supported bare SDK model ID")

    from course_llm import client_from_env

    client = client_from_env(default_max_output_tokens=8192)
    payload = {
        "checkov": json.load(open(checkov_json, encoding="utf-8")) if os.path.exists(checkov_json) else None,
        "semgrep": json.load(open(semgrep_json, encoding="utf-8")) if os.path.exists(semgrep_json) else None
    }
    print(remediate(client, model, payload))


def compact_findings(payload):
    """Keep every finding and its evidence, excluding bulky scanner bookkeeping."""
    if not isinstance(payload, dict) or not {'checkov', 'semgrep'} <= payload.keys():
        return payload
    findings = []
    groups = payload['checkov'] or []
    if isinstance(groups, dict):
        groups = [groups]
    for group in groups:
        for item in group['results']['failed_checks']:
            findings.append({
                'tool': 'checkov', 'check_id': item['check_id'],
                'file': item.get('repo_file_path', item['file_path']).lstrip('/'),
                'title': item['check_name'], 'lines': item.get('file_line_range'),
                'resource': item.get('resource'), 'code_block': item.get('code_block'),
                'guideline': item.get('guideline'), 'check_result': item.get('check_result'),
            })
    for item in (payload['semgrep'] or {}).get('results', []):
        path = Path(item['path'])
        if path.is_absolute():
            path = path.relative_to(Path(__file__).resolve().parents[1])
        findings.append({
            'tool': 'semgrep', 'check_id': item['check_id'], 'file': str(path),
            'title': item['extra']['message'],
            'lines': [item['start']['line'], item['end']['line']],
            'code': item['extra'].get('lines'), 'metadata': item['extra'].get('metadata', {}),
        })
    return findings


def remediate(client, model, payload):
    """Request remediation for an explicit findings payload through the client seam."""
    text = json.dumps(compact_findings(payload))
    if len(text) > 200000:
        raise ValueError('Findings exceed the request limit; split into explicit batches. No findings were sent.')
    resp = client.models.generate_content(
        model=model,
        contents=[
            {"role":"user","parts":[{"text":PROMPT}]},
            {"role":"user","parts":[{"text":text}]}
        ],
    )
    return resp.text or "[]"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python src/gemini_remediate.py reports/checkov.json reports/semgrep.json")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
