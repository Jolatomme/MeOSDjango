# MeOSDjango — Prioritized Improvement Backlog

> Generated from the Django application audit on **2026-10-22**.
> This is a reference backlog, not an implementation record.
> Status of all items: **Open** unless noted otherwise.

## Priority legend

- **P0** — Block the next production deploy. Security, data-loss or correctness risk.
- **P1** — Minimum credible modern Django engineering baseline; next 1–2 sprints.
- **P2** — Scale, maintainability and polish; backlog.

**Effort:** **S** < 1 day · **M** 1–3 days · **L** 1–2 weeks.

## Audit baseline (verified)

- `pytest`: **1,778 tests passed** in ~22 s.
- `jest`: **88 tests passed**.
- `python manage.py check`: clean.
- `python manage.py makemigrations --check`: no changes.
- `python manage.py check --deploy` with `DEBUG=0`: only **W009** (weak local dev secret).
- Runtime: **Django 5.2.13 / Python 3.14.7**.
- Latest Django at audit time: **6.1.2**; latest 5.2 LTS patch: **5.2.18**.
- No `.github/workflows`; no dependency lockfile; no lint/type-check/pre-commit configuration.
- `package.json` and `package-lock.json` exist locally but are **untracked**.

## If you only do five things first

1. **P0-01** — Fix stored XSS via inline JSON.
2. **P0-02** — Lock down the O’checklist web UI and deletion.
3. **P0-03** — Harden O’checklist ingestion.
4. **P0-04** — Fix MOP transaction handling and silent “OK” responses.
5. **P1-01** — Add a CI quality gate.

---

# P0 — Block next deploy

## P0-01 — Replace unsafe inline JSON with `json_script` `security` `S`

**Where:** `results/templates/results/start_list.html:60`, `duel.html:207`, `verifie_moi.html:196`, `grouping_index.html:170`, `class_results.html:155`, `performance.html:71`, etc.

**Why:** `json.dumps(...)` does not escape `</script>`. A competitor, club or class name containing `</script><script>…` breaks out of the script block and gives stored XSS. Race creation is public, so this is reachable by an attacker.

**Done when:**
- No `json.dumps(...)|safe` remains in templates.
- Python objects are passed to `json_script` (or a custom filter escaping `<`, `>`, `&`, U+2028/2029).
- A regression test uses a `</script>` payload.
- Start list, duel, verifie-moi, grouping and performance pages still work.

---

## P0-02 — Protect the O’checklist web UI and destructive clear action `security` `S/M`

**Where:** `ochecklist/views.py:267-310`.

**Why:** `report_list`, `report_detail`, `runner_detail` and `clear_reports` have no authentication. `clear_reports` is POST + CSRF, but any visitor can load the page, get a token, and delete reports. The pages expose names, clubs, card numbers and comments.

**Done when:**
- All O’checklist HTML views require login/staff.
- `clear_reports` requires POST + permission.
- Anonymous access returns 302/403, covered by tests.
- The machine `POST /ochecklist/update/` endpoint remains available for the Android app.

---

## P0-03 — Harden O’checklist ingestion `security` `M`

**Where:** `ochecklist/views.py` — `ochecklist_update`, `verify_content_digest`, `decompress_if_needed`.

**Why:** Auth is optional; if only one of `OCHECKLIST_HEADER_KEY` / `OCHECKLIST_HEADER_VALUE` is configured, auth is silently disabled. There is no YAML schema validation: `Data` as a dict, missing `created`, or a missing runner name can produce a 500. Gzip decompression is unbounded.

**Done when:**
- Header auth is required by default; partial configuration fails closed; a dev-only explicit bypass exists.
- `Data` must be a list of dicts; required fields and types are validated; malformed payloads return 400, not 500.
- Gzip output is capped.
- Tests cover missing fields, wrong types, oversized input and invalid digest.

---

## P0-04 — Fix MOP transaction handling and silent “OK” responses `data-loss` `M`

**Where:** `results/mop_receiver.py:501-527`; freeze check at `:477-483`.

**Why:** One `transaction.atomic()` wraps all elements, and each element catches `Exception`. A `DatabaseError` marks the transaction for rollback; later writes fail, but the view still returns `'OK'`. MeOS may treat the import as successful and skip replaying the document; even if it retries, a false `OK` hides the failure. The freeze check catches every exception and proceeds, so it fails open.

**Done when:**
- The whole document runs in one transaction when the tables are transactional (InnoDB); DB errors are re-raised.
- Database errors are never swallowed.
- The response is non-OK if any element failed.
- Freeze-check failures return an explicit error/503.
- The XML body uses only the standard MOP statuses (`OK`, `BADCMP`, `NOZIP`, `BADPWD`, `ERROR`).
- Tests cover a missing column, bad date and frozen competition.

