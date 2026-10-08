#!/usr/bin/env python3
"""Replay the public offline teaching checks; fixture scores are not model scores."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', choices=['lab1', 'lab2', 'lab3', 'lab4', 'lab5', 'lab6', 'project', 'all'], required=True)
    parser.add_argument('--runtime', type=Path, default=Path(sys.prefix))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = args.runtime.resolve()
    python = str(runtime / 'bin/python')
    def run(*command):
        subprocess.run([python, '-B', *map(str, command)], cwd=root, check=True)
    labs = ['lab1', 'lab2', 'lab3', 'lab4', 'lab5', 'lab6', 'project'] if args.lab == 'all' else [args.lab]
    for lab in labs:
        subject = 'project' if lab == 'project' else 'labs/' + lab
        output = root / 'reports/offline' / lab
        output.mkdir(parents=True, exist_ok=True)
        run('tools/offline_replay.py', '--suite', subject, '--output', output/'unit_results.json')
        if lab in {'lab2', 'project'}:
            run('tools/offline_promptfoo.py', '--runtime', runtime, '--subject', subject,
                '--output', output/'results.json')
            run(subject+'/tools/metrics.py', output/'results.json', output/'metrics.csv')
        if lab == 'lab3':
            run('tools/offline_scanners.py', '--runtime', runtime, '--output-dir', output)
        if lab == 'lab4':
            run('labs/lab4/tools/offline_fixture_replay.py', '--output-dir', output)
        if lab == 'lab5':
            run('tools/offline_promptfoo.py', '--runtime', runtime, '--subject', subject,
                '--output', output/'results.json')
            arena = output/'arena'
            resume = ['--resume'] if (arena/'state.json').exists() else []
            run('labs/lab5/src/run_arena.py', '--offline', '--output', arena, *resume)
        if lab == 'lab6':
            benchmark = output/'benchmark'
            resume = ['--resume'] if (benchmark/'state.json').exists() else []
            run('labs/lab6/src/run_benchmark.py', '--offline', '--output', benchmark, *resume)
        print(f'{lab}: offline evidence in reports/offline/{lab}; live inference NOT RUN', flush=True)


if __name__ == '__main__':
    main()
