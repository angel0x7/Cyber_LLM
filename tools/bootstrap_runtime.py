#!/usr/bin/env python3
"""Create, extend, or inspect the course-local Python 3.12 runtime."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".venv"
PYTHON = RUNTIME / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def clean_env():
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PATH"] = str(PYTHON.parent) + os.pathsep + environment.get("PATH", "")
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return environment


def run(*arguments, capture=False):
    return subprocess.run(
        [str(PYTHON), *arguments],
        cwd=ROOT,
        env=clean_env(),
        check=False,
        text=True,
        capture_output=capture,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preflight", action="store_true", help="Install the small provider-check profile")
    action.add_argument("--full", action="store_true", help="Install the complete lab profile in the same .venv")
    action.add_argument("--doctor", action="store_true", help="Inspect local runtime without changing it")
    args = parser.parse_args()

    if args.doctor:
        if os.environ.get("PYTHONPATH") or os.environ.get("PYTHONHOME"):
            print("Host Python path overrides are set; bootstrap ignores them for course checks.")
        if not PYTHON.is_file():
            print("Course .venv is missing. Run python3.12 tools/bootstrap_runtime.py --preflight.")
            return 2
    else:
        if sys.version_info[:2] != (3, 12):
            print("Python 3.12 is required. Run this helper with python3.12.")
            return 2
        if not PYTHON.is_file():
            print("Creating course-local .venv with Python 3.12.")
            created = subprocess.run(
                [sys.executable, "-m", "venv", str(RUNTIME)],
                cwd=ROOT,
                env=clean_env(),
                check=False,
            )
            if created.returncode:
                print("Could not create .venv; check the local Python 3.12 installation.")
                return created.returncode

    version = run("-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))", capture=True)
    if version.returncode or not version.stdout.strip().startswith("3.12."):
        print("Course .venv must use Python 3.12; move aside the old .venv and rerun.")
        return 2
    print("Course Python:", version.stdout.strip())

    if args.doctor:
        packages = run("-c", "import httpx, dotenv, pydantic; print('Preflight imports: PASS')", capture=True)
        print(packages.stdout.strip() if packages.returncode == 0 else "Preflight imports: MISSING")
        checked = run("-m", "pip", "check", capture=True)
        print("pip check:", "PASS" if checked.returncode == 0 else "FAILED (inspect with .venv Python -m pip check)")
        node = RUNTIME / "node-v22.22.0-linux-x64" / "bin" / "node"
        node_ok = True
        if node.is_file():
            result = subprocess.run([str(node), "--version"], capture_output=True, text=True, check=False)
            node_ok = result.returncode == 0 and result.stdout.strip() == "v22.22.0"
            print("Local Node:", result.stdout.strip() if node_ok else "INCOMPATIBLE (use Node 22.22.0)")
            cli = RUNTIME / "node-tools" / "node_modules" / "promptfoo" / "dist" / "src" / "main.js"
            if cli.is_file():
                promptfoo = subprocess.run([str(node), str(cli), "--version"], capture_output=True, text=True, check=False)
                promptfoo_ok = promptfoo.returncode == 0 and promptfoo.stdout.strip() == "0.123.1"
                print("Local Promptfoo:", "0.123.1" if promptfoo_ok else "INCOMPATIBLE (use Promptfoo 0.123.1)")
                node_ok = node_ok and promptfoo_ok
            else:
                print("Local Promptfoo: not installed (needed for Promptfoo labs)")
        else:
            print("Local Node: not installed (needed for Promptfoo labs)")
        return 0 if packages.returncode == 0 and checked.returncode == 0 and node_ok else 2

    lock = "requirements.txt" if args.full else "runtime/requirements-preflight.lock"
    print("Installing", lock, "in the course-local .venv.", flush=True)
    installed = run("-m", "pip", "install", "-r", lock)
    if installed.returncode:
        print("Install failed; use this .venv's Python to inspect pip output.")
    return installed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
