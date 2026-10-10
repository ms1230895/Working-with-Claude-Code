# Spec: Delete Expense

## Overview
Let a signed-in user remove an expense they saved by mistake. Steps 7 and 8
let a user add an expense and correct one, but an expense that should not be
there at all (a duplicate, a test entry) can only be removed with a
hand-written `DELETE`, and `/expenses/<id>/delete` still answers with the text
`Delete expense — coming in Step 9`. This step replaces that placeholder with
a confirmation page that shows the expense, and a POST handler that deletes
it. It adds a "Delete" link beside "Edit" in every row of the table on
`/profile`, which is how the user reaches the page. Deleting cannot be undone,
so it takes two steps: the link opens the confirmation page, and only the
button on that page deletes. It reuses the ownership check from Step 8 and
adds the first helper in `database/db.py` that removes a row. It is the last
of the three expense steps (add, edit, delete); after it no route in `app.py`
is a placeholder.

## Depends on
- Step 1 — Database Setup: the `expenses` table and `get_db()`.
- Step 3 — Login and Logout: `g.user` and `login_required`.
- Step 4 — Profile Page Design: the expense table in `templates/profile.html`
  and the flash message area in `base.html`.
- Step 5 — Backend Connections: the summary cards, the table and the category
  breakdown are read from the database on every request, so they are correct
  after a delete without any extra work.
- Step 7 — Add Expense: the `.auth-*` page layout the expense pages use,
  `static/css/expense.css` and its `.expense-cancel` link.
- Step 8 — Edit Expense: `get_expense()`, `get_own_expense_or_404()`,
  `MAX_EXPENSE_ID`, the "Actions" column and `.profile-row-action`. This step
  reuses all of them.

## Routes
- `GET /expenses/<int:expense_id>/delete` — show a confirmation page with the
  expense's date, description, category and amount — logged-in, owner only
  (already exists as a placeholder; the `delete_expense` endpoint name stays)
- `POST /expenses/<int:expense_id>/delete` — delete the expense and redirect
  to `/profile` — logged-in, owner only

The URL variable is renamed from `id` to `expense_id`, as Step 8 did for the
edit route, so it no longer hides Python's built-in `id`. The address itself
does not change.

The POST sends no form fields. The expense is named by the URL and the owner
is the signed-in user; anything in the request body is ignored.

Answers that are not the page:
- Signed out, GET or POST: redirect to `/login`. Nothing is read or deleted.
- The expense does not exist, or belongs to another user: 404, for GET and
  POST alike. The two cases get the same answer, so the page does not reveal
  which ids exist.
- Any other method: 405.

## Database changes
No database changes. No new tables, columns, constraints or indexes, and
`init_db()` and `seed_db()` are not touched. The row is really removed: there
is no `deleted_at` column and no archive table.

Nothing refers to an expense, so the `DELETE` cannot fail on a foreign key.
`expenses.id` is `AUTOINCREMENT`, so the id of a deleted expense is never
given to a later one.

One addition to `database/db.py` (no schema change):
- `remove_expense(expense_id, user_id)` — deletes one row and returns `True`
  when a row was deleted, `False` when none matched. Its `WHERE` filters on
  both `id` and `user_id`, so another user's expense is left alone and looks
  the same as one that does not exist.

The helper is not called `delete_expense`: that is the name of the view in
`app.py`, and `app.py` imports the helpers by name. The pairs are
`add_expense` / `create_expense()`, `edit_expense` / `update_expense()` and
`delete_expense` / `remove_expense()`.

## Templates
- **Create:** `templates/expense_delete.html` — the confirmation page. It
  extends `base.html`, loads `static/css/expense.css` through the `head`
  block and uses the same layout as the expense form (`.auth-section`,
  `.auth-container`, `.auth-header`, `.auth-card`). It takes one value,
  `expense`, the row from `get_expense()`.
  - Title block: `Delete expense — Spendly`.
  - `<h1 class="auth-title">`: `Delete expense`.
  - Subtitle (`.auth-subtitle`): `This cannot be undone`.
  - Inside the card, a `<dl class="expense-summary">` with four rows, each a
    `<dt>` and a `<dd>`:

    | `<dt>` | `<dd>` |
    |---|---|
    | Date | `expense.date|format_date` |
    | Description | `expense.description`, or `—` when it is `NULL` |
    | Category | `expense.category` |
    | Amount | `expense.amount|format_money` |

  - Under it, a form: `method="POST"`,
    `action="{{ url_for('delete_expense', expense_id=expense.id) }}"`,
    `class="expense-form"`. It holds one control, a
    `<button type="submit" class="btn-submit expense-delete-button">` with
    the text `Delete expense`. No inputs, visible or hidden.
  - Under the form, the same link as on the expense form:
    `<a href="{{ url_for('profile') }}" class="expense-cancel">Cancel</a>`.
  - The button has no `autofocus`, so pressing Enter on arrival does not
    delete.
