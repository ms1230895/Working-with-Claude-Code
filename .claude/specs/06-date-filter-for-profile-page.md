# Spec: Date Filter for Profile Page

## Overview
Let a signed-in user limit the profile page to a date range. Step 5 connected
`/profile` to the database, but the page always covers every expense the user
has: the three summary figures, the recent expenses table and the category
breakdown cannot answer "what did I spend in September?". This step adds a
filter card to the page with four preset ranges (This month, Last 3 months,
Last 6 months, All time) and a custom range with a start date and an end date.
The range travels in the query string of `GET /profile`, so a filtered page can
be bookmarked and refreshed, and nothing is stored on the server. The three
expense helpers in `database/db.py` gain two optional arguments, and all three
blocks on the page use the same range, so the figures always agree with the
rows below them. It comes before the add, edit and delete steps (7, 8 and 9)
so that those steps write into a page that can already show any period.

## Depends on
- Step 1 — Database Setup: the `expenses` table, whose `date` column holds
  `YYYY-MM-DD` text.
- Step 3 — Login and Logout: `g.user` and `login_required`, which tell the
  route whose expenses to read.
- Step 4 — Profile Page Design: `templates/profile.html`,
  `static/css/profile.css` and the `format_date` filter.
- Step 5 — Backend Connections: `get_expense_stats()`,
  `get_recent_expenses()` and `get_category_totals()`, which this step
  extends.

## Routes
- `GET /profile` — show the profile page for the signed-in user, limited to
  an optional date range — logged-in (already exists; the `profile` endpoint
  name stays)

  Two optional query parameters, both `YYYY-MM-DD`:
  - `date_from` — first day included.
  - `date_to` — last day included.

  Example: `/profile?date_from=2026-09-01&date_to=2026-09-30`.

No new routes. The filter form uses `method="get"`, so there is no POST.

## Database changes
No database changes. No new tables, columns, constraints or indexes, and
`init_db()` and `seed_db()` are not touched.

The three expense helpers in `database/db.py` gain two optional keyword
arguments, `date_from=None` and `date_to=None`. Each is a `YYYY-MM-DD` string
or `None`. Called without them, every helper returns what it returns today.
- `get_expense_stats(user_id, date_from=None, date_to=None)`
- `get_recent_expenses(user_id, limit=10, date_from=None, date_to=None)`
- `get_category_totals(user_id, date_from=None, date_to=None)`

