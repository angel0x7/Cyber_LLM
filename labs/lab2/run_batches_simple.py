#!/usr/bin/env python3
"""Run Lab 2 Promptfoo tests in explicit batches, without changing providers."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


LAB_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = "promptfooconfig_offline.yaml"
DEFAULT_TESTS = "_generated/tests_flat.yaml"


def load_tests(test_file):
    path = Path(test_file)
    if not path.is_absolute():
        path = LAB_DIR / path
    with path.open(encoding="utf-8") as handle:
        tests = yaml.safe_load(handle)
    if not isinstance(tests, list):
        raise ValueError(f"Expected a YAML list of tests in {path}")
    return tests


def split_into_batches(tests, batch_size):
    return [tests[offset : offset + batch_size] for offset in range(0, len(tests), batch_size)]


def _resolved(path):
    path = Path(path)
    return path if path.is_absolute() else (LAB_DIR / path)


def _validate_offline_config(config):
    """Refuse non-synthetic providers while the course offline guard is active."""
    if os.environ.get("LLM_OFFLINE") != "1":
        return
    providers = config.get("providers") or []
    allowed = {"python:custom_provider.py"}
    ids = {
        provider.get("id")
        for provider in providers
        if isinstance(provider, dict) and provider.get("id")
    }
    if not ids or not ids.issubset(allowed):
        raise ValueError(
            "LLM_OFFLINE=1 permits only the local python:custom_provider.py fixture provider"
        )


def create_batch_config(base_config, batch_file, batch_num, output_dir):
    base_path = _resolved(base_config)
    with base_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a Promptfoo config mapping in {base_path}")
    _validate_offline_config(config)

    config.pop("tests", None)
    config_dir = base_path.parent
    for provider in config.get("providers", []):
        if not isinstance(provider, dict):
            continue
        provider_id = provider.get("id", "")
        if isinstance(provider_id, str) and provider_id.startswith("python:"):
            provider_path = Path(provider_id[len("python:") :])
            if not provider_path.is_absolute():
                provider_path = (config_dir / provider_path).resolve()
            provider["id"] = f"python:{provider_path.as_posix()}"

    prompts = []
    for prompt in config.get("prompts", []):
        if isinstance(prompt, str) and prompt.startswith("file://"):
            relative = prompt[len("file://") :]
            prompt = f"file://{(config_dir / relative).resolve()}"
        prompts.append(prompt)
    if prompts:
        config["prompts"] = prompts
    config["tests"] = f"file://{Path(batch_file).resolve()}"

    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = LAB_DIR / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    config_path = output_path / f"_temp_config_batch_{batch_num:02d}.yaml"
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
    return config_path


def create_batch_file(batch, batch_num, output_dir):
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = LAB_DIR / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    batch_path = output_path / f"batch_{batch_num:02d}_temp.yaml"
    with batch_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(batch, handle, sort_keys=False, allow_unicode=True)
    return batch_path


def _classify_batch_result(output_json):
    if not output_json.exists():
        return "failed"
    try:
        data = json.loads(output_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "failed"
    container = data.get("results", {})
    results = container.get("results", []) if isinstance(container, dict) else container
    for result in results or []:
        response = result.get("response", {}) if isinstance(result, dict) else {}
        error = str(response.get("error", "") if isinstance(response, dict) else "")
        if any(token in error.lower() for token in ("429", "rate limit", "too many requests", "503", "service unavailable", "overloaded")):
            return "provider_error"
    return "complete"


def run_batch(config_path, batch_num, output_dir, timeout_seconds):
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = LAB_DIR / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    output_json = output_path / f"batch_{batch_num:02d}_results.json"
    output_html = output_path / f"batch_{batch_num:02d}_report.html"
    command = [
        "npx",
        "promptfoo",
        "eval",
        "-c",
        str(config_path),
        "-o",
        str(output_json),
        "-o",
        str(output_html),
    ]
    print(f"Running batch {batch_num}: {' '.join(command)}")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=LAB_DIR,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        print(f"Batch {batch_num} timed out after {elapsed:.1f}s", file=sys.stderr)
        return "timeout"
    status = _classify_batch_result(output_json)
    if completed.returncode != 0 and status == "complete":
        status = "failed"
    print(f"Batch {batch_num}: {status}")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0, help="Pause between batches in seconds")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--tests", default=DEFAULT_TESTS)
    parser.add_argument("--start", type=int, default=1, help="First one-based batch number")
    parser.add_argument("--end", type=int, help="Last one-based batch number, inclusive")
    parser.add_argument("--output-dir", default="reports/batches")
    args = parser.parse_args(argv)

    if args.batch_size < 1 or args.start < 1 or args.delay < 0:
        parser.error("batch size and start must be positive; delay cannot be negative")
    config_path = _resolved(args.config)
    with config_path.open(encoding="utf-8") as handle:
        base_config = yaml.safe_load(handle)
    if not isinstance(base_config, dict):
        parser.error(f"Invalid Promptfoo config: {config_path}")
    try:
        _validate_offline_config(base_config)
        tests = load_tests(args.tests)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))

    batches = split_into_batches(tests, args.batch_size)
    end = min(args.end or len(batches), len(batches))
    if args.start > end:
        parser.error(f"start batch {args.start} is after end batch {end}")

    statuses = []
    for batch_num in range(args.start, end + 1):
        batch = batches[batch_num - 1]
        batch_file = create_batch_file(batch, batch_num, "_generated/batches")
        batch_config = create_batch_config(
            config_path,
            batch_file,
            batch_num,
            "reports/batches",
        )
        status = run_batch(batch_config, batch_num, args.output_dir, args.timeout)
        statuses.append({"batch": batch_num, "status": status})
        if status in {"provider_error", "timeout", "failed"}:
            break
        if args.delay and batch_num < end:
            time.sleep(args.delay)

    output_path = Path(args.output_dir)
    if not output_path.is_absolute():
        output_path = LAB_DIR / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    summary_path = output_path / "batch_summary.json"
    summary_path.write_text(json.dumps(statuses, indent=2) + "\n", encoding="utf-8")
    return 0 if statuses and all(row["status"] == "complete" for row in statuses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
