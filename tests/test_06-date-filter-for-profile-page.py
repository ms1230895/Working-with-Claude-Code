"""Tests for Step 6: Date Filter for Profile Page.

Based on .claude/specs/06-date-filter-for-profile-page.md.

Test plan
---------
* parse_filter_date(): real dates, stripping, and every kind of non-date text
  (including week dates and SQL / HTML payloads) returning None.
* get_date_presets(today): fixed "today" values, year boundaries, month ends.
* Database helpers: date_from / date_to on get_expense_stats,
  get_recent_expenses and get_category_totals (inclusive ends, open ranges,
  empty ranges, tie rule, row limit, user isolation, injection safety,
  read-only behaviour).
* GET /profile: auth guard, filter card markup, filtered figures, empty
  states, validation errors, escaping, presets and the active preset,
  user isolation, nothing remembered, nothing written.

Safety: database.db.DB_PATH is pointed at a throwaway file before app.py is
imported (importing it runs init_db() and seed_db()) and again, per test, at a
fresh file under tmp_path. The developer's expense_tracker.db is never opened.
"""
import atexit
import re
import shutil
import sys
import tempfile
from collections import namedtuple
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from flask import url_for

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database.db as db_module  # noqa: E402

# app.py calls init_db() and seed_db() when it is imported. Point the database
# at a throwaway directory first, so the real expense_tracker.db is untouched.
_IMPORT_TMP = tempfile.mkdtemp(prefix="spendly-import-")
atexit.register(shutil.rmtree, _IMPORT_TMP, ignore_errors=True)
db_module.DB_PATH = Path(_IMPORT_TMP) / "import_time.db"

import app as app_module  # noqa: E402

# The real function, kept before any test replaces it with a fixed-date wrapper
_REAL_GET_DATE_PRESETS = app_module.get_date_presets

PASSWORD = "password123"
EN_DASH = "–"
EM_DASH = "—"
FROZEN_TODAY = date(2026, 10, 10)
PRESET_LABELS = ["This month", "Last 3 months", "Last 6 months", "All time"]

# (amount, category, date, description) - the five rows from the spec's
# "Definition of done"
SPEC_ROWS = [
    (100.00, "Food", "2026-10-05", "October lunch"),
    (500.00, "Bills", "2026-09-20", "September bill"),
    (50.00, "Transport", "2026-09-01", "September metro"),
    (250.00, "Shopping", "2026-08-15", "August shoes"),
    (400.00, "Health", "2026-03-10", "March pharmacy"),
]
ALL_DESCRIPTIONS = [
    "October lunch",
    "September bill",
    "September metro",
    "August shoes",
    "March pharmacy",
]

BOB_ROWS = [
    (7777.00, "Entertainment", "2026-09-10", "Bob concert"),
    (333.00, "Other", "2026-03-15", "Bob March gig"),
    (999.00, "Food", "2026-10-02", "Bob October treat"),
]


# --------------------------------------------------------------------------- #
# Expected figures for the spec's five-row data set                           #
# --------------------------------------------------------------------------- #

RangeCase = namedtuple(
    "RangeCase", "date_from date_to total count top descriptions line"
)

FILTERED_RANGES = [
    pytest.param(
        RangeCase("2026-09-01", "2026-09-30", 550.0, 2, "Bills",
                  ["September bill", "September metro"],
                  f"01 Sep 2026 {EN_DASH} 30 Sep 2026"),
        id="september",
    ),
    pytest.param(
        RangeCase("2026-09-01", None, 650.0, 3, "Bills",
                  ["October lunch", "September bill", "September metro"],
                  "From 01 Sep 2026"),
        id="from-only",
    ),
    pytest.param(
        RangeCase(None, "2026-08-31", 650.0, 2, "Health",
                  ["August shoes", "March pharmacy"],
                  "Up to 31 Aug 2026"),
        id="to-only",
    ),
    pytest.param(
        RangeCase("2026-09-01", "2026-09-01", 50.0, 1, "Transport",
                  ["September metro"],
                  f"01 Sep 2026 {EN_DASH} 01 Sep 2026"),
        id="single-day-both-ends-included",
    ),
    pytest.param(
        RangeCase("2026-09-20", "2026-10-05", 600.0, 2, "Bills",
                  ["October lunch", "September bill"],
                  f"20 Sep 2026 {EN_DASH} 05 Oct 2026"),
        id="boundaries-on-expense-dates",
    ),
    pytest.param(
        RangeCase("2026-10-01", "2026-10-10", 100.0, 1, "Food",
                  ["October lunch"],
                  f"01 Oct 2026 {EN_DASH} 10 Oct 2026"),
        id="this-month-range",
    ),
    pytest.param(
        RangeCase("2026-08-01", "2026-10-10", 900.0, 4, "Bills",
                  ["October lunch", "September bill", "September metro",
                   "August shoes"],
                  f"01 Aug 2026 {EN_DASH} 10 Oct 2026"),
        id="last-3-months-range",
    ),
    pytest.param(
        RangeCase("2026-05-01", "2026-10-10", 900.0, 4, "Bills",
                  ["October lunch", "September bill", "September metro",
                   "August shoes"],
                  f"01 May 2026 {EN_DASH} 10 Oct 2026"),
        id="last-6-months-range",
    ),
    pytest.param(
        RangeCase("2026-03-10", "2026-03-10", 400.0, 1, "Health",
                  ["March pharmacy"],
                  f"10 Mar 2026 {EN_DASH} 10 Mar 2026"),
        id="single-day-oldest-expense",
    ),
]

EMPTY_RANGES = [
    pytest.param(
        RangeCase("2027-01-01", None, 0.0, 0, None, [], "From 01 Jan 2027"),
        id="from-in-the-future",
    ),
    pytest.param(
        RangeCase(None, "2026-01-01", 0.0, 0, None, [], "Up to 01 Jan 2026"),
        id="to-before-first-expense",
    ),
    pytest.param(
        RangeCase("2026-04-01", "2026-07-31", 0.0, 0, None, [],
                  f"01 Apr 2026 {EN_DASH} 31 Jul 2026"),
        id="gap-between-expenses",
    ),
]


# --------------------------------------------------------------------------- #
# A tiny HTML tree, so tests read the page by structure and not by raw text   #
# --------------------------------------------------------------------------- #

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}
        self.parent = parent
        self.children = []

    def classes(self):
        return self.attrs.get("class", "").split()

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def find_all(self, tag=None, cls=None, attrs=None):
        found = []
        for node in self.descendants():
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes():
                continue
            if attrs and any(node.attrs.get(k) != v for k, v in attrs.items()):
                continue
            found.append(node)
        return found

    def tokens(self):
        # Visible text pieces in document order, whitespace collapsed
        out = []

        def walk(node):
            for child in node.children:
                if isinstance(child, str):
                    piece = " ".join(child.split())
                    if piece:
                        out.append(piece)
                elif child.tag not in ("script", "style"):
                    walk(child)

        walk(self)
        return out

    def text(self):
        return " ".join(self.tokens())


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]", [], None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in _VOID_TAGS:
            self.current = node

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def parse_page(response):
    builder = _TreeBuilder()
    builder.feed(response.get_data(as_text=True))
    builder.close()
    return builder.root


