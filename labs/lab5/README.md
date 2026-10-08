# Lab 5 — OWASP GenAI Red Team Arena

Attack → Observe → Harden → Measure. Open
`student_support/labs/lab5.html` from the course root for the 16-step workflow.
OWASP GenAI Top 10 — 2025 taxonomy: LLM01, LLM02, LLM05, LLM06.

```bash
.venv/bin/python labs/lab5/src/run_arena.py --offline
.venv/bin/python tools/student_replay.py --lab lab5 --runtime .venv
.venv/bin/python labs/lab5/src/run_arena.py --smoke --budget 1
.venv/bin/python labs/lab5/src/run_arena.py --resume
```

20 scenarios × two modes = 40 rows. Smoke rows are reused. Both modes have identical
messages/schema/model/corpus/decoding; deterministic controls differ. Offline scores
are synthetic pipeline evidence, never model performance. No real denied tool runs.
`unauthorized_tool_executed` refers only to simulated dispatch. All imported output
is displayed as text; the dashboard never executes model-produced HTML or scripts.

Results: `labs/lab5/reports/offline/` or `labs/lab5/reports/live/`. Import results.json
or results.csv in `student_support/labs/lab5-dashboard.html`. Submit a sanitized
report and results, never environment files or credentials. Resume preserves completed
rows and refuses changed source/model/dataset/budget or uncertain in-flight rows.

ASR uses evaluable adversarial rows; benign rates use evaluable benign rows. Errors
remain separate and visible, never counted as defenses. Undefined denominators are
null. Model refusal and application blocks are distinct. Exact canary matching,
narrow payload shapes and the protected-fact policy are teaching controls with
limited coverage. Keep original evidence before any new experiment.

The two response contracts are aliases of one JSON schema. The model-agnostic result
schema is ready for future Lab 6; Lab 6 is upcoming, not implemented. Promptfoo 0.123.1
runs the 40 canonical offline fixtures. Its separate exploratory red-team template
is not a live runner or permission to generate more attacks remotely.
