# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Spendly is a personal expense tracker built with Flask. It started as a course scaffold that is filled in step by step, so large parts are intentionally unimplemented. Comments and placeholder responses name the course step that will build each part (for example `"Logout — coming in Step 3"`).

## Commands

The virtual environment lives one directory above the repo, at `../venv` (Python 3.12). The system `python3` does not have Flask installed, so activate the venv or call its interpreter directly.

```bash
source ../venv/bin/activate
pip install -r requirements.txt
python app.py        # dev server on http://127.0.0.1:5001, debug mode with auto-reload
pytest               # pytest and pytest-flask are installed; no tests exist yet
pytest path/to/test_file.py::test_name   # single test
```

There is no build step and no linter configured.

## Architecture

**Backend.** `app.py` is the whole application: one module-level `Flask` app with every route in it. There are no blueprints, no app factory, no config and no `secret_key` yet.

- Working routes only render templates and accept GET: `/`, `/register`, `/login`, `/terms`, `/privacy`.
- The forms in `login.html` and `register.html` POST to `/login` and `/register`, which currently answer 405 because POST handling is not written. Both templates already display an `error` variable if one is passed.
- `/logout`, `/profile`, `/expenses/add`, `/expenses/<id>/edit` and `/expenses/<id>/delete` are placeholders that return a plain string.
- `database/db.py` is the data layer: plain `sqlite3` with parameterized queries, no ORM. `get_db()` returns a new connection with `row_factory = sqlite3.Row` and foreign keys enabled; the caller closes it. `init_db()` creates the `users` and `expenses` tables with `CREATE TABLE IF NOT EXISTS`. `seed_db()` inserts a demo user (`demo@spendly.com`, password `demo123`) with 8 sample expenses, and does nothing once `users` has a row.
- `app.py` calls `init_db()` and `seed_db()` at import time, so the database exists before any route runs. No route reads or writes it yet.
- The database file `expense_tracker.db` is created in the project root and is gitignored. Delete it to get fresh seed data on the next start.
- Expense categories are a fixed list: Food, Transport, Bills, Health, Entertainment, Shopping, Other. The schema does not enforce it.

**Templates.** Every page extends `templates/base.html`, which owns the navbar, the footer and the global assets. It exposes four blocks: `title`, `head`, `content`, `scripts`. The footer links (Terms, Privacy) are in `base.html`, not in the individual pages. Internal links use `url_for('<endpoint>')`.

**Styles.** `static/css/style.css` is the global stylesheet.

- Colours, fonts, radii and widths are CSS custom properties on `:root`. Use these tokens instead of new literal values.
- A global reset sets `margin: 0; padding: 0` on every element, so new content has no spacing until you add it. `<dialog>` also loses its default centring and needs `margin: auto`.
- Sections are separated by banner comments; follow that layout when adding a section.
- `.legal-*` classes are shared by `terms.html` and `privacy.html`. `.hero-badge` is reused by those two pages as their "Legal" badge.

**Page-specific assets.** A page that needs its own CSS or JS loads it through the `head` or `scripts` block. The landing page is the only one that does so today:

- `static/css/landing.css` loads after `style.css` and overrides the base `.hero*` rules. It defines its own `--hero-*` colour tokens scoped to `.hero`.
- `style.css` still carries the previous hero rules (`.hero-visual`, `.mock-*`), which no template uses any more.
- `static/js/landing.js` drives the "See how it works" video modal. The modal is a native `<dialog>`; the YouTube `<iframe>` sits inside a `<template>` and is cloned into the page on open and removed on close, which is what stops playback.
- `static/js/main.js` is loaded on every page and is an empty placeholder.

**JavaScript.** Vanilla JS only. The project does not use a JS framework or third-party libraries.

## Known placeholders

- The YouTube video ID in `templates/landing.html` is a placeholder.
- `privacy@spendly.example` in `templates/privacy.html` is a placeholder address.
- `privacy.html` names Google Fonts as the only third-party service; the landing page now also embeds YouTube.