def ancestor(node, tag=None, cls=None):
    current = node.parent
    while current is not None:
        if (tag is None or current.tag == tag) and (
            cls is None or cls in current.classes()
        ):
            return current
        current = current.parent
    return None


# --------------------------------------------------------------------------- #
# Page readers                                                                #
# --------------------------------------------------------------------------- #

def filter_card(page):
    for heading in page.find_all("h2", cls="profile-card-title"):
        if heading.text() == "Filter by date":
            return ancestor(heading, cls="profile-card")
    return None


def preset_links(page):
    return [a for a in page.find_all("a") if a.text() in PRESET_LABELS]


def preset_link(page, label):
    matches = [a for a in preset_links(page) if a.text() == label]
    assert len(matches) == 1, f"Expected exactly one '{label}' link, got {len(matches)}"
    return matches[0]


def active_preset_labels(page):
    return [a.text() for a in preset_links(page)
            if a.attrs.get("aria-current") == "true"]


def date_input(page, name):
    inputs = page.find_all("input", attrs={"name": name})
    assert len(inputs) == 1, f"Expected exactly one input named {name}, got {len(inputs)}"
    return inputs[0]


def filter_form(page):
    form = ancestor(date_input(page, "date_from"), tag="form")
    assert form is not None, "date_from input is not inside a <form>"
    return form


def clear_links(page):
    return [a for a in page.find_all("a") if a.text() == "Clear"]


def error_alerts(page):
    return page.find_all("p", cls="auth-error")


def stat_value(page, label):
    tokens = page.tokens()
    assert label in tokens, f"Summary label '{label}' not found on the page"
    return tokens[tokens.index(label) + 1]


def summary(page):
    return (
        stat_value(page, "Total spent"),
        stat_value(page, "Transactions"),
        stat_value(page, "Top category"),
    )


def expense_rows(page):
    rows = []
    for tr in page.find_all("tr"):
        cells = [td.text() for td in tr.find_all("td")]
        if cells:
            rows.append(cells)
    return rows


def row_descriptions(page):
    return [row[1] for row in expense_rows(page)]


def money(amount):
    return f"₹{amount:,.2f}"


RANGE_LINE_PATTERNS = [
    re.compile(r"\d{2} [A-Z][a-z]{2} \d{4} " + EN_DASH + r" \d{2} [A-Z][a-z]{2} \d{4}"),
    re.compile(r"From \d{2} [A-Z][a-z]{2} \d{4}"),
    re.compile(r"Up to \d{2} [A-Z][a-z]{2} \d{4}"),
]


def has_range_line(page):
    text = page.text()
    return any(p.search(text) for p in RANGE_LINE_PATTERNS)


# --------------------------------------------------------------------------- #
# Fixtures and helpers                                                        #
# --------------------------------------------------------------------------- #

@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    """A new SQLite file with the tables and no rows, used by every test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "spendly_test.db")
    db_module.init_db()
    return db_module.DB_PATH


# Not named "app" on purpose: pytest-flask pushes a request context for any
# test that uses a fixture called "app", which would share `g` between requests.
@pytest.fixture
def spendly_app(empty_db):
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return app_module.app


@pytest.fixture
def client(spendly_app):
    return spendly_app.test_client()


@pytest.fixture
def frozen_today(monkeypatch):
    """The route builds its presets for 10 Oct 2026, whatever the real date is."""
    freeze_presets(monkeypatch, FROZEN_TODAY)
    return FROZEN_TODAY


def freeze_presets(monkeypatch, today):
    monkeypatch.setattr(
        app_module,
        "get_date_presets",
        lambda _ignored: _REAL_GET_DATE_PRESETS(today),
    )


def url(endpoint, **values):
    with app_module.app.test_request_context():
        return url_for(endpoint, **values)


def insert_expenses(user_id, rows):
    conn = db_module.get_db()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO expenses (user_id, amount, category, date, description)"
                " VALUES (?, ?, ?, ?, ?)",
                [(user_id, amount, category, day, desc)
                 for amount, category, day, desc in rows],
            )
    finally:
        conn.close()


def make_user(name, email, rows=()):
    user_id = db_module.create_user(name, email, PASSWORD)
    insert_expenses(user_id, rows)
    return {"id": user_id, "name": name, "email": email, "password": PASSWORD}


def sign_in(test_client, user):
    response = test_client.post(
        url("login"), data={"email": user["email"], "password": user["password"]}
    )
    assert response.status_code == 302, "Sign-in should redirect"
    assert urlparse(response.headers["Location"]).path == url("profile")
    return test_client


def get_profile(test_client, **params):
    return test_client.get(url("profile"), query_string=params)


def snapshot_db():
    conn = db_module.get_db()
    try:
        users = [tuple(r) for r in conn.execute(
            "SELECT id, name, email, password_hash FROM users ORDER BY id")]
        expenses = [tuple(r) for r in conn.execute(
            "SELECT * FROM expenses ORDER BY id")]
    finally:
        conn.close()
    return users, expenses


@pytest.fixture
def alice(empty_db):
    return make_user("Alice Tester", "alice@example.com", SPEC_ROWS)


@pytest.fixture
def bob(empty_db):
    return make_user("Bob Other", "bob@example.com", BOB_ROWS)


@pytest.fixture
def auth_client(client, alice):
    """A test client signed in as Alice, who owns the spec's five expenses."""
    return sign_in(client, alice)


@pytest.fixture
def profile_page(auth_client):
    response = get_profile(auth_client)
    assert response.status_code == 200
    return parse_page(response)


@pytest.fixture
def carol(empty_db):
    """Twelve September expenses (and two outside September) for one user."""
    rows = [
        (10.0 * day, "Food", f"2026-09-{day:02d}", f"entry-{day:02d}")
        for day in range(1, 13)
    ]
    rows.append((1000.0, "Bills", "2026-08-31", "outside-before"))
    rows.append((2000.0, "Bills", "2026-10-01", "outside-after"))
    return make_user("Carol Many", "carol@example.com", rows)


# --------------------------------------------------------------------------- #
# parse_filter_date                                                           #
# --------------------------------------------------------------------------- #

class TestParseFilterDate:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("2026-09-01", date(2026, 9, 1)),
            ("2026-12-31", date(2026, 12, 31)),
            ("2024-02-29", date(2024, 2, 29)),
            ("  2026-09-30  ", date(2026, 9, 30)),
            ("1999-01-05", date(1999, 1, 5)),
        ],
    )
    def test_parse_filter_date_real_date_returns_date(self, text, expected):
        result = app_module.parse_filter_date(text)
        assert result == expected, f"{text!r} should parse to {expected}"
        assert isinstance(result, date) and not isinstance(result, datetime), (
            "Expected a datetime.date, not a datetime"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "abc",
            "2026-13-45",
            "2026-00-10",
            "2026-09-31",
            "2026-02-30",
            "2025-02-29",
            "2026-W36-2",
            "2026-W36",
            "20260901",
            "2026/09/01",
            "09-01-2026",
            "2026-09-01T00:00:00",
            "2026-09-01' OR '1'='1",
            '"><script>alert(1)</script>',
        ],
    )
    def test_parse_filter_date_not_a_real_date_returns_none(self, text):
        assert app_module.parse_filter_date(text) is None, (
            f"{text!r} is not a real YYYY-MM-DD date and should give None"
        )


