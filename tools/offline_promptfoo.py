#!/usr/bin/env python3
"""Run pinned promptfoo with only synthetic/model-boundary fixtures, in a fresh copy."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def parse_version(output: str) -> str:
    for line in output.splitlines():
        candidate = line.strip()
        if re.fullmatch(r"\d+\.\d+\.\d+", candidate):
            return candidate
    return output.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--subject', choices=['project', 'labs/lab2', 'labs/lab5'], default='project')
    parser.add_argument('--config', default='promptfooconfig_offline.yaml')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = args.runtime.resolve()
    node = runtime / 'node-v22.22.0-linux-x64/bin/node'
    cli = runtime / 'node-tools/node_modules/promptfoo/dist/src/main.js'
    if not node.is_file():
        print('Local Node 22.22.0 is missing. Install the pinned runtime described in docs/RUNTIME_REPLAY.md.', file=sys.stderr)
        return 2
    if not cli.is_file():
        print('Local Promptfoo 0.123.1 is missing. Run npm ci with runtime/package-lock.json as described in docs/RUNTIME_REPLAY.md.', file=sys.stderr)
        return 2
    node_version = subprocess.run([str(node), '--version'], capture_output=True, text=True, check=False)
    if node_version.returncode or node_version.stdout.strip() != 'v22.22.0':
        print('Incompatible local Node. This course requires Node 22.22.0.', file=sys.stderr)
        return 2
    promptfoo_version = subprocess.run([str(node), str(cli), '--version'], capture_output=True, text=True, check=False)
    promptfoo_version_text = parse_version(promptfoo_version.stdout)
    if promptfoo_version.returncode or promptfoo_version_text != '0.123.1':
        print(f'Incompatible local Promptfoo. This course requires Promptfoo 0.123.1; detected {promptfoo_version_text or "no version"}.', file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix='llm-sec-promptfoo-'))
    subject = work / args.subject
    shutil.copytree(root / args.subject, subject,
                    ignore=shutil.ignore_patterns('.env', '.venv', '__pycache__', 'node_modules', 'logs.jsonl'))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    guards = root / 'tools/offline_guard'
    env = {'HOME': str(work), 'PATH': str(runtime/'node-v22.22.0-linux-x64/bin')+':'+str(Path(sys.executable).parent)+':/usr/bin:/bin',
           'LANG': 'C.UTF-8', 'LLM_OFFLINE': '1', 'PYTHON_DOTENV_DISABLED': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(guards),
           'COURSE_PYTHON': sys.executable, 'MODEL_ID': 'offline-fixture',
           'PROMPTFOO_DISABLE_TELEMETRY': '1', 'PROMPTFOO_DISABLE_UPDATE': '1',
           'PROMPTFOO_CONFIG_DIR': str(work/'.promptfoo'),
           'NODE_OPTIONS': '--require='+str(guards/'node.cjs'),
           'LLM_LOG_PATH': str(work/'application.jsonl')}
    cmd = [str(node), str(cli), 'eval', '-c', args.config, '-o', str(output), '--no-cache', '--no-progress-bar']
    proc = subprocess.run(cmd, cwd=subject, env=env, capture_output=True, text=True, timeout=300)
    output.with_suffix('.log').write_text(proc.stdout+proc.stderr)
    trace = work/'application.jsonl'
    if trace.exists():
        shutil.copyfile(trace, output.with_suffix('.application.jsonl'))
    output.with_suffix('.execution.json').write_text(json.dumps({
        'command': cmd, 'cwd': str(subject), 'exit_code': proc.returncode,
        'network': 'blocked by Python and Node guards', 'live_inference': 'NOT RUN'}, indent=2)+'\n')
    print(proc.stdout[-5000:])
    print(proc.stderr[-1500:], file=sys.stderr)
    return proc.returncode

if __name__ == '__main__':
    raise SystemExit(main())
