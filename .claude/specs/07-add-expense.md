# Spec: Add Expense

## Overview
Let a signed-in user record a new expense. Until now every row in the
`expenses` table came from `seed_db()` or from a hand-written `INSERT`, and
`/expenses/add` only answers with the text `Add expense — coming in Step 7`.
The profile page already links to that address twice (the button in the header
and the one in the empty state), so a newly registered user reaches a dead end.
This step replaces the placeholder with a form page (amount, category, date and
an optional description) and a POST handler that checks the input on the server
and saves one row for the signed-in user. It adds the first helper in
`database/db.py` that writes to `expenses`. After saving, the user is sent back
to `/profile`, where Steps 5 and 6 already show the new row, the new totals and
the new category share. It comes before edit and delete (Steps 8 and 9), which
need rows the user created themselves.

## Depends on
- Step 1 — Database Setup: the `expenses` table and `get_db()`.
- Step 3 — Login and Logout: `g.user` and `login_required`, which tell the
  route whose expense is being saved.
- Step 4 — Profile Page Design: the two "Add expense" links in
  `templates/profile.html`, and the flash message area in `base.html`.
- Step 5 — Backend Connections: the profile page reads the saved row back.
- Step 6 — Date Filter for Profile Page: `parse_filter_date()` in `app.py`,
  and its rule that every stored `date` is zero-padded `YYYY-MM-DD` text.

## Routes
- `GET /expenses/add` — show the empty form, with the date set to today —
  logged-in (already exists as a placeholder; the `add_expense` endpoint name
  stays)
- `POST /expenses/add` — check the input, save the expense for the signed-in
  user and redirect to `/profile` — logged-in

Form fields sent by the POST:
- `amount` — required. Digits, optionally a dot and one or two more digits.
- `category` — required. One of the seven fixed categories.
- `date` — required. `YYYY-MM-DD`, not later than today.
- `description` — optional. At most 200 characters.

Any other method on this address answers 405.

## Database changes
No database changes. The `expenses` table already has every column this step
writes (`user_id`, `amount`, `category`, `date`, `description`), and
`created_at` fills itself. No new tables, columns, constraints or indexes, and
`init_db()` and `seed_db()` are not touched.

Two additions to `database/db.py` (no schema change):
- `CATEGORIES` — a module-level tuple with the seven category names, in this
  order: `Food`, `Transport`, `Bills`, `Health`, `Entertainment`, `Shopping`,
  `Other`. It is the one place the list is written; the form and the check
  both read it.