---

## P0-05 — Correct `Mop*` primary keys and ambiguous admin lookups `data-model` `M/L`

**Where:** `results/models.py`, `results/admin.py`.

**Why:** The models declare `cid` as `primary_key=True` while the real key is composite `(cid, id)` — or more fields for link tables. Verified locally:

```text
Mopcompetitor.objects.get(pk=cid) -> MultipleObjectsReturned
```

Default admin change links use `pk`, so Mopcompetitor/Mopclass/Moporganization/Mopteam change pages are broken or open the wrong row. Using `id` alone is not a fix: local data shows `id` repeats across competitions.

**Done when one of these is chosen and documented:**

- **If MOP admin editing is not required:** use `CompositePrimaryKey('cid', 'id')` (and all key fields for link tables), unregister the Mop models from admin, and add read-only custom views if needed. Django admin does **not** support composite primary keys in 5.2–6.1. Because tables are `managed=False`, apply the model-state migration with `--fake` or `SeparateDatabaseAndState`.
- **If MOP admin editing is required:** add a surrogate unique key column via `setup_db` after verifying MeOS tolerates it, or build custom admin views. Keep the composite uniqueness constraint.

**Acceptance:** no `MultipleObjectsReturned`; admin/custom view resolves the intended row; ORM filters use `(cid, id)`; tests cover multiple rows per `cid`.

---

## P0-06 — Fix env parsing, secrets and fail-fast production config `config` `M`

**Where:** `MeOSDjango/settings.py:58,63-67,230-240`; `dev_settings.example.py`; `.env` loader.

**Why:**
- `SECRET_KEY` and DB credentials come only from the untracked `dev_settings` module, not `.env`.
- `MOP_PASSWORD = MEOS_PASSWORD` ignores the documented `MOP_PASSWORD` env var.
- `DEBUG=True` and `ALLOWED_HOSTS=['*']` default to insecure values.
- `SITE_NAME`, `SITE_SUBTITLE`, `CLUB_NAME` and colors are read through `_env_flag`, which returns booleans.

Verified:

```text
SITE_NAME='Mon Club'         -> False
CLUB_COLOR_PRIMARY='#123456' -> False
MOP_PASSWORD='env-secret'    -> 'meos'
```

If `dev_settings.example.py` is copied unchanged, branding defaults to `True`, producing titles like “True” and invalid CSS colors.

**Done when:**
- `_env_str` is used for strings; sane string defaults exist.
- `SECRET_KEY`, DB credentials and `MOP_PASSWORD` are env-first, with a documented dev fallback.
- Production raises `ImproperlyConfigured` for `DEBUG=True`, `ALLOWED_HOSTS=['*']` or a weak secret.
- Tests cover env set/unset and a fresh template copy.
- `.env.example` documents every supported variable.

---

## P0-07 — Bound uploads and harden XML/gzip `security` `M`

**Where:** `results/classViews.py:468,505`; `results/forms.py`; O’checklist gzip handling.

**Why:** Public file-checker views read the entire upload into memory. `MeosFileForm` has no size limit. XML uses `xml.etree` without `defusedxml`. O’checklist decompresses gzip without an output limit. The MOP body default of 2.5 MB may also reject large races.

**Done when:**
- Upload size is validated server-side and documented.
- `defusedxml` is used for all XML.
- Gzip output is capped, with a test using a compression bomb.
- MOP body limits are deliberate and documented.
- Rate limiting is applied to public upload/check endpoints.

---

## P0-08 — Remove anonymous FTP helper and secret-bearing artifacts `security` `S`

**Where:** untracked `ftp_server.py`; `DEPLOY.md` backup/patch steps; `.gitignore`.

**Why:** `ftp_server.py` starts an anonymous FTP server with **full read/write/delete** on `0.0.0.0:2121` for the entire project directory, including `dev_settings.py` and potentially `.env`. `DEPLOY.md` also creates `dev_settings.backup` and `settings_local.patch` at the repo root, neither of which is ignored.

**Done when:**
- `ftp_server.py` is deleted or moved outside the repo.
- `dev_settings.backup`, `settings_local.patch`, `staticfiles/`, `media/` and scratch YAML are ignored.
- A secret scan is run; rotate any secret that may have been exposed.

---

# P1 — Next 1–2 sprints

## P1-01 — Add CI quality gate and Dependabot `ci` `M`

Add GitHub Actions on PR/push:

- Python 3.12/3.13 + Django 5.2 LTS.
- MySQL 8 service.
- `pytest`, `jest`, `ruff`, `mypy`.
- `compilemessages`, `check --deploy`, `makemigrations --check`.
- `pip-audit`.
- Dependabot for pip/npm/GitHub Actions.

