# Lab 4 — Comparaison des défenses face aux attaques

## Objectif

Comparer un bras non gardé et un bras gardé sur les mêmes entrées adversariales, en séparant les blocages locaux, les décisions du modèle et les erreurs d’exécution.

## Résultats obtenus

- Replay officiel offline: **27 tests réussis**, aucune erreur.
- Fixtures de comparaison: **47 cas par bras**. Le bras non gardé a 47 décisions synthétiques `model_safe_decision`; le bras gardé bloque localement **8/47 cas (17,0 %)** et laisse les 39 autres atteindre la fixture.
- Les deux bras utilisent des sorties explicitement étiquetées `SYNTHETIC_OFFLINE_FIXTURE_ONLY_NOT_MODEL_PERFORMANCE`; aucune inférence modèle n’a été exécutée pour ces résultats.

## Preuves

- Replay: [`../../reports/offline/lab4/unit_results.json`](../../reports/offline/lab4/unit_results.json).
- Comparaison: [`../../reports/offline/lab4/lab4_fixture_metrics.csv`](../../reports/offline/lab4/lab4_fixture_metrics.csv).
- Données par bras: [`../../reports/offline/lab4/lab4_fixture_unguarded.json`](../../reports/offline/lab4/lab4_fixture_unguarded.json), [`../../reports/offline/lab4/lab4_fixture_guarded.json`](../../reports/offline/lab4/lab4_fixture_guarded.json).
- Interface pédagogique: [`../../student_support/labs/lab4.html`](../../student_support/labs/lab4.html).