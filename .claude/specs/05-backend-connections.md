# Spec: Backend Connections

## Overview
Connect the profile page to the database. Step 4 built `/profile` as a design
step: the name, email and join date come from `g.user`, but the three summary
figures, the expense table and the category breakdown are fixed sample values
written in the `profile` view, and a note on the page says so. This step
replaces those literals with queries on the `expenses` table, limited to the
signed-in user, and removes the note. It adds three read-only helpers to
`database/db.py` and returns data in the shape the template already reads, so
the layout from Step 4 stays as it is. After this step every user sees their
own figures: the demo user sees the eight seeded expenses, and a newly
registered user sees the empty state. It comes before the add, edit and delete
steps (7, 8 and 9) so that those steps have a page that shows the result of
each write.

## Depends on
- Step 1 — Database Setup: the `expenses` table, `get_db()` and the eight
  expenses `seed_db()` inserts for the demo user.
- Step 3 — Login and Logout: `g.user` and `login_required`, which tell the
  route whose expenses to read.
- Step 4 — Profile Page Design: `templates/profile.html`,
  `static/css/profile.css`, the `format_money` and `format_date` filters, and
  the shape of `stats`, `expenses` and `categories`.

## Routes
- `GET /profile` — show the profile page with the signed-in user's own
  expenses, read from the database — logged-in (already exists; the `profile`
  endpoint name stays)

No new routes.

## Database changes
No database changes. The `expenses` table already has every column this step
reads (`user_id`, `amount`, `category`, `date`, `description`). No new tables,
columns, constraints or indexes, and `init_db()` and `seed_db()` are not
touched.

Three new helper functions are added to `database/db.py` (no schema change).
All three only read:
- `get_expense_stats(user_id)` — returns a dict with `total_spent` (float,
  `0.0` when the user has no expenses), `transaction_count` (int) and
  `top_category` (str, or `None` when the user has no expenses).
- `get_recent_expenses(user_id, limit=10)` — returns a list of `sqlite3.Row`
  with the columns `id`, `date`, `description`, `category` and `amount`,
  newest first. An empty list when the user has no expenses.
- `get_category_totals(user_id)` — returns a list of dicts with `name` (str),
  `total` (float) and `percent` (int, 0 to 100), largest total first. An
  empty list when the user has no expenses.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html`
  - Remove the sample data note (the `<p class="profile-note">` element and
    its `info` icon).
  - "Top category" card: show `—` when `stats.top_category` is `None`.
  - Description cell: show `—` when `expense.description` is empty. The
    column allows `NULL`, and Jinja would otherwise print the word `None`.
  - Nothing else changes: same blocks, same classes, same loops.

## Files to change
- `app.py`
  - Import `get_expense_stats`, `get_recent_expenses` and
    `get_category_totals` from `database.db`.
  - In `profile`, delete the three sample literals and their comments, and
    call the three helpers with `g.user["id"]` instead. The
    `render_template(...)` call keeps the same three names.
- `database/db.py` — add the three helpers listed under Database changes.
- `templates/profile.html` — the changes listed under Templates.
- `static/css/profile.css` — delete the "Sample data note" section (its
  banner comment and the two `.profile-note` rules), which no template uses
  after this step.
- `CLAUDE.md` — update the Architecture notes: `/profile` reads the signed-in
  user's expenses through the three helpers, the sample data and its note are
  gone, the three helpers are listed with the other `database/db.py`
  functions, and `/profile` joins `/login` and `load_user()` as a reader of
  the database.

## Files to create
None.

## New dependencies
No new dependencies. `sqlite3` is in the standard library.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **Only the signed-in user's rows.** Every query in this step has
  `WHERE user_id = ?`, and the value is always `g.user["id"]`. Never read a
  user id from the URL, the query string or a form.
- **Where the SQL lives.** Database access stays in `database/db.py`;
  `app.py` calls the helpers and does not write SQL itself. Every connection
  is closed in a `finally` block, as the existing functions do.
- **Read only.** The three helpers run `SELECT` statements only. Adding,
  editing and deleting expenses are Steps 7, 8 and 9.
- **Totals come from SQL.** Use `COUNT(*)`, `SUM(amount)` and `GROUP BY
  category` in the queries. Do not fetch every row and add the amounts up in
  Python.
- **`get_expense_stats`.** `SUM(amount)` over no rows is `NULL`; wrap it in
  `COALESCE(..., 0)` so `total_spent` is `0.0`, never `None`. The count and
  the total cover all of the user's expenses, not only the ones in the
  table. `top_category` is the category with the largest total; when two
  categories have the same total, the one that comes first alphabetically
  wins.
- **`get_recent_expenses`.** `ORDER BY date DESC, id DESC`, so two expenses
  on the same day are still listed newest first, then `LIMIT ?` with the
  `limit` argument. `date` stays the `YYYY-MM-DD` text the database stores;
  the template formats it with `format_date`.
- **`get_category_totals`.** `ORDER BY` the total descending, then the
  category name ascending, the same tie rule as `top_category`. Only
  categories the user has spent in are listed; a category with no expenses
  is left out. `percent` is the category total as a share of the user's
  total, rounded to a whole number with `round()`. The rounded values may
  add up to 99 or 101; that is expected. When the user's total is `0`,
  `percent` is `0`, not a division by zero.
- **Shape.** The template already reads `stats.total_spent`,
  `expense.date`, `category.percent` and so on. A `sqlite3.Row` works with
  that syntax, because Jinja falls back to `row["date"]` when the attribute
  does not exist. Keep the key names from Step 4; do not rename them.
- **Amounts.** Do not round amounts in SQL or in the helpers. A `REAL` sum
  can come back as `3610.4900000000002`; `format_money` already prints two
  decimals.
- **Categories.** The category names shown are the ones stored in the rows.
  The fixed list (Food, Transport, Bills, Health, Entertainment, Shopping,
  Other) is not enforced in this step.
- **Empty state.** A user with no expenses gets `₹0.00`, `0` and `—` in the
  summary cards, the empty state from Step 4 in place of the table, and no
  category breakdown. The page must not raise an error for such a user.
- **Escaping.** Descriptions and category names are typed by users. Leave
  Jinja's autoescaping on and never use `|safe` on them.
- **Never show `password_hash`.** The helpers select from `expenses` only
  and do not join `users`.
- **CSS.** The only stylesheet change is deleting the unused "Sample data
  note" section. No new rules, no new tokens, no literal colour values.
- **Not in this step:** add, edit and delete forms; edit and delete controls
  on the rows; date filters; pagination or a "view all" page; totals per
  month; changing the seed data; automated tests.

## Definition of done
- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /profile` redirects to `/login`.
- [ ] Signed in as `demo@spendly.com` / `demo123` on a fresh database
      (delete `expense_tracker.db` and restart), the summary cards read
      `₹3,610.49`, `8` and `Bills`.
