#!/usr/bin/env python3
"""Replay Lab 4 through its real runner with a synthetic, local-only model fixture.

All output files carry a synthetic fixture label and must not be used as model
safety or performance evidence. No model client or credential is constructed.
"""

import argparse
from collections import Counter
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


LABEL = "SYNTHETIC_OFFLINE_FIXTURE_ONLY_NOT_MODEL_PERFORMANCE"
MODEL_ID = "offline-fixture"
FIXTURE_JSON = '{"is_safe":"yes","rationale":"Synthetic offline fixture; not model output."}'
GUARD_MARKER = "LLM_LAB4_FIXTURE_GUARDED"


def course_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parser_for(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "reports" / "offline" / "lab4",
        help="Directory for synthetic Lab 4 replay results (default: reports/offline/lab4)",
    )
    return parser


def guard_is_loaded(guard_dir: Path) -> bool:
    module = sys.modules.get("sitecustomize")
    loaded_from = getattr(module, "__file__", None)
    if not loaded_from:
        return False
    try:
        return Path(loaded_from).resolve() == (guard_dir / "sitecustomize.py").resolve()
    except OSError:
        return False


def run_guarded_child(args: argparse.Namespace, root: Path) -> int:
    """Re-exec under the course network/.env audit guard and a clean environment."""
    guard_dir = root / "tools" / "offline_guard"
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    launcher_log_path = output_dir / "lab4_fixture_launcher.log"

    with tempfile.TemporaryDirectory(prefix="lab4-fixture-home-") as home:
        clean_env = {
            "PATH": str(Path(sys.executable).parent) + os.pathsep + "/usr/bin:/bin",
            "HOME": home,
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(guard_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "LLM_OFFLINE": "1",
            "MODEL_ID": MODEL_ID,
            GUARD_MARKER: "1",
        }
        proc = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--output-dir", str(output_dir)],
            cwd=root,
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    launcher_log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    print(f"Launcher log: {launcher_log_path}")
    return proc.returncode


def read_attacks(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_run(args: argparse.Namespace, root: Path) -> int:
    """Execute run() and metrics against a disposable Lab 4 copy."""
    guard_dir = root / "tools" / "offline_guard"
    if os.getenv(GUARD_MARKER) != "1" or os.getenv("LLM_OFFLINE") != "1":
        raise RuntimeError("Fixture replay must run in the guarded LLM_OFFLINE child process")
    if not guard_is_loaded(guard_dir):
        raise RuntimeError("Course offline_guard was not loaded from PYTHONPATH")
    if os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("Fixture replay environment must not contain a model API key")

    source_lab = Path(__file__).resolve().parents[1]
    source_attacks = source_lab / "attacks" / "attacks.txt"
    expected_attacks = read_attacks(source_attacks)
    if len(expected_attacks) != 47:
        raise ValueError(f"Expected the unchanged 47-prompt corpus, found {len(expected_attacks)}")
    source_hash = file_sha256(source_attacks)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        mode: output_dir / f"lab4_fixture_{mode}.json"
        for mode in ("unguarded", "guarded")
    }
    metrics_path = output_dir / "lab4_fixture_metrics.csv"
    execution_path = output_dir / "lab4_fixture_execution.json"
    log_stream = io.StringIO()
    calls_by_mode = Counter()
    row_counts = {}

    ignore = shutil.ignore_patterns(
        ".env",
        ".venv",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "reports",
    )
    with tempfile.TemporaryDirectory(prefix="llm-sec-lab4-fixture-") as work_dir:
        copy_lab = Path(work_dir) / "lab4"
        shutil.copytree(source_lab, copy_lab, ignore=ignore)
        copied_attacks = copy_lab / "attacks" / "attacks.txt"
        attacks = read_attacks(copied_attacks)
        if file_sha256(copied_attacks) != source_hash or attacks != expected_attacks:
            raise RuntimeError("Temporary copy changed the attack corpus")

        sys.path.insert(0, str(copy_lab))
        previous_cwd = Path.cwd()
        os.chdir(copy_lab)
        try:
            from src import metrics, run_suite
            from src.guardrails import OUTPUT_CONTRACT, SYSTEM_INSTRUCTION, load_policy

            class FixtureOnlyClient:
                fixture_only = True

            fixture_client = FixtureOnlyClient()
            policy = load_policy("config/policy.yaml")

            def fixture_model(client, model_id, prompt, *, system_instruction=None):
                if client is not fixture_client or not getattr(client, "fixture_only", False):
                    raise RuntimeError("Fixture-only client invariant failed")
                if model_id != MODEL_ID:
                    raise RuntimeError("Replay attempted to use a non-fixture model ID")
                expected_system = SYSTEM_INSTRUCTION if active_mode[0] == "guarded" else None
                if system_instruction != expected_system:
                    raise RuntimeError("Runner system-instruction configuration changed")
                if OUTPUT_CONTRACT not in f"{system_instruction or ''}\n{prompt}":
                    raise RuntimeError("Runner did not request the shared JSON decision contract")
                calls_by_mode[active_mode[0]] += 1
                return FIXTURE_JSON

            active_mode = [None]
            for mode in ("unguarded", "guarded"):
                active_mode[0] = mode
                with contextlib.redirect_stdout(log_stream):
                    run_suite.run(
                        attacks,
                        mode,
                        str(output_paths[mode]),
                        client=fixture_client,
                        model_id=MODEL_ID,
                        policy=policy,
                        call_model_fn=fixture_model,
                        sleep_seconds=0,
                        retry_delay_seconds=0,
                    )
                rows = json.loads(output_paths[mode].read_text(encoding="utf-8"))
                if len(rows) != 47 or [row["attack"] for row in rows] != attacks:
                    raise RuntimeError(f"{mode} output does not contain all 47 attack rows in order")
                for row in rows:
                    row["fixture_label"] = LABEL
                    row["model_inference"] = "NOT RUN"
                output_paths[mode].write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                row_counts[mode] = dict(Counter(row["status"] for row in rows))

            with contextlib.redirect_stdout(log_stream):
                metrics.main(str(output_paths["unguarded"]), str(output_paths["guarded"]), str(metrics_path))
        finally:
            os.chdir(previous_cwd)
            sys.path.remove(str(copy_lab))

    report = {
        "label": LABEL,
        "purpose": "Exercise the real Lab 4 runner and metrics with a fixed local response.",
        "interpretation": "Synthetic plumbing only; this is not model safety, refusal, or performance evidence.",
        "model_inference": "NOT RUN",
        "fixture_model_id": MODEL_ID,
        "fixture_response": FIXTURE_JSON,
        "fixture_response_sha256": hashlib.sha256(FIXTURE_JSON.encode("utf-8")).hexdigest(),
        "provider_client": "FixtureOnlyClient; no SDK client constructed",
        "network_guard": str((guard_dir / "sitecustomize.py").relative_to(root)) + " loaded through PYTHONPATH",
        "dotenv": "PYTHON_DOTENV_DISABLED=1; .env excluded from temporary copy; no API key in child environment",
        "attack_count": 47,
        "attack_sha256": source_hash,
        "temporary_source_copy": "created for replay and removed after completion",
        "sleep_seconds": 0,
        "fixture_calls_by_mode": dict(calls_by_mode),
        "rows_by_mode": row_counts,
        "outputs": {mode: str(path) for mode, path in output_paths.items()},
        "metrics": str(metrics_path),
    }
    execution_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_dir / "lab4_fixture_replay.log").write_text(log_stream.getvalue(), encoding="utf-8")
    print(f"Synthetic fixture replay complete: {execution_path}")
    print(f"Results are plumbing diagnostics only; no live model inference was run.")
    return 0


def main() -> int:
    root = course_root()
    args = parser_for(root).parse_args()
    if os.getenv(GUARD_MARKER) == "1":
        return fixture_run(args, root)
    return run_guarded_child(args, root)


if __name__ == "__main__":
    raise SystemExit(main())
