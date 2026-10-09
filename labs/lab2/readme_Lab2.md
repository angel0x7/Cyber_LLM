# Lab 2 — Évaluation de prompts et classification

## Objectif

Comparer deux configurations de prompts sur un jeu de 30 cas chacune, suivre la couverture des cas, puis distinguer les classifications des refus, erreurs de parsing et erreurs de transport. Les labels du jeu restent provisoires.

## Résultats obtenus

- Replay officiel offline: **12 tests réussis**, aucune erreur; aucune inférence live dans le replay.
- Fixtures offline: **30/30 cas classifiés par prompt**, couverture complète, précision **1,000**, rappel **1,000** et F1 **1,000** pour les deux prompts. Ces valeurs décrivent le fournisseur synthétique `synthetic-fixture-v1` uniquement.
- Tentative live archivée: **30 erreurs de transport pour chacun des deux prompts**. Les cas ont été observés, mais aucun n’a été classifié; le scoring est donc incomplet et précision/rappel/F1 ne sont pas calculables.



## Preuves

- Replay: [`../../reports/offline/lab2/unit_results.json`](../../reports/offline/lab2/unit_results.json).
- Métriques offline: [`../../reports/offline/lab2/metrics_summary.csv`](../../reports/offline/lab2/metrics_summary.csv) et `metrics.csv`.
- Métriques de la tentative live: [`reports/metrics_summary.csv`](reports/metrics_summary.csv).
- Configuration d’évaluation: [`promptfooconfig_live.yaml`](promptfooconfig_live.yaml).
- Interface pédagogique: [`../../student_support/labs/lab2.html`](../../student_support/labs/lab2.html).