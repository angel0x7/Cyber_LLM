# Lab 3 — Scan de sécurité et vérification des corrections

## Objectif

Scanner les configurations Terraform, Kubernetes et Docker, analyser les résultats Checkov/Semgrep, puis vérifier les changements avec un second scan. Les exemples vulnérables sont destinés à l’analyse et ne doivent pas être déployés.

## Résultats obtenus

- Replay officiel offline: **8 tests réussis**, aucune erreur.
- Scan Checkov initial: Terraform **4 réussites / 24 échecs**, Kubernetes **69 / 20**, Dockerfile **38 / 3**.
- Scan Checkov après: les mêmes nombres sont conservés (**111 contrôles réussis, 47 en échec** au total). Les résultats ne montrent donc pas de réduction des findings Checkov dans les fichiers rescannés.
- Semgrep: **2 findings** avant et après: image Docker taggée `latest` (warning) et conteneur Kubernetes privilégié (error).
- `remediation_suggestions.json` est vide: aucune suggestion de remédiation exploitable n’est enregistrée.




## Preuves

- Replay: [`../../reports/offline/lab3/unit_results.json`](../../reports/offline/lab3/unit_results.json).
- Rapports Checkov/Semgrep avant: [`../../reports/offline/lab3/checkov.json`](../../reports/offline/lab3/checkov.json), [`../../reports/offline/lab3/semgrep.json`](../../reports/offline/lab3/semgrep.json).
- Rapports après: [`reports/checkov_after.json`](reports/checkov_after.json), [`reports/semgrep_after.json`](reports/semgrep_after.json).
- Suggestions: [`reports/remediation_suggestions.json`](reports/remediation_suggestions.json).
- Interface pédagogique: [`../../student_support/labs/lab3.html`](../../student_support/labs/lab3.html).