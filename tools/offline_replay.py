#!/usr/bin/env python3
"""Run each course unittest suite in a disposable copy, without network or .env reads."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

SUITES = ['labs/lab1', 'labs/lab2', 'labs/lab3', 'labs/lab4', 'labs/lab5', 'labs/lab6', 'project']

BOOTSTRAP = r'''
import io, json, os, pathlib, sys, time, unittest
blocked = []
def guard(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        blocked.append(event)
        raise RuntimeError('Offline test attempted network access')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if pathlib.Path(os.fsdecode(args[0])).name == '.env':
            blocked.append('private_dotenv_read')
            raise RuntimeError('Offline test attempted to read private .env')
sys.addaudithook(guard)
sys.path.insert(0, os.getcwd())
if len(sys.argv) > 2:
    sys.path.insert(0, sys.argv[2])
suite = unittest.defaultTestLoader.discover('tests')
start = time.monotonic()
result = unittest.TextTestRunner(verbosity=2).run(suite)
record = {'tests_run': result.testsRun, 'failures': len(result.failures),
          'errors': len(result.errors), 'skipped': len(result.skipped),
          'seconds': round(time.monotonic()-start, 4),
          'blocked_access_attempts': blocked,
          'status': 'PASS' if result.wasSuccessful() and not blocked else 'BLOCKED'}
pathlib.Path(sys.argv[1]).write_text(json.dumps(record, indent=2)+'\n')
sys.exit(0 if record['status']=='PASS' else 1)
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', choices=SUITES, action='append')
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='llm-sec-offline-tests-'))
    env = {'PATH': str(Path(sys.executable).parent)+'/usr/bin:/bin',
           'HOME': str(work), 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
           'LLM_OFFLINE': '1', 'PYTHON_DOTENV_DISABLED': '1',
           'GEMINI_API_KEY': 'dummy-offline', 'MODEL_ID': 'offline-fixture',
           'PROMPTFOO_DISABLE_TELEMETRY': '1',
           'PYTHONPATH': str(work) + os.pathsep + str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get('PYTHONPATH', '')}
    records = []
    shutil.copytree(source / 'course_llm', work / 'course_llm',
                    ignore=shutil.ignore_patterns('__pycache__'))
    for name in (args.suite or SUITES):
        if name == 'labs/lab6' and not (work/'labs/lab5').exists():
            shutil.copytree(source/'labs/lab5', work/'labs/lab5',
                            ignore=shutil.ignore_patterns('.env', '.venv', '__pycache__', 'reports'))
        target = work / name
        shutil.copytree(source / name, target,
                        ignore=shutil.ignore_patterns('.env', '.venv', '__pycache__', '.pytest_cache', 'node_modules'))
        record_path = work / (name.replace('/', '-')+'.json')
        started = time.monotonic()
        proc = subprocess.run([sys.executable, '-I', '-B', '-c', BOOTSTRAP, str(record_path), str(work)],
                              cwd=target, env=env, capture_output=True, text=True, timeout=180)
        log_path = output.parent / (output.stem+'-'+name.replace('/', '-')+'.log')
        log_path.write_text(proc.stdout+proc.stderr)
        record = json.loads(record_path.read_text()) if record_path.exists() else {
            'status': 'BLOCKED', 'tests_run': 0, 'errors': 1,
            'seconds': round(time.monotonic()-started, 4)}
        record.update(suite=name, exit_code=proc.returncode, log=str(log_path))
        records.append(record)
        print(name, record['status'], record['tests_run'])
    data = {'python': sys.version, 'executable': sys.executable, 'work_dir': str(work),
            'source': str(source), 'suites': records,
            'tests_run': sum(x['tests_run'] for x in records),
            'status': 'PASS' if all(x['status']=='PASS' for x in records) else 'BLOCKED',
            'live_inference': 'NOT RUN'}
    output.write_text(json.dumps(data, indent=2)+'\n')
    return 0 if data['status']=='PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
