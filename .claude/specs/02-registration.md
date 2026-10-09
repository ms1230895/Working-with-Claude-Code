# Spec: Registration

## Overview
Make the "Create account" form work. Today `templates/register.html` posts to
`/register`, but the route only accepts GET, so submitting the form answers
405. This step adds POST handling: validate the submitted name, email and
password, hash the password, and save a new row in the `users` table that
Step 1 created. It is the first route that writes to the database and the
first half of authentication: Step 3 (login and logout) needs real user
accounts to sign in with, so registration comes before it.

## Depends on
- Step 1 — Database Setup: the `users` table, `get_db()` and `init_db()` in
  `database/db.py`.

## Routes
- `GET /register` — show the registration form — public (already exists)
- `POST /register` — validate the form, create the user, redirect to
  `/login` — public (new)

Both methods are handled by the existing `register` view function, so
`url_for('register')` keeps working.

## Database changes
No database changes. The `users` table already has every column this step
needs (`name`, `email`, `password_hash`, `created_at`) and `email` is already
`UNIQUE`.

Two new helper functions are added to `database/db.py` (no schema change):
- `get_user_by_email(email)` — returns the matching `sqlite3.Row`, or `None`.
- `create_user(name, email, password)` — hashes the password, inserts the
  user and returns the new user's `id`. Raises `sqlite3.IntegrityError` if
  the email is already taken.

## Templates
- **Create:** none
- **Modify:** `templates/register.html`
  - Keep what the user typed after a failed submit: fill the `name` and
    `email` inputs from the values passed back by the route. Never refill
    the password.
  - Add `minlength="8"` to the password input so the browser enforces the
    same rule the placeholder already states.
  - Change the form `action` from the hardcoded `/register` to
    `{{ url_for('register') }}`.

## Files to change
- `app.py` — accept `GET` and `POST` on `/register`; import `request`,
  `redirect`, `url_for`; add the validation and the call to `create_user`.
- `database/db.py` — add `get_user_by_email()` and `create_user()`.
- `templates/register.html` — the three changes listed under Templates.
- `CLAUDE.md` — update the Architecture notes: `/register` now handles POST
  and is the first route that writes to the database.

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security` is already installed and already
imported in `database/db.py`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Never store, log or send back the plain password. Only `password_hash` is
  saved.
- Validate on the server even though the inputs have `required`; browser
  checks can be bypassed. Rules, checked in this order, first failure wins:
  1. Name, email and password are all present. Name and email are stripped
     of surrounding spaces first; the password is not stripped.
  2. Email contains `@` with text on both sides.
  3. Password is at least 8 characters.
  4. Email is not already registered.
- Lower-case the email before the lookup and before saving, so
  `Demo@Spendly.com` and `demo@spendly.com` count as the same account.
- On a validation failure, re-render `register.html` with a short `error`
  message plus the submitted `name` and `email`. Do not redirect.
- The duplicate-email message is exactly:
  `An account with this email already exists.`
- Also catch `sqlite3.IntegrityError` around the insert and show the same
  duplicate-email message, in case two people register the same email at
  the same moment.
- On success, redirect to `url_for('login')` (Post/Redirect/Get), so a
  browser refresh cannot submit the form twice.
- Do not log the user in. No `session`, no `secret_key`, no flash messages
  in this step — those arrive with Step 3.
- Database access stays in `database/db.py`; `app.py` calls the helpers and
  does not write SQL itself. Every connection is closed in a `finally`
  block, as the existing functions do.
- No new CSS is expected: the form reuses the existing `.auth-*`,
  `.form-*` and `.btn-submit` classes, and errors use `.auth-error`.

## Definition of done
- [ ] `python app.py` starts without errors.
- [ ] `GET /register` still shows the form.
- [ ] Submitting a new name, email and 8+ character password redirects to
      `/login`, with no 405.
- [ ] The new user appears in the `users` table with the email in
      lower case.
- [ ] The saved `password_hash` is not the plain password (it starts with
      `scrypt:` or `pbkdf2:`).
- [ ] Registering `demo@spendly.com` again shows
      `An account with this email already exists.` and adds no row.
- [ ] Registering `DEMO@Spendly.com` shows the same error.
- [ ] A password shorter than 8 characters shows an error and adds no row
      (test with the `minlength` attribute removed in dev tools, or with
      `curl`).
- [ ] An email without `@` shows an error and adds no row.
- [ ] A name made only of spaces shows an error and adds no row.
- [ ] After any error, the name and email fields still hold what was typed
      and the password field is empty.
- [ ] Refreshing the page after a successful registration does not create
      a second user.
- [ ] `/login`, `/`, `/terms` and `/privacy` still load as before.
