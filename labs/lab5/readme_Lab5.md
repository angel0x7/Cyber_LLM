# Lab 5 — OWASP GenAI Red Team Arena

## Objectif

Évaluer 20 scénarios dans deux modes (vulnerable et hardened), puis séparer les succès d’attaque, les refus du modèle et les blocages de l’application. Les scénarios couvrent notamment les risques OWASP GenAI LLM01, LLM02, LLM05 et LLM06.

## Résultats obtenus

- Replay officiel offline: **32 tests réussis**, aucune erreur.
- Arène offline: **40 lignes synthétiques**, soit 20 par mode. En mode vulnerable, **16/20** cas adversariaux sont étiquetés `attack_success`. En mode hardened, **0/20** le sont et **16/20** sont bloqués localement. Les quatre tâches bénignes sont réussies dans chaque mode.
- Une tentative live locale conserve seulement **2 lignes en erreur de transport**. Elles ne fournissent pas de résultats de modèle interprétables.



## Preuves

- Replay: [`../../reports/offline/lab5/unit_results.json`](../../reports/offline/lab5/unit_results.json).
- Résultats offline: [`reports/offline/results.json`](reports/offline/results.json) et `results.csv`.
- Tentative live: [`reports/live/results.json`](reports/live/results.json).
- Guide du lab: [`README.md`](README.md) et [`../../student_support/labs/lab5.html`](../../student_support/labs/lab5.html).