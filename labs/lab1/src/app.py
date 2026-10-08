import os, json, time
from course_llm.client import load_course_env as load_dotenv
from google import genai
from google.genai import errors as genai_errors
from pydantic import ValidationError
from .schema import Analysis
from .filters import basic_input_filter
from .prompts import SYSTEM_POLICY, USER_TEMPLATE

SEVERITY_CANONICAL = {
    "low": "low",
    "medium": "medium",
    "med": "medium",
    "moderate": "medium",
    "mid": "medium",
    "high": "high",
    "critical": "critical",
    "crit": "critical",
    "severe": "high",
}

def normalize_severity(analysis: Analysis):
    for finding in analysis.findings:
        raw_severity = finding.severity.strip().lower()
        normalized_key = " ".join(raw_severity.replace("-", " ").split())
        canonical = SEVERITY_CANONICAL.get(normalized_key, "medium")
        finding.severity = canonical

def get_client():
    if os.getenv("LLM_OFFLINE") == "1":
        raise RuntimeError("LLM_OFFLINE=1 blocks live inference")
    from course_llm import client_from_env

    return client_from_env(default_max_output_tokens=2048)

def analyze_text(client, model_id: str, content: str):
    safe = basic_input_filter(content)
    attempts = 0
    while True:
        try:
            resp = client.models.generate_content(
                model=model_id,
                contents=USER_TEMPLATE.format(content=safe),
                config={
                    "system_instruction": SYSTEM_POLICY,
                    "response_mime_type": "application/json",
                },
            )
            break
        except genai_errors.ServerError as err:
            attempts += 1
            if attempts >= 3:
                return {
                    "error": f"Gemini API error after retries: {err.__class__.__name__}: {err}",
                }
            time.sleep(min(2 ** attempts, 8))
        except genai_errors.APIError as err:
            return {
                "error": f"Gemini API error: {err.__class__.__name__}: {err}",
            }
        except Exception as err:
            if getattr(err, "category", None) == "output_truncated":
                return {"error": "OUTPUT_TRUNCATED", "error_code": "OUTPUT_TRUNCATED", "raw": ""}
            return {
                "error": f"Unexpected error: {err.__class__.__name__}: {err}",
            }

    raw = getattr(resp, "text", None) or getattr(resp, "output_text", "")
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    if not raw:
        return {"error": "Empty response from model", "raw": ""}
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "findings" in data:
            for finding in data["findings"]:
                if isinstance(finding, dict) and "cwe" in finding:
                    cwe_value = finding["cwe"]
                    if isinstance(cwe_value, list):
                        finding["cwe"] = ", ".join(str(item) for item in cwe_value)
                    elif cwe_value is not None and not isinstance(cwe_value, str):
                        finding["cwe"] = str(cwe_value)
        analysis = Analysis(**data)
        normalize_severity(analysis)
        return analysis
    except ValidationError as err:
        return {
            "error": "Response failed schema validation",
            "details": err.errors(),
            "raw": raw[:2000],
        }
    except Exception as e:
        return {"error": f"Invalid JSON from model: {e}", "raw": raw[:2000]}

def main(*, client=None, model_id=None):
    if client is None:
        if os.getenv("LLM_OFFLINE") == "1":
            raise RuntimeError("LLM_OFFLINE=1 blocks live inference and dotenv loading")
        load_dotenv()
        model_id = model_id or os.getenv("MODEL_ID")
        if not model_id or model_id.startswith(("google:", "openrouter:")) or model_id in {"gemini-3-pro-preview", "gemini-2.0-flash"}:
            raise ValueError("Set MODEL_ID to a supported bare SDK ID selected in Phase 1B")
        client = get_client()
    elif not model_id:
        raise ValueError("Injected clients require an explicit fixture model_id")

    # baseline over data/prompts_lab1.json
    here = os.path.dirname(os.path.dirname(__file__))
    data_path = os.path.join(here, "data", "prompts_lab1.json")
    with open(data_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    results = []
    for i, item in enumerate(items, 1):
        res = analyze_text(client, model_id, item["text"])
        if hasattr(res, "model_dump"):
            payload = res.model_dump()
        else:
            payload = res
        results.append({"id": i, "input": item, "result": payload})

    # write report
    reports_dir = os.path.join(here, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    out = os.path.join(reports_dir, "baseline.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out} with {len(results)} items.")

if __name__ == "__main__":
    main()
