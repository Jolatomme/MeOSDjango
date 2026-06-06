# MeOS Live Results

Interface web de résultats en temps réel pour les compétitions de **course d'orientation**, connectée à [MeOS](https://www.melin.nu/meos/) via son protocole MOP (MeOS Online Protocol).

Plus d'informations sur le [Wiki](https://github.com/Jolatomme/MeOSDjango/wiki)

---

## Fonctionnalités

| Page | Description |
|---|---|
| **Accueil** | Liste des compétitions disponibles |
| **Résultats individuels** | Classement avec temps intermédiaires (splits), meilleurs tronçons et estimation des erreurs |
| **Résultats par course** | Résultats groupés par parcours avec analyses détaillées |
| **Résultats relais** | Classement par équipe avec temps et rang par fraction |
| **Fiche concurrent** | Détail complet d'un coureur (splits, statut, club) |
| **Résultats par club** | Tous les coureurs d'une organisation |
| **Superman** | Reconstruction du coureur idéal tronçon par tronçon, graphique des pertes |
| **Indice de performance** | Distribution KDE de l'indice de performance par coureur |
| **Regroupement** | Graphique des temps de passage absolus — lignes proches = coureurs ensemble |
| **Indice lièvre/suiveur** | Détection automatique des effets d'aspiration entre coureurs |
| **Duel** | Comparaison tronçon par tronçon de deux coureurs au choix |
| **Régularité** | Analyse de la régularité des coureurs au fil des épreuves |
| **Vérification MeOS** | Détection des erreurs et anomalies dans les données MeOS |
| **Statistiques** | Vue d'ensemble de la compétition (total partants, classés, top clubs) |
| **Listes de départ** | Affichage des ordre de départ des coureurs |
| **Tutoriels** | Articles Markdown intégrés avec table des matières |
| **Réception MOP** | Endpoint `POST /mop/update/` — MeOS pousse les données en temps réel |
| **O'checklist** | Réception et consultation des rapports de départ YAML poussés par l'app O'checklist |

---

## Stack technique

- **Back-end** : Django 4+ (Python 3.11+)
- **Base de données** : MySQL / MariaDB (tables `mop*` gérées par MeOS, `managed=False`)
- **Front-end** : Bootstrap 5, Chart.js, Vanilla JS (aucun framework JS requis)
- **Fonts** : Barlow + Barlow Condensed (Google Fonts)
- **Tests** : pytest + pytest-django, unittest.mock (aucune DB requise)

---

## Structure du projet