- `create_expense(user_id, amount, category, date, description=None)` —
  inserts one row and returns the new id. It is the first expense helper
  that writes. It does not check its arguments; the route does that before
  calling it, as `register` does for `create_user()`.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html`. Title block: `Add expense — Spendly`.
  - Loads `static/css/expense.css` through the `head` block.
  - Uses the single-card form layout the sign-in page has:
    `.auth-section` > `.auth-container` > `.auth-header` and `.auth-card`.
  - Header: `<h1 class="auth-title">Add expense</h1>` and a one-line
    `.auth-subtitle`.
  - The error message, when there is one, in
    `<div class="auth-error" role="alert">` at the top of the card.
  - A `<form method="POST">` whose action is `url_for('add_expense')`, with
    four `.form-group` blocks, each with its own `<label for>`:
    - `Amount (₹)` — `<input type="number" name="amount" step="0.01"
      min="0.01" inputmode="decimal" required autofocus>`.
    - `Category` — a `<select name="category" required>`. The first option
      is `Choose a category` with an empty value; then one `<option>` per
      entry in `categories`. The option that matches the submitted value is
      marked `selected`.
    - `Date` — `<input type="date" name="date" required>` with `max` set to
      today. Filled with today on the first visit.
    - `Description (optional)` — `<input type="text" name="description"
      maxlength="200">`.
  - A `Save expense` submit button (`.btn-submit`) and a `Cancel` link to
    `url_for('profile')`.
  - After an error, every field shows what the user typed.
- **Modify:** none. `templates/profile.html` already links to
  `url_for('add_expense')` in both places, and `base.html` already prints
  flashed messages.

## Files to change
- `app.py`
  - Import `CATEGORIES` and `create_expense` from `database.db`, and `re`
    from the standard library.
  - Move `add_expense` out of the "Placeholder routes" section, to sit after
    `analytics`. It accepts GET and POST and stays behind `login_required`.
  - GET renders `add_expense.html` with `categories=CATEGORIES`,
    `today=date.today().isoformat()` and `date=today`.
  - POST reads the four fields, checks them in the order listed under
    "Errors", then either re-renders the form or saves, flashes
    `Expense added.` and redirects to `url_for('profile')`.
  - `edit_expense` and `delete_expense` are not touched.
- `database/db.py` — add `CATEGORIES` and `create_expense()`.
- `CLAUDE.md` — update the Architecture notes: what `/expenses/add` now does
  and its checks, `CATEGORIES` and `create_expense()`, that `/expenses/add`
  now writes to the database as well as `/register`, the new template and
  `expense.css`, and that only edit and delete are still placeholders.

## Files to create
- `templates/add_expense.html`
- `static/css/expense.css`

## New dependencies
No new dependencies. `re` and `datetime` are in the standard library. No form
library (no Flask-WTF), no date picker and no new JavaScript: the browser's
own `number`, `date` and `select` controls are the inputs.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **Whose expense.** `user_id` is always `g.user["id"]`. Never read a user id
  from the form or the query string, and do not put one in a hidden input.
- **Where the SQL lives.** The `INSERT` is in `create_expense()` in
  `database/db.py`; `app.py` writes no SQL. The helper opens its own
  connection, saves inside `with conn:` and closes the connection in a
  `finally` block, as `create_user()` does.
- **The browser's checks are not enough.** `required`, `min`, `max`,
  `maxlength` and the `<select>` help the user, but a POST can be sent
  without the form. Every rule below is checked again in the route.
- **Errors.** The first rule that fails decides the message, as in
  `register` and `login`. Each field is stripped before it is checked.
  1. `amount`, `category` or `date` is empty: `Please fill in the amount,
     category and date.`
  2. `amount` is not digits with an optional dot and one or two decimals:
     `Please enter a valid amount, like 250 or 250.50.`
  3. `amount` is zero: `Amount must be greater than zero.`
  4. `amount` is more than 9,999,999.99: `Amount cannot be more than
     ₹9,999,999.99.`
  5. `category` is not in `CATEGORIES`: `Please choose a category from the
     list.`
  6. `date` is not a real `YYYY-MM-DD` date: `Please enter a valid date.`
  7. `date` is after today: `The date cannot be in the future.`
  8. `description` is longer than 200 characters: `Description cannot be
     longer than 200 characters.`

  On an error the page answers 200, saves nothing and shows the form again
  with the message and the typed values. It never answers 400 or 500 for
  bad input.
- **Checking the amount.** Use
  `re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", text)`. `fullmatch`, not `match`
  with `$`, which lets a trailing newline through. `[0-9]`, not `\d`, which
  also matches digits from other scripts. This one pattern rejects a minus
  sign, a plus sign, `1e5`, `nan`, `inf`, `1,200`, `₹250`, `.5`, `5.` and
  three or more decimals, all with message 2. Do not call `float()` on text
  that has not passed the pattern: `float("nan")` and `float("inf")` do not
  raise. After the pattern passes, `float(text)` is the value to save.
- **Checking the date.** Reuse `parse_filter_date()` as it is; do not rename
  it and do not write a second parser. Compare the parsed `date` with
  `date.today()`. Save `parsed.isoformat()`, never the text from the form,
  so the stored value is always zero-padded `YYYY-MM-DD` and Step 6's text
  comparison keeps working.
- **Checking the category.** An exact, case-sensitive match against
  `CATEGORIES`. `food` is not `Food`.
- **Description.** Optional. An empty description, or one that is only
  spaces, is saved as `NULL` (pass `None`), not as an empty string; the
  profile table already prints `—` for it.
- **After saving.** `flash("Expense added.")`, then
  `redirect(url_for("profile"))`, so refreshing the next page cannot submit
  the form again. The redirect carries no date range.
- **A signed-out POST.** `login_required` redirects it to `/login`, and
  nothing is saved.
- **No CSRF token.** The project's forms (`register`, `login`, `logout`) rely
  on the `SameSite=Lax` session cookie. This form does the same. Adding
  tokens is a change to every form and is not part of this step.
- **Escaping.** The typed values are printed back into the form. Leave
  Jinja's autoescaping on, never use `|safe`, and keep every `value="..."`
  attribute quoted.
- **Template logic.** The template loops over `categories` and marks the
  selected option. It does not hold its own copy of the category list and
  does not work out today's date.
- **CSS.** New rules go in `static/css/expense.css`, with a banner comment
  at the top. New classes start with `expense-`.
  - Only the `:root` tokens: no literal colour values, spacing in `0.25rem`
    steps, font sizes from the 12, 14, 16, 20, 24, 32px scale.
  - Reuse `.auth-section`, `.auth-container`, `.auth-header`, `.auth-title`,
    `.auth-subtitle`, `.auth-card`, `.auth-error`, `.form-group`,
    `.form-input` and `.btn-submit` as they are. Do not copy their values
    into `expense.css`.
  - Put `.form-input` on the `<select>` too. If it lacks something a
    `<select>` needs, add it under an `expense-` class.
  - The inputs, the select, the button and the "Cancel" link have a visible
    focus style.
  - `style.css` and `profile.css` are not changed in this step.