# --------------------------------------------------------------------------- #
# get_date_presets                                                            #
# --------------------------------------------------------------------------- #

class TestGetDatePresets:
    def test_get_date_presets_returns_four_presets_in_order(self):
        presets = _REAL_GET_DATE_PRESETS(date(2026, 10, 10))
        assert [p["label"] for p in presets] == PRESET_LABELS
        for preset in presets:
            assert {"label", "date_from", "date_to"} <= set(preset), (
                f"Preset is missing keys: {preset}"
            )

    def test_get_date_presets_all_time_has_no_dates(self):
        all_time = _REAL_GET_DATE_PRESETS(date(2026, 10, 10))[-1]
        assert all_time["label"] == "All time"
        assert all_time["date_from"] is None
        assert all_time["date_to"] is None

    @pytest.mark.parametrize(
        "today, this_month, last_3, last_6",
        [
            pytest.param(date(2026, 10, 10), "2026-10-01", "2026-08-01", "2026-05-01",
                         id="spec-example-oct-2026"),
            pytest.param(date(2027, 1, 15), "2027-01-01", "2026-11-01", "2026-08-01",
                         id="spec-example-jan-2027"),
            pytest.param(date(2027, 2, 28), "2027-02-01", "2026-12-01", "2026-09-01",
                         id="february"),
            pytest.param(date(2026, 12, 31), "2026-12-01", "2026-10-01", "2026-07-01",
                         id="december-last-day"),
            pytest.param(date(2026, 6, 30), "2026-06-01", "2026-04-01", "2026-01-01",
                         id="six-months-lands-on-january"),
            pytest.param(date(2026, 7, 1), "2026-07-01", "2026-05-01", "2026-02-01",
                         id="first-of-month"),
            pytest.param(date(2026, 1, 1), "2026-01-01", "2025-11-01", "2025-08-01",
                         id="first-of-january"),
            pytest.param(date(2026, 5, 31), "2026-05-01", "2026-03-01", "2025-12-01",
                         id="31st-with-shorter-months-before"),
            pytest.param(date(2024, 3, 31), "2024-03-01", "2024-01-01", "2023-10-01",
                         id="leap-year"),
            pytest.param(date(2026, 2, 15), "2026-02-01", "2025-12-01", "2025-09-01",
                         id="mid-february"),
        ],
    )
    def test_get_date_presets_start_dates_and_end_today(
        self, today, this_month, last_3, last_6
    ):
        by_label = {p["label"]: p for p in _REAL_GET_DATE_PRESETS(today)}
        assert by_label["This month"]["date_from"] == this_month
        assert by_label["Last 3 months"]["date_from"] == last_3
        assert by_label["Last 6 months"]["date_from"] == last_6
        for label in ("This month", "Last 3 months", "Last 6 months"):
            assert by_label[label]["date_to"] == today.isoformat(), (
                f"'{label}' should end today ({today.isoformat()})"
            )

    def test_get_date_presets_dates_are_zero_padded_iso_strings(self):
        for preset in _REAL_GET_DATE_PRESETS(date(2026, 3, 5)):
            for key in ("date_from", "date_to"):
                value = preset[key]
                if value is None:
                    continue
                assert isinstance(value, str)
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), (
                    f"{key} of '{preset['label']}' is not YYYY-MM-DD: {value!r}"
                )


# --------------------------------------------------------------------------- #
# Database helpers                                                            #
# --------------------------------------------------------------------------- #