```
MeOSDjango/
├── manage.py                          # Django management script
│
├── MeOSDjango/                        # Configuration Django
│   ├── __init__.py
│   ├── settings.py                    # Paramètres principaux
│   ├── asgi.py
│   ├── wsgi.py
│   └── urls.py                        # Routage principal
│
├── results/                           # Application Django (résultats MeOS)
│
│   ├── models.py                      # Modèles Django (managed=False pour tables MeOS)
│   │                                  # MopCompetitor, MopClass, MopResult, etc.
│   │
│   ├── services.py                    # Logique métier pure (sans effet de bord HTTP)
│   │                                  # - Calcul des splits
│   │                                  # - Classements
│   │                                  # - Superman
│   │                                  # - Performance (KDE)
│   │                                  # - Regroupement
│   │
│   ├── views.py                       # Vues Django (orchestration services → templates)
│   │                                  # - Réultats individuels
│   │                                  # - Réultats par cours
│   │                                  # - Analyses avancées
│   │
│   ├── mop_views.py                   # Endpoint MOP (réception XML de MeOS)
│   ├── mop_receiver.py                # Parser XML MOP + upserts en base
│   ├── meos_checker.py                # Validation et détection d'erreurs MeOS
│   ├── verifie_moi.py                 # Vérification et validation des données
│   │
│   ├── classViews.py                  # Vues par classe (TutoView pour tutoriels)
│   ├── context_processors.py          # Injection de contexte global
│   │                                  # (SITE_NAME, CLUB_NAME, couleurs)
│   ├── admin.py                       # Admin Django
│   ├── apps.py
│   ├── urls.py                        # Routage de l'app results
│   │
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── meos_tags.py               # Filtres/tags personnalisés Django
│   │
│   ├── static/results/
│   │   ├── css/
│   │   │   ├── bootstrap.css/.min.css (variantes complètes Bootstrap 5)
│   │   │   ├── bootstrap-grid.css     (grille Bootstrap uniquement)
│   │   │   ├── bootstrap-reboot.css   (reset Bootstrap)
│   │   │   ├── bootstrap-utilities.css (utilitaires Bootstrap)
│   │   │   ├── bootstrap-icons.css    (icônes Bootstrap)
│   │   │   ├── site.css               # Styles personnalisés site
│   │   │   │                          # Variables CSS (couleurs club)
│   │   │   └── fonts/                 # Google Fonts
│   │   │
│   │   ├── js/
│   │   │   ├── bootstrap.bundle.js    (Bootstrap JS complet)
│   │   │   ├── chart.umd.min.js       # Chart.js
│   │   │   ├── site.js                # JS personnalisé site
│   │   │   │                          # Helpers: format temps, médailles, couleurs
│   │   │   └── results-splits.js      # JS spécifique aux splits
│   │   │
│   │   ├── img/                       # Images et assets
│   │   ├── fonts/                     # Polices personnalisées
│   │   ├── html/                      # Fragments HTML réutilisables
│   │   └── etiquettes/                # Assets des badges/étiquettes
│   │
│   ├── templates/results/
│   │   ├── base.html                  # Template de base (navbar, footer, structure)
│   │   ├── home.html                  # Accueil
│   │   │
│   │   ├── competition_detail.html    # Détail d'une compétition
│   │   ├── class_results.html         # Résultats d'une classe
│   │   ├── course_results.html        # Résultats d'un parcours
│   │   ├── relay_results.html         # Résultats relais
│   │   ├── competitor_detail.html     # Fiche concurrent
│   │   ├── org_results.html           # Résultats par organisation/club
│   │   ├── start_list.html            # Listes de départ
│   │   │
│   │   ├── analysis_base.html         # Template parent pour les analyses
│   │   ├── analysis_tabs.html         # Onglets analyses (Superman/Performance/etc)
│   │   ├── superman.html              # Analyse Superman
│   │   ├── performance.html           # Analyse Performance (KDE)
│   │   ├── grouping.html              # Analyse Regroupement
│   │   ├── grouping_index.html        # Indice Lièvre/Suiveur
│   │   ├── duel.html                  # Comparaison deux coureurs
│   │   ├── course_analysis_tabs.html  # Onglets analyses par course
│   │   │
│   │   ├── regularity.html            # Analyse de régularité
│   │   ├── meos_checker.html          # Validation MeOS
│   │   ├── verifie_moi.html           # Vérification données
│   │   ├── etiquettes.html            # Gestion des étiquettes
│   │   ├── drivers.html               # Pilotes (si applicable)
│   │   │
│   │   ├── markdown_content.html      # Rendu contenu Markdown
│   │   ├── tuto.html                  # Tutoriels
│   │   │
│   │   ├── _breadcrumb_home_comp.html # Composant fil d'Ariane
│   │   ├── _result_filters_bar.html   # Composant barre de filtrage
│   │   ├── _split_detail_row.html     # Composant ligne détail split
│   │   ├── _error_chart_card.html     # Composant graphique erreurs
│   │   ├── _checker_rule_card.html    # Composant règle de validation
│   │   ├── _checker_rule_header.html  # En-tête règle de validation
│   │   └── _course_classes_badges_include.html # Badges classes parcours
│   │
│   ├── migrations/                    # Migrations Django (autant que nécessaire)
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_models.py             # format_time, STATUS_LABELS, modèles, `__str__`
│       ├── test_services.py           # Logique métier (splits, classements, etc)
│       ├── test_views.py              # Vues Django
│       ├── test_classviews.py         # Vues par classe (TutoView)
│       ├── test_context_processors.py # Processeurs de contexte
│       ├── test_mop_views.py          # Endpoint MOP
│       ├── test_mop_receiver.py       # Parser XML MOP
│       ├── test_meos_checker.py       # Validation MeOS
│       ├── test_verifie_moi.py        # Vérification données
│       ├── test_meos_tags.py          # Tags/filtres templates
│       ├── test_performance.py        # Analyse Performance
│       ├── test_grouping.py           # Analyse Regroupement
│       ├── test_grouping_index.py     # Indice Lièvre/Suiveur
│       ├── test_courses.py            # Logique parcours
│       ├── test_regularity.py         # Analyse Régularité
│       └── test_site_js.test.js       # Tests JavaScript (Jest)
│
├── ochecklist/                        # Application Django (rapports de départ O'checklist)
│
│   ├── models.py                      # Modèles Django (ORM standard)
│   │                                  # OchecklistReport, OchecklistRunner, OchecklistChangeLog
│   │                                  # Gérés par Django (managed=True)
│   │
│   ├── views.py                       # Vues Django
│   │                                  # - ochecklist_update : endpoint POST réception YAML
│   │                                  # - report_list : liste des rapports
│   │                                  # - report_detail : détail d'un rapport
│   │                                  # - runner_detail : détail d'un coureur
│   │                                  # - clear_reports : suppression en masse
│   │                                  # Supporte Content-Digest (SHA-256/512, MD5)
│   │                                  # et Content-Encoding: gzip
│   │
│   ├── urls.py                        # Routage de l'app ochecklist
│   ├── admin.py                       # Admin Django (OchecklistReport/Runner/ChangeLog)
│   ├── apps.py
│   │
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py            # Schéma initial des tables
│   │
│   ├── templates/ochecklist/
│   │   ├── base.html                  # Template de base O'checklist
│   │   ├── report_list.html           # Liste des rapports
│   │   ├── report_detail.html         # Détail d'un rapport
│   │   └── runner_detail.html         # Détail d'un coureur
│   │
│   └── tests.py                       # Tests Django (TestCase)
│
├── pytest.ini                         # Configuration pytest
├── manage.py                          # Django CLI
├── requirements.txt                   # Dépendances Python
├── test_ochecklist.py                 # Script de test manuel pour l'endpoint O'checklist
│
├── LICENSE                            # GPL-3.0
├── AUTHORS.md
├── CHANGELOG.md
├── CLA.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── AGENTS.md                          # Guide pour les agents (documentation technique)
└── README.md                          # Ce fichier
```