One private helper is added, for example
`_expense_filter(user_id, date_from, date_to)`, which returns the `WHERE`
text and its parameters. All three helpers use it, so the range is applied
in one place.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html`
  - **Filter card**, between the header and the summary cards: a
    `.profile-card` holding a `<form method="get">` whose action is
    `url_for('profile')`.
    - Card title `Filter by date`, an `<h2 class="profile-card-title">` with
      a `calendar` icon.
    - Four preset links in one row: `This month`, `Last 3 months`,
      `Last 6 months`, `All time`. The preset that matches the range in use
      is marked with a class and `aria-current="true"`.
    - Two inputs of `type="date"`, named `date_from` and `date_to`, each with
      a visible `<label>` (`From`, `To`). They are filled with the range in
      use.
    - An `Apply` submit button.
    - A `Clear` link to `url_for('profile')`, shown only while a filter is
      in use.
    - The error message, when there is one, in `<p class="auth-error"
      role="alert">` above the inputs.
    - One line that states the range in use, with the dates passed through
      `format_date`: `01 Sep 2026 – 30 Sep 2026`, `From 01 Sep 2026` or
      `Up to 30 Sep 2026`. The day keeps its leading zero, as in the
      table. Not shown when no filter is in use.
  - **Empty state.** Two cases instead of one:
    - No filter in use and no expenses: unchanged (`No expenses yet. Add
      your first one to see it here.` and the "Add expense" link).
    - A filter in use and no expenses in the range: `No expenses in this
      period.` and a `Clear filter` link to `url_for('profile')`.
  - Nothing else changes: the header, the summary cards, the table and the
    category breakdown keep their markup and classes.

## Files to change
- `app.py`
  - A new section with a banner comment, `Date filter`, above `Routes`,
    holding two small functions:
    - `parse_filter_date(text)` — returns a `datetime.date`, or `None` when
      the text is not a real `YYYY-MM-DD` date.
    - `get_date_presets(today)` — returns the four presets as a list of
      dicts with `label`, `date_from` and `date_to` (`YYYY-MM-DD` strings,
      or `None` for "All time").
  - `profile` reads `date_from` and `date_to` from `request.args`, checks
    them, calls the three helpers with the range, and passes to the
    template: `stats`, `expenses`, `categories`, `date_from`, `date_to`,
    `filter_active`, `filter_error` and `presets`.
  - Import `date` from `datetime` next to the existing `datetime` import.
- `database/db.py` — the two optional arguments on the three helpers and
  the private `_expense_filter` helper.
- `templates/profile.html` — the changes listed under Templates.
- `static/css/profile.css` — a new `Date filter` section between `Header`
  and `Summary cards`, with rules for the filter at 600px in the existing
  media query.
- `CLAUDE.md` — update the Architecture notes: `/profile` accepts
  `date_from` and `date_to`, how a bad range is handled, the two new
  arguments on the three helpers, that the stats now cover the range in use
  instead of always every expense, and the `profile-filter-*` classes.

## Files to create
None.

## New dependencies
No new dependencies. `datetime` is in the standard library. No `dateutil`,
no date picker library and no new JavaScript: the browser's own
`<input type="date">` is the picker.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **Only the signed-in user's rows.** Every query keeps `WHERE user_id = ?`,
  and the value is always `g.user["id"]`. The date range narrows that set;
  it never replaces the `user_id` condition. Never read a user id from the
  query string.
- **Where the SQL lives.** Database access stays in `database/db.py`;
  `app.py` calls the helpers and writes no SQL. Every connection is closed
  in a `finally` block, as the existing functions do.
- **Building the `WHERE` text.** `_expense_filter` starts from
  `user_id = ?` and appends `AND date >= ?` when `date_from` is given and
  `AND date <= ?` when `date_to` is given. Only these fixed strings are
  joined; the dates themselves are always `?` parameters. Never put a date
  into the SQL with an f-string, `%` or `+`.
- **Both ends are included.** `date_from=2026-09-01&date_to=2026-09-01`
  shows the expenses of 1 September.
- **Open ranges.** `date_from` alone means that day and everything after
  it. `date_to` alone means that day and everything before it. Neither
  means no filter. An empty value (`/profile?date_from=&date_to=`, which is
  what the form sends when both inputs are empty) counts as not given and
  is not an error.
- **Comparing dates.** `expenses.date` is `YYYY-MM-DD` text, and text in
  that form sorts in date order, so `>=` and `<=` on the column are
  correct. This holds only while every stored date has that exact form;
  Step 7 must save dates the same way.
- **Checking the input.** The values come from a URL, so a `type="date"`
  input is not a guarantee. `parse_filter_date` strips the text and parses
  it with `datetime.strptime(text, "%Y-%m-%d")`; a `ValueError` means
  `None`. Do not use `date.fromisoformat`, which also accepts week dates
  such as `2026-W36-2`. The value passed to the helpers is always
  `parsed.isoformat()`, never the text from the URL, so the SQL only ever
  sees a zero-padded date.
- **Errors.** The first rule that fails decides the message, as in
  `register` and `login`:
  1. A value that is given but is not a real date: `Please enter valid
     dates.`
  2. The start date is after the end date: `The start date cannot be after
     the end date.`

  On an error the page answers 200, applies no filter (it shows all of the
  user's expenses), shows the message in the filter card and keeps what the
  user typed in the inputs. It never answers 400 or 500 for a bad date.
- **Presets.** `get_date_presets(today)` is called with `date.today()`.
  Each preset except "All time" ends today.
  - `This month` — from the first day of the current month.
  - `Last 3 months` — from the first day of the month two months before the
    current one. On 10 Oct 2026 that is 1 Aug 2026.
  - `Last 6 months` — from the first day of the month five months before
    the current one. On 10 Oct 2026 that is 1 May 2026.
  - `All time` — no parameters; the link is `url_for('profile')`.

  Work out the start month with whole-number arithmetic on
  `year * 12 + month`, so January and February give a month in the previous
  year. The presets are plain links built with
  `url_for('profile', date_from=..., date_to=...)`; they need no JavaScript.
- **Active preset.** A preset is active when the range in use equals its
  two dates. "All time" is active when no filter is in use. A custom range
  that matches no preset marks none of them.
- **`filter_active`.** `True` when at least one valid date is applied.
  `False` when no date was given and when there was an error.
- **Stats follow the range.** With a filter in use, "Total spent",
  "Transactions" and "Top category" cover the expenses in the range, and
  each category's `percent` is its share of the total in the range. The
  tie rule from Step 5 (the alphabetically first category wins) is
  unchanged.
- **The table limit stays.** The table still lists the 10 newest expenses,
  now the 10 newest in the range. The stats count every expense in the
  range, including those the table does not list.
- **Read only.** The page still only runs `SELECT` statements. The filter
  is a GET request, changes nothing on the server and needs no CSRF token.
- **Nothing is remembered.** The range is not stored in the session. After
  signing in, and after "Clear", the page shows all expenses.
- **Escaping.** The typed values are printed back into the inputs. Leave
  Jinja's autoescaping on, never use `|safe`, and keep every `value="..."`
  attribute quoted.
- **Template dates.** The line that states the range uses `format_date`.
  The template does not slice or compare date strings itself; the route
  decides `filter_active` and which preset is active.
- **CSS.** All new rules go in `static/css/profile.css`, in a `Date filter`
  section with a banner comment. New classes start with `profile-filter`.
  - Only the `:root` tokens: no literal colour values, spacing in `0.25rem`
    steps, font sizes from the 12, 14, 16, 20, 24, 32px scale.
  - Reuse `.profile-card`, `.profile-card-title`, `.btn-primary`,
    `.profile-btn` and `.form-input`. Reuse `.auth-error` for the error
    message as it is; do not copy its values into `profile.css`.
  - If `.btn-primary` lacks something a `<button>` needs (border, cursor,
    font), add it under the filter's own classes in `profile.css`.
    `style.css` is not changed in this step.
  - The active preset is `--accent` text on `--accent-light`.
  - The links, inputs and button have a visible focus style.
  - Up to 600px wide, the two inputs and the button stack in one column and
    the preset links wrap; the page gets no horizontal scrollbar.
- **Icons.** One new icon, `calendar`, beside the card title. Every control
  has a text label, so the page works when the Lucide script cannot load.
- **Markup.** Still one `<h1>`. Each date input has its own `<label for>`.
- **Not in this step:** filtering by category or by text; sorting;
  pagination or a "view all" page; totals per month or a chart; remembering
  the last range; a JavaScript date picker; add, edit and delete (Steps 7,
  8 and 9); changing the seed data; a database index on `date`. Automated
  tests are written afterwards with `/test-feature`, not as part of this
  step.

## Definition of done
Set-up for the checks below: register a new user, find its id with
`SELECT id FROM users ORDER BY id DESC LIMIT 1;`, and insert five rows for it:

```sql
INSERT INTO expenses (user_id, amount, category, date, description) VALUES
  (<id>, 100.00, 'Food',      '2026-10-05', 'October lunch'),
  (<id>, 500.00, 'Bills',     '2026-09-20', 'September bill'),
  (<id>,  50.00, 'Transport', '2026-09-01', 'September metro'),
  (<id>, 250.00, 'Shopping',  '2026-08-15', 'August shoes'),
  (<id>, 400.00, 'Health',    '2026-03-10', 'March pharmacy');