**Done when:** a clean clone passes CI; checks are required on PRs.

---

## P1-02 — Pin/lock dependencies and commit JS configuration `deps` `S/M`

- Pin `Django~=5.2.18` (or add a tested 6.x matrix later).
- Add a lockfile/constraints; split `requirements-dev.txt`.
- Move `pytest*` out of production requirements.
- Commit `package.json` and `package-lock.json`; use `npm ci`.

**Done when:** a fresh clone installs the same versions today and in six months.

---

## P1-03 — Add `pyproject.toml`, ruff, mypy and pre-commit `tooling` `M`

- `ruff` for lint/format.
- `mypy` + `django-stubs`.
- pre-commit hooks.
- CI integration.

**Done when:** `pre-commit run --all-files` is clean and CI enforces it.

---

## P1-04 — Add test settings and real MySQL integration tests `testing` `M/L`

- Add `test_settings.py` with fixed secret, `ALLOWED_HOSTS`, fast password hashers, locmem email/cache.
- Run `migrate` + `setup_db` against MySQL in CI.
- Test raw SQL, `setup_db` idempotence, MOP XML ingestion, admin change pages and O’checklist.
- Add `--cov-branch` and a coverage threshold.
- Stop globally patching `competition_visible` / `get_negative_time_stats` in `conftest.py`.

**Done when:** the MySQL job proves the schema and raw SQL actually work.

---

## P1-05 — Add E2E and missing JS tests `testing` `M`

- Playwright for live polling/favorites, race creation/manage, language switch, O’checklist upload and admin login.
- Jest tests for `live.js` (~1,100 lines currently untested).
- Extract testable modules from large inline scripts (`start_list.html`, `duel.html`, etc.).

**Done when:** critical flows are covered without needing manual browser checks.

---

## P1-06 — Add logging, error tracking and metrics `observability` `M`

- `LOGGING` configuration; make `logger.info` operational events visible.
- `ADMINS`, `DEFAULT_FROM_EMAIL`, Sentry SDK + `SENTRY_DSN`.
- Request IDs.
- Metrics for MOP ingestion, live API latency and DB health.

**Done when:** a production 500 or MOP failure produces an actionable alert.

---

## P1-07 — Fix N+1 queries, caching and DB tuning `performance` `M/L`

- `HomeView`: filter/annotate with `Exists` instead of per-competition `competition_visible` + `has_individual_competitors`.
- `CompetitionDetailView`: aggregate class counts/controls rather than per-class queries.
- Cache `get_negative_time_stats` with invalidation on MOP update.
- Use Redis/memcached for live/race-index caches.
- Set `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`.
- Add `assertNumQueries` tests and benchmark key pages.

**Done when:** home/detail query counts are bounded and live pages stay fast under load.

---

## P1-08 — Configure static files and cache busting `static` `S/M`

- Use WhiteNoise + `CompressedManifestStaticFilesStorage`, or configure the host to serve hashed assets.
- Remove `whitenoise` if it is not used.
- Add cache headers for static and `org_logo` files.
- Add `collectstatic` to CI/deploy checks.

**Done when:** deploys cannot leave browsers on stale `site.css` / `live.js`.

---

## P1-09 — Fix admin and visibility bugs `admin` `S/M`

- `CompetitionConfigAdmin.search_fields=('_name',)` raises `FieldError`; use a real field or custom raw-SQL search.
- `get_queryset()` creates/deletes `CompetitionConfig` rows on GET; move sync to a management command or explicit admin action.
- `CompetitionListView` lists hidden/deleted competitions while detail pages 404 them; filter publicly or require staff.
- Replace MOP admin views if P0-05 removes them.

**Done when:** admin search works, GET has no side effects, and hidden races are not publicly listed.

---

## P1-10 — Align documentation and security policy `docs` `S/M`

- README: add `setup_db`, correct Django/Python badges, document tests and `.env`.
- AGENTS: migrations `0007`, tracked `package.json`, `docs/` path, real env behavior, test limitations.
- DEPLOY: `0007`, `nat`/`card`/`bib`/`prel`, `setup_db`, DB backups, backups outside the repo.
- SECURITY: real contact email, accurate Dependabot/pip-audit/CSP claims.
- Commit `Docs/` or remove references to it.

**Done when:** a new contributor can clone, configure, migrate, seed and run the app without guessing.

---

## P1-11 — Rate-limit public endpoints `security` `M`

- Race creation (currently honeypot + 2-second token only).
- MeOS file checkers.
- MOP update.
- O’checklist update.
- Optional CAPTCHA for public race creation.

**Done when:** limits return 429 and are covered by tests; trivial abuse is no longer possible.

