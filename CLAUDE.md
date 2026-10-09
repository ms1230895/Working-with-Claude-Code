# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Spendly is a personal expense tracker built with Flask. It started as a course scaffold that is filled in step by step, so large parts are intentionally unimplemented. Comments and placeholder responses name the course step that will build each part (for example `"Profile page — coming in Step 4"`).

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

**Backend.** `app.py` is the whole application: one module-level `Flask` app with every route in it. There are no blueprints and no app factory. The only configuration is for the session: `secret_key` comes from the `SECRET_KEY` environment variable, with a random key as the fallback, and the session cookie is `SameSite=Lax`. With the fallback, every restart of the dev server signs everyone out.

- `/`, `/terms` and `/privacy` only render templates and accept GET.
- `/register` accepts GET and POST. POST validates on the server, in this order: all three fields present, email has text on both sides of an `@`, password at least 8 characters, email not already registered. On success it saves the user with `create_user()`, flashes `Account created. Please sign in.` and redirects to `/login`. On a failure it re-renders `register.html` with `error`, `name` and `email`. Registering does not sign the user in.
- Emails are lower-cased in the route before the lookup and before saving, because SQLite's `UNIQUE` on `users.email` is case-sensitive.
- `/login` accepts GET and POST. POST checks, in this order: email and password present, then `authenticate_user()` finds a matching account. A wrong email and a wrong password get the same message. On success it clears the session, stores `session["user_id"]` and redirects to `/`. On a failure it re-renders `login.html` with `error` and `email`. The 8-character password rule is not applied when signing in; the demo password is shorter.
- `/logout` accepts POST only; GET answers 405. It clears the session, flashes `You have been signed out.` and redirects to `/`. The clear comes first, because flashed messages are stored in the session.
- `load_user()` runs before every request and puts the signed-in user's row in `g.user`, or `None`. The session holds only `user_id`. A session whose user no longer exists is cleared. Requests for static files skip the lookup.
- `login_required` redirects to `/login` when `g.user` is `None`. It goes under the `@app.route(...)` line.
- A signed-in user who opens `GET /login` or `GET /register` is redirected to `/`.
- `/profile`, `/expenses/add`, `/expenses/<id>/edit` and `/expenses/<id>/delete` are placeholders that return a plain string. All four are behind `login_required`.
- `database/db.py` is the data layer: plain `sqlite3` with parameterized queries, no ORM. `get_db()` returns a new connection with `row_factory = sqlite3.Row` and foreign keys enabled; the caller closes it. `init_db()` creates the `users` and `expenses` tables with `CREATE TABLE IF NOT EXISTS`. `seed_db()` inserts a demo user (`demo@spendly.com`, password `demo123`) with 8 sample expenses, and does nothing once `users` has a row.
- `database/db.py` also holds the user helpers. `get_user_by_email(email)` and `get_user_by_id(user_id)` return the user's row or `None`. `create_user(name, email, password)` hashes the password with werkzeug, inserts the user and returns the new id; a duplicate email raises `sqlite3.IntegrityError`. `authenticate_user(email, password)` returns the user's row when the email and password match, otherwise `None`. The helpers that take an email expect it already lower-cased. Routes call these helpers and contain no SQL and no password checks.
- `app.py` calls `init_db()` and `seed_db()` at import time, so the database exists before any route runs. `/register` is the only route that writes to it so far; `/login` and `load_user()` read it.
- The database file `expense_tracker.db` is created in the project root and is gitignored. Delete it to get fresh seed data on the next start.
- Expense categories are a fixed list: Food, Transport, Bills, Health, Entertainment, Shopping, Other. The schema does not enforce it.

**Templates.** Every page extends `templates/base.html`, which owns the navbar, the footer and the global assets. It exposes four blocks: `title`, `head`, `content`, `scripts`. The footer links (Terms, Privacy) are in `base.html`, not in the individual pages. Internal links use `url_for('<endpoint>')`. The navbar reads `g.user`: a signed-out visitor sees "Sign in" and "Get started", a signed-in user sees their name and a "Sign out" button, which is a POST form. `base.html` also prints flashed messages at the top of `<main>`, above the `content` block.

**Styles.** `static/css/style.css` is the global stylesheet.

- Colours, fonts, radii and widths are CSS custom properties on `:root`. Use these tokens instead of new literal values.
- A global reset sets `margin: 0; padding: 0` on every element, so new content has no spacing until you add it. `<dialog>` also loses its default centring and needs `margin: auto`.
- Sections are separated by banner comments; follow that layout when adding a section.
- `.nav-logout` makes the "Sign out" button look like a navbar link. Below 600px the navbar hides every `<a>` except `.nav-cta`; the button stays visible because it is not an `<a>`.
- The "Flash messages" section styles `.flash-list` and `.flash`. There is one style, for confirmations; form errors use `.auth-error`.
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
