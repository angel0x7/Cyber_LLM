# Assessment — LLM Security

Current six-lab assessment model, explicitly authorized for this course expansion:
**Six labs = 50%; final project = 50%. Each lab is scored /10.**

Lab component = **(sum of Lab 1..Lab 6 / 60) × 50**.

Lab 1 /10 · Lab 2 /10 · Lab 3 /10 · Lab 4 /10 · Lab 5 /10 · Lab 6 /10.
Lab 6 — Cross-Model GenAI Security Benchmark: submit LAB6_REPORT.md or PDF plus sanitized benchmark CSV/JSON.

Lab 6 /10: reproducibility 2; experimental fairness 2; security interpretation 2; benign utility 1; reliability/latency 1; cost analysis 1; limitations/scientific reasoning 1.
The archived syllabus PDFs retain the historical four-lab breakdown. This current
assessment document supersedes that breakdown; the 50/50 module split is retained.

Choose Secure RAG **OR** Safe Agent. Both starter tracks are supplied.

## Project rubric (60 raw points, scaled to 50% of course grade)

- Architecture & reproducibility: 15
- Guardrails efficacy: 10
- Automated evaluation depth: 10
- Red-team evidence: 10
- Risk mapping (OWASP/ATLAS): 5
- Report quality: 10

Retained from the course assignment authority, README-llm-cybersec.md.
The original syllabus is preserved in Syllabus-Summary/. The project rubric is unchanged.

## Deliverables and defense

Source and setup instructions; prompts; policy files; application evaluation config;
raw results.json; report.html; metrics.csv; replay application.jsonl; a 3–5 page
analysis (five pages meets the original assignment specification); a seven-minute
video or live demo. Moodle supplies the submission destination and defense time.
Include threat model, architecture, guards, measured failures/fixes, limitations,
and OWASP/ATLAS mapping. Keep all credentials out of submissions.

## Retained project thresholds

JSON validity ≥0.95; safety on attack tests ≥0.85; RAG citations on ≥0.80 of
eligible knowledge questions; Agent allow-listed tools only, maximum three steps.
Report coverage and provider errors separately. Offline fixtures validate software,
not live model thresholds. Live replay evidence has documented limits; meeting a threshold must be demonstrated in the submitted application.

## Lab checkpoints

Lab 1: threat/risk mapping, completeness, clarity; compare naive/secure prompts
and validate the structured contract. Lab 2: reproducibility, evaluation design,
and analysis; preserve PROVISIONAL_GROUND_TRUTH until label review is complete.
Lab 3: correct scanner use, remediation quality, verification rigor; scan before
and after reviewed changes without deploying deliberately insecure examples.
Lab 4: attack coverage, guarded/unguarded comparison, correctly separated outcomes,
and an evidence-based explanation of residual risk.


## Lab 5 — OWASP GenAI Red Team Arena /10

Execution/evidence 2; OWASP mapping 2; vulnerable–hardened interpretation 2;
model–application defense distinction 2; cost/latency 1; reproducibility 1.
Submit LAB5_REPORT.md or PDF plus sanitized results.json or results.csv.
Successful jailbreak counts are not grading rewards.
