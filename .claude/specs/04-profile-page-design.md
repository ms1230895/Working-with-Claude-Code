# Spec: Profile Page Design

## Overview
Build the page a signed-in user lands on. Today `/profile` returns the plain
string `Profile page — coming in Step 4`, and a successful sign-in sends the
user back to the landing page because there is nowhere better to go. This step
replaces the placeholder with a real template: a header with the user's name,
email and join date, three summary figures, a table of recent expenses and a
spending breakdown by category. It is a design step. The account details come
from `g.user`, which Step 3 already loads on every request, but the figures,
the expense rows and the category totals are fixed sample values written in the
route. Step 5 replaces those sample values with queries on the `expenses`
table, without changing the template. Doing the layout first means the queries
in Step 5 have a finished page to fill, and the page can be reviewed on its own.

## Depends on
- Step 1 — Database Setup: the `users` table, whose `name`, `email` and
  `created_at` columns the page shows.
- Step 3 — Login and Logout: `g.user`, `login_required`, the navbar link to
  `url_for('profile')`, and the note in that spec that the sign-in redirect
  moves to the profile page in this step.

## Routes
- `GET /profile` — show the profile page — logged-in (already exists as a
  placeholder; the `profile` endpoint name stays)
- `POST /login` — unchanged, except a successful sign-in now redirects to
  `/profile` instead of `/` — public (already exists)

No new routes.

A signed-in user who opens `GET /login` or `GET /register` is still redirected
to `/`. Only the redirect after a successful sign-in changes.

## Database changes
No database changes, and no new helper functions in `database/db.py`.

The account details come from `g.user`, which is the full `users` row
(`id`, `name`, `email`, `password_hash`, `created_at`). The route runs no
query of its own in this step.

## Templates
- **Create:** `templates/profile.html`
  - Extends `base.html`. Title block: `Profile — Spendly`. Loads
    `static/css/profile.css` through the `head` block.
  - **Header:** a card holding a round avatar showing the first letter of the
    user's name in upper case, the name as the page's only `<h1>`, the email,
    and `Member since <Month YYYY>` (for example `Member since October 2026`).
    An "Add expense" link styled with `.btn-primary`, with a plus icon,
    pointing to `url_for('add_expense')`.
  - **Sample data note:** one short line under the header saying the figures
    below are sample data. Step 5 removes it.
  - **Summary:** three cards — "Total spent", "Transactions", "Top category" —
    each with one icon.
  - **Recent expenses:** a `<table>` with the columns Date, Description,
    Category, Amount, newest first. The category is shown as a pill. When
    the list is empty, show an empty
    state in place of the table: a short message and the same "Add expense"
    link.
  - **By category:** one row per category with its name, its total, its share
    as a whole-number percentage, and a horizontal bar whose width is that
    percentage. Largest first. Hidden when the expense list is empty.
- **Modify:** `templates/base.html` — one `<script>` tag that loads Lucide
  icons, above the `main.js` tag. The navbar is not changed; it already
  links the user's name to `url_for('profile')`.
- **Modify:** `templates/privacy.html` — one sentence in "Third Party
  Services" naming the icon CDN.

## Files to change
- `app.py`
  - Replace the body of `profile` with `render_template("profile.html", ...)`,
    passing `stats`, `expenses` and `categories`. Move the view out of the
    "Placeholder routes" section, above its banner comment.
  - Add two Jinja filters with `@app.template_filter`, in their own section
    with a banner comment: `format_money` and `format_date`.
  - In `login`, change the redirect after a successful sign-in from
    `url_for('landing')` to `url_for('profile')`.
- `templates/base.html` — the Lucide script tag.
- `static/js/main.js` — one guarded `lucide.createIcons()` call.
- `static/css/style.css` — one new token on `:root`, `--shadow-card`.
- `templates/privacy.html` — one sentence about the icon CDN.
- `CLAUDE.md` — update the Architecture notes: `/profile` renders a template
  with sample data, sign-in redirects to `/profile`, the two template
  filters, `profile.css` as a second page-specific stylesheet, and Lucide
  as the one third-party script. The
  example placeholder string in "What this is" names the profile page; change
  it to one that still exists (for example
  `"Add expense — coming in Step 7"`).

## Files to create
- `templates/profile.html`
- `static/css/profile.css`

