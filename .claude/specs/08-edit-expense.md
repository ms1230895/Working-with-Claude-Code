# Spec: Edit Expense

## Overview
Let a signed-in user correct an expense they already saved. Step 7 added the
form that creates an expense, but a typo in the amount or a wrong category can
only be fixed with a hand-written `UPDATE`, and `/expenses/<id>/edit` still
answers with the text `Edit expense — coming in Step 8`. This step replaces
that placeholder with the Step 7 form, filled with the saved values, and a POST
handler that checks the input with the same rules and updates the row. It adds
an "Edit" link to every row of the table on `/profile`, which is how the user
reaches the page. It is the first route that takes an expense id from the URL,
so it is also the first one that has to check that the expense belongs to the
signed-in user. It adds the first helpers in `database/db.py` that read and
change a single expense. It comes before delete (Step 9), which needs the same
ownership check and puts its control in the same table column.

## Depends on
- Step 1 — Database Setup: the `expenses` table and `get_db()`.
- Step 3 — Login and Logout: `g.user` and `login_required`.
- Step 4 — Profile Page Design: the expense table in `templates/profile.html`
  and the flash message area in `base.html`.
- Step 5 — Backend Connections: `get_recent_expenses()` already returns each
  row's `id`, which the "Edit" link needs.
- Step 6 — Date Filter for Profile Page: `parse_filter_date()`, and its rule
  that every stored `date` is zero-padded `YYYY-MM-DD` text.
- Step 7 — Add Expense: `check_expense_form()`, `render_expense_form()`,
  `CATEGORIES`, `templates/add_expense.html` and `static/css/expense.css`.
  This step reuses all of them.

## Routes
- `GET /expenses/<int:expense_id>/edit` — show the form filled with the saved
  expense — logged-in, owner only (already exists as a placeholder; the
  `edit_expense` endpoint name stays)
- `POST /expenses/<int:expense_id>/edit` — check the input, update the expense
  and redirect to `/profile` — logged-in, owner only

The URL variable is renamed from `id` to `expense_id`, so it no longer hides
Python's built-in `id`. The address itself does not change.

Form fields sent by the POST are the four from Step 7, with the same rules:
`amount`, `category`, `date`, `description`.

Answers that are not the form:
- Signed out, GET or POST: redirect to `/login`. Nothing is read or changed.
- The expense does not exist, or belongs to another user: 404. The two cases
  get the same answer, so the page does not reveal which ids exist.
- Any other method: 405.

## Database changes
No database changes. Every column this step writes (`amount`, `category`,
`date`, `description`) already exists. No new tables, columns, constraints or
indexes, no `updated_at` column, and `init_db()` and `seed_db()` are not
touched.

Two additions to `database/db.py` (no schema change):
- `get_expense(expense_id, user_id)` — returns the row with `id`, `date`,
  `description`, `category` and `amount`, or `None`. Its query filters on both
  `id` and `user_id`, so another user's expense comes back as `None`, the
  same as one that does not exist.
- `update_expense(expense_id, user_id, amount, category, date,
  description=None)` — updates the four fields of one row and returns `True`
  when a row was changed, `False` when none matched. Its `WHERE` also filters
  on both `id` and `user_id`. It never changes `user_id` or `created_at`. It
  does not check its arguments; the route does that first, as it does for
  `create_expense()`.

## Templates
- **Create:** none.
- **Modify:** `templates/add_expense.html`, renamed to
  `templates/expense_form.html` with `git mv`. It becomes the one form
  template for both pages, and still extends `base.html`.
  - It takes one new value, `expense_id`. It is `None` on the add page and
    the expense's id on the edit page. Everything that differs between the
    two pages is decided from it:

    | | Add (`expense_id` is `None`) | Edit |
    |---|---|---|
    | Title block | `Add expense — Spendly` | `Edit expense — Spendly` |
    | `<h1>` | `Add expense` | `Edit expense` |
    | Subtitle | `Record something you spent` | `Change the details of this expense` |
    | Form action | `url_for('add_expense')` | `url_for('edit_expense', expense_id=expense_id)` |
    | Submit button | `Save expense` | `Save changes` |

  - The four fields, their attributes, the error block and the "Cancel"
    link to `url_for('profile')` are the same on both pages and are written
    once. The add page must look and behave exactly as it does now.
