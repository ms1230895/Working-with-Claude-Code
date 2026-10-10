# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Spendly is a personal expense tracker built with Flask. It started as a course scaffold that is filled in step by step, so large parts are intentionally unimplemented. Comments and placeholder responses name the course step that will build each part (for example `"Add expense — coming in Step 7"`).

## Commands

The virtual environment lives one directory above the repo, at `../venv` (Python 3.12). The system `python3` does not have Flask installed, so activate the venv or call its interpreter directly.

```bash
source ../venv/bin/activate
pip install -r requirements.txt
python app.py        # dev server on http://127.0.0.1:5001, debug mode with auto-reload
pytest               # runs every file in tests/ (pytest and pytest-flask are installed)
pytest path/to/test_file.py::test_name   # single test
```

Tests live in `tests/`, one file per step, named after its spec (`test_07-add-expense.py`). Each file points `database.db.DB_PATH` at a temporary file before it imports `app`, and again for every test, so the tests never open `expense_tracker.db`.

There is no build step and no linter configured.

## Architecture

**Backend.** `app.py` is the whole application: one module-level `Flask` app with every route in it. There are no blueprints and no app factory. The only configuration is for the session: `secret_key` comes from the `SECRET_KEY` environment variable, with a random key as the fallback, and the session cookie is `SameSite=Lax`. With the fallback, every restart of the dev server signs everyone out.