- [ ] The table has 8 rows, newest first. The first row is
      `Gift wrap and card · Other · ₹150.00` and the last is
      `Electricity bill · Bills · ₹1,200.00`. The dates are in the current
      month, as `seed_db()` writes them, not the fixed September dates of
      Step 4.
- [ ] The category breakdown lists 7 categories in this order: Bills
      (`₹1,200.00`, 33%), Shopping (`₹999.99`, 28%), Health (`₹450.00`,
      12%), Food (`₹430.50`, 12%), Entertainment (`₹300.00`, 8%), Other
      (`₹150.00`, 4%), Transport (`₹80.00`, 2%).
- [ ] The page no longer says its figures are sample data, and the page
      source contains no `profile-note`.
- [ ] A newly registered user who signs in sees `₹0.00`, `0` and `—` in the
      summary cards, the "No expenses yet" empty state, and no category
      breakdown, with no error page.
- [ ] Adding one row by hand for the new user, for example
      `INSERT INTO expenses (user_id, amount, category, date, description)
      VALUES (<id>, 99.50, 'Food', '2026-10-10', 'Test lunch');`, and
      refreshing shows `₹99.50`, `1`, `Food`, one table row and one category
      at 100%.
- [ ] After that insert, the demo user's page still shows `₹3,610.49` and 8
      rows: no user sees another user's expenses.
- [ ] A row inserted with `description` set to `NULL` shows `—` in the
      Description column, not `None`.
- [ ] A row with the description `<b>Test</b>` shows those characters as
      text, not as bold text.
- [ ] With 11 or more expenses for one user, the table shows the 10 newest,
      while "Transactions" and "Total spent" count all of them.
- [ ] `grep -n "execute" app.py` finds nothing: all SQL is in
      `database/db.py`.
- [ ] `grep -n "profile-note" -r static templates` finds nothing.
- [ ] `grep '#' static/css/profile.css` finds no hex colour values.
- [ ] The page source contains no `scrypt:` or `pbkdf2:` text.
- [ ] "Add expense" still opens `/expenses/add`, which still shows its
      placeholder text.
- [ ] `/`, `/login`, `/register`, `/terms` and `/privacy` look as before,
      with no error in the browser console.