- **Modify:** `templates/profile.html`
  - The cell in the "Actions" column gets the class `profile-actions` and a
    second link, after "Edit":
    `<a href="{{ url_for('delete_expense', expense_id=expense.id) }}"
    class="profile-row-action profile-row-action-danger">`, holding a Lucide
    `trash-2` icon (`.profile-icon`) and the visible text `Delete`.
  - Every link reads "Delete", so each one gets an `aria-label` built the
    same way as the "Edit" one, for example `Delete Lunch, 24 Sep 2026`:
    the visible text first, then the description, or the category when
    there is no description, then the date through `format_date`.
  - The "Edit" link, the column header and the rest of the page do not
    change.
- `templates/expense_form.html` is not changed. The edit page gets no
  "Delete" control in this step.

## Files to change
- `app.py`
  - Import `remove_expense` from `database.db`.
  - Move `delete_expense` out of the "Placeholder routes" section, to sit
    after `edit_expense`, and delete that section's banner comment: no
    placeholder is left. The route accepts GET and POST, stays behind
    `login_required`, and its argument is `expense_id`.
  - Both methods start with `get_own_expense_or_404(expense_id)`.
  - GET: render `expense_delete.html` with `expense`.
  - POST: call `remove_expense(expense_id, g.user["id"])`. When it returns
    `False`, `abort(404)`. Otherwise flash `Expense deleted.` and redirect
    to `url_for('profile')`.
  - `add_expense`, `edit_expense`, `check_expense_form()`,
    `render_expense_form()` and `get_own_expense_or_404()` are not changed.
- `database/db.py` — add `remove_expense()`, after `update_expense()`.
- `templates/profile.html` — the "Delete" link (see above).
- `static/css/profile.css` — in the table section, beside
  `.profile-row-action`: the `.profile-actions` cell, the space between the
  two links, and `.profile-row-action-danger`.
- `static/css/expense.css` — the banner comment now also names the delete
  page; new rules for `.expense-summary` and `.expense-delete-button`.
- `tests/test_07-add-expense.py` — delete
  `test_delete_expense_still_returns_its_placeholder_text`. It asserts the
  placeholder text this step removes. No other test and no assertion in
  either test file changes; every other test must pass as it is. That
  includes the two tests beside it, which still hold: a signed-out GET to
  `/expenses/1/delete` redirects to `/login`, and a signed-in GET to the
  user's own expense deletes nothing.
- `CLAUDE.md` — update the Architecture notes: what `/expenses/<id>/delete`
  now does (GET confirms, POST deletes, the 404 cases, the flash message),
  `remove_expense()` and why it is not called `delete_expense`, that the
  route now writes to the database, the new template, the "Delete" link with
  `.profile-row-action-danger` and `.profile-actions`, that `expense.css`
  also styles the delete page, that the delete page loads its own CSS, and
  that no route is a placeholder any more.

## Files to create
- `templates/expense_delete.html`

## New dependencies
No new dependencies. No form library and no new JavaScript: the confirmation
is a page, not a `confirm()` call or a `<dialog>`.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **GET never deletes.** This is the rule that matters most in this step. A
  link, a browser prefetch, a crawler or an `<img src>` on another site can
  all send a GET. The GET only shows the confirmation page; the `DELETE`
  runs on a POST and nowhere else. The "Delete" control in the table is a
  link to the confirmation page, not a form that deletes.
- **Whose expense.** The id in the URL is chosen by the visitor, so it
  proves nothing. Both the GET and the POST call
  `get_own_expense_or_404(expense_id)` before they do anything else.
  - `user_id` is always `g.user["id"]`. Never read it, or an expense id,
    from the form or the query string. The form has no hidden inputs: the
    id is already in its action.
  - 404, not 403 and not a redirect, for an expense that belongs to someone
    else. It is the same answer a missing id gets, and the confirmation
    page shows none of that expense's values.
  - `remove_expense()` filters on `user_id` as well. The route's check and
    the query's `WHERE` both have to hold; neither replaces the other.
  - When `remove_expense()` returns `False` (the row went away between the
    check and the delete), answer 404. Do not flash `Expense deleted.`