## New dependencies
No new pip packages. One front-end library, loaded as a script tag and not
installed: Lucide icons 1.54.0 from `unpkg.com` (ISC licence). No charting
library: the category bars are plain elements with a width.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- **No SQL in this step.** `app.py` writes no SQL and `database/db.py` is
  not touched. Reading real expenses is Step 5.
- **Never show `password_hash`.** The template reads only `name`, `email`
  and `created_at` from `g.user`. Do not pass the user row to the template
  under another name; `g` is already available in every template.
- **Escaping.** The name and email are typed by the user. Leave Jinja's
  autoescaping on and never use `|safe` on them.
- **Shape of the sample data.** Use the shape Step 5 will produce, so the
  template does not change when the real queries arrive:
  - `stats` — a dict with `total_spent` (float), `transaction_count` (int)
    and `top_category` (str).
  - `expenses` — a list of dicts with the keys `date`, `description`,
    `category` and `amount`, the same names as the `expenses` columns.
    `date` is a `YYYY-MM-DD` string, as the database stores it. Newest first.
  - `categories` — a list of dicts with `name`, `total` (float) and `percent`
    (int, 0 to 100). Largest total first.
- **Values of the sample data.** Use the eight expenses that `seed_db()`
  inserts, with fixed dates, so the page looks the same for the demo user
  after Step 5:

  | date       | description         | category      | amount  |
  |------------|---------------------|---------------|---------|
  | 2026-09-24 | Gift wrap and card  | Other         | 150.00  |
  | 2026-09-19 | Lunch with friends  | Food          | 180.00  |
  | 2026-09-15 | Headphones          | Shopping      | 999.99  |
  | 2026-09-12 | Movie tickets       | Entertainment | 300.00  |
  | 2026-09-08 | Pharmacy            | Health        | 450.00  |
  | 2026-09-05 | Metro card recharge | Transport     | 80.00   |
  | 2026-09-03 | Groceries           | Food          | 250.50  |
  | 2026-09-01 | Electricity bill    | Bills         | 1200.00 |

  `stats`: total spent `3610.49`, 8 transactions, top category `Bills`.

  `categories`: Bills 1200.00 (33), Shopping 999.99 (28), Health 450.00 (12),
  Food 430.50 (12), Entertainment 300.00 (8), Other 150.00 (4),
  Transport 80.00 (2). The percentages are rounded, so they add up to 99.
- The sample values are literals in the `profile` view, under a comment that
  says Step 5 replaces them. Do not compute the totals from the list in
  Python; Step 5 gets them from SQL.
- **`format_money`.** Turns a number into `₹` plus the amount with thousands
  separators and two decimals: `3610.49` becomes `₹3,610.49`. Every amount
  on the page goes through it. Indian digit grouping (`1,00,000`) is out of
  scope.
- **`format_date`.** Takes the text SQLite stores, either `YYYY-MM-DD` or
  `YYYY-MM-DD HH:MM:SS`, and an optional `strftime` format. The default
  gives `24 Sep 2026`. "Member since" calls it with `'%B %Y'`. The template
  never slices date strings itself.
- **Avatar.** The first character of `g.user['name']`, upper-cased.
  Registration already refuses an empty name. No image upload and no
  external avatar service.
- **CSS.** All new rules go in `static/css/profile.css`, loaded after
  `style.css` through the `head` block, as `landing.css` is. The one
  exception is the `--shadow-card` token, which goes on `:root` in
  `style.css`. Prefix the
  classes with `profile-`. Follow the banner-comment layout of `style.css`.
  - Use the tokens on `:root` for every colour, font, radius and width:
    cards on `--paper-card` with `--border` and `--radius-md`, headings in
    `--font-display`, secondary text in `--ink-muted`, bars in `--accent` on
    a `--border-soft` track, the avatar in `--accent` on `--accent-light`.
  - Every bar is the same colour. Do not copy the literal hex values that
    `.mock-bar-3`, `.mock-bar-4` and `.auth-error` carry in `style.css`.
  - The page content is capped at `--max-width` with `2rem` side padding,
    so its edges line up with the navbar.
  - The global reset removes all margin and padding; give every new element
    its spacing explicitly.
  - Reuse `.btn-primary` for "Add expense". Do not reuse the stale
    `.hero-visual` and `.mock-*` rules, and do not delete them in this step.
