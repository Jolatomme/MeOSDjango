# MeOS Live Results

![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)
![Django](https://img.shields.io/badge/django-5.1%2B-092E20?logo=django)
![MySQL](https://img.shields.io/badge/MySQL-8%2B-4479A1?logo=mysql)
![Licence](https://img.shields.io/badge/licence-GPL--3.0-green)
[![Wiki](https://img.shields.io/badge/docs-wiki-ff69b4)](https://github.com/Jolatomme/MeOSDjango/wiki)

Interface web de résultats en temps réel pour les compétitions de **course d'orientation**, connectée à [MeOS](https://www.melin.nu/meos/) via son protocole MOP (MeOS Online Protocol).

> **Documentation complète** : [Wiki MeOSDjango](https://github.com/Jolatomme/MeOSDjango/wiki)

## Fonctionnalités

| Page | Description |
|---|---|
| **Accueil** | Liste des compétitions disponibles |
| **Résultats individuels** | Classement avec splits, meilleurs tronçons, estimation des erreurs |
| **Résultats par course** | Résultats groupés par parcours avec analyses |
| **Résultats relais** | Classement par équipe avec temps et rang par fraction |
| **Fiche concurrent** | Détail complet d'un coureur |
| **Résultats par club** | Tous les coureurs d'une organisation |
| **Superman** | Coureur idéal tronçon par tronçon, graphique des pertes |
| **Indice de performance** | Distribution KDE de l'indice de performance par coureur |
| **Regroupement** | Graphique des temps de passage absolus |
| **Indice lièvre/suiveur** | Détection des effets d'aspiration |
| **Duel** | Comparaison tronçon par tronçon de deux coureurs |
| **Régularité** | Analyse de la régularité des coureurs |
| **Vérification MeOS** | Détection d'erreurs dans les données MeOS |
| **Statistiques** | Vue d'ensemble de la compétition |
| **Listes de départ** | Ordres de départ |
| **Tutoriels** | Articles Markdown intégrés |
| **Réception MOP** | Endpoint `POST /mop/update/` — MeOS pousse les données en temps réel |
| **O'checklist** | Rapports de départ YAML |

## Stack

**Back-end** : Django 5.1+ (Python 3.11+) · **Base de données** : MySQL 8+ / MariaDB 10.6+ · **Front-end** : Bootstrap 5, Chart.js, Vanilla JS · **Tests** : pytest, Jest

## Démarrage rapide

```bash
git clone https://github.com/Jolatomme/MeOSDjango.git
cd MeOSDjango
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Créer MeOSDjango/dev_settings.py — voir le wiki Installation
python manage.py migrate
python manage.py runserver
```

→ [Installation détaillée](https://github.com/Jolatomme/MeOSDjango/wiki/Installation)
→ [Déploiement production](https://github.com/Jolatomme/MeOSDjango/wiki/Deploiement)

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) et [CLA.md](CLA.md).

## Auteurs

Voir [AUTHORS.md](AUTHORS.md).

## Licence

GPL-3.0 — voir [LICENSE](LICENSE).
