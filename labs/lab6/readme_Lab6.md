# Lab 6 — Benchmark de sécurité multi-modèles

## Objectif

Comparer les mêmes scénarios et la même application sur quatre modèles, avec contrôle préalable d’admission, suivi des coûts et séparation des lignes évaluables des erreurs. Le benchmark complet comporte 160 conditions; le smoke test décide si chaque modèle peut être admis.

## Résultats obtenus

- Replay officiel offline: **22 tests réussis**, aucune erreur.
- Artefact offline: **160 lignes synthétiques**. Elles valident le traitement des résultats, mais ne constituent pas une mesure comparative des modèles.
- Smoke live archivé: **16 appels** sur les quatre modèles. DeepSeek V4.1 Flash, GLM 5.3 et Kimi K3 sont `ADMITTED`; Xiaomi MiMo V2.5 Pro est `MODEL_INCOMPATIBLE` en raison d’échecs du contrat d’identité/coût. Coût des 16 lignes: environ **0,0150 USD**.
- Le benchmark complet n’a pas été lancé, car la règle d’admission n’est pas satisfaite par les quatre modèles. L’audit de prix OpenRouter est conservé dans `reports/prices.json`.


## Preuves

- Replay: [`../../reports/offline/lab6/unit_results.json`](../../reports/offline/lab6/unit_results.json).
- Benchmark synthétique: [`../../reports/offline/lab6/benchmark/benchmark.json`](../../reports/offline/lab6/benchmark/benchmark.json).
- Smoke live: [`reports/live/benchmark.json`](reports/live/benchmark.json); exécution gardée dans `reports/live/`.
- Audit de prix: [`reports/prices.json`](reports/prices.json).
- Guide du lab: [`README.md`](README.md) et [`../../student_support/labs/lab6.html`](../../student_support/labs/lab6.html).