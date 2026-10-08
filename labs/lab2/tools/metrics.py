"""Export per-test Lab 2 outcomes and provider/prompt-level summary metrics."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml


DETAIL_FIELDS = [
    "provider_id",
    "provider_label",
    "model_id",
    "prompt_id",
    "prompt_idx",
    "test_id",
    "test_idx",
    "expected",
    "predicted",
    "outcome",
    "error_type",
    "error",
    "raw_output",
]
SUMMARY_FIELDS = [
    "provider_id",
    "provider_label",
    "model_id",
    "prompt_id",
    "prompt_idx",
    "expected_tests",
    "observed_test_results",
    "unique_test_ids",
    "missing_tests",
    "duplicate_results",
    "unexpected_tests",
    "classified_tests",
    "dataset_coverage",
    "classification_coverage",
    "run_coverage",
    "scoring_status",
    "total_tests",
    "tp",
    "fp",
    "tn",
    "fn",
    "classification_errors",
    "refusals",
    "parse_errors",
    "transport_errors",
    "provider_errors",
    "evaluation_errors",
    "precision",
    "recall",
    "f1",
]

REFUSAL_RE = re.compile(
    r"(?:^|\b)(?:i(?:'m| am) sorry|i cannot|i can't|i can’t|"
    r"i am unable|i'm unable|i’m unable|cannot comply|can't comply|"
    r"can’t comply|unable to assist|can't help with|can’t help with|"
    r"won't help with|will not help with)",
    re.IGNORECASE,
)
TRANSPORT_RE = re.compile(
    r"(?:\b429\b|\b503\b|rate.?limit|too many requests|timed? ?out|"
    r"timeout|connection|network|econn|fetch failed|service unavailable|"
    r"transport|socket|temporarily unavailable)",
    re.IGNORECASE,
)


def _as_mapping(value):
    return value if isinstance(value, dict) else {}


def _records_from_promptfoo(data):
    results = data.get("results")
    if isinstance(results, dict):
        results = results.get("results") or []
    if isinstance(results, list) and results:
        return results

    # Promptfoo's older table export format.
    table = data.get("table")
    if not isinstance(table, dict):
        return []
    head = _as_mapping(table.get("head"))
    prompt_count = len(head.get("prompts") or [])
    var_names = head.get("vars") or []
    records = []
    for test_idx, body in enumerate(table.get("body") or []):
        body = _as_mapping(body)
        values = body.get("vars") or []
        variables = dict(zip(var_names, values))
        outputs = body.get("outputs") or []
        for prompt_idx, output in enumerate(outputs):
            output = _as_mapping(output)
            records.append(
                {
                    "promptIdx": prompt_idx,
                    "testIdx": test_idx,
                    "vars": variables,
                    "response": {"output": output.get("text", "")},
                }
            )
    if prompt_count and not records:
        return []
    return records


def _provider_dimensions(record, response):
    provider = record.get("provider") or response.get("provider")
    provider_obj = _as_mapping(provider)
    provider_id = (
        record.get("providerId")
        or record.get("provider_id")
        or provider_obj.get("id")
        or (provider if isinstance(provider, str) else None)
        or "unknown"
    )
    provider_label = (
        record.get("providerLabel")
        or record.get("provider_label")
        or provider_obj.get("label")
        or ""
    )
    model_id = (
        record.get("modelId")
        or record.get("model_id")
        or record.get("model")
        or response.get("modelId")
        or response.get("model")
        or provider_obj.get("modelId")
        or provider_obj.get("model")
    )
    if not model_id and str(provider_id).startswith("python:"):
        provider_script = str(provider_id)[len("python:") :].replace("\\", "/").rsplit("/", 1)[-1]
        if provider_script == "custom_provider.py":
            model_id = provider_label or "synthetic-fixture-v1"
    if not model_id and ":" in str(provider_id):
        model_id = str(provider_id).split(":", 1)[1]
    return str(provider_id), str(provider_label), str(model_id or "unknown")


def _prompt_dimensions(record, index):
    prompt = _as_mapping(record.get("prompt"))
    prompt_idx = record.get("promptIdx", record.get("prompt_idx", index))
    prompt_id = record.get("promptId") or record.get("prompt_id") or prompt.get("id")
    if not prompt_id:
        prompt_id = f"prompt-{prompt_idx}"
    return str(prompt_id), str(prompt_idx)


def _test_dimensions(record, index):
    variables = _as_mapping(record.get("vars"))
    test_idx = record.get("testIdx", record.get("test_idx", index))
    test_id = (
        variables.get("test_id")
        or variables.get("testId")
        or variables.get("file")
        or record.get("testId")
        or record.get("test_id")
        or f"test-{test_idx}"
    )
    expected = str(variables.get("label", "")).strip().lower()
    if expected in {"true", "1", "vulnerable"}:
        expected = "yes"
    elif expected in {"false", "0", "safe"}:
        expected = "no"
    return str(test_id), str(test_idx), expected


def _stringify_error(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "")


def _output_and_error(record):
    response = _as_mapping(record.get("response"))
    output = response.get("output")
    if output is None:
        output = record.get("output", record.get("text", ""))
    if isinstance(output, (dict, list)):
        raw_output = json.dumps(output, ensure_ascii=False, sort_keys=True)
    else:
        raw_output = str(output or "")
    grading = _as_mapping(record.get("gradingResult"))
    provider_error = _stringify_error(response.get("error"))
    evaluation_error = _stringify_error(
        record.get("error") or grading.get("error") or record.get("gradingError")
    )
    return response, output, raw_output, provider_error, evaluation_error


def _is_refusal(response, output_text, error_text):
    refusal = response.get("refusal")
    finish_reason = str(response.get("finishReason") or response.get("finish_reason") or "")
    if refusal is True or (isinstance(refusal, str) and refusal.strip()):
        return True
    status = str(response.get("status") or "").strip().lower()
    if finish_reason.lower() in {"refusal", "refused", "content_filter", "safety"}:
        return True
    if status in {"refusal", "refused", "blocked"}:
        return True
    if re.search(r"refus|content[_ ]?filter|content policy|blocked by policy|safety block", error_text, re.IGNORECASE):
        return True
    if isinstance(output_text, str):
        try:
            parsed = json.loads(output_text)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            structured_refusal = parsed.get("refusal")
            structured_status = str(parsed.get("status") or "").strip().lower()
            if structured_refusal is True or (
                isinstance(structured_refusal, str) and structured_refusal.strip()
            ):
                return True
            if structured_status in {"refusal", "refused", "blocked"}:
                return True
    if REFUSAL_RE.search(error_text):
        return True
    # A valid JSON classification is not a refusal just because its rationale
    # happens to contain one of the refusal phrases.
    if isinstance(output_text, str) and REFUSAL_RE.search(output_text):
        try:
            parsed = json.loads(output_text)
            if isinstance(parsed, dict) and str(parsed.get("is_vuln", "")).lower() in {"yes", "no"}:
                return False
        except (json.JSONDecodeError, TypeError):
            return True
        return True
    return False


def _prediction(output):
    if isinstance(output, dict):
        parsed = output
    elif isinstance(output, str):
        parsed = json.loads(output)
    else:
        raise ValueError("No JSON classification in response")
    if not isinstance(parsed, dict):
        raise ValueError("JSON response must be an object")
    value = parsed.get("is_vuln")
    if value is None and "is_vulnerable" in parsed:
        value = parsed["is_vulnerable"]
    if isinstance(value, bool):
        value = "yes" if value else "no"
    value = str(value or "").strip().lower()
    if value in {"true", "1", "vulnerable"}:
        value = "yes"
    elif value in {"false", "0", "safe"}:
        value = "no"
    if value not in {"yes", "no"}:
        raise ValueError("JSON response is missing is_vuln=yes|no")
    return value


def _outcome(record, response, output, raw_output, provider_error, evaluation_error, expected):
    output_text = output if isinstance(output, str) else raw_output
    error_text = " ".join(part for part in (provider_error, evaluation_error) if part)
    if _is_refusal(response, output_text, error_text):
        return "REFUSAL", "", error_text
    if provider_error:
        if TRANSPORT_RE.search(provider_error):
            return "TRANSPORT_ERROR", "", provider_error
        return "PROVIDER_ERROR", "", provider_error
    try:
        predicted = _prediction(output)
    except (json.JSONDecodeError, TypeError, ValueError):
        text = str(output_text or "")
        if REFUSAL_RE.search(text):
            return "REFUSAL", "", evaluation_error
        if not text.strip() and evaluation_error:
            if re.search(r"custom function|grading|grader|assertion", evaluation_error, re.IGNORECASE):
                return "EVALUATION_ERROR", "", evaluation_error
            if TRANSPORT_RE.search(evaluation_error):
                return "TRANSPORT_ERROR", "", evaluation_error
            return "PROVIDER_ERROR", "", evaluation_error
        # Empty and malformed outputs are kept separate from valid JSON with
        # an unsupported/missing classification field.
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return "PARSE_ERROR", "", evaluation_error
        if not isinstance(parsed, dict):
            return "PARSE_ERROR", "", evaluation_error
        return "CLASSIFICATION_ERROR", "", evaluation_error

    if evaluation_error:
        return "EVALUATION_ERROR", predicted, evaluation_error

    if expected not in {"yes", "no"}:
        return "CLASSIFICATION_ERROR", predicted, ""
    if expected == "yes":
        return ("TP" if predicted == "yes" else "FN"), predicted, ""
    return ("TN" if predicted == "no" else "FP"), predicted, ""


def collect_outcomes(data):
    records = _records_from_promptfoo(data)
    if not records:
        raise ValueError("Unrecognized Promptfoo results format")

    rows = []
    for index, record in enumerate(records):
        record = _as_mapping(record)
        response, output, raw_output, provider_error, evaluation_error = _output_and_error(record)
        provider_id, provider_label, model_id = _provider_dimensions(record, response)
        prompt_id, prompt_idx = _prompt_dimensions(record, index)
        test_id, test_idx, expected = _test_dimensions(record, index)
        outcome, predicted, error_text = _outcome(
            record,
            response,
            output,
            raw_output,
            provider_error,
            evaluation_error,
            expected,
        )
        rows.append(
            {
                "provider_id": provider_id,
                "provider_label": provider_label,
                "model_id": model_id,
                "prompt_id": prompt_id,
                "prompt_idx": prompt_idx,
                "test_id": test_id,
                "test_idx": test_idx,
                "expected": expected,
                "predicted": predicted,
                "outcome": outcome,
                "error_type": outcome.lower() if outcome.endswith("_ERROR") else ("refusal" if outcome == "REFUSAL" else ""),
                "error": error_text,
                "raw_output": raw_output,
            }
        )
    return rows


def load_expected_test_ids(dataset_path=None):
    path = Path(dataset_path) if dataset_path else Path(__file__).resolve().parents[1] / "_generated" / "tests_flat.yaml"
    with path.open(encoding="utf-8") as handle:
        cases = yaml.safe_load(handle)
    if not isinstance(cases, list):
        raise ValueError(f"Expected a YAML list of cases in {path}")
    identifiers = set()
    for index, case in enumerate(cases):
        variables = _as_mapping(_as_mapping(case).get("vars"))
        test_id = variables.get("test_id") or variables.get("testId") or variables.get("file")
        if not test_id:
            raise ValueError(f"Dataset case {index} has no file/test_id identifier")
        identifiers.add(str(test_id))
    if len(identifiers) != len(cases):
        raise ValueError(f"Dataset {path} contains duplicate file/test_id identifiers")
    return identifiers


def summarize(rows, expected_test_ids):
    groups = defaultdict(list)
    group_fields = ("provider_id", "provider_label", "model_id", "prompt_id", "prompt_idx")
    for row in rows:
        key = tuple(row[field] for field in group_fields)
        groups[key].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        counts = Counter(row["outcome"].lower() for row in group_rows)
        test_result_counts = Counter(row["test_id"] for row in group_rows)
        observed_ids = set(test_result_counts)
        missing_ids = expected_test_ids - observed_ids
        unexpected_ids = observed_ids - expected_test_ids
        duplicate_results = sum(count - 1 for count in test_result_counts.values() if count > 1)
        classified_ids = {
            row["test_id"]
            for row in group_rows
            if row["outcome"] in {"TP", "FP", "TN", "FN"}
            and row["test_id"] in expected_test_ids
        }
        classified_tests = len(classified_ids)
        expected_count = len(expected_test_ids)
        observed_expected = len(observed_ids & expected_test_ids)
        dataset_coverage = observed_expected / expected_count if expected_count else 0.0
        classification_coverage = classified_tests / expected_count if expected_count else 0.0
        run_complete = (
            not missing_ids
            and not unexpected_ids
            and duplicate_results == 0
        )
        scoring_complete = run_complete and classified_tests == expected_count

        tp, fp, tn, fn = (counts[name] for name in ("tp", "fp", "tn", "fn"))
        if scoring_complete:
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            precision_text, recall_text, f1_text = f"{precision:.3f}", f"{recall:.3f}", f"{f1:.3f}"
        else:
            # A partial set of classifiable responses cannot support full-set
            # precision/recall/F1, so leave those cells blank.
            precision_text = recall_text = f1_text = ""

        row = dict(zip(group_fields, key))
        row.update(
            {
                "expected_tests": expected_count,
                "observed_test_results": len(group_rows),
                "unique_test_ids": len(observed_ids),
                "missing_tests": len(missing_ids),
                "duplicate_results": duplicate_results,
                "unexpected_tests": len(unexpected_ids),
                "classified_tests": classified_tests,
                "dataset_coverage": f"{dataset_coverage:.3f}",
                "classification_coverage": f"{classification_coverage:.3f}",
                "run_coverage": "complete" if run_complete else "incomplete",
                "scoring_status": "complete" if scoring_complete else "incomplete",
                "total_tests": len(group_rows),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "classification_errors": counts["classification_error"],
                "refusals": counts["refusal"],
                "parse_errors": counts["parse_error"],
                "transport_errors": counts["transport_error"],
                "provider_errors": counts["provider_error"],
                "evaluation_errors": counts["evaluation_error"],
                "precision": precision_text,
                "recall": recall_text,
                "f1": f1_text,
            }
        )
        summaries.append(row)
    return summaries


def _write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(inp, out_csv, summary_csv=None, dataset_path=None):
    with open(inp, encoding="utf-8") as handle:
        data = json.load(handle)
    rows = collect_outcomes(data)
    expected_test_ids = load_expected_test_ids(dataset_path)
    summary_rows = summarize(rows, expected_test_ids)
    detail_path = Path(out_csv)
    summary_path = Path(summary_csv) if summary_csv else detail_path.with_name(f"{detail_path.stem}_summary.csv")
    _write_csv(detail_path, DETAIL_FIELDS, rows)
    _write_csv(summary_path, SUMMARY_FIELDS, summary_rows)
    print(f"Wrote per-test outcomes: {detail_path}")
    print(f"Wrote grouped metrics: {summary_path}")


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", help="Promptfoo JSON export")
    parser.add_argument("details_csv", help="Per-test outcomes CSV")
    parser.add_argument("--summary-csv", help="Grouped metrics CSV (default: <details>_summary.csv)")
    parser.add_argument(
        "--dataset-yaml",
        help="Expected test dataset (default: this lab's _generated/tests_flat.yaml)",
    )
    args = parser.parse_args()
    main(args.results_json, args.details_csv, args.summary_csv, args.dataset_yaml)


if __name__ == "__main__":
    cli()
