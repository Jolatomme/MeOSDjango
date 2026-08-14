# AGENTS.md

## Commands

```bash
# Run dev server
python manage.py runserver

# Run all tests (no DB required)
pytest

# Run specific test file
pytest results/tests/test_views.py -v

# Apply Django migrations (ochecklist tables + results tables managed by Django)
python manage.py migrate

# Serve static files (prod)
python manage.py collectstatic

# Create mop* tables / add missing columns (e.g. mopCompetitor.card)
python manage.py setup_db
#   --dry-run       show SQL without executing
#   --force         drop existing tables first (DANGEROUS, incompatible with --dry-run)
#   --fake-initial  mark tables as created in django_migrations (existing DBs)

# JavaScript unit tests (requires jest + jest-environment-jsdom)
npx jest test_site_js.test.js
```

## Architecture

- **Two Django apps** inside `MeOSDjango/` project:
  - **`results/`** — MeOS live results (main app)
  - **`ochecklist/`** — O'checklist Android app YAML report receiver
- **`results/`** — MeOS tables `mop*` are NOT managed by Django (models use `managed=False`). MeOS creates and manages them directly (tables can also be created with `setup_db`). Django manages only `MeosTutorial` and `CompetitionConfig` (`db_table = results_competitionconfig`), with migrations `0001`→`0006` (some migrations are historical leftovers of former `mop*` models).
- **`ochecklist/`** — Tables ARE managed by Django (`managed=True`), with a standard `0001_initial.py` migration.
- **MOP endpoint**: `POST /mop/update/` (XML, from MeOS) — app `results/`
- **O'checklist endpoint**: `POST /ochecklist/update/` (YAML, from O'checklist Android app) — app `ochecklist/`
  - Supports `Content-Encoding: gzip` decompression
  - Verifies `Content-Digest` header (SHA-256/512, MD5)
  - Optional auth via custom header (`OCHECKLIST_HEADER_KEY` / `OCHECKLIST_HEADER_VALUE`)

## Testing

- Python tests run **without a database** — DB is fully mocked via `unittest.mock` (see `results/tests/conftest.py`)
- `pytest.ini` adds `--cov=results --cov=ochecklist` (coverage)
- JavaScript unit tests for `site.js` (COUtils): `npx jest test_site_js.test.js` — run from `results/tests/`, requires `jest` + `jest-environment-jsdom` (see header of `results/tests/test_site_js.test.js`)

## Config

- `MeOSDjango/settings.py` imports `MeOSDjango/dev_settings.py` (try/except) — local dev config, DB credentials included
- Production: do NOT commit `dev_settings.py` with credentials; override settings via environment variables instead
- Configurable via env vars: `MOP_PASSWORD`, `SITE_NAME`, `SITE_SUBTITLE`, `SITE_LOGO_URL`, `CLUB_NAME`, `CLUB_COLOR_PRIMARY`, `CLUB_COLOR_ACCENT`, `OCHECKLIST_HEADER_KEY`, `OCHECKLIST_HEADER_VALUE`
- Required: `MOP_PASSWORD` must match MeOS Online config
- Optional: `OCHECKLIST_HEADER_KEY` / `OCHECKLIST_HEADER_VALUE` for O'checklist endpoint auth

## Project Structure

```
MeOSDjango/
├── manage.py                          # Django CLI
│
├── MeOSDjango/                        # Configuration Django
│   ├── __init__.py
│   ├── settings.py                    # Paramètres principaux
│   ├── dev_settings.py                # Config locale (DB, clés) — importée par settings.py
│   ├── urls.py                        # Routage principal (inclut results/ + ochecklist/)
│   ├── asgi.py
│   └── wsgi.py
│
├── results/                           # App Django — Résultats MeOS
│   ├── models.py                      # Mop* (managed=False) + CompetitionConfig,
│   │                                  # MeosTutorial (managed=True)
│   ├── services.py                    # Business logic (no HTTP)
│   ├── views.py                       # Django views
│   ├── mop_views.py                   # MOP XML endpoint
│   ├── mop_receiver.py                # XML parser
│   ├── meos_checker.py                # MeOS data validation
│   ├── verifie_moi.py                 # Data verification
│   ├── classViews.py                  # Class-based views (TutoView)
│   ├── context_processors.py          # Global context (SITE_NAME, etc.)
│   ├── forms.py                       # MeosFileForm + règles de vérification (R1–R8)
│   ├── admin.py
│   ├── apps.py
│   ├── urls.py
│   ├── management/commands/
│   │   └── setup_db.py                # Crée les tables mop* / colonnes manquantes
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── meos_tags.py               # Custom template filters/tags
│   ├── static/results/                # CSS, JS (site.js, results-splits.js…), images, fonts
│   ├── templates/results/             # Django templates
│   ├── migrations/                    # 0001–0006 (mop* historiques + modèles Django-managed)
│   └── tests/                         # Suite pytest (DB mockée) + test_site_js.test.js (jest)
│       ├── conftest.py
│       └── test_*.py
│
├── ochecklist/                        # App Django — Rapports de départ O'checklist
│   ├── models.py                      # OchecklistReport, OchecklistRunner,
│   │                                  # OchecklistChangeLog (managed=True)
│   ├── views.py                       # ochecklist_update (POST), report_list,
│   │                                  # report_detail, runner_detail, clear_reports
│   ├── urls.py                        # /ochecklist/update/, /ochecklist/, etc.
│   ├── admin.py                       # Admin Django (3 modèles)
│   ├── apps.py
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py            # Schéma initial des tables
│   ├── tests/                         # test_admin, test_helpers, test_models,
│   │                                  # test_urls, test_views
│   └── templates/ochecklist/
│       ├── base.html                  # Template de base
│       ├── report_list.html           # Liste des rapports
│       ├── report_detail.html         # Détail rapport (runners, statuts)
│       └── runner_detail.html         # Détail coureur
│
├── docs/                              # Exemples MOP (example0001.xml, protocole /mip/)
├── pytest.ini                         # Configuration pytest (dont --cov)
├── requirements.txt                   # Dépendances Python
├── .github/                           # Issue templates, SECURITY.md
│
├── LICENSE                            # GPL-3.0
├── AUTHORS.md
├── CHANGELOG.md
├── CLA.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── AGENTS.md                          # Ce fichier
└── README.md
```