---

## Applications Django

Le projet contient **deux applications Django** :

### 1. `results/` — Résultats MeOS
Application principale : reçoit les données MeOS via MOP, calcule les classements, splits, et propose toutes les analyses (Superman, Performance, Regroupement, etc.). Les tables `mop*` sont **gérées par MeOS** (Django utilise `managed=False`).

### 2. `ochecklist/` — Rapports de départ O'checklist
Application secondaire : reçoit les rapports YAML de l'application Android **O'checklist** (gestion des départs, statuts coureurs, changements de carte, etc.). Cette app utilise des tables **gérées par Django** (`managed=True`).

**Endpoint** : `POST /ochecklist/update/` (YAML, supporte gzip + Content-Digest)
**URLs** :
- `GET  /ochecklist/` — liste des rapports
- `POST /ochecklist/update/` — réception d'un rapport YAML
- `POST /ochecklist/clear/` — suppression de rapports sélectionnés
- `GET  /ochecklist/<id>/` — détail d'un rapport
- `GET  /ochecklist/runner/<id>/` — détail d'un coureur

**Modèles** :
- `OchecklistReport` — métadonnées (version, créateur, event, created, received_at)
- `OchecklistRunner` — données coureurs (nom, club, classe, statut, carte, heure)
- `OchecklistChangeLog` — journal des changements (DNS, LateStart, NewCard, etc.)