- **Inline styles.** The only inline style allowed is the width of a
  category bar (`style="width: {{ category.percent }}%"`), because it is
  data. Colours and sizes stay in the stylesheet.
- **Markup.** One `<h1>`; section headings are `<h2>`. The expense list is a
  real `<table>` with `<thead>` and `<th scope="col">`. The Amount column is
  right-aligned.
- **Responsive.** Up to 900px wide, the expense table and the category
  breakdown stack in one column. Up to 600px, the three summary cards stack
  too, and the table scrolls sideways inside its own wrapper instead of
  widening the page. The media queries live in `profile.css`.
- **Not in this step:** edit and delete controls on the rows (Steps 8 and
  9), date filters, pagination, editing the name or email, changing the
  password, and a navbar link to the profile at widths under 600px (the
  name link is hidden there today).
- **Icons.** Lucide, as the `spendly-ui-designer` skill asks. Load version
  1.54.0 from `unpkg.com` in `base.html`, pinned (never `@latest`), with an
  `integrity` hash and `crossorigin="anonymous"`. `static/js/main.js` calls
  `lucide.createIcons()` once, and only when `window.lucide` exists, so
  every page still works when the CDN cannot be reached. In a template an
  icon is `<i data-lucide="name">`. Every icon sits next to visible text;
  none carries meaning alone. At most one icon per button, per card title
  and per stat card. This is the one exception to the project's "no
  third-party libraries" rule; no other JavaScript is added in this step.
- **Design language**, from the `spendly-ui-designer` skill. Where the skill
  and the existing `style.css` differ, the existing tokens and fonts win, as
  the skill itself says:
  - Spacing: every padding, margin and gap in `profile.css` is a multiple
    of 4px (`0.25rem` steps).
  - Type sizes: only 12, 14, 16, 20, 24 and 32px.
  - Amounts use `font-variant-numeric: tabular-nums`.
  - Table rows have a hover state.
  - One accent colour, `--accent`. Amounts are not coloured red.
  - Shadow: only `--shadow-card`. `profile.css` still holds no literal
    colour value.

## Definition of done
- [ ] `python app.py` starts without errors.
- [ ] Signed out, `GET /profile` redirects to `/login`.
- [ ] Signing in as `demo@spendly.com` / `demo123` lands on `/profile`, not
      on `/`.
- [ ] The page shows "Demo User", `demo@spendly.com`, the avatar letter "D"
      and a `Member since <Month YYYY>` line that matches the `created_at`
      of the demo user's row.
- [ ] A newly registered user who signs in sees their own name, email and
      avatar letter, with the same sample figures below.
- [ ] Registering with the name `<b>Test</b>` shows those characters as
      text on the profile page and in the navbar, not as bold text.
- [ ] The summary cards read `₹3,610.49`, `8` and `Bills`.
- [ ] The table has 8 rows, newest first, the first being
      `24 Sep 2026 · Gift wrap and card · Other · ₹150.00`.
- [ ] The category breakdown lists 7 categories from Bills (`₹1,200.00`,
      33%) down to Transport (`₹80.00`, 2%), and the Bills bar is the
      longest.
- [ ] A line on the page says the figures are sample data.
- [ ] "Add expense" opens `/expenses/add`, which still shows its
      placeholder text.
- [ ] Clicking the name in the navbar opens `/profile` from any page.
- [ ] With the `expenses` list in the view temporarily set to `[]`, the
      table is replaced by the empty state and the category breakdown is
      gone. Restore the list afterwards.
- [ ] The page source contains no `scrypt:` or `pbkdf2:` text.
- [ ] `grep '#' static/css/profile.css` finds no hex colour values.
- [ ] At a window width of 800px the table and the breakdown are stacked;
      at 500px the summary cards are stacked too and the page itself has no
      horizontal scrollbar.
- [ ] Signed in on `/profile`, every icon shows: a plus on "Add expense",
      one in the sample data note, one in each summary card and one beside
      each card title. Inspecting the loaded page finds no `<i data-lucide>`
      element left.
- [ ] With `unpkg.com` blocked (dev tools, network request blocking), the
      page still shows every button label, heading and figure.
- [ ] Hovering a table row changes its background.
- [ ] Signed in, visiting `/login` or `/register` still redirects to `/`.
- [ ] `/`, `/login`, `/register`, `/terms` and `/privacy` look as before,
      with no error in the browser console.
