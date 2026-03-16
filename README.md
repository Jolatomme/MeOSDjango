# MeOS Live Results

Interface web de résultats en temps réel pour les compétitions de **course d'orientation**, connectée à [MeOS](https://www.melin.nu/meos/) via son protocole MOP (MeOS Online Protocol).

---

## Fonctionnalités

| Page | Description |
|---|---|
| **Accueil** | Liste des compétitions disponibles |
| **Résultats individuels** | Classement avec temps intermédiaires (splits), meilleurs tronçons et estimation des erreurs |
| **Résultats relais** | Classement par équipe avec temps et rang par fraction |
| **Fiche concurrent** | Détail complet d'un coureur (splits, statut, club) |
| **Résultats par club** | Tous les coureurs d'une organisation |
| **Superman** | Reconstruction du coureur idéal tronçon par tronçon, graphique des pertes |
| **Indice de performance** | Distribution KDE de l'indice de performance par coureur |
| **Regroupement** | Graphique des temps de passage absolus — lignes proches = coureurs ensemble |
| **Indice lièvre/suiveur** | Détection automatique des effets d'aspiration entre coureurs |
| **Duel** | Comparaison tronçon par tronçon de deux coureurs au choix |
| **Statistiques** | Vue d'ensemble de la compétition (total partants, classés, top clubs) |
| **Tutoriels** | Articles Markdown intégrés avec table des matières |
| **Réception MOP** | Endpoint `POST /mop/update/` — MeOS pousse les données en temps réel |

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
results/
│
├── models.py               # Modèles Django (managed=False) mappés sur les tables MeOS
│                           # + constantes de statut + format_time()
│
├── services.py             # Logique métier pure (sans effet de bord HTTP)
│                           # splits, classements, superman, performance, regroupement…
│
├── views.py                # Vues Django — orchestration services → templates
├── classViews.py           # TutoView (ListView générique pour les tutoriels)
├── mop_views.py            # Endpoint MOP (réception XML de MeOS)
├── mop_receiver.py         # Parser XML MOP + upserts en base
├── context_processors.py   # Injection SITE_NAME, CLUB_NAME, couleurs dans chaque requête
├── urls.py                 # Table de routage complète
│
├── templates/results/
│   ├── base.html           # Layout principal (Bootstrap, dark mode, médailles)
│   ├── analysis_base.html  # Layout commun aux pages d'analyse
│   ├── analysis_tabs.html  # Onglets Superman / Performance / Regroupement / Duel
│   ├── home.html
│   ├── competition_detail.html
│   ├── class_results.html
│   ├── relay_results.html
│   ├── competitor_detail.html
│   ├── org_results.html
│   ├── statistics.html
│   ├── superman.html
│   ├── performance.html
│   ├── grouping.html
│   ├── grouping_index.html
│   ├── duel.html
│   ├── markdown_content.html
│   └── tuto.html
│
├── static/results/
│   ├── css/site.css        # Styles personnalisés (variables couleur club)
│   └── js/site.js          # COUtils — helpers JS partagés (médailles, couleurs, temps)
│
└── tests/
    ├── test_models.py          # format_time, STATUS_LABELS, propriétés Mopcompetitor
    ├── test_services.py        # Toutes les fonctions de services.py (mocks DB)
    ├── test_views.py           # Toutes les vues (RequestFactory, mocks)
    ├── test_classviews.py      # TutoView
    ├── test_context_processors.py
    ├── test_mop_receiver.py    # Parser MOP (XML)
    ├── test_performance.py     # Analyse indice de performance
    ├── test_grouping.py        # Analyse regroupement
    ├── test_grouping_index.py  # Indice lièvre/suiveur (_hare_integral, compute_grouping_index)
    └── test_site_js_test.js    # Tests JS (Jest)
```

---

## Déploiement

### Prérequis

- Python 3.11+
- MySQL 8+ ou MariaDB 10.6+
- MeOS configuré pour pousser vers `POST /mop/update/`

### 1. Cloner et installer les dépendances

```bash
git clone https://github.com/<organisation>/<repo>.git
cd <repo>

python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configuration

Créer un fichier `settings_local.py` (ou configurer les variables d'environnement) :

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

# Personnalisation du site (optionnel)
SITE_NAME          = 'Nom du site'
SITE_SUBTITLE      = 'Sous titre du site'
CLUB_NAME          = 'Mon Club'
CLUB_COLOR_PRIMARY = '#1a6b3c'   # couleur principale (navbar, badges)
CLUB_COLOR_ACCENT  = '#f0a500'   # couleur d'accent (highlights)
```

### 3. Initialiser la base de données

Les tables `mop*` sont créées et gérées par MeOS (`managed=False`). Django ne touche pas à leur schéma. Seules les tables Django standard doivent être migrées :

```bash
python manage.py migrate
python manage.py collectstatic
```

### 4. Lancer en développement

```bash
python manage.py runserver
```

### 5. Lancer en production (exemple Gunicorn + Nginx)

Cette partie va dépendre des psécificités de votre hébergeur.

### 6. Configurer MeOS

Dans MeOS → *Online Results* :
- **URL** : `http://results.monclub.fr/mop/update/`
- **Password** : la valeur de `MOP_PASSWORD`
- **Intervalle** : 5–10 secondes recommandé

---

## Tests

Tous les tests tournent **sans base de données** (DB entièrement mockée).

### Lancer tous les tests Python

```bash
pytest
```

### Avec rapport de couverture

```bash
pytest results/tests
```

### Lancer un fichier de test spécifique

```bash
pytest results/tests/test_services.py -v
pytest results/tests/test_views.py -v
pytest results/tests/test_mop_receiver.py -v
```

### Tests JavaScript (Jest)

```bash
npm install
npm test
```

### Résumé de la couverture

| Fichier | Tests |
|---|---|
| `models.py` | `test_models.py` — format_time, STATUS_LABELS, propriétés, \_\_str\_\_ |
| `services.py` | `test_services.py` + `test_performance.py` + `test_grouping.py` + `test_grouping_index.py` |
| `views.py` | `test_views.py` — toutes les vues, helpers, cas limites |
| `classViews.py` | `test_classviews.py` |
| `context_processors.py` | `test_context_processors.py` |
| `mop_receiver.py` | `test_mop_receiver.py` — MOPComplete, MOPDiff, XML invalide |
| `site.js` | `test_site_js_test.js` |

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

---

## Licence

MIT
