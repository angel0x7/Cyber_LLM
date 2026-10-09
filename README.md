# Cyber_LLM — bilan des labs

Ce dépôt rassemble six labs de sécurité GenAI et le projet final Secure RAG / Safe Agent. Les rapports ci-dessous résument le travail et les artefacts présents dans le dépôt au 9 octobre 2026. Ils distinguent les tests, les fix offline  et les appels.

## Résumé des résultats

| Module | Rejeu officiel offline | Résultat spécifique conservé | État live local |
|---|---:|---|---|
| [Lab 1](labs/lab1/readme_Lab1.md) | 7/7 tests réussis | Rapport de base à 3 cas, réponses mockées | Non mesuré |
| [Lab 2](labs/lab2/readme_Lab2.md) | 12/12 tests réussis | 60 classifications fixtures; précision/rappel/F1 à 1,000 | 60 erreurs de transport, score non calculable |
| [Lab 3](labs/lab3/readme_Lab3.md) | 8/8 tests réussis | Checkov et Semgrep avant/après | Aucune validation live nécessaire |
| [Lab 4](labs/lab4/readme_Lab4.md) | 27/27 tests réussis | 47 cas par bras; 8 blocages locaux sur le bras gardé | Fixtures seulement pour la comparaison archivée |
| [Lab 5](labs/lab5/readme_Lab5.md) | 32/32 tests réussis | 40 lignes offline synthétiques, 20 par mode | Deux lignes archivées en erreur de transport |
| [Lab 6](labs/lab6/readme_Lab6.md) | 22/22 tests réussis | 160 conditions offline synthétiques; smoke live de 16 lignes | 3 modèles admis, 1 incompatible; benchmark complet non lancé |
| [Projet Secure RAG / Safe Agent](project/README.md) | 27/27 tests réussis | Évaluation Promptfoo offline: 8/8 cas réussis | Appel RAG et évaluation live interrompus lors de la connexion fournisseur |

Les six suites de labs totalisent **108/108 tests**; le projet ajoute **27/27**, soit **135 tests réussis** dans les dernières preuves offline enregistrées. Ces nombres valident les contrats logiciels testés, pas la robustesse générale des modèles. Les résultats détaillés et leurs limites sont documentés dans chaque rapport.

## Parcours

Les labs couvrent l’analyse des risques et des prompts (Lab 1), l’évaluation de classifieurs et de prompts (Lab 2), le scan de configuration et l’analyse des corrections (Lab 3), la comparaison d’attaques avec/sans garde (Lab 4), l’arène red team OWASP GenAI (Lab 5), puis un smoke test et un benchmark multi-modèles (Lab 6). Le projet final propose au choix une application Secure RAG ou un Safe Agent.


## Rejouer les tests offline

Depuis la racine du dépôt, charger l’environnement puis lancer le replay voulu:

```sh
source ./course_env.sh
.venv/bin/python tools/student_replay.py --lab lab1 --runtime "$REPLAY_ENV"
```

Remplacer `lab1` par `lab2` à `lab6` ou `project`. Le replay officiel s’exécute hors réseau et marque explicitement l’inférence live comme non exécutée. Les expériences live ont besoin d’un fournisseur joignable et de ses identifiants privés; ne placez jamais de clés dans les rapports ou les soumissions.

## Lecture des preuves

- `reports/offline/<module>/unit_results.json` et les journaux associés attestent les tests du replay isolé.
- Les rapports de Lab 2, Lab 4 et Lab 5 qui portent `synthetic_fixture` sont des données pédagogiques déterministes, pas des réponses de modèle.
- Le smoke de Lab 6 est un contrôle d’admission limité; il ne remplace pas les 160 conditions du benchmark complet.
- Les erreurs réseau, de transport, de schéma et les lignes manquantes restent des échecs ou des observations incomplètes. Elles ne sont jamais comptées comme des défenses réussies.
- Les métriques de Lab 2 reposent sur des labels provisoires; elles ne doivent pas être présentées comme une vérité terrain révisée.