---

# P2 — Scale and quality

## P2-01 — Fix O’checklist data integrity and N+1 queries `data` `M`

- Reports are keyed only by `event` name; annual events with the same name overwrite each other. Include date/version or create a new report per upload.
- Validate required fields (`created`, `Data`, runner name) and return 400.
- Add unique constraints/indexes for `(report, runner_id)` and search fields.
- Replace per-runner `filter(name=...).first()` with an in-memory map and bulk upserts.

---

## P2-02 — Bulk MOP upserts and control deletion `performance` `M`

- Replace per-row SELECT+INSERT/UPDATE with `INSERT … ON DUPLICATE KEY UPDATE` or equivalent bulk operations.
- Handle `<ctrl delete="true">`; `process_control` currently ignores it.
- Benchmark a `MOPComplete` with thousands of competitors.

---

## P2-03 — Split large modules, add types and narrow exceptions `maintainability` `L`

- Split `results/views.py` (~1,770 lines) and `results/services.py` (~1,470 lines) by domain.
- Add type hints incrementally; enable stricter mypy settings.
- Replace broad `except Exception` blocks with specific exceptions.
- Remove cross-module private-helper imports.
- Review `RenderShortcutMixin` bypassing standard `TemplateResponse`.

---

## P2-04 — Add releases, tags and versioned changelog `release` `S`

- SemVer tags and GitHub Releases.
- Versioned `CHANGELOG.md` instead of one `[Unreleased]` block.
- Make `SECURITY.md` supported versions match real tags.

---

## P2-05 — Improve dev onboarding and clean up dead code `devx` `M`

- Docker Compose with MySQL for reproducible local setup.
- `Makefile` / `justfile` for test, lint, migrate, setup_db, compilemessages, collectstatic.
- `.env.example`.
- Remove or use dead items: `django.contrib.humanize`, `python-dotenv`, `whitenoise` if unused, `MEDIA_*`, `SITE_LOGO_URL`, `SECURE_BROWSER_XSS_FILTER`.
- `django_extensions` only in dev.
- Fix minor bugs: `CompetitionConfigAdmin._date` ordering, `format_time` unit docs, `Mopclass.verbose_name`, O’checklist clear count.

---

## P2-06 — Accessibility, SEO and load testing `quality` `M`

- Playwright + axe checks.
- Skip link, keyboard handlers for clickable `div`/`span`, missing `aria-hidden` on icons.
- Meta description/Open Graph, `robots.txt`, sitemap.
- Lighthouse budget.
- k6/locust load test for live polling and MOP ingestion.

---

## P2-07 — Add CSP and remove inline handlers `security` `M/L`

- Use `django-csp` with nonces.
- Remove inline `onclick` handlers and inline scripts where possible.
- Test CSP headers and browser console for violations.

---

## Suggested sequence

1. **Security/data-loss:** P0-01 → P0-02 → P0-03 → P0-04 → P0-06 → P0-07 → P0-08.
2. **Model correctness:** P0-05, then P1-09 for replacement admin views if needed.
3. **Engineering baseline:** P1-01 → P1-02 → P1-03 → P1-10 → P1-04.
4. **Quality/scale:** P1-05 → P1-06 → P1-07 → P1-08 → P1-11.
5. **Backlog:** P2 items.

## What “state of the art” would mean here

A credible target baseline for this repo:

- Django 5.2 LTS pinned + lockfile.
- CI green on every PR with tests, lint, types, migrations and deploy checks.
- Env-only secrets; production fails fast on unsafe config.
- Real MySQL integration tests + E2E for critical flows.
- Structured logging, error tracking and health/metrics.
- Redis cache, sane DB connection settings and bounded query counts.
- Hashed static assets and reliable deploys.
- CSP, rate limiting and upload hardening.
- Accurate docs, releases/tags and dependency automation.

Not every modern tool is needed: **DRF, Celery, ASGI or Kubernetes would be overkill here**. The gap is the engineering baseline, not the absence of fashionable infrastructure.

---

# Implementation status

## Already done

- P0-01 — Replace unsafe inline JSON with `json_script` `security` `S`
- P0-04 — Fix MOP transaction handling and silent “OK” responses `data-loss` `M`
- P0-05 — Correct `Mop*` primary keys and ambiguous admin lookups `data-model` `M/L`
- P0-08 — Remove anonymous FTP helper and secret-bearing artifacts `security` `S`

## Would skip

All O'checklist revelevant actions as O'checklist is still under development.

- P0-02 — Protect the O’checklist web UI and destructive clear action `security` `S/M`
- P0-03 — Harden O’checklist ingestion `security` `M`
- P0-07 — Bound uploads and harden XML/gzip `security` `M`