```

- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /profile?date_from=2026-09-01` redirects to `/login`.
- [ ] Signed in as the new user, `/profile` shows the filter card with four
      preset links, two date inputs and an "Apply" button. "All time" is
      marked active, there is no "Clear" link, and the summary cards read
      `₹1,300.00`, `5` and `Bills`.
- [ ] Choosing 1 Sep 2026 and 30 Sep 2026 and pressing "Apply" opens
      `/profile?date_from=2026-09-01&date_to=2026-09-30`. The cards read
      `₹550.00`, `2` and `Bills`; the table has 2 rows (`September bill`,
      then `September metro`); the breakdown lists Bills (`₹500.00`, 91%)
      and Transport (`₹50.00`, 9%).
- [ ] On that page both inputs still show the chosen dates, a line reads
      `01 Sep 2026 – 30 Sep 2026`, a "Clear" link is shown and no preset is
      marked active.
- [ ] Refreshing that page, or opening its URL in a new tab, shows the same
      filtered figures.
- [ ] "Clear" opens `/profile` and the cards read `₹1,300.00`, `5` and
      `Bills` again.
- [ ] `/profile?date_from=2026-09-01` (no end date) reads `₹650.00`, `3` and
      `Bills`, with the line `From 01 Sep 2026`.
- [ ] `/profile?date_to=2026-08-31` (no start date) reads `₹650.00`, `2` and
      `Health`, with the line `Up to 31 Aug 2026`.