class TestExpenseStatsHelper:
    def test_get_expense_stats_without_range_covers_every_expense(self, alice):
        stats = db_module.get_expense_stats(alice["id"])
        assert stats["total_spent"] == pytest.approx(1300.0)
        assert stats["transaction_count"] == 5
        assert stats["top_category"] == "Bills"

    def test_get_expense_stats_none_range_equals_no_range(self, alice):
        plain = db_module.get_expense_stats(alice["id"])
        explicit = db_module.get_expense_stats(
            alice["id"], date_from=None, date_to=None
        )
        assert plain == explicit

    @pytest.mark.parametrize("case", FILTERED_RANGES + EMPTY_RANGES)
    def test_get_expense_stats_range_counts_only_expenses_in_range(self, alice, case):
        stats = db_module.get_expense_stats(
            alice["id"], date_from=case.date_from, date_to=case.date_to
        )
        assert stats["total_spent"] == pytest.approx(case.total)
        assert stats["transaction_count"] == case.count
        assert stats["top_category"] == case.top

    def test_get_expense_stats_empty_range_gives_zero_total_and_no_category(
        self, alice
    ):
        stats = db_module.get_expense_stats(alice["id"], date_from="2027-01-01")
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert stats["top_category"] is None

    def test_get_expense_stats_range_ties_pick_alphabetically_first_category(
        self, empty_db
    ):
        user = make_user("Tie Breaker", "tie@example.com", [
            (100.0, "Transport", "2026-09-05", "tie one"),
            (100.0, "Food", "2026-09-06", "tie two"),
            (900.0, "Bills", "2026-01-05", "outside the range"),
        ])
        in_range = db_module.get_expense_stats(
            user["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert in_range["top_category"] == "Food", (
            "Food and Transport tie inside the range; the alphabetically "
            "first category should win and the larger outside row is ignored"
        )
        everything = db_module.get_expense_stats(user["id"])
        assert everything["top_category"] == "Bills"


class TestRecentExpensesHelper:
    def test_get_recent_expenses_without_range_lists_all_newest_first(self, alice):
        rows = db_module.get_recent_expenses(alice["id"])
        assert [r["description"] for r in rows] == ALL_DESCRIPTIONS

    @pytest.mark.parametrize("case", FILTERED_RANGES + EMPTY_RANGES)
    def test_get_recent_expenses_range_lists_only_rows_in_range(self, alice, case):
        rows = db_module.get_recent_expenses(
            alice["id"], date_from=case.date_from, date_to=case.date_to
        )
        assert [r["description"] for r in rows] == case.descriptions

    def test_get_recent_expenses_rows_have_expense_columns(self, alice):
        row = db_module.get_recent_expenses(
            alice["id"], date_from="2026-09-20", date_to="2026-09-20"
        )[0]
        assert row["date"] == "2026-09-20"
        assert row["description"] == "September bill"
        assert row["category"] == "Bills"
        assert row["amount"] == pytest.approx(500.0)

    def test_get_recent_expenses_default_limit_is_ten_newest_in_range(self, carol):
        rows = db_module.get_recent_expenses(
            carol["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert [r["description"] for r in rows] == [
            f"entry-{day:02d}" for day in range(12, 2, -1)
        ]

    def test_get_recent_expenses_explicit_limit_applies_inside_range(self, carol):
        rows = db_module.get_recent_expenses(
            carol["id"], limit=3, date_from="2026-09-01", date_to="2026-09-30"
        )
        assert [r["description"] for r in rows] == [
            "entry-12", "entry-11", "entry-10"
        ]

    def test_get_recent_expenses_same_date_newest_id_first(self, empty_db):
        user = make_user("Same Day", "sameday@example.com", [
            (10.0, "Food", "2026-09-05", "first saved"),
            (20.0, "Food", "2026-09-05", "second saved"),
        ])
        rows = db_module.get_recent_expenses(
            user["id"], date_from="2026-09-05", date_to="2026-09-05"
        )
        assert [r["description"] for r in rows] == ["second saved", "first saved"]


class TestCategoryTotalsHelper:
    def test_get_category_totals_without_range_lists_every_category(self, alice):
        totals = db_module.get_category_totals(alice["id"])
        assert [t["name"] for t in totals] == [
            "Bills", "Health", "Shopping", "Food", "Transport"
        ]
        assert [t["total"] for t in totals] == pytest.approx(
            [500.0, 400.0, 250.0, 100.0, 50.0]
        )

    def test_get_category_totals_range_percent_is_share_of_range_total(self, alice):
        totals = db_module.get_category_totals(
            alice["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert [(t["name"], t["total"], t["percent"]) for t in totals] == [
            ("Bills", pytest.approx(500.0), 91),
            ("Transport", pytest.approx(50.0), 9),
        ]

    @pytest.mark.parametrize(
        "date_from, date_to, expected",
        [
            ("2026-09-01", None,
             [("Bills", 500.0, 77), ("Food", 100.0, 15), ("Transport", 50.0, 8)]),
            (None, "2026-08-31",
             [("Health", 400.0, 62), ("Shopping", 250.0, 38)]),
        ],
        ids=["from-only", "to-only"],
    )
    def test_get_category_totals_open_ranges(
        self, alice, date_from, date_to, expected
    ):
        totals = db_module.get_category_totals(
            alice["id"], date_from=date_from, date_to=date_to
        )
        assert [(t["name"], t["total"], t["percent"]) for t in totals] == [
            (name, pytest.approx(total), percent) for name, total, percent in expected
        ]

    @pytest.mark.parametrize("case", EMPTY_RANGES)
    def test_get_category_totals_empty_range_returns_empty_list(self, alice, case):
        totals = db_module.get_category_totals(
            alice["id"], date_from=case.date_from, date_to=case.date_to
        )
        assert totals == []

    def test_get_category_totals_range_ties_list_alphabetically_first(self, empty_db):
        user = make_user("Tie Breaker", "tie2@example.com", [
            (100.0, "Transport", "2026-09-05", "tie one"),
            (100.0, "Food", "2026-09-06", "tie two"),
            (900.0, "Bills", "2026-01-05", "outside the range"),
        ])
        totals = db_module.get_category_totals(
            user["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert [(t["name"], t["percent"]) for t in totals] == [
            ("Food", 50), ("Transport", 50)
        ]


class TestHelpersUserScopeAndSafety:
    def test_helpers_range_never_includes_another_users_rows(self, alice, bob):
        stats = db_module.get_expense_stats(
            alice["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        rows = db_module.get_recent_expenses(
            alice["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        totals = db_module.get_category_totals(
            alice["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert stats["total_spent"] == pytest.approx(550.0)
        assert stats["transaction_count"] == 2
        assert "Bob concert" not in [r["description"] for r in rows]
        assert "Entertainment" not in [t["name"] for t in totals]

    def test_helpers_range_returns_the_other_users_own_rows(self, alice, bob):
        stats = db_module.get_expense_stats(
            bob["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        rows = db_module.get_recent_expenses(
            bob["id"], date_from="2026-09-01", date_to="2026-09-30"
        )
        assert stats["total_spent"] == pytest.approx(7777.0)
        assert stats["transaction_count"] == 1
        assert stats["top_category"] == "Entertainment"
        assert [r["description"] for r in rows] == ["Bob concert"]

    @pytest.mark.parametrize(
        "date_from, date_to",
        [
            ("2026-09-01' OR '1'='1", None),
            (None, "2026-09-30' OR '1'='1"),
            ("2026-01-01'; DROP TABLE expenses; --", "2026-12-31"),
        ],
        ids=["or-in-from", "or-in-to", "drop-table"],
    )
    def test_helpers_treat_injection_text_as_data(
        self, alice, bob, date_from, date_to
    ):
        before = snapshot_db()
        stats = db_module.get_expense_stats(
            alice["id"], date_from=date_from, date_to=date_to
        )
        rows = db_module.get_recent_expenses(
            alice["id"], date_from=date_from, date_to=date_to
        )
        totals = db_module.get_category_totals(
            alice["id"], date_from=date_from, date_to=date_to
        )
        assert stats["transaction_count"] <= 5, "Another user's rows leaked in"
        assert stats["total_spent"] <= 1300.0 + 1e-9
        assert all(r["description"] in ALL_DESCRIPTIONS for r in rows)
        assert all(t["name"] != "Entertainment" for t in totals)
        assert snapshot_db() == before, "A helper changed the database"

    def test_helpers_do_not_write_to_the_database(self, alice, bob):
        before = snapshot_db()
        for kwargs in ({}, {"date_from": "2026-09-01", "date_to": "2026-09-30"}):
            db_module.get_expense_stats(alice["id"], **kwargs)
            db_module.get_recent_expenses(alice["id"], **kwargs)
            db_module.get_category_totals(alice["id"], **kwargs)
        assert snapshot_db() == before


# --------------------------------------------------------------------------- #
# GET /profile - auth guard                                                   #
# --------------------------------------------------------------------------- #

class TestProfileAuthGuard:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"date_from": "2026-09-01"},
            {"date_from": "2026-09-01", "date_to": "2026-09-30"},
            {"date_from": "abc"},
            {"date_from": "", "date_to": ""},
        ],
        ids=["no-params", "from-only", "both", "invalid", "empty-values"],
    )
    def test_profile_signed_out_redirects_to_login(self, client, alice, params):
        response = get_profile(client, **params)
        assert response.status_code == 302, "Signed-out visitors must be redirected"
        assert urlparse(response.headers["Location"]).path == url("login")

    def test_profile_signed_out_response_contains_no_expense_data(self, client, alice):
        response = get_profile(client, date_from="2026-09-01")
        assert b"September bill" not in response.data
        assert b"Filter by date" not in response.data


# --------------------------------------------------------------------------- #
# GET /profile - the filter card                                              #
# --------------------------------------------------------------------------- #

class TestFilterCard:
    def test_profile_page_answers_200(self, auth_client):
        response = get_profile(auth_client)
        assert response.status_code == 200

    def test_filter_card_title_is_h2_with_calendar_icon(self, profile_page):
        card = filter_card(profile_page)
        assert card is not None, "No .profile-card with an h2 'Filter by date'"
        icons = card.find_all("i", attrs={"data-lucide": "calendar"})
        assert icons, "Expected a calendar icon beside the card title"

    def test_filter_card_sits_between_header_and_summary_cards(
        self, profile_page, alice
    ):
        tokens = profile_page.tokens()
        member_since = next(i for i, t in enumerate(tokens) if t.startswith("Member since"))
        assert member_since < tokens.index("Filter by date") < tokens.index("Total spent")

    def test_filter_card_has_four_preset_links_in_order(self, profile_page):
        card = filter_card(profile_page)
        links = [a.text() for a in card.find_all("a") if a.text() in PRESET_LABELS]
        assert links == PRESET_LABELS

    def test_filter_form_uses_get_and_targets_profile_url(self, profile_page):
        form = filter_form(profile_page)
        assert form.attrs.get("method", "").lower() == "get"
        assert urlparse(form.attrs.get("action", "")).path == url("profile")

    def test_filter_form_has_two_date_inputs_with_visible_labels(self, profile_page):
        form = filter_form(profile_page)
        for name, label_text in (("date_from", "From"), ("date_to", "To")):
            field = date_input(profile_page, name)
            assert field.attrs.get("type") == "date"
            assert ancestor(field, tag="form") is form, (
                f"{name} input is outside the filter form"
            )
            field_id = field.attrs.get("id")
            assert field_id, f"{name} input needs an id for its label"
            labels = profile_page.find_all("label", attrs={"for": field_id})
            assert len(labels) == 1, f"{name} needs exactly one <label for>"
            assert labels[0].text() == label_text

    def test_filter_form_has_apply_submit_button(self, profile_page):
        form = filter_form(profile_page)
        buttons = [
            b for b in form.find_all("button")
            if b.attrs.get("type", "submit") == "submit" and b.text() == "Apply"
        ]
        inputs = [
            i for i in form.find_all("input", attrs={"type": "submit"})
            if i.attrs.get("value") == "Apply"
        ]
        assert buttons or inputs, "Expected an 'Apply' submit button in the form"

    def test_page_has_a_single_h1(self, profile_page):
        assert len(profile_page.find_all("h1")) == 1

    def test_unfiltered_page_marks_all_time_active_only(self, profile_page):
        assert active_preset_labels(profile_page) == ["All time"]

    def test_active_preset_differs_from_inactive_by_a_class(self, profile_page):
        active = set(preset_link(profile_page, "All time").classes())
        inactive = set(preset_link(profile_page, "This month").classes())
        assert active - inactive, (
            "The active preset should carry a class the other presets lack"
        )

    def test_unfiltered_page_has_no_clear_link_no_range_line_no_error(
        self, profile_page
    ):
        assert clear_links(profile_page) == []
        assert not has_range_line(profile_page)
        assert error_alerts(profile_page) == []

    def test_unfiltered_page_inputs_are_empty(self, profile_page):
        assert date_input(profile_page, "date_from").attrs.get("value", "") == ""
        assert date_input(profile_page, "date_to").attrs.get("value", "") == ""

    def test_unfiltered_page_shows_all_expenses_and_full_summary(self, profile_page):
        assert summary(profile_page) == (money(1300), "5", "Bills")
        assert row_descriptions(profile_page) == ALL_DESCRIPTIONS

    def test_add_expense_link_still_points_at_add_expense_route(self, profile_page):
        hrefs = [
            a.attrs.get("href") for a in profile_page.find_all("a")
            if a.text() == "Add expense"
        ]
        assert url("add_expense") in hrefs


# --------------------------------------------------------------------------- #
# GET /profile - a valid range                                                #
# --------------------------------------------------------------------------- #

class TestFilteredProfile:
    @pytest.mark.parametrize("case", FILTERED_RANGES)
    def test_range_shows_matching_summary_cards_and_rows(
        self, auth_client, frozen_today, case
    ):
        params = {k: v for k, v in (("date_from", case.date_from),
                                     ("date_to", case.date_to)) if v}
        response = get_profile(auth_client, **params)
        assert response.status_code == 200
        page = parse_page(response)
        assert summary(page) == (money(case.total), str(case.count), case.top)
        assert row_descriptions(page) == case.descriptions
        assert error_alerts(page) == []

    @pytest.mark.parametrize("case", FILTERED_RANGES)
    def test_range_line_states_the_range_in_use(self, auth_client, frozen_today, case):
        params = {k: v for k, v in (("date_from", case.date_from),
                                     ("date_to", case.date_to)) if v}
        page = parse_page(get_profile(auth_client, **params))
        assert case.line in page.text(), f"Expected the line {case.line!r}"

    @pytest.mark.parametrize("case", FILTERED_RANGES)
    def test_range_fills_inputs_with_the_range_in_use(
        self, auth_client, frozen_today, case
    ):
        params = {k: v for k, v in (("date_from", case.date_from),
                                     ("date_to", case.date_to)) if v}
        page = parse_page(get_profile(auth_client, **params))
        assert date_input(page, "date_from").attrs.get("value", "") == (case.date_from or "")
        assert date_input(page, "date_to").attrs.get("value", "") == (case.date_to or "")

    def test_september_range_lists_rows_in_order_with_amounts(self, auth_client):
        page = parse_page(get_profile(
            auth_client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        rows = expense_rows(page)
        assert len(rows) == 2
        assert rows[0] == ["20 Sep 2026", "September bill", "Bills", money(500)]
        assert rows[1] == ["01 Sep 2026", "September metro", "Transport", money(50)]

    def test_september_range_breakdown_lists_only_categories_in_range(
        self, auth_client
    ):
        page = parse_page(get_profile(
            auth_client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        text = page.text()
        assert re.search(r"Bills\s+₹500\.00\W+91%", text), (
            "Expected Bills at ₹500.00 and 91% of the range total"
        )
        assert re.search(r"Transport\s+₹50\.00\W+9%", text), (
            "Expected Transport at ₹50.00 and 9% of the range total"
        )
        for outside in ("Food", "Shopping", "Health"):
            assert outside not in page.tokens(), (
                f"{outside} is outside the range and must not be listed"
            )

    def test_filtered_page_shows_clear_link_to_unfiltered_profile(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2026-09-01"))
        links = clear_links(page)
        assert len(links) == 1, "Expected exactly one 'Clear' link while filtered"
        parsed = urlparse(links[0].attrs["href"])
        assert parsed.path == url("profile")
        assert parsed.query == "", "Clear must not carry any date parameters"

    def test_clear_link_opens_the_unfiltered_page(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2026-09-01"))
        href = clear_links(page)[0].attrs["href"]
        cleared = parse_page(auth_client.get(href))
        assert summary(cleared) == (money(1300), "5", "Bills")
        assert clear_links(cleared) == []

    def test_custom_range_marks_no_preset_active(self, auth_client, frozen_today):
        page = parse_page(get_profile(
            auth_client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        assert active_preset_labels(page) == []

    def test_submitting_the_form_fields_applies_the_range(self, auth_client):
        page = parse_page(get_profile(auth_client))
        form = filter_form(page)
        fields = {
            i.attrs["name"]: i.attrs.get("value", "")
            for i in form.find_all("input") if i.attrs.get("name")
        }
        fields["date_from"] = "2026-09-01"
        fields["date_to"] = "2026-09-30"
        response = auth_client.get(form.attrs["action"], query_string=fields)
        assert response.status_code == 200
        assert summary(parse_page(response)) == (money(550), "2", "Bills")

    def test_filtered_url_gives_same_figures_on_refresh_and_in_new_session(
        self, auth_client, spendly_app, alice
    ):
        params = {"date_from": "2026-09-01", "date_to": "2026-09-30"}
        first = summary(parse_page(get_profile(auth_client, **params)))
        refreshed = summary(parse_page(get_profile(auth_client, **params)))
        other_tab = sign_in(spendly_app.test_client(), alice)
        reopened = summary(parse_page(get_profile(other_tab, **params)))
        assert first == refreshed == reopened == (money(550), "2", "Bills")


# --------------------------------------------------------------------------- #
# GET /profile - empty states                                                 #
# --------------------------------------------------------------------------- #

class TestEmptyStates:
    @pytest.mark.parametrize("case", EMPTY_RANGES)
    def test_range_without_expenses_shows_period_message_and_zero_summary(
        self, auth_client, case
    ):
        params = {k: v for k, v in (("date_from", case.date_from),
                                     ("date_to", case.date_to)) if v}
        response = get_profile(auth_client, **params)
        assert response.status_code == 200
        page = parse_page(response)
        assert summary(page) == (money(0), "0", EM_DASH)
        assert "No expenses in this period." in page.tokens()
        assert expense_rows(page) == []
        assert error_alerts(page) == []

    def test_empty_period_offers_clear_filter_link_to_profile(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2027-01-01"))
        links = [a for a in page.find_all("a") if a.text() == "Clear filter"]
        assert len(links) == 1, "Expected one 'Clear filter' link"
        parsed = urlparse(links[0].attrs["href"])
        assert parsed.path == url("profile")
        assert parsed.query == ""

    def test_empty_period_hides_the_original_empty_state(self, auth_client):
        text = parse_page(get_profile(auth_client, date_from="2027-01-01")).text()
        assert "No expenses yet" not in text
        assert "Add your first one" not in text

    def test_empty_period_shows_no_category_breakdown(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2027-01-01"))
        assert "By category" not in page.tokens()
        assert not re.search(r"\d+%", page.text()), (
            "No category percentages should be shown for an empty range"
        )

    def test_empty_period_still_states_the_range_and_offers_clear(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2027-01-01"))
        assert "From 01 Jan 2027" in page.text()
        assert len(clear_links(page)) == 1

    def test_clear_filter_link_restores_all_expenses(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2027-01-01"))
        href = next(a for a in page.find_all("a")
                    if a.text() == "Clear filter").attrs["href"]
        restored = parse_page(auth_client.get(href))
        assert summary(restored) == (money(1300), "5", "Bills")

    def test_new_registered_user_sees_original_empty_state(self, client):
        register = client.post(url("register"), data={
            "name": "New Person", "email": "new@example.com", "password": PASSWORD,
        })
        assert register.status_code == 302
        login = client.post(url("login"), data={
            "email": "new@example.com", "password": PASSWORD,
        })
        assert login.status_code == 302
        page = parse_page(get_profile(client))
        assert summary(page) == (money(0), "0", EM_DASH)
        assert "No expenses yet. Add your first one to see it here." in page.tokens()
        assert "No expenses in this period." not in page.tokens()
        assert clear_links(page) == []

    @pytest.mark.parametrize(
        "params",
        [{}, {"date_from": "", "date_to": ""}],
        ids=["no-params", "empty-values"],
    )
    def test_user_without_expenses_and_no_filter_keeps_original_message(
        self, client, empty_db, params
    ):
        sign_in(client, make_user("Nobody Yet", "nobody@example.com"))
        page = parse_page(get_profile(client, **params))
        assert "No expenses yet. Add your first one to see it here." in page.tokens()
        assert "No expenses in this period." not in page.tokens()

    def test_user_without_expenses_but_with_filter_sees_period_message(
        self, client, empty_db
    ):
        sign_in(client, make_user("Nobody Yet", "nobody2@example.com"))
        page = parse_page(get_profile(client, date_from="2026-01-01"))
        assert "No expenses in this period." in page.tokens()
        assert "No expenses yet" not in page.text()


# --------------------------------------------------------------------------- #
# GET /profile - empty values, reversed range and invalid input              #
# --------------------------------------------------------------------------- #

class TestInvalidAndEmptyInput:
    def test_empty_date_values_count_as_not_given(self, auth_client):
        response = get_profile(auth_client, date_from="", date_to="")
        assert response.status_code == 200
        page = parse_page(response)
        assert error_alerts(page) == []
        assert row_descriptions(page) == ALL_DESCRIPTIONS
        assert summary(page) == (money(1300), "5", "Bills")
        assert clear_links(page) == []
        assert active_preset_labels(page) == ["All time"]

    def test_empty_values_in_the_raw_url_count_as_not_given(self, auth_client):
        response = auth_client.get(url("profile") + "?date_from=&date_to=")
        assert response.status_code == 200
        page = parse_page(response)
        assert error_alerts(page) == []
        assert len(expense_rows(page)) == 5

    def test_one_empty_value_is_ignored_and_the_other_applies(self, auth_client):
        page = parse_page(get_profile(auth_client, date_from="2026-09-01", date_to=""))
        assert error_alerts(page) == []
        assert summary(page) == (money(650), "3", "Bills")

    def test_reversed_range_shows_error_and_all_expenses(self, auth_client):
        response = get_profile(
            auth_client, date_from="2026-09-30", date_to="2026-09-01"
        )
        assert response.status_code == 200, "A bad range must not answer 4xx or 5xx"
        page = parse_page(response)
        alerts = error_alerts(page)
        assert len(alerts) == 1
        assert alerts[0].text() == "The start date cannot be after the end date."
        assert row_descriptions(page) == ALL_DESCRIPTIONS
        assert summary(page) == (money(1300), "5", "Bills")

    def test_reversed_range_keeps_what_the_user_typed(self, auth_client):
        page = parse_page(get_profile(
            auth_client, date_from="2026-09-30", date_to="2026-09-01"
        ))
        assert date_input(page, "date_from").attrs.get("value") == "2026-09-30"
        assert date_input(page, "date_to").attrs.get("value") == "2026-09-01"

    @pytest.mark.parametrize(
        "params",
        [
            {"date_from": "2026-13-45"},
            {"date_from": "abc"},
            {"date_to": "abc"},
            {"date_from": "2026-09-01", "date_to": "not-a-date"},
            {"date_from": "not-a-date", "date_to": "2026-09-30"},
            {"date_from": "2026-02-30"},
            {"date_to": "2025-02-29"},
            {"date_from": "2026-W36-2"},
            {"date_from": "20260901"},
            {"date_from": "9" * 5000},
            {"date_from": "abc", "date_to": "def"},
            {"date_from": "2026-09-30", "date_to": "garbage"},
        ],
        ids=["month-13-day-45", "text-from", "text-to", "good-from-bad-to",
             "bad-from-good-to", "feb-30", "feb-29-non-leap", "week-date",
             "no-dashes", "very-long", "both-bad", "reversed-looking-but-bad"],
    )
    def test_invalid_date_shows_error_and_all_expenses(self, auth_client, params):
        response = get_profile(auth_client, **params)
        assert response.status_code == 200, "A bad date must not answer 4xx or 5xx"
        page = parse_page(response)
        alerts = error_alerts(page)
        assert len(alerts) == 1, "Expected exactly one error message"
        assert alerts[0].text() == "Please enter valid dates."
        assert row_descriptions(page) == ALL_DESCRIPTIONS
        assert summary(page) == (money(1300), "5", "Bills")

    @pytest.mark.parametrize(
        "params",
        [{"date_from": "abc"}, {"date_to": "def"},
         {"date_from": "2026-13-45", "date_to": "2026-09-30"}],
        ids=["from", "to", "both"],
    )
    def test_invalid_date_keeps_what_the_user_typed(self, auth_client, params):
        page = parse_page(get_profile(auth_client, **params))
        assert date_input(page, "date_from").attrs.get("value", "") == params.get("date_from", "")
        assert date_input(page, "date_to").attrs.get("value", "") == params.get("date_to", "")

    @pytest.mark.parametrize(
        "params",
        [{"date_from": "abc"}, {"date_from": "2026-09-30", "date_to": "2026-09-01"}],
        ids=["invalid", "reversed"],
    )
    def test_error_message_is_in_filter_card_above_the_inputs(
        self, auth_client, params
    ):
        page = parse_page(get_profile(auth_client, **params))
        alert = error_alerts(page)[0]
        assert alert.attrs.get("role") == "alert"
        assert ancestor(alert, cls="profile-card") is filter_card(page)
        order = list(page.descendants())
        assert order.index(alert) < order.index(date_input(page, "date_from")), (
            "The error should sit above the inputs"
        )

    @pytest.mark.parametrize(
        "params",
        [{"date_from": "abc"}, {"date_from": "2026-09-30", "date_to": "2026-09-01"}],
        ids=["invalid", "reversed"],
    )
    def test_error_applies_no_filter_so_no_clear_link_or_range_line(
        self, auth_client, params
    ):
        page = parse_page(get_profile(auth_client, **params))
        assert clear_links(page) == []
        assert not has_range_line(page)
        assert "No expenses in this period." not in page.tokens()

    def test_valid_dates_show_no_error_message(self, auth_client):
        page = parse_page(get_profile(
            auth_client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        assert error_alerts(page) == []

    @pytest.mark.parametrize(
        "value",
        ["null", "0", "-1", "None", "éè", ";", "%", "../../etc/passwd",
         " ", "2026-09-01 2026-09-30", "2026-09-31"],
    )
    def test_unusual_values_never_crash_the_page(self, auth_client, value):
        for name in ("date_from", "date_to"):
            response = get_profile(auth_client, **{name: value})
            assert response.status_code == 200, (
                f"{name}={value!r} answered {response.status_code}"
            )

    def test_sql_injection_text_in_date_from_is_rejected(self, auth_client, bob):
        before = snapshot_db()
        response = get_profile(auth_client, date_from="2026-09-01' OR '1'='1")
        assert response.status_code == 200
        page = parse_page(response)
        assert [a.text() for a in error_alerts(page)] == ["Please enter valid dates."]
        assert row_descriptions(page) == ALL_DESCRIPTIONS
        assert snapshot_db() == before

    def test_sql_injection_drop_table_in_date_to_leaves_tables_intact(
        self, auth_client
    ):
        before = snapshot_db()
        response = get_profile(
            auth_client, date_to="2026-09-30'; DROP TABLE expenses; --"
        )
        assert response.status_code == 200
        assert [a.text() for a in error_alerts(parse_page(response))] == [
            "Please enter valid dates."
        ]
        assert snapshot_db() == before, "Tables or rows changed"
        assert len(expense_rows(parse_page(get_profile(auth_client)))) == 5

    @pytest.mark.parametrize(
        "payload",
        [
            '"><script>alert(1)</script>',
            '" onfocus="alert(1)" autofocus="',
            "<img src=x onerror=alert(1)>",
        ],
        ids=["script-tag", "attribute-breakout", "img-onerror"],
    )
    @pytest.mark.parametrize("name", ["date_from", "date_to"])
    def test_typed_value_is_escaped_when_printed_back(self, auth_client, name, payload):
        response = get_profile(auth_client, **{name: payload})
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert payload not in html, "The raw payload appears unescaped in the page"
        page = parse_page(response)
        field = date_input(page, name)
        assert field.attrs.get("value") == payload, (
            "The typed text should come back inside the quoted value attribute"
        )
        assert not any(key.startswith("on") for key in field.attrs), (
            "The payload must not create event-handler attributes"
        )
        assert "autofocus" not in field.attrs
        assert not page.find_all("img", attrs={"src": "x"})
        assert len(page.find_all("h1")) == 1

    def test_script_payload_is_html_escaped_in_source(self, auth_client):
        response = get_profile(auth_client, date_from='"><script>alert(1)</script>')
        assert b"<script>alert(1)</script>" not in response.data
        assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.data


# --------------------------------------------------------------------------- #
# GET /profile - presets                                                      #
# --------------------------------------------------------------------------- #

class TestPresets:
    def test_preset_links_use_the_expected_ranges(self, auth_client, frozen_today):
        page = parse_page(get_profile(auth_client))
        expected = {
            "This month": ("2026-10-01", "2026-10-10"),
            "Last 3 months": ("2026-08-01", "2026-10-10"),
            "Last 6 months": ("2026-05-01", "2026-10-10"),
        }
        for label, (start, end) in expected.items():
            parsed = urlparse(preset_link(page, label).attrs["href"])
            assert parsed.path == url("profile")
            query = parse_qs(parsed.query)
            assert query.get("date_from") == [start], f"{label} start"
            assert query.get("date_to") == [end], f"{label} end"

    def test_all_time_link_is_plain_profile_url(self, auth_client, frozen_today):
        page = parse_page(get_profile(auth_client))
        parsed = urlparse(preset_link(page, "All time").attrs["href"])
        assert parsed.path == url("profile")
        assert parsed.query == "", "All time must carry no parameters"

    def test_route_builds_presets_for_the_current_date(
        self, auth_client, monkeypatch
    ):
        seen = []

        def spy(today):
            seen.append(today)
            return _REAL_GET_DATE_PRESETS(today)

        monkeypatch.setattr(app_module, "get_date_presets", spy)
        assert get_profile(auth_client).status_code == 200
        assert seen, "The route never asked for the presets"
        for passed in seen:
            assert isinstance(passed, date)
            # one day of slack, in case the test straddles midnight
            assert abs((date.today() - passed).days) <= 1

    def test_this_month_link_shows_october_figures_and_is_active(
        self, auth_client, frozen_today
    ):
        page = parse_page(get_profile(auth_client))
        href = preset_link(page, "This month").attrs["href"]
        page = parse_page(auth_client.get(href))
        assert summary(page) == (money(100), "1", "Food")
        assert active_preset_labels(page) == ["This month"]

    @pytest.mark.parametrize("label", ["Last 3 months", "Last 6 months"])
    def test_longer_preset_links_show_the_same_figures_and_are_active(
        self, auth_client, frozen_today, label
    ):
        page = parse_page(get_profile(auth_client))
        href = preset_link(page, label).attrs["href"]
        page = parse_page(auth_client.get(href))
        assert summary(page) == (money(900), "4", "Bills")
        assert "March pharmacy" not in row_descriptions(page), (
            "The March expense is outside both ranges"
        )
        assert active_preset_labels(page) == [label]

    def test_all_time_link_shows_everything_and_is_active(
        self, auth_client, frozen_today
    ):
        filtered = parse_page(get_profile(auth_client, date_from="2026-09-01"))
        href = preset_link(filtered, "All time").attrs["href"]
        page = parse_page(auth_client.get(href))
        assert summary(page) == (money(1300), "5", "Bills")
        assert active_preset_labels(page) == ["All time"]
        assert clear_links(page) == []

    @pytest.mark.parametrize(
        "today, expected_start",
        [
            (date(2027, 1, 15), {"Last 3 months": "2026-11-01",
                                 "Last 6 months": "2026-08-01"}),
            (date(2026, 12, 5), {"Last 3 months": "2026-10-01",
                                 "Last 6 months": "2026-07-01"}),
        ],
        ids=["jan-2027", "dec-2026"],
    )
    def test_preset_links_cross_the_year_boundary(
        self, auth_client, monkeypatch, today, expected_start
    ):
        freeze_presets(monkeypatch, today)
        page = parse_page(get_profile(auth_client))
        for label, start in expected_start.items():
            query = parse_qs(urlparse(preset_link(page, label).attrs["href"]).query)
            assert query.get("date_from") == [start], label
            assert query.get("date_to") == [today.isoformat()], label

    @pytest.mark.parametrize(
        "date_from, date_to, label",
        [
            ("2026-10-01", "2026-10-10", "This month"),
            ("2026-08-01", "2026-10-10", "Last 3 months"),
            ("2026-05-01", "2026-10-10", "Last 6 months"),
        ],
    )
    def test_typed_range_equal_to_a_preset_marks_that_preset(
        self, auth_client, frozen_today, date_from, date_to, label
    ):
        page = parse_page(get_profile(
            auth_client, date_from=date_from, date_to=date_to
        ))
        assert active_preset_labels(page) == [label]
        assert preset_link(page, label).attrs.get("aria-current") == "true"

    @pytest.mark.parametrize(
        "date_from, date_to",
        [
            ("2026-10-01", "2026-10-09"),
            ("2026-09-02", "2026-10-10"),
            ("2026-08-01", None),
            (None, "2026-10-10"),
            ("2026-09-01", "2026-09-30"),
        ],
        ids=["end-one-day-early", "start-one-day-late", "from-only",
             "to-only", "september"],
    )
    def test_range_matching_no_preset_marks_none_active(
        self, auth_client, frozen_today, date_from, date_to
    ):
        params = {k: v for k, v in (("date_from", date_from),
                                     ("date_to", date_to)) if v}
        page = parse_page(get_profile(auth_client, **params))
        assert active_preset_labels(page) == []

    def test_only_one_preset_is_ever_marked_active(self, auth_client, frozen_today):
        page = parse_page(get_profile(
            auth_client, date_from="2026-10-01", date_to="2026-10-10"
        ))
        marked = [a for a in preset_links(page) if "aria-current" in a.attrs]
        assert len(marked) == 1


# --------------------------------------------------------------------------- #
# GET /profile - only the signed-in user's rows                               #
# --------------------------------------------------------------------------- #

class TestUserIsolation:
    def test_range_shows_only_the_signed_in_users_expenses(
        self, client, alice, bob
    ):
        sign_in(client, bob)
        page = parse_page(get_profile(
            client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        assert summary(page) == (money(7777), "1", "Entertainment")
        assert row_descriptions(page) == ["Bob concert"]
        assert "September bill" not in page.text()

    def test_other_users_expenses_in_a_range_are_not_shown(
        self, client, alice, empty_db
    ):
        stranger = make_user("No March Spending", "stranger@example.com")
        sign_in(client, stranger)
        page = parse_page(get_profile(
            client, date_from="2026-03-01", date_to="2026-03-31"
        ))
        assert "No expenses in this period." in page.tokens()
        assert "March pharmacy" not in page.text()
        assert summary(page) == (money(0), "0", EM_DASH)

    def test_user_id_in_the_query_string_is_ignored(self, client, alice, bob):
        sign_in(client, bob)
        page = parse_page(get_profile(
            client, user_id=alice["id"], date_from="2026-09-01",
            date_to="2026-09-30",
        ))
        assert row_descriptions(page) == ["Bob concert"]
        assert "September bill" not in page.text()

    def test_unfiltered_page_for_one_user_never_lists_the_other_users_rows(
        self, client, alice, bob
    ):
        sign_in(client, alice)
        page = parse_page(get_profile(client))
        assert not any(d.startswith("Bob") for d in row_descriptions(page))
        assert summary(page) == (money(1300), "5", "Bills")


# --------------------------------------------------------------------------- #
# GET /profile - the row limit and the stats                                  #
# --------------------------------------------------------------------------- #

class TestRowLimitAndStats:
    def test_table_lists_ten_newest_in_range_while_stats_count_all(
        self, client, carol
    ):
        sign_in(client, carol)
        page = parse_page(get_profile(
            client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        assert row_descriptions(page) == [
            f"entry-{day:02d}" for day in range(12, 2, -1)
        ]
        # 10 + 20 + ... + 120 = 780, over 12 transactions
        assert summary(page) == (money(780), "12", "Food")

    def test_table_limit_also_applies_without_a_filter(self, client, carol):
        sign_in(client, carol)
        page = parse_page(get_profile(client))
        descriptions = row_descriptions(page)
        assert len(descriptions) == 10
        assert descriptions[0] == "outside-after"
        assert summary(page) == (money(3780), "14", "Bills")

    def test_rows_outside_the_range_do_not_count_in_the_stats(self, client, carol):
        sign_in(client, carol)
        page = parse_page(get_profile(
            client, date_from="2026-09-01", date_to="2026-09-30"
        ))
        assert "outside-before" not in page.text()
        assert "outside-after" not in page.text()
        assert stat_value(page, "Top category") == "Food", (
            "Bills (3000 in total) is outside the range and must not win"
        )


# --------------------------------------------------------------------------- #
# Nothing remembered, nothing written                                         #
# --------------------------------------------------------------------------- #

class TestStateAndSideEffects:
    def test_range_is_not_remembered_for_the_next_request(self, auth_client):
        filtered = parse_page(get_profile(auth_client, date_from="2026-09-01"))
        assert summary(filtered) == (money(650), "3", "Bills")
        plain = parse_page(get_profile(auth_client))
        assert summary(plain) == (money(1300), "5", "Bills")
        assert clear_links(plain) == []

    def test_range_is_not_stored_in_the_session(self, auth_client):
        get_profile(auth_client, date_from="2026-09-01", date_to="2026-09-30")
        with auth_client.session_transaction() as session:
            assert "user_id" in session
            assert not [k for k in session if "date" in k.lower()], (
                f"Session keys: {list(session)}"
            )

    def test_signing_out_and_in_again_opens_profile_without_a_filter(
        self, auth_client, alice
    ):
        get_profile(auth_client, date_from="2026-09-01", date_to="2026-09-30")
        logout = auth_client.post(url("logout"))
        assert logout.status_code == 302
        login = auth_client.post(url("login"), data={
            "email": alice["email"], "password": alice["password"],
        }, follow_redirects=True)
        assert login.status_code == 200
        page = parse_page(login)
        assert summary(page) == (money(1300), "5", "Bills")
        assert active_preset_labels(page) == ["All time"]
        assert clear_links(page) == []

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"date_from": "2026-09-01", "date_to": "2026-09-30"},
            {"date_from": "2027-01-01"},
            {"date_from": "2026-09-30", "date_to": "2026-09-01"},
            {"date_from": "abc"},
            {"date_from": "2026-09-01' OR '1'='1"},
        ],
        ids=["none", "september", "empty-range", "reversed", "invalid",
             "injection"],
    )
    def test_profile_requests_do_not_change_the_database(
        self, auth_client, bob, params
    ):
        before = snapshot_db()
        response = get_profile(auth_client, **params)
        assert response.status_code == 200
        assert snapshot_db() == before, "A GET /profile request wrote to the database"
