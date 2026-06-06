# AGENTS.md

## Commands

```bash
# Run dev server
python manage.py runserver

# Run all tests (no DB required)
pytest

# Run specific test file
pytest results/tests/test_views.py -v

# Apply Django migrations (creates ochecklist tables)
python manage.py migrate
python manage.py collectstatic

# Manual test of the O'checklist endpoint
python test_ochecklist.py
```

## Architecture

- **Two Django apps** inside `MeOSDjango/` project:
  - **`results/`** — MeOS live results (main app)
  - **`ochecklist/`** — O'checklist Android app YAML report receiver
- **`results/`** — MeOS tables are NOT managed by Django (models use `managed=False`). MeOS creates and manages the `mop*` tables directly. Django only manages its own auth/content_types tables and the `ochecklist_*` tables.
- **`ochecklist/`** — Tables ARE managed by Django (`managed=True`), with a standard `0001_initial.py` migration.
- **MOP endpoint**: `POST /mop/update/` (XML, from MeOS) — app `results/`
- **O'checklist endpoint**: `POST /ochecklist/update/` (YAML, from O'checklist Android app) — app `ochecklist/`
  - Supports `Content-Encoding: gzip` decompression
  - Verifies `Content-Digest` header (SHA-256/512, MD5)
  - Optional auth via custom header (`OCHECKLIST_HEADER_KEY` / `OCHECKLIST_HEADER_VALUE`)

## Testing

- All tests run **without a database** — DB is fully mocked via `unittest.mock`
- JavaScript tests: `npm test` (requires Jest)
- Manual O'checklist endpoint testing: `python test_ochecklist.py`

## Config

- Local dev config in `MeOSDjango/dev_settings.py` (DB credentials included)
- Production uses `settings_local.py` or environment variables
- Required: `MOP_PASSWORD` must match MeOS Online config
- Optional: `OCHECKLIST_HEADER_KEY` / `OCHECKLIST_HEADER_VALUE` for O'checklist endpoint auth

## Project Structure

```
MeOSDjango/
├── manage.py                          # Django management script
│
├── MeOSDjango/                        # Configuration Django
│   ├── __init__.py
│   ├── settings.py                    # Paramètres principaux
│   ├── asgi.py
│   ├── wsgi.py
│   └── urls.py                        # Routage principal (inclut results/ + ochecklist/)
│
├── results/                           # App Django — Résultats MeOS
│   ├── models.py                      # MopCompetitor, MopClass, etc. (managed=False)
│   ├── services.py                    # Business logic (no HTTP)
│   ├── views.py                       # Django views
│   ├── mop_views.py                   # MOP XML endpoint
│   ├── mop_receiver.py                # XML parser
│   ├── meos_checker.py                # MeOS data validation
│   ├── verifie_moi.py                 # Data verification
│   ├── classViews.py                  # Class-based views (TutoView)
│   ├── context_processors.py          # Global context (SITE_NAME, etc.)
│   ├── admin.py
│   ├── apps.py
│   ├── urls.py
│   ├── templatetags/
│   │   ├── __init__.py
│   │   └── meos_tags.py               # Custom template filters/tags
│   ├── static/results/                # CSS, JS, images, fonts
│   ├── templates/results/             # Django templates
│   ├── migrations/                    # Empty (MeOS tables unmanaged)
│   └── tests/                         # pytest suite
│
├── ochecklist/                        # App Django — Rapports de départ O'checklist
│   ├── models.py                      # OchecklistReport, OchecklistRunner,
│   │                                  # OchecklistChangeLog (managed=True)
│   ├── views.py                       # ochecklist_update (POST), report_list,
│   │                                  # report_detail, runner_detail, clear_reports
│   ├── urls.py                        # /ochecklist/update/, /ochecklist/, etc.
│   ├── admin.py                       # Admin Django (3 modèles)
│   ├── apps.py
│   ├── tests.py                       # Django TestCase (à compléter)
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py            # Schéma initial des tables
│   └── templates/ochecklist/
│       ├── base.html                  # Template de base
│       ├── report_list.html           # Liste des rapports
│       ├── report_detail.html         # Détail rapport (runners, statuts)
│       └── runner_detail.html         # Détail coureur
│
├── test_ochecklist.py                 # Script de test manuel pour l'endpoint YAML
├── pytest.ini                         # Configuration pytest
├── manage.py                          # Django CLI
├── requirements.txt                   # Dépendances Python
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