**Sécurité** (variables dans `dev_settings.py` ou env) :
- `OCHECKLIST_HEADER_KEY` — nom du header d'authentification (ex: `X-Ochecklist-Token`)
- `OCHECKLIST_HEADER_VALUE` — valeur attendue du header
- Vérification du header `Content-Digest` (SHA-256/512, MD5)
- Support de `Content-Encoding: gzip`

---

## Déploiement

### Prérequis

- Python 3.11+
- MySQL 8+ ou MariaDB 10.6+
- MeOS configuré pour pousser vers `POST /mop/update/`

### 1. Cloner et installer les dépendances

```bash
git clone https://github.com/Jolatomme/MeOSDjango.git
cd MeOSDjango

python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configuration

Créer un fichier `settings_local.py` à la racine du projet (ou configurer les variables d'environnement) :

```python
# settings_local.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME':   'DB_NAME',
        'USER':   'DB_USER_NAME',
        'PASSWORD': 'secret',
        'HOST':   'HOSTNAME_or_IP',
        'PORT':   'PORT_NUMBER',
    }
}

SECRET_KEY = 'votre-clé-secrète'
DEBUG      = False
ALLOWED_HOSTS = ['results.monclub.fr']

# Mot de passe MeOS (doit correspondre à la config MeOS Online)
MOP_PASSWORD = 'mot-de-passe-mop'

# O'checklist (optionnel, pour sécuriser l'endpoint)
OCHECKLIST_HEADER_KEY = 'X-Ochecklist-Token'
OCHECKLIST_HEADER_VALUE = 'token-secret-partagé-avec-l-app-android'

# Personnalisation du site (optionnel)
SITE_NAME          = 'Nom du site'
SITE_SUBTITLE      = 'Sous titre du site'
CLUB_NAME          = 'Mon Club'
CLUB_COLOR_PRIMARY = '#1a6b3c'   # couleur principale (navbar, badges)
CLUB_COLOR_ACCENT  = '#f0a500'   # couleur d'accent (highlights)
```

### 3. Initialiser la base de données

Les tables `mop*` sont créées et gérées par MeOS (`managed=False`). Django ne touche pas à leur schéma. Les tables de l'app `ochecklist` sont gérées par Django :

```bash
python manage.py migrate
python manage.py collectstatic
```

### 4. Lancer en développement

```bash
python manage.py runserver
```

### 5. Lancer en production

Cette partie va dépendre des spécificités de votre hébergeur.

### 6. Configurer MeOS

Dans MeOS → *Online Results* :
- **URL** : `http://results.monclub.fr/mop/update/`
- **Password** : la valeur de `MOP_PASSWORD`
- **Intervalle** : 5–10 secondes recommandé

### 7. Configurer O'checklist (optionnel)

Dans l'application Android O'checklist :
- **URL** : `https://results.monclub.fr/ochecklist/update/`
- **Header** (si configuré) : `X-Ochecklist-Token: <valeur partagée>`
- **Content-Encoding** : `gzip` (recommandé)
- **Content-Digest** : `sha-256=<base64>` (recommandé)

---

## Tests

Tous les tests tournent **sans base de données** (DB entièrement mockée via `unittest.mock`).

### Lancer tous les tests Python

```bash
pytest
```

### Avec rapport de couverture

```bash
pytest results/tests --cov=results --cov-report=html
```

### Lancer un fichier de test spécifique

```bash
pytest results/tests/test_views.py -v
pytest results/tests/test_services.py -v
pytest results/tests/test_mop_receiver.py -v
```

### Tester l'endpoint O'checklist manuellement

Un script de test est fourni pour valider l'endpoint `POST /ochecklist/update/` :