- `/`, `/terms` and `/privacy` only render templates and accept GET.
- `/register` accepts GET and POST. POST validates on the server, in this order: all three fields present, email has text on both sides of an `@`, password at least 8 characters, email not already registered. On success it saves the user with `create_user()`, flashes `Account created. Please sign in.` and redirects to `/login`. On a failure it re-renders `register.html` with `error`, `name` and `email`. Registering does not sign the user in.
- Emails are lower-cased in the route before the lookup and before saving, because SQLite's `UNIQUE` on `users.email` is case-sensitive.
- `/login` accepts GET and POST. POST checks, in this order: email and password present, then `authenticate_user()` finds a matching account. A wrong email and a wrong password get the same message. On success it clears the session, stores `session["user_id"]` and redirects to `/profile`. On a failure it re-renders `login.html` with `error` and `email`. The 8-character password rule is not applied when signing in; the demo password is shorter.
- `/logout` accepts POST only; GET answers 405. It clears the session, flashes `You have been signed out.` and redirects to `/`. The clear comes first, because flashed messages are stored in the session.
- `load_user()` runs before every request and puts the signed-in user's row in `g.user`, or `None`. The session holds only `user_id`. A session whose user no longer exists is cleared. Requests for static files skip the lookup.
- `login_required` redirects to `/login` when `g.user` is `None`. It goes under the `@app.route(...)` line.
- A signed-in user who opens `GET /login` or `GET /register` is redirected to `/`.
- `/profile` accepts GET and is behind `login_required`. It renders `profile.html`. The name, email and join date come from `g.user`. `stats`, `expenses` and `categories` come from three helpers in `database/db.py`, each called with `g.user["id"]`, so a user sees only their own expenses. A user with no expenses gets `₹0.00`, `0` and `—` in the summary cards, an empty state in place of the table, and no category breakdown.
- `/profile` takes an optional date range in the query string: `date_from` and `date_to`, both `YYYY-MM-DD`, both ends included. Either one may be left out, and an empty value counts as left out. The summary cards, the table and the category breakdown all use the same range. A value that is not a real date, or a start after the end, is not an HTTP error: the page answers 200, shows a message in the filter card and filters nothing. The range is not kept in the session.
- `app.py` has two helpers for the filter. `parse_filter_date(text)` returns a `date`, or `None` for anything that is not a `YYYY-MM-DD` date. `get_date_presets(today)` returns the four preset ranges the page links to (This month, Last 3 months, Last 6 months, All time). The view passes `parsed.isoformat()` to the database helpers, never the text from the URL. `parse_filter_date()` also checks the date on the add-expense form, so a change to it affects both pages.
- `/analytics` accepts GET and is behind `login_required`. It renders `analytics.html`, a "Coming soon" page, and passes it no data.
- `/expenses/add` accepts GET and POST and is behind `login_required`. GET renders `add_expense.html` with the date set to today. POST strips the four fields and passes them to `check_expense_form()`, which returns `(error, amount, expense_date)`. It checks, in this order: amount, category and date present; amount is digits with at most two decimals (`AMOUNT_PATTERN.fullmatch`, before any `float()`); amount above zero; amount at most `MAX_AMOUNT` (9,999,999.99); category in `CATEGORIES`, case-sensitive; date is a real `YYYY-MM-DD` date (`parse_filter_date()`); date not after today; description at most `MAX_DESCRIPTION_LENGTH` (200) characters. On a failure it re-renders the form with `error` and the typed values and answers 200; both the GET and the failure path render through `render_expense_form()`. On success it saves with `create_expense()`, flashes `Expense added.` and redirects to `/profile`. The owner is always `g.user["id"]`, the saved date is `parsed.isoformat()`, and an empty description is saved as `NULL`.
- `/expenses/<id>/edit` and `/expenses/<id>/delete` are placeholders that return a plain string. Both are behind `login_required`.
- `app.py` registers two Jinja filters. `format_money` turns a number into `₹3,610.49`. `format_date` takes the text SQLite stores (`YYYY-MM-DD`, with or without a time) and an optional `strftime` format; the default gives `24 Sep 2026`. Templates use these filters instead of formatting amounts and dates themselves.
- `database/db.py` is the data layer: plain `sqlite3` with parameterized queries, no ORM. `get_db()` returns a new connection with `row_factory = sqlite3.Row` and foreign keys enabled; the caller closes it. `init_db()` creates the `users` and `expenses` tables with `CREATE TABLE IF NOT EXISTS`. `seed_db()` inserts a demo user (`demo@spendly.com`, password `demo123`) with 8 sample expenses, and does nothing once `users` has a row.
- `database/db.py` also holds the user helpers. `get_user_by_email(email)` and `get_user_by_id(user_id)` return the user's row or `None`. `create_user(name, email, password)` hashes the password with werkzeug, inserts the user and returns the new id; a duplicate email raises `sqlite3.IntegrityError`. `authenticate_user(email, password)` returns the user's row when the email and password match, otherwise `None`. The helpers that take an email expect it already lower-cased. Routes call these helpers and contain no SQL and no password checks.
- `database/db.py` holds the expense helpers too. `create_expense(user_id, amount, category, date, description=None)` inserts one row and returns the new id; it does not check its arguments, the route does. The other three only read, and every one of their queries filters on `user_id`. `get_recent_expenses(user_id, limit=10)` returns the newest rows first, ordered by `date` and then `id`. `get_expense_stats(user_id)` returns a dict with `total_spent`, `transaction_count` and `top_category`, counted over all of the user's expenses; `top_category` is `None` when there are none. `get_category_totals(user_id)` returns one dict per category the user has spent in, with `name`, `total` and `percent`, largest total first. When two categories have the same total, the alphabetically first one comes first, in both helpers. The totals come from SQL (`COUNT`, `SUM`, `GROUP BY`); amounts are not rounded there, because `format_money` does that.
- The three reading helpers also take `date_from=None` and `date_to=None` (`YYYY-MM-DD` strings). With a range, the rows, the totals and each `percent` cover only the expenses in it; the table still lists at most `limit` rows, while the stats count every expense in the range. `_expense_filter()` builds the `WHERE` text and its parameters for all three, from fixed strings only. The comparison is on text, so it depends on every stored `date` being zero-padded `YYYY-MM-DD`.
- `app.py` calls `init_db()` and `seed_db()` at import time, so the database exists before any route runs. `/register` and `/expenses/add` are the routes that write to it so far; `/login`, `/profile` and `load_user()` read it.
- The database file `expense_tracker.db` is created in the project root and is gitignored. Delete it to get fresh seed data on the next start.
- Expense categories are a fixed list: Food, Transport, Bills, Health, Entertainment, Shopping, Other. It is written once, as the `CATEGORIES` tuple in `database/db.py`; the add-expense form and its check both read it. The sample rows in `seed_db()` keep their own strings. The schema does not enforce it.

**Templates.** Every page extends `templates/base.html`, which owns the navbar, the footer and the global assets. It exposes four blocks: `title`, `head`, `content`, `scripts`. The footer links (Terms, Privacy) are in `base.html`, not in the individual pages. Internal links use `url_for('<endpoint>')`. The navbar reads `g.user`: a signed-out visitor sees "Sign in" and "Get started", a signed-in user sees an "Analytics" link, their name, which links to `/profile`, and a "Sign out" button, which is a POST form. The Analytics link gets `.nav-active` and `aria-current="page"` when `request.endpoint` is `analytics`; no other navbar link has an active state. `base.html` also prints flashed messages at the top of `<main>`, above the `content` block.

