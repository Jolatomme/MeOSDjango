# AGENTS.md

## Commands

```bash
# Run dev server
python manage.py runserver

# Run all tests (no DB required)
pytest

# Run specific test file
pytest results/tests/test_views.py -v

# Apply Django migrations
python manage.py migrate
python manage.py collectstatic
```

## Architecture

- **Single Django app**: `results/` inside `meos_results` project
- **MeOS tables are NOT managed by Django** — models.py uses `managed=False`. MeOS creates and manages the `mop*` tables directly. Django only manages its own auth/content_types tables.
- **MOP endpoint**: `POST /mop/update/` receives XML from MeOS client

## Testing

- All tests run **without a database** — DB is fully mocked via `unittest.mock`
- JavaScript tests: `npm test` (requires Jest)

## Config

- Local dev config in `meos_results/dev_settings.py` (DB credentials included)
- Production uses `settings_local.py` or environment variables
- Required: `MOP_PASSWORD` must match MeOS Online config

## Project Structure

```
meos_results/
├── manage.py
├── results/
│   ├── models.py       # MopCompetitor, MopClass, etc. (managed=False)
│   ├── services.py     # Business logic (no HTTP)
│   ├── views.py       # Django views
│   ├── mop_views.py   # MOP endpoint
│   ├── mop_receiver.py # XML parser
│   └── tests/        # pytest suite
└── meos_results/
    ├── settings.py
    └── dev_settings.py
```