- **Ids SQLite cannot hold.** `get_own_expense_or_404()` already answers 404
  for an id above `MAX_EXPENSE_ID`, before any query runs. Do not add a
  second check, and do not call `remove_expense()` before it.
- **Where the SQL lives.** The `DELETE` is in `database/db.py`; `app.py`
  writes no SQL. `remove_expense()` opens its own connection, closes it in a
  `finally` block, deletes inside `with conn:` and reads `cursor.rowcount`
  for its return value, as `update_expense()` does.
- **One row at most.** The `WHERE` is `id = ? AND user_id = ?`, nothing
  wider. There is no "delete all", no delete by category or date range, and
  the helper takes one id.
- **Deleting twice.** A second POST for the same expense (a double click, or
  the back button and the button again) finds nothing and answers 404.
  Nothing else is deleted and nothing is flashed.
- **After deleting.** `flash("Expense deleted.")`, then
  `redirect(url_for("profile"))`, so refreshing the next page cannot send
  the form again. The redirect carries no date range.
- **No undo.** The row is removed for good. No soft delete, no "Undo" link
  in the flash message.
- **No CSRF token.** As in Steps 7 and 8, the form relies on the
  `SameSite=Lax` session cookie, which is not sent with a POST from another
  site. That protection only holds because the delete is a POST.
- **Escaping.** The description and the category are printed on the
  confirmation page and in the `aria-label`. Leave Jinja's autoescaping on,
  never use `|safe`, and keep every attribute quoted.
- **Template logic.** `expense_delete.html` prints the four values through
  the existing filters (`format_date`, `format_money`) and looks nothing up.
- **CSS.**
  - Only the `:root` tokens in both files: no literal colour values, spacing
    in `0.25rem` steps, font sizes from the 12, 14, 16, 20, 24, 32px scale.
    The red is `var(--danger)`.
  - `profile.css`: the two links sit on one line with space between them
    (the global reset leaves none), and `.profile-actions` does not wrap.
    `.profile-row-action-danger` changes the colour to `var(--danger)`,
    including the `:focus-visible` outline; the hover style stays the
    underline.
  - The table keeps scrolling sideways inside `.profile-table-wrap` on a
    narrow screen. Raise `.profile-table`'s `min-width` if the second link
    needs it; the page itself must not scroll sideways.
  - `expense.css`: `.expense-summary` lays each row out as label on the
    left, value on the right, with a `var(--border-soft)` line between
    rows. The amount uses tabular numbers. A 200-character description
    without spaces wraps inside the card (`overflow-wrap: anywhere`).
  - `.expense-delete-button` sets the button's background to
    `var(--danger)`. It needs its own `:hover` rule, because
    `.btn-submit:hover` would turn it green. The form has the class
    `expense-form`, so the existing `:focus-visible` rule in `expense.css`
    already covers the button.
  - `style.css` is not changed.
- **Icons.** The `trash-2` icon sits beside the visible text `Delete`, so
  the link works when the Lucide script cannot load. It uses the existing
  `.profile-icon` (16px); no new icon size. The confirmation page needs no
  icon.
- **Markup.** One `<h1>` on the confirmation page. The page says in visible
  text that the delete cannot be undone; the red colour is not the only
  warning.
- **Not in this step:** a "Delete" control on the edit page; a JavaScript
  `confirm()` or a `<dialog>` in place of the confirmation page; undo, soft
  delete or a bin; deleting several expenses at once; deleting an account; a
  custom 404 page; returning to the date range the user came from; CSRF
  tokens; pagination of the table; removing the unused `.hero-visual` and
  `.mock-*` rules. Automated tests for this step are written afterwards with
  `/test-feature`.

## Definition of done
Set-up for the checks below: start from a fresh database (delete
`expense_tracker.db` and restart), so the demo user has expenses 1 to 8.
Register a second user, sign in as it and add two expenses: `250.50`, `Food`,
today, `Lunch` (id 9), and `80`, `Transport`, today, no description (id 10).

- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /expenses/9/delete` and a POST to it both redirect to
      `/login`, and `SELECT COUNT(*) FROM expenses WHERE id = 9;` is `1`.
- [ ] Signed in as the second user, each row of the table on `/profile` has
      an "Edit" link and a "Delete" link on one line, and the "Delete" link
      of the `Lunch` row opens `/expenses/9/delete`.
- [ ] That page has the title and heading `Delete expense`, the text
      `This cannot be undone`, today's date, `Lunch`, `Food` and `₹250.50`,
      a "Delete expense" button and a "Cancel" link. The placeholder text
      `coming in Step 9` is gone.
- [ ] `/expenses/10/delete` shows `—` for the description.
- [ ] Opening `/expenses/9/delete` and refreshing it several times deletes
      nothing: the row is still in the table on `/profile`.
- [ ] "Cancel" opens `/profile` and deletes nothing.
- [ ] Pressing "Delete expense" on `/expenses/9/delete` redirects to
      `/profile`, which shows `Expense deleted.`, the cards `₹80.00`, `1`
      and `Transport`, one row in the table, and only `Transport` in the
      category breakdown.
- [ ] Refreshing `/profile` after that changes nothing more, and the message
      is gone.
- [ ] `SELECT COUNT(*) FROM expenses WHERE id = 9;` is `0`, and
      `SELECT COUNT(*) FROM expenses;` is `9`: one row went, no other.
- [ ] `GET /expenses/9/delete` now answers 404, and so does a second POST to
      it. The second POST flashes nothing and deletes nothing.
- [ ] Deleting expense 10 as well leaves the empty state on `/profile`: the
      cards `₹0.00`, `0` and `—`, `No expenses yet`, and no category
      breakdown.
- [ ] Adding a new expense after that gives it id 11, not 9 or 10.
- [ ] Signed in as the second user, `GET /expenses/1/delete` (a demo user's
      expense) answers 404 and shows none of that expense's values.
- [ ] Signed in as the second user, a POST to `/expenses/1/delete` answers
      404, and `SELECT COUNT(*) FROM expenses WHERE id = 1;` is still `1`.
- [ ] A POST to `/expenses/11/delete` that also sends `user_id=1` and
      `expense_id=1` deletes expense 11 and leaves expense 1 in place.
- [ ] `GET /expenses/999999/delete` answers 404.
- [ ] `GET /expenses/99999999999999999999999/delete` answers 404, not 500,
      and so does a POST to it.
- [ ] `GET /expenses/abc/delete` answers 404.
- [ ] A PUT, PATCH or DELETE to `/expenses/1/delete` answers 405.
- [ ] An expense with the description `<script>alert(1)</script>` shows no
      alert on `/profile` or on its confirmation page, and the page source
      shows it escaped in the summary and in the "Delete" link's
      `aria-label`.
- [ ] An expense with a 200-character description without spaces stays
      inside the card on its confirmation page.
- [ ] Signed in as `demo@spendly.com` / `demo123`, `/profile` shows eight
      "Delete" links, each opens the right expense, and deleting the
      `Headphones` row removes `Shopping` from the category breakdown and
      lowers "Total spent" by `₹999.99`.
- [ ] With a date range chosen on `/profile`, the "Delete" links still work,
      and after a delete the page shows all expenses again (no range).
- [ ] `/expenses/add` and `/expenses/<id>/edit` look and work as before:
      saving flashes `Expense added.` and `Expense updated.`
- [ ] `grep -n "execute" app.py` finds nothing: all SQL is in
      `database/db.py`.
- [ ] `grep -n "coming in Step" app.py` finds nothing.
- [ ] `grep '#' static/css/profile.css static/css/expense.css` finds no hex
      colour values.
- [ ] `git diff main -- static/css/style.css templates/expense_form.html` is
      empty.
- [ ] With the keyboard alone, Tab reaches every "Delete" link on `/profile`
      and the button and the "Cancel" link on the confirmation page, each
      with a visible focus style. Arriving on the confirmation page and
      pressing Enter at once deletes nothing.
- [ ] Hovering the "Delete expense" button does not turn it green.
- [ ] At a window width of 500px the table scrolls sideways inside its
      card, both links can be reached, and neither `/profile` nor the
      confirmation page has a horizontal scrollbar.
- [ ] With `unpkg.com` blocked, each row still shows the text `Delete` and
      the link still works.
- [ ] `pytest` passes, after the one test named under "Files to change" is
      deleted.
- [ ] `python3 -m black --check .` reports nothing to change.
- [ ] `/`, `/login`, `/register`, `/terms`, `/privacy` and `/analytics` look
      as before, with no error in the browser console.
