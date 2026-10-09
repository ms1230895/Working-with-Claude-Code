# Spec: Login and Logout

## Overview
Make the "Sign in" form work and add a way to sign out. Today
`templates/login.html` posts to `/login`, but the route only accepts GET, so
submitting the form answers 405, and `/logout` returns a placeholder string.
This step adds POST handling to `/login`: check the submitted email and
password against the `users` table that Step 2 fills, and remember the signed-in
user in Flask's signed session cookie. It also adds `/logout`, a navbar that
reflects whether someone is signed in, and a `login_required` guard for the
routes that later steps will build. It is the second half of authentication:
every step after this one (profile, adding and editing expenses) needs to know
which user is making the request.

## Depends on
- Step 1 — Database Setup: the `users` table and `get_db()` in
  `database/db.py`.
- Step 2 — Registration: real user accounts with werkzeug password hashes,
  and the `get_user_by_email()` helper.

## Routes
- `GET /login` — show the sign-in form; a signed-in user is redirected to
  `/` instead — public (already exists)
- `POST /login` — check the credentials, start the session, redirect to
  `/` — public (new)
- `POST /logout` — end the session, redirect to `/` — public; works whether
  or not anyone is signed in (replaces the `GET /logout` placeholder)
- `GET /register` — unchanged, except a signed-in user is redirected to `/`
  — public (already exists)
- `/profile`, `/expenses/add`, `/expenses/<id>/edit`,
  `/expenses/<id>/delete` — still placeholders, now behind `login_required`
  — logged-in

`GET` and `POST` on `/login` are handled by the existing `login` view
function, and logout keeps the endpoint name `logout`, so every existing
`url_for('login')` keeps working.

`/logout` accepts POST only. Signing out changes state, and a GET link can be
triggered by a browser prefetch or by an image tag on another site.
`GET /logout` answers 405.

## Database changes
No database changes. The `users` table already has `id`, `name`, `email` and
`password_hash`.

Two new helper functions are added to `database/db.py` (no schema change):
- `get_user_by_id(user_id)` — returns the matching `sqlite3.Row`, or `None`.
- `authenticate_user(email, password)` — looks the user up with
  `get_user_by_email()` and checks the password with werkzeug's
  `check_password_hash`. Returns the user's row when both match, otherwise
  `None`. Expects an email that is already lower-cased, like the other
  helpers.

## Templates
- **Create:** none
- **Modify:** `templates/login.html`
  - Change the form `action` from the hardcoded `/login` to
    `{{ url_for('login') }}`.
  - Keep the email the user typed after a failed submit: fill the `email`
    input from the value passed back by the route. Never refill the
    password.
  - Do not add `minlength` to the password input. The demo account's
    password (`demo123`) has 7 characters and must still sign in.
- **Modify:** `templates/base.html`
  - Navbar, signed out: unchanged ("Sign in" and "Get started").
  - Navbar, signed in: the user's name as a link to `url_for('profile')`,
    and a "Sign out" button inside a small
    `<form method="POST" action="{{ url_for('logout') }}">`.
  - Show flashed messages (`get_flashed_messages()`) at the top of
    `<main>`, above the `content` block, so every page can display them.

## Files to change
- `app.py`
  - Import `flash`, `g` and `session` from `flask`, plus `os`, `secrets` and
    `functools.wraps`.
  - Set `app.secret_key` and the session cookie settings.
  - Add a `before_request` function that loads the signed-in user into
    `g.user`.
  - Add the `login_required` decorator and apply it to the four placeholder
    routes.
  - Add POST handling to `login`; replace the `logout` placeholder.
  - Redirect signed-in users away from `GET /login` and `GET /register`.
  - Flash a message after a successful registration and after sign-out.
- `database/db.py` — add `get_user_by_id()` and `authenticate_user()`;
  import `check_password_hash`.
- `templates/login.html` — the changes listed under Templates.
- `templates/base.html` — the changes listed under Templates.
- `static/css/style.css` — a "Sign out" button style in the Navbar section,
  and a new Flash messages section.
- `CLAUDE.md` — update the Architecture notes: sessions and `secret_key`
  now exist, `/login` handles POST, `/logout` is POST-only, `g.user`,
  `login_required`, and flashed messages in `base.html`.

## Files to create
None.

## New dependencies
No new dependencies. `session`, `flash` and `g` come with Flask, and
`check_password_hash` comes with werkzeug. Both are already in
`requirements.txt`. Do not add Flask-Login, Flask-WTF or python-dotenv.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **Secret key.** Read it from the `SECRET_KEY` environment variable. If the
  variable is not set, fall back to `secrets.token_hex(32)` generated at
  start-up. Never write a real key into the code or commit one. With the
  fallback, every restart of the dev server (including the debug
  auto-reload) signs everyone out; that is expected in development.
- **Session cookie.** Set `SESSION_COOKIE_SAMESITE = "Lax"` and leave
  `SESSION_COOKIE_HTTPONLY` at its default (`True`).
- **What the session holds.** Only `session["user_id"]`. Do not store the
  name, the email or anything about the password in the session.
