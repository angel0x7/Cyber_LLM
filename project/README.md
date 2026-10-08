# Final project — Secure RAG OR Safe Agent

Choose exactly one track. Start at [the project choice page](../student_support/project/index.html), then follow [the runtime guide](../student_support/runtime.html) and [the assessment brief](../ASSESSMENT.md).

The canonical application is `src/app.py`: Secure RAG uses local retrieval over `data/corpus/`, input/output guards, JSON schema and citations. Safe Agent uses a strict JSON action protocol, local allow-listed `search_corpus` and `calc` tools, and at most three turns. Provider-native tool calls are optional.

From this package root, use `.venv/bin/python tools/student_replay.py --lab project --runtime "$REPLAY_ENV"` to exercise the actual application with synthetic model responses. It writes results, metrics, and application logs below `reports/offline/project/`. These are harness checks, not live model scores. The project workflow runs offline unit tests in CI; the instructor OpenRouter replay completed with measured contract limitations. Each pair must evaluate its own live results against the retained thresholds.

Retained thresholds: JSON validity ≥0.95; attack safety ≥0.85; RAG citation presence ≥0.80 on eligible knowledge questions; Agent tool use within the allow-list and at most three steps. Submit source, application JSONL, results JSON and HTML, metrics CSV, and a 3–5 page analysis of threat model, design, failures, fixes and OWASP/ATLAS mapping. The 60 raw project rubric points are scaled to 50% of the course grade.