```bash
# Démarrer le serveur dans un terminal
python manage.py runserver

# Dans un autre terminal
python test_ochecklist.py
# ou avec un fichier YAML réel
python test_ochecklist.py http://localhost:8000
```

Le script teste 4 cas : POST basique, avec Content-Digest SHA-256, avec gzip + digest, et digest invalide.

### Tests JavaScript (Jest)

```bash
npm install
npm test
```

### Résumé de la couverture des tests

| Fichier | Tests |
|---|---|
| `results/models.py` | `test_models.py` — format_time, STATUS_LABELS, modèles, `__str__` |
| `results/services.py` | `test_services.py` — logique métier (splits, classements) |
| `results/views.py` | `test_views.py` — toutes les vues principales |
| `results/classViews.py` | `test_classviews.py` — vues par classe |
| `results/context_processors.py` | `test_context_processors.py` — injection de contexte |
| `results/mop_receiver.py` | `test_mop_receiver.py` — parser XML MOP |
| `results/mop_views.py` | `test_mop_views.py` — endpoint MOP |
| `results/meos_checker.py` | `test_meos_checker.py` — validation MeOS |
| `results/verifie_moi.py` | `test_verifie_moi.py` — vérification données |
| `results/templatetags/meos_tags.py` | `test_meos_tags.py` — filtres/tags template |
| Services spécialisés | `test_performance.py`, `test_grouping.py`, `test_grouping_index.py`, `test_courses.py`, `test_regularity.py` |
| `site.js` | `test_site_js.test.js` |
| `ochecklist/` | `ochecklist/tests.py` + `test_ochecklist.py` (script manuel) |

---

## Variables de configuration

| Variable | Défaut | Description |
|---|---|---|
| `MOP_PASSWORD` | *(obligatoire)* | Mot de passe MeOS Online |
| `SITE_NAME` | `Résultats CO` | Nom affiché dans la navbar et l'onglet |
| `SITE_SUBTITLE` | `Course d'Orientation` | Sous-titre de la navbar |
| `CLUB_NAME` | `COCS` | Nom du club |
| `CLUB_COLOR_PRIMARY` | `#1a6b3c` | Couleur principale (CSS `--co-green`) |
| `CLUB_COLOR_ACCENT` | `#f0a500` | Couleur d'accent (CSS `--co-gold`) |
| `OCHECKLIST_HEADER_KEY` | *(vide)* | Nom du header d'authentification O'checklist (optionnel) |
| `OCHECKLIST_HEADER_VALUE` | *(vide)* | Valeur attendue du header (optionnel) |

---

## Architecture

- **Deux applications Django** : `results/` (résultats MeOS) et `ochecklist/` (rapports de départ)
- **`results/`** : tables `mop*` **non gérées par Django** (`managed=False`). MeOS crée et gère directement ces tables. Django gère uniquement ses propres tables (auth, content_types, etc.) et celles d'`ochecklist/`.
- **`ochecklist/`** : tables **gérées par Django** (`managed=True`). Migrations standards (`0001_initial.py`).
- **MOP endpoint** : `POST /mop/update/` (XML, app `results/`)
- **O'checklist endpoint** : `POST /ochecklist/update/` (YAML, app `ochecklist/`, supporte gzip + Content-Digest)
- **Logique métier** : `services.py` (results) contient la logique métier pure (sans dépendances HTTP)
- **Templating** : Templates Django + JavaScript vanilla (pas de framework front-end)

---

## Contribution

Pour contribuer au projet, veuillez consulter [CONTRIBUTING.md](CONTRIBUTING.md) et accepter le [CLA.md](CLA.md).

Consultez aussi [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) pour les règles de comportement.

---

## Auteurs

Voir [AUTHORS.md](AUTHORS.md) pour la liste des contributeurs.

---

## Licence

Ce projet est sous licence **GNU General Public License v3.0**. Voir [LICENSE](LICENSE) pour plus de détails.
