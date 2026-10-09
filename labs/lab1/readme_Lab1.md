# Lab 1 — Analyse des risques et réponses structurées

## Objectif

Établir une base d’analyse de contenus liés à la sécurité LLM, observer les risques identifiés et vérifier le contrat de réponse structuré avant toute comparaison de prompts.

## Résultats obtenus

- Replay officiel offline: **7 tests réussis**, aucune erreur. Aucune inférence live n’est exécutée par ce replay.
- Le rapport de base présent contient **3 cas**. Les réponses indiquent explicitement « Stubbed response for testing without external API »: ce sont des sorties mockées, pas une mesure du modèle.
- Les fichiers source, tests et rapport conservé sont dans `src/`, `tests/` et `reports/`.

## Preuves

- Replay: [`../../reports/offline/lab1/unit_results.json`](../../reports/offline/lab1/unit_results.json) et son journal `unit_results-labs-lab1.log`.
- Résultat de base: [`reports/baseline.json`](reports/baseline.json).
- Interface pédagogique: [`../../student_support/labs/lab1.html`](../../student_support/labs/lab1.html).