- **Modify:** `templates/profile.html`
  - The expense table gets a fifth column. Header:
    `<th scope="col">Actions</th>`.
  - Each row gets a cell with one link:
    `<a href="{{ url_for('edit_expense', expense_id=expense.id) }}"
    class="profile-row-action">`, holding a Lucide `pencil` icon
    (`.profile-icon`) and the visible text `Edit`.
  - Every link reads "Edit", so each one also gets an `aria-label` that
    names its row and starts with the visible text, for example
    `Edit Lunch, 24 Sep 2026`. It uses the description, or the category when
    there is no description, and the date through `format_date`.
  - Nothing else on the page changes.

## Files to change
- `app.py`
  - Import `abort` from `flask`, and `get_expense` and `update_expense` from
    `database.db`.
  - `render_expense_form(today, expense_id=None, **values)` renders
    `expense_form.html` and passes `expense_id` on. `add_expense` keeps
    calling it without `expense_id`.
  - Add `get_own_expense_or_404(expense_id)` beside the other expense form
    helpers. It returns the signed-in user's expense, or calls `abort(404)`.
    Step 9 will use it too.
  - Move `edit_expense` out of the "Placeholder routes" section, to sit
    after `add_expense`. It accepts GET and POST and stays behind
    `login_required`.
  - GET: load the expense, then render the form with the saved values.
  - POST: load the expense, strip the four fields, pass them to
    `check_expense_form()`, then either re-render the form or save, flash
    `Expense updated.` and redirect to `url_for('profile')`.
  - `add_expense`, `check_expense_form()` and `delete_expense` are not
    changed.
- `database/db.py` — add `get_expense()` and `update_expense()`, after
  `create_expense()`.
- `templates/add_expense.html` → `templates/expense_form.html` (see above).
- `templates/profile.html` — the "Actions" column and the "Edit" links.
- `static/css/profile.css` — a `.profile-row-action` rule for the link, in
  the table section.
- `static/css/expense.css` — the banner comment only: it now says the file
  styles the add and the edit form. No rule changes.
- `tests/test_07-add-expense.py`
  - Delete `test_edit_expense_still_returns_its_placeholder_text`. It
    asserts the placeholder text this step removes.
  - `table_rows()` returns the first four cells of each row. Two tests
    compare a whole row with its four values, and the "Actions" column adds
    a fifth cell.
- `tests/test_06-date-filter-for-profile-page.py` — `expense_rows()` returns
  the first four cells, for the same reason.
- No assertion in either file changes. Every other test must pass as it is.
- `CLAUDE.md` — update the Architecture notes: what `/expenses/<id>/edit`
  now does, the ownership check and the 404, `get_own_expense_or_404()`,
  `get_expense()` and `update_expense()`, that `/expenses/<id>/edit` now
  writes to the database, the renamed template and its `expense_id` value,
  the "Actions" column and `.profile-row-action`, and that only delete is
  still a placeholder.

## Files to create
No new files. (`templates/expense_form.html` is `add_expense.html` renamed.)

## New dependencies
No new dependencies. `abort` is part of Flask. No form library and no new
JavaScript.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **Whose expense.** This is the rule that matters most in this step. The id
  in the URL is chosen by the visitor, so it proves nothing. Both the GET and
  the POST load the expense with `get_expense(expense_id, g.user["id"])`
  before they do anything else, and answer 404 when it returns `None`.
  - `user_id` is always `g.user["id"]`. Never read it from the form or the
    query string, and do not put it, or the expense id, in a hidden input:
    the id is already in the form's action.
  - 404, not 403 and not a redirect, for an expense that belongs to someone
    else. It is the same answer a missing id gets.
  - On a POST the ownership check comes before the form checks. A POST to
    another user's expense answers 404 whether its fields are valid or not.
  - `update_expense()` filters on `user_id` as well. The route's check and
    the query's `WHERE` both have to hold; neither replaces the other.
  - When `update_expense()` returns `False` (the row went away between the
    check and the update), answer 404. Do not flash `Expense updated.`
- **Ids SQLite cannot hold.** Flask's `int` converter accepts any number of
  digits. `sqlite3` raises `OverflowError` for an integer above
  `2**63 - 1`, which would answer 500. `get_own_expense_or_404()` answers
  404 for such an id before any query runs.