- **Icons.** None are required. If one is added, it sits beside a text
  label, so the page works when the Lucide script cannot load.
- **Markup.** One `<h1>`. Every control has its own `<label for>`.
- **Not in this step:** edit and delete (Steps 8 and 9); an "Add another"
  button; adding several expenses at once; custom categories; a category
  `CHECK` constraint in the schema; receipts or attachments; currencies
  other than ₹; recurring expenses; protection against a double click that
  sends the form twice; CSRF tokens; changing the seed data; a link to the
  form in the navbar. Automated tests are written afterwards with
  `/test-feature`, not as part of this step.

## Definition of done
Set-up for the checks below: register a new user and sign in. Its profile
shows the empty state.

- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /expenses/add` redirects to `/login`.
- [ ] Signed in, the "Add expense" button on `/profile` opens
      `/expenses/add`, which shows a form with Amount, Category, Date and
      Description, a "Save expense" button and a "Cancel" link. The
      placeholder text `coming in Step 7` is gone.
- [ ] The date input shows today, and the category select shows
      `Choose a category` followed by the seven categories in the order
      Food, Transport, Bills, Health, Entertainment, Shopping, Other.
- [ ] Saving amount `250.50`, category `Food`, today's date and description
      `Lunch` redirects to `/profile`, which shows the message
      `Expense added.`, the cards `₹250.50`, `1` and `Food`, and one table
      row with today's date, `Lunch`, `Food` and `₹250.50`.
- [ ] Refreshing `/profile` after that does not add a second row, and the
      message is gone.
- [ ] Saving a second expense of `1200`, `Bills`, with the description left
      empty makes the cards read `₹1,450.50`, `2` and `Bills`; the new row
      shows `—` as its description.
- [ ] `SELECT description FROM expenses ORDER BY id DESC LIMIT 1;` gives
      `NULL` for that row, not an empty string.
- [ ] `SELECT user_id, date FROM expenses ORDER BY id DESC LIMIT 2;` shows
      the new user's id on both rows and dates in `YYYY-MM-DD` form.
- [ ] "Cancel" opens `/profile` and saves nothing.
- [ ] Each of these, sent as a POST with the other fields valid, answers
      200, shows the given message, keeps the typed values in the form and
      adds no row:
  - amount empty → `Please fill in the amount, category and date.`
  - amount `abc`, `-5`, `1e5`, `nan`, `inf`, `1,200` or `10.999` →
    `Please enter a valid amount, like 250 or 250.50.`
  - amount `0` or `0.00` → `Amount must be greater than zero.`
  - amount `10000000` → `Amount cannot be more than ₹9,999,999.99.`
  - category `Travel` or `food` → `Please choose a category from the list.`
  - date `2026-13-45` or `abc` → `Please enter a valid date.`
  - date tomorrow → `The date cannot be in the future.`
  - description of 201 characters → `Description cannot be longer than 200
    characters.`
- [ ] Amount `9999999.99` is accepted and shows as `₹9,999,999.99`.
- [ ] A POST with amount empty and category `Travel` shows the first
      message only: the first rule that fails decides.
- [ ] A POST that also sends `user_id=1` saves the row under the signed-in
      user, not under user 1.
- [ ] A description of `<script>alert(1)</script>` is saved, shows no alert
      on `/profile`, and the page source shows it escaped.
- [ ] A description of `x'); DROP TABLE expenses;--` is saved as that text,
      and the `expenses` table still exists.
- [ ] Signed out, a POST to `/expenses/add` redirects to `/login` and adds
      no row.
- [ ] Signed in as `demo@spendly.com` / `demo123`, `/profile` does not show
      the new user's expenses.
- [ ] An expense saved with a date in last month is counted in the cards on
      `/profile`, and is left out when the "This month" preset is chosen.
- [ ] `/expenses/1/edit` and `/expenses/1/delete` still show their
      placeholder text.
- [ ] `grep -n "execute" app.py` finds nothing: all SQL is in
      `database/db.py`.
- [ ] The category list is written once, as `CATEGORIES` in
      `database/db.py`. `app.py` and the template do not write the names
      out again. (The sample rows in `seed_db()` keep their own strings.)
- [ ] `grep '#' static/css/expense.css` finds no hex colour values.
- [ ] `git diff main -- static/css/style.css static/css/profile.css` is
      empty.
- [ ] The form can be used with the keyboard alone: Tab reaches every
      field, "Save expense" and "Cancel", each with a visible focus style.
- [ ] At a window width of 500px the form fits and the page has no
      horizontal scrollbar.
- [ ] With `unpkg.com` blocked, the form still shows every label and still
      saves.
- [ ] `pytest` still passes: the existing tests for Step 6 are not broken.
- [ ] `/`, `/login`, `/register`, `/terms`, `/privacy` and `/analytics` look
      as before, with no error in the browser console.