- **Loading the user.** A `before_request` function reads
  `session.get("user_id")`, fetches the row with `get_user_by_id()` and puts
  it in `g.user` (`None` when nobody is signed in). If the id is in the
  session but no such user exists any more (for example the database file
  was deleted), clear the session and treat the visitor as signed out. Skip
  the lookup when `request.endpoint == "static"`, so CSS and JS requests do
  not open a database connection.
- **Templates read `g.user`.** Flask makes `g` available in every template,
  so no context processor is needed.
- **Sign-in validation**, checked in this order, first failure wins:
  1. Email and password are both present. The email is stripped of
     surrounding spaces first; the password is not stripped. Message:
     `Please enter your email and password.`
  2. `authenticate_user(email_lower, password)` returns a user. Message:
     `Invalid email or password.`
- The message for a wrong email and for a wrong password is exactly the
  same, so the form does not tell a stranger which emails have accounts.
- Lower-case the email before the lookup, as registration does, so
  `Demo@Spendly.com` signs in to `demo@spendly.com`.
- Do not apply the 8-character password rule when signing in. It is a rule
  for creating passwords, and the seeded demo password is shorter.
- On a failed sign-in, re-render `login.html` with `error` and the submitted
  `email`. Do not redirect.
- On a successful sign-in: call `session.clear()`, then set
  `session["user_id"]`, then redirect to `url_for('landing')`
  (Post/Redirect/Get). Clearing first means a session that existed before
  sign-in is never reused. The redirect target moves to the profile page in
  Step 4, when that page exists.
- **Sign-out:** `session.clear()`, flash `You have been signed out.`, then
  redirect to `url_for('landing')`. It must not fail when nobody is signed
  in.
- **`login_required`:** a decorator built with `functools.wraps`. When
  `g.user` is `None` it redirects to `url_for('login')`; otherwise it calls
  the view. It goes under `@app.route(...)`, so the route registers the
  wrapped function. No `next` parameter in this step: redirecting to a URL
  taken from the query string needs validation that is out of scope here.
- **Flash messages.** Two only: `Account created. Please sign in.` after a
  successful registration, and `You have been signed out.` after sign-out.
  Validation errors keep using the `error` variable and `.auth-error`; they
  are not flashed.
- Never store, log or send back the plain password.
- Database access stays in `database/db.py`; `app.py` calls the helpers and
  does not write SQL or call `check_password_hash` itself. Every connection
  is closed in a `finally` block, as the existing functions do.
- **CSS.** The "Sign out" control is a `<button>`, styled to look like the
  other navbar links (`--ink-muted`, `--ink` on hover, no border, no
  background, inherits the font). The flash message uses
  `--accent-light`, `--accent`, `--border` and `--radius-sm`. Add the new
  flash rules as their own section with a banner comment, and remember the
  global reset removes all margin and padding.
- On screens up to 600px wide the navbar hides every link except
  `.nav-cta`. When signed in, the "Sign out" button must stay visible at
  that width; the name link may be hidden.
- CSRF tokens are out of scope for this step. `SameSite=Lax` on the session
  cookie stops other sites from sending the POST with the user's session.
- Vanilla HTML forms only; no JavaScript is needed for this step.

## Definition of done
- [ ] `python app.py` starts without errors, with and without `SECRET_KEY`
      set in the environment.
- [ ] `GET /login` still shows the form.
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/`, with
      no 405.
- [ ] After signing in, the navbar shows "Demo User" and "Sign out"
      instead of "Sign in" and "Get started", on every page.
- [ ] Signing in as `DEMO@Spendly.com` / `demo123` also works.
- [ ] A wrong password shows `Invalid email or password.` and the navbar
      still shows "Sign in".
- [ ] An email with no account shows exactly the same message.
- [ ] After a failed sign-in, the email field still holds what was typed
      and the password field is empty.
- [ ] Submitting with an empty email or password (remove `required` in dev
      tools, or use `curl`) shows `Please enter your email and password.`
- [ ] A user created through `/register` can sign in with the password
      they chose.
- [ ] After registering, the sign-in page shows
      `Account created. Please sign in.` once; it is gone after a refresh.
- [ ] Clicking "Sign out" returns to `/`, shows
      `You have been signed out.` once, and the navbar shows "Sign in"
      again.
- [ ] `GET /logout` typed into the address bar answers 405 and does not
      sign the user out.
- [ ] Signed out, visiting `/profile`, `/expenses/add`, `/expenses/1/edit`
      and `/expenses/1/delete` each redirects to `/login`.
- [ ] Signed in, those four URLs show their placeholder text.
- [ ] Signed in, visiting `/login` or `/register` redirects to `/`.
- [ ] With `SECRET_KEY` set, sign in as a newly registered user (not the
      demo user, whose id is recreated by the seed), delete
      `expense_tracker.db` and restart the server: the visitor is signed
      out, with no error page.
- [ ] The browser's cookie list shows a `session` cookie marked HttpOnly
      with SameSite `Lax`.
- [ ] At a window width under 600px, "Sign out" is still visible when
      signed in.
- [ ] `/`, `/terms` and `/privacy` still load as before, signed in and
      signed out.