- **Where the SQL lives.** The `SELECT` and the `UPDATE` are in
  `database/db.py`; `app.py` writes no SQL. Each helper opens its own
  connection and closes it in a `finally` block. `update_expense()` saves
  inside `with conn:`, as `create_expense()` does, and reads
  `cursor.rowcount` for its return value.
- **GET changes nothing.** Opening the edit page never writes to the
  database. Only the POST updates.
- **One set of rules.** The edit form is checked by `check_expense_form()`
  exactly as it is: same rules, same order, same messages, same limits. Do
  not copy the checks into `edit_expense` and do not add a second version.
  On an error the page answers 200, changes nothing and shows the form
  again with the message and the typed values.
- **What the form shows on a GET.**
  - Amount: the saved amount with two decimals, built in the view as
    `f"{amount:.2f}"`. `1200.0` shows as `1200.00`, not `1200.0`.
  - Category: the saved one is selected. A row whose category is not in
    `CATEGORIES` (only possible through a hand-written `INSERT`) shows
    `Choose a category`, and the user has to pick one to save.
  - Date: the saved text.
  - Description: the saved text, or empty when it is `NULL`.
- **What is saved.** As in Step 7: `float()` of the amount only after the
  pattern passed, `parsed.isoformat()` for the date and never the text from
  the form, and `None` for a description that is empty or only spaces.
- **Saving without changes** is allowed. It updates the row with the same
  values, flashes `Expense updated.` and redirects.
- **After saving.** `flash("Expense updated.")`, then
  `redirect(url_for("profile"))`, so refreshing the next page cannot send
  the form again. The redirect carries no date range.
- **No CSRF token.** As in Step 7, the form relies on the `SameSite=Lax`
  session cookie. That protection only holds because the change is a POST;
  never update on a GET.
- **Escaping.** The saved and the typed values are printed into the form.
  Leave Jinja's autoescaping on, never use `|safe`, and keep every
  `value="..."` and `aria-label="..."` attribute quoted.
- **Template logic.** The template decides its texts and its action from
  `expense_id` and nothing else. It does not format the amount and does not
  look anything up.
- **CSS.**
  - `.profile-row-action` goes in `static/css/profile.css`, in the table
    section. Only the `:root` tokens: no literal colour values, spacing in
    `0.25rem` steps, font sizes from the 12, 14, 16, 20, 24, 32px scale.
  - The link has a hover style and a visible `:focus-visible` style.
  - The icon uses the existing `.profile-icon` (16px); no new icon size.
  - The table keeps scrolling sideways inside `.profile-table-wrap` on a
    narrow screen. Raise `.profile-table`'s `min-width` if the fifth
    column needs it; the page itself must not scroll sideways.
  - `style.css` is not changed. `expense.css` gets no new rules.
- **Icons.** The `pencil` icon sits beside the visible text `Edit`, so the
  link works when the Lucide script cannot load.
- **Markup.** One `<h1>` on the form page. Every control keeps its own
  `<label for>`.
- **Not in this step:** delete, and the delete control in the "Actions"
  column (Step 9); an `updated_at` column or an edit history; a custom 404
  page; returning to the date range the user came from; editing from a
  modal or inside the table row; editing several expenses at once; moving
  an expense to another user; a "nothing changed" message; protection
  against two tabs saving the same expense; CSRF tokens; pagination of the
  table. Automated tests for this step are written afterwards with
  `/test-feature`.

## Definition of done
Set-up for the checks below: start from a fresh database (delete
`expense_tracker.db` and restart), so the demo user has expenses 1 to 8.
Register a second user, sign in as it and add one expense: `250.50`, `Food`,
today, `Lunch`. Its id is 9.

- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /expenses/9/edit` and a POST to it both redirect to
      `/login`, and the row is unchanged.
- [ ] Signed in as the second user, the table on `/profile` has an
      "Actions" column, and the row has an "Edit" link that opens
      `/expenses/9/edit`.
- [ ] That page has the title and heading `Edit expense`, a "Save changes"
      button and a "Cancel" link. The placeholder text `coming in Step 8`
      is gone.
- [ ] The form shows amount `250.50`, category `Food` selected, today's
      date and description `Lunch`.
- [ ] Changing the amount to `300`, the category to `Transport` and the
      description to `Taxi`, then saving, redirects to `/profile`, which
      shows `Expense updated.`, the cards `₹300.00`, `1` and `Transport`,
      and one row with `Taxi`, `Transport` and `₹300.00`.
- [ ] Refreshing `/profile` after that changes nothing more, and the message
      is gone.
- [ ] `SELECT COUNT(*) FROM expenses WHERE user_id = <second user>;` is
      still `1`: the edit changed the row and did not add one.
- [ ] `SELECT user_id, created_at FROM expenses WHERE id = 9;` gives the
      same values before and after the edit.
- [ ] Clearing the description and saving shows `—` in the table, and
      `SELECT description FROM expenses WHERE id = 9;` gives `NULL`.
- [ ] Changing the date to one in last month and saving keeps the expense in
      the cards on `/profile`, and leaves it out when "This month" is
      chosen. The stored date is in `YYYY-MM-DD` form.
- [ ] Opening the edit page and pressing "Save changes" without changing
      anything redirects to `/profile` with `Expense updated.` and the same
      values.
- [ ] "Cancel" opens `/profile` and changes nothing.
- [ ] Each of these, sent as a POST to `/expenses/9/edit` with the other
      fields valid, answers 200, shows the given message, keeps the typed
      values in the form and leaves the row unchanged:
  - amount empty → `Please fill in the amount, category and date.`
  - amount `abc`, `-5`, `1e5`, `nan`, `inf`, `1,200` or `10.999` →
    `Please enter a valid amount, like 250 or 250.50.`
  - amount `0` → `Amount must be greater than zero.`
  - amount `10000000` → `Amount cannot be more than ₹9,999,999.99.`
  - category `Travel` or `food` → `Please choose a category from the list.`
  - date `2026-13-45` → `Please enter a valid date.`
  - date tomorrow → `The date cannot be in the future.`
  - description of 201 characters → `Description cannot be longer than 200
    characters.`
- [ ] After such an error the page is still the edit page: heading
      `Edit expense`, and the form's action is `/expenses/9/edit`.
- [ ] Signed in as the second user, `GET /expenses/1/edit` (a demo user's
      expense) answers 404 and shows none of that expense's values.
- [ ] Signed in as the second user, a valid POST to `/expenses/1/edit`
      answers 404, and `SELECT * FROM expenses WHERE id = 1;` is unchanged.
- [ ] The same POST with an invalid amount also answers 404, not the form.
- [ ] `GET /expenses/999999/edit` answers 404.
- [ ] `GET /expenses/99999999999999999999999/edit` answers 404, not 500.
- [ ] `GET /expenses/abc/edit` answers 404.
- [ ] A POST to `/expenses/9/edit` that also sends `user_id=1` leaves the
      row under the second user.
- [ ] A PUT or DELETE to `/expenses/9/edit` answers 405.
- [ ] A description of `<script>alert(1)</script>` is saved, shows no alert
      on `/profile` or on the edit page, and the page source shows it
      escaped in the table, in the `aria-label` and in the input's `value`.
- [ ] A description of `x'); DROP TABLE expenses;--` is saved as that text,
      and the `expenses` table still exists.
- [ ] Signed in as `demo@spendly.com` / `demo123`, `/profile` shows eight
      "Edit" links, each opens the right expense, and the amount `999.99`
      row shows `999.99` in the form.
- [ ] `/expenses/add` looks and works as before: title and heading
      `Add expense`, button `Save expense`, date set to today, and saving
      flashes `Expense added.`
- [ ] `/expenses/1/delete` still shows its placeholder text.
- [ ] `grep -n "execute" app.py` finds nothing: all SQL is in
      `database/db.py`.
- [ ] `ls templates` shows `expense_form.html` and no `add_expense.html`,
      and `grep -rn "add_expense.html" app.py templates` finds nothing.
- [ ] `grep '#' static/css/profile.css static/css/expense.css` finds no hex
      colour values.
- [ ] `git diff main -- static/css/style.css` is empty.
- [ ] With the keyboard alone, Tab reaches every "Edit" link on `/profile`
      and every control on the edit page, each with a visible focus style.
- [ ] At a window width of 500px the table scrolls sideways inside its
      card, the "Edit" link can be reached, and the page has no horizontal
      scrollbar.
- [ ] With `unpkg.com` blocked, each row still shows the text `Edit` and
      the link still works.
- [ ] `pytest` passes, after the changes to the two test files named under
      "Files to change": one test deleted, two row helpers adjusted.
- [ ] `/`, `/login`, `/register`, `/terms`, `/privacy` and `/analytics` look
      as before, with no error in the browser console.
