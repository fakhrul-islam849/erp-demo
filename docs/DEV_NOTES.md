# Dev Notes — decisions made along the way

Running log of setup decisions, why they were made, and whether they need anything extra for production. Newest at the bottom.

## Templates & static files location
- `templates/` and `static/` live at the project root (sibling to `manage.py`), not inside an app — chosen because no apps existed yet and these are shared site-wide (base layout, template assets), not owned by one app.
- `config/settings.py` changes:
  - `TEMPLATES[0]['DIRS'] = [BASE_DIR / 'templates']`
  - `STATICFILES_DIRS = [BASE_DIR / 'static']` (new setting, added below `STATIC_URL`)
- **Works unchanged in production** — these paths don't depend on `DEBUG`.
- **Still needed before going live** (not done yet): `STATIC_ROOT` setting + `python manage.py collectstatic` + something to actually serve the collected files (WhiteNoise middleware or Nginx). See earlier deployment discussion — `STATICFILES_DIRS` is dev source, `STATIC_ROOT` is the prod deploy artifact, they're not the same thing.

## Database: moved to PostgreSQL early (not SQLite)
- Switched off SQLite before building any real features, specifically because SQLite locks the whole file on writes — bad fit for an ERP with concurrent employees, plus it has no real authentication (no username/password concept at all).
- PostgreSQL is used locally; credentials live in `.env` (gitignored), read via `django-environ` in `config/settings.py`.

## djangorestframework — deferred, not removed for good
- Installed once, then uninstalled — decided it's not needed until (a) the desktop app integration, and (b) the attendance/screenshot feature (the screenshot-capturing client needs an API endpoint to POST to). Both are future work per the original requirements doc. Reinstall when either of those starts.
