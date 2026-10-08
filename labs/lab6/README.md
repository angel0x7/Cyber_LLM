# Lab 6 — Cross-Model GenAI Security Benchmark

Same attacks. Same application. Different models.

Open `../../student_support/labs/lab6.html` for the complete 15-step workflow,
report questions, rubric, budget and limitations. All commands run from the course root.

```sh
.venv/bin/python labs/lab6/src/run_benchmark.py --offline
.venv/bin/python tools/student_replay.py --lab lab6 --runtime .venv
.venv/bin/python labs/lab6/src/audit_prices.py --output labs/lab6/reports/prices.json
.venv/bin/python labs/lab6/src/run_benchmark.py --smoke --prices labs/lab6/reports/prices.json --budget 5
.venv/bin/python labs/lab6/src/run_benchmark.py --resume --budget 5
```

Offline data is **SYNTHETIC / NOT BENCHMARK EVIDENCE**. The live 160-row experiment
reuses the frozen Lab 5 application. All four models must pass admission before full
execution. One $5 cap includes smoke and retries. Unknown charges retain reservations.
Use `--resume` after a disconnect; never delete paid evidence to restart.

Submit LAB6_REPORT.md or PDF plus sanitized benchmark CSV/JSON. Lab 6 is /10;
all six labs contribute `(sum /60) × 50%`, with the Final Project contributing 50%.