**Styles.** `static/css/style.css` is the global stylesheet.

- Colours, fonts, radii and widths are CSS custom properties on `:root`. Use these tokens instead of new literal values. `--shadow-card` is the one shadow; a card that needs a shadow uses it.
- A global reset sets `margin: 0; padding: 0` on every element, so new content has no spacing until you add it. `<dialog>` also loses its default centring and needs `margin: auto`.
- Sections are separated by banner comments; follow that layout when adding a section.
- `.nav-logout` makes the "Sign out" button look like a navbar link. Below 600px the navbar hides every `<a>` except `.nav-cta`; the button stays visible because it is not an `<a>`.
- The "Flash messages" section styles `.flash-list` and `.flash`. There is one style, for confirmations; form errors use `.auth-error`.
- `.legal-*` classes are shared by `terms.html` and `privacy.html`. `.hero-badge` is reused by those two pages as their "Legal" badge.

**Page-specific assets.** A page that needs its own CSS or JS loads it through the `head` or `scripts` block. The landing page, the profile page and the add-expense page do so today:

- `static/css/expense.css` styles the add-expense form. Its classes start with `expense-`. The page layout and the inputs come from the `.auth-*` and `.form-*` rules in `style.css`; this file adds only the select's cursor, the "Cancel" link and the keyboard focus outline, with `:root` tokens only.
- `static/css/profile.css` styles the profile page. Its classes start with `profile-`. It uses only the `:root` tokens from `style.css`, with no literal colour values, and has its own media queries at 900px and 600px. On a narrow screen the expense table scrolls sideways inside `.profile-table-wrap`. It follows the `spendly-ui-designer` skill: spacing moves in 0.25rem (4px) steps, font sizes come from one scale (12, 14, 16, 20, 24, 32px), and amounts use tabular numbers. `.profile-card` is the shared card surface, `.profile-pill` the category pill, `.profile-btn` a `.btn-primary` with an icon beside its label, and `.profile-icon` (with `-md` and `-lg`) sets icon sizes of 16, 20 and 24px. The `profile-filter-*` classes style the date filter card; it reuses `.form-input` and `.auth-error` from `style.css`, and `.profile-filter-input` brings `.form-input` onto this page's spacing and type scale.
- `static/css/landing.css` loads after `style.css` and overrides the base `.hero*` rules. It defines its own `--hero-*` colour tokens scoped to `.hero`.
- `style.css` still carries the previous hero rules (`.hero-visual`, `.mock-*`), which no template uses any more.
- `static/js/landing.js` drives the "See how it works" video modal. The modal is a native `<dialog>`; the YouTube `<iframe>` sits inside a `<template>` and is cloned into the page on open and removed on close, which is what stops playback.
- `static/js/main.js` is loaded on every page. It calls `lucide.createIcons()` when the Lucide script has loaded, and does nothing otherwise.

**JavaScript.** Vanilla JS only. The project does not use a JS framework. The one third-party library is Lucide icons, version 1.54.0, loaded from `unpkg.com` by a `<script>` tag in `base.html`, with the version pinned and an `integrity` hash. Changing the version means recomputing the hash.

**Icons.** Write `<i data-lucide="name">` in a template; `main.js` swaps it for an `<svg>` and keeps its classes. An icon always sits next to visible text and never carries meaning alone, because every page must stay usable when the Lucide script cannot load.

## Known placeholders

- The YouTube video ID in `templates/landing.html` is a placeholder.
- `templates/analytics.html` is a stand-in built from existing classes (`.cta-*`, `.hero-badge`, `.btn-primary`). It does not follow the Figma "Coming Soon Page Wireframe" design yet.
- `privacy@spendly.example` in `templates/privacy.html` is a placeholder address.
- `privacy.html` names Google Fonts and unpkg as third-party services; the landing page also embeds YouTube, which it does not name.

## Skills

- `.claude/SKILLS/frontend-design/skill.md` is the `spendly-ui-designer` skill: design rules for Spendly pages (spacing grid, type scale, soft shadow, Lucide icons). It has `disable-model-invocation: true`, so it runs only when the user types `/spendly-ui-designer`. Where the skill and the existing `style.css` tokens differ, the existing tokens and fonts win.