- [ ] `/profile?date_from=2026-09-01&date_to=2026-09-01` reads `₹50.00`, `1`
      and `Transport`: both ends are included.
- [ ] `/profile?date_from=2027-01-01` reads `₹0.00`, `0` and `—`, shows
      `No expenses in this period.` with a "Clear filter" link, and shows no
      category breakdown and no error page.
- [ ] `/profile?date_from=&date_to=` shows all 5 expenses and no error
      message.
- [ ] `/profile?date_from=2026-09-30&date_to=2026-09-01` shows
      `The start date cannot be after the end date.`, answers 200 and shows
      all 5 expenses.
- [ ] `/profile?date_from=2026-13-45` and `/profile?date_from=abc` each show
      `Please enter valid dates.`, answer 200 and show all 5 expenses.
- [ ] `/profile?date_from=2026-09-01' OR '1'='1` shows
      `Please enter valid dates.`; it does not raise an error and does not
      change which rows are shown.
- [ ] `/profile?date_from="><script>alert(1)</script>` shows no alert, and
      the page source shows the value escaped.
- [ ] The "This month" link points to `date_from` = the first day of the
      current month and `date_to` = today. Checked in October 2026 it reads
      `₹100.00`, `1` and `Food`, and "This month" is marked active.
- [ ] Checked in October 2026, "Last 3 months" starts at `2026-08-01` and
      reads `₹900.00`, `4` and `Bills`; "Last 6 months" starts at
      `2026-05-01` and reads the same, because the March expense is outside
      it.
- [ ] In a Python shell, `get_date_presets(date(2027, 1, 15))` gives
      `2026-11-01` as the start of "Last 3 months" and `2026-08-01` as the
      start of "Last 6 months".
- [ ] Signed in as `demo@spendly.com` / `demo123`,
      `/profile?date_from=2026-03-01&date_to=2026-03-31` shows
      `No expenses in this period.`: the new user's March expense is not
      shown to another user.
- [ ] With 11 or more expenses in one range for one user, the table shows
      the 10 newest of them, while "Transactions" and "Total spent" count
      all of them.
- [ ] Signing out and in again opens `/profile` with no filter in use.
- [ ] `grep -n "execute" app.py` finds nothing: all SQL is in
      `database/db.py`.
- [ ] In `database/db.py`, no query text contains a date value: the dates
      appear only in the parameter tuples.
- [ ] `grep '#' static/css/profile.css` finds no hex colour values.
- [ ] `git diff main -- static/css/style.css` is empty.
- [ ] At a window width of 500px the inputs and the button are stacked and
      the page has no horizontal scrollbar.
- [ ] The filter can be used with the keyboard alone: Tab reaches every
      preset, both inputs, "Apply" and "Clear", each with a visible focus
      style.
- [ ] The calendar icon shows beside "Filter by date", and inspecting the
      loaded page finds no `<i data-lucide>` element left.
- [ ] With `unpkg.com` blocked, the filter still shows every label and
      still works.
- [ ] "Add expense" still opens `/expenses/add`, which still shows its
      placeholder text.
- [ ] `/`, `/login`, `/register`, `/terms` and `/privacy` look as before,
      with no error in the browser console.
