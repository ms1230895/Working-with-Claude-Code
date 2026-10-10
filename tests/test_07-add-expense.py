"""Tests for Step 7: Add Expense.

Based on .claude/specs/07-add-expense.md.

Test plan
---------
* CATEGORIES and create_expense(): the seven names in order, the signature,
  the returned id, the stored values, NULL for a missing description, no
  checking of arguments, parameterised SQL.
* Auth guard: signed-out GET and POST to /expenses/add go to /login and add
  no row.
* GET /expenses/add: the form markup (labels, the four controls and their
  attributes, the category options in order, today in the date input and in
  its max, Save expense button, Cancel link, one <h1>, layout classes, no
  placeholder text, no user id field).
* POST happy path: redirect to /profile, the flash shown once and gone after
  a refresh, the stored row, the profile cards and table, a second expense
  with an empty description, every category and a range of accepted amounts.
* Stored values: blank description saved as NULL, fields stripped, zero-padded
  YYYY-MM-DD date.
* Validation: each rule in the spec's Errors list with its exact message,
  answering 200, adding no row and keeping the typed values in the form.
  Parametrised over the spec's bad amounts, categories, dates and descriptions.
* Rule order: the first failing rule decides the message.
* Boundaries: 9999999.99, 0.01, 200-character description, today's date.
* Security: forged user_id ignored, HTML escaped on /profile and in the
  re-rendered form, SQL text stored as plain text, users cannot see each
  other's expenses (including the demo user).
* Other methods answer 405; /expenses/<id>/edit and /delete are unchanged.
* Step 6 interaction: a last-month expense counts overall and is left out by
  a range starting on the first of this month.
* expense.css is served and holds no hex colours.
* A walk through the spec's "Definition of done" set-up, from registration.

Safety: database.db.DB_PATH is pointed at a throwaway file before app.py is
imported (importing it runs init_db() and seed_db()) and again, per test, at a
fresh file under tmp_path. The developer's expense_tracker.db is never opened.
Where "today" matters the tests read datetime.date.today() themselves, and a
test skips if the date changes while it runs.
"""
import atexit
import inspect
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest
from flask import url_for

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database.db as db_module  # noqa: E402

# app.py calls init_db() and seed_db() when it is imported. Point the database
# at a throwaway directory first, so the real expense_tracker.db is untouched.
# When another test file has already imported app, leave its choice alone
# (unless it is somehow still the real file).
_REAL_DB_PATH = (ROOT / "expense_tracker.db").resolve()
_IMPORT_TMP = tempfile.mkdtemp(prefix="spendly-import-07-")
atexit.register(shutil.rmtree, _IMPORT_TMP, ignore_errors=True)
if "app" not in sys.modules or Path(db_module.DB_PATH).resolve() == _REAL_DB_PATH:
    db_module.DB_PATH = Path(_IMPORT_TMP) / "import_time.db"

import app as app_module  # noqa: E402

PASSWORD = "password123"
EM_DASH = "—"
SPEC_CATEGORIES = (
    "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
)

# The exact messages from the spec's "Errors" list
M_EMPTY = "Please fill in the amount, category and date."
M_AMOUNT = "Please enter a valid amount, like 250 or 250.50."
M_ZERO = "Amount must be greater than zero."
M_MAX = "Amount cannot be more than ₹9,999,999.99."
M_CATEGORY = "Please choose a category from the list."
M_DATE = "Please enter a valid date."
M_FUTURE = "The date cannot be in the future."
M_DESC = "Description cannot be longer than 200 characters."
FLASH_TEXT = "Expense added."

LONG_DESCRIPTION = "x" * 201


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
    body = response.get_data(as_text=True)
    builder.feed(body)
    builder.close()
    builder.root.raw = body
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

def control(page, name):
    found = page.find_all(attrs={"name": name})
    assert len(found) == 1, f"Expected exactly one control named {name!r}, got {len(found)}"
    return found[0]


def add_form(page):
    form = ancestor(control(page, "amount"), tag="form")
    assert form is not None, "The amount input is not inside a <form>"
    return form


def options(select):
    out = []
    for opt in select.find_all("option"):
        text = opt.text()
        out.append((opt.attrs.get("value", text), text, "selected" in opt.attrs))
    return out


def field_value(page, name):
    return control(page, name).attrs.get("value", "")


def selected_categories(page):
    return [value for value, _text, selected in options(control(page, "category"))
            if selected]


def error_alerts(page):
    return page.find_all(cls="auth-error")


def flash_texts(page):
    return [node.text() for node in page.find_all(cls="flash")]


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


def table_rows(page):
    rows = []
    for tr in page.find_all("tr"):
        cells = [td.text() for td in tr.find_all("td")]
        if cells:
            rows.append(cells)
    return rows


def preset_link(page, label):
    matches = [a for a in page.find_all("a") if a.text() == label]
    assert len(matches) == 1, f"Expected exactly one '{label}' link, got {len(matches)}"
    return matches[0]


def money(amount):
    return f"₹{amount:,.2f}"


def shown_date(day):
    # What the format_date filter prints by default, e.g. "24 Sep 2026"
    return day.strftime("%d %b %Y")


def assert_no_active_content(page):
    for node in page.descendants():
        on_attrs = [a for a in node.attrs if a.startswith("on")]
        assert not on_attrs, f"<{node.tag}> carries an event handler: {on_attrs}"
        assert node.tag != "img", "An <img> was injected into the page"
        if node.tag == "script":
            assert not any(
                "alert" in child for child in node.children if isinstance(child, str)
            ), "An injected <script> reached the page"


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
def spendly_app(empty_db, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "TESTING", True)
    monkeypatch.setitem(app_module.app.config, "SECRET_KEY", "test-secret")
    return app_module.app


@pytest.fixture
def client(spendly_app):
    return spendly_app.test_client()


@pytest.fixture
def today():
    return date.today()


def ensure_same_day(day):
    """Skip a test whose date-based expectations a midnight rollover broke."""
    if date.today() != day:
        pytest.skip("The date changed while the test was running")


def url(endpoint, **values):
    with app_module.app.test_request_context():
        return url_for(endpoint, **values)


def make_user(name, email):
    user_id = db_module.create_user(name, email, PASSWORD)
    return {"id": user_id, "name": name, "email": email, "password": PASSWORD}


def sign_in(test_client, user):
    response = test_client.post(
        url("login"), data={"email": user["email"], "password": user["password"]}
    )
    assert response.status_code == 302, "Sign-in should redirect"
    assert urlparse(response.headers["Location"]).path == url("profile")
    return test_client


@pytest.fixture
def alice(empty_db):
    return make_user("Alice Tester", "alice@example.com")


@pytest.fixture
def auth_client(client, alice):
    """A test client signed in as Alice, who has no expenses yet."""
    return sign_in(client, alice)


@pytest.fixture
def form_page(auth_client):
    response = auth_client.get(url("add_expense"))
    assert response.status_code == 200
    return parse_page(response)


def db_rows(user_id=None):
    conn = db_module.get_db()
    try:
        if user_id is None:
            cursor = conn.execute("SELECT * FROM expenses ORDER BY id")
        else:
            cursor = conn.execute(
                "SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (user_id,)
            )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def description_type(row_id):
    conn = db_module.get_db()
    try:
        row = conn.execute(
            "SELECT typeof(description) AS kind FROM expenses WHERE id = ?", (row_id,)
        ).fetchone()
        return row["kind"]
    finally:
        conn.close()


def table_exists(name):
    conn = db_module.get_db()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


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


def _resolve(value, today):
    # "@+N" stands for N days after today, as YYYY-MM-DD
    if isinstance(value, str) and value.startswith("@+"):
        return (today + timedelta(days=int(value[2:]))).isoformat()
    return value


def valid_form(today, **overrides):
    """A valid POST body. A value of None leaves that field out altogether."""
    data = {
        "amount": "250.50",
        "category": "Food",
        "date": today.isoformat(),
        "description": "Lunch",
    }
    data.update(overrides)
    return {k: _resolve(v, today) for k, v in data.items() if v is not None}


def post_add(test_client, data, **kwargs):
    return test_client.post(url("add_expense"), data=data, **kwargs)


def get_profile(test_client, **params):
    return test_client.get(url("profile"), query_string=params)


def assert_form_echoes(page, data):
    """After an error the form shows what the user typed."""
    for name in ("amount", "date", "description"):
        assert field_value(page, name).strip() == data.get(name, "").strip(), (
            f"The {name} field does not show the typed value"
        )
    typed_category = data.get("category", "").strip()
    selected = selected_categories(page)
    if typed_category in SPEC_CATEGORIES:
        assert selected == [typed_category], (
            f"Expected {typed_category!r} to be selected, got {selected}"
        )
    else:
        assert not [v for v in selected if v in SPEC_CATEGORIES], (
            f"A category was selected although {typed_category!r} was typed"
        )


def assert_rejected(test_client, data, message, today):
    """POST data and check the whole 'error' contract; returns the parsed page."""
    before = db_rows()
    response = post_add(test_client, data)
    ensure_same_day(today)
    assert response.status_code == 200, (
        f"Bad input must answer 200, got {response.status_code}"
    )
    assert "Location" not in response.headers, "Bad input must not redirect"
    page = parse_page(response)
    alerts = error_alerts(page)
    assert len(alerts) == 1, f"Expected one error message, got {len(alerts)}"
    assert alerts[0].attrs.get("role") == "alert", "The error needs role='alert'"
    assert alerts[0].text() == message, (
        f"Expected {message!r}, got {alerts[0].text()!r}"
    )
    assert db_rows() == before, "A rejected POST must not change the expenses table"
    assert FLASH_TEXT not in flash_texts(page)
    assert_form_echoes(page, data)
    return page


def _short(value):
    return repr(value)[:40]


# --------------------------------------------------------------------------- #
# CATEGORIES                                                                  #
# --------------------------------------------------------------------------- #

class TestCategoriesConstant:
    def test_categories_is_a_tuple_of_the_seven_names_in_spec_order(self):
        assert isinstance(db_module.CATEGORIES, tuple), "CATEGORIES must be a tuple"
        assert db_module.CATEGORIES == SPEC_CATEGORIES

    def test_categories_has_no_duplicates(self):
        assert len(set(db_module.CATEGORIES)) == 7


# --------------------------------------------------------------------------- #
# create_expense()                                                            #
# --------------------------------------------------------------------------- #

class TestCreateExpenseHelper:
    def test_create_expense_signature_matches_the_spec(self):
        params = inspect.signature(db_module.create_expense).parameters
        assert list(params) == ["user_id", "amount", "category", "date", "description"]
        assert params["description"].default is None, (
            "description must default to None"
        )

    def test_create_expense_returns_the_new_row_id(self, empty_db, alice):
        first = db_module.create_expense(alice["id"], 12.5, "Food", "2026-01-02", "Tea")
        second = db_module.create_expense(alice["id"], 20, "Bills", "2026-01-03", "Gas")
        assert isinstance(first, int)
        assert [row["id"] for row in db_rows()] == [first, second]
        assert second > first

    def test_create_expense_stores_the_values_it_is_given(self, empty_db, alice):
        new_id = db_module.create_expense(
            alice["id"], 12.5, "Transport", "2026-03-04", "Metro card"
        )
        (row,) = db_rows()
        assert row["id"] == new_id
        assert row["user_id"] == alice["id"]
        assert row["amount"] == pytest.approx(12.5)
        assert row["category"] == "Transport"
        assert row["date"] == "2026-03-04"
        assert row["description"] == "Metro card"

    def test_create_expense_accepts_keyword_arguments(self, empty_db, alice):
        new_id = db_module.create_expense(
            user_id=alice["id"], amount=3.0, category="Other",
            date="2026-02-01", description="Misc",
        )
        assert db_rows()[0]["id"] == new_id

    def test_create_expense_without_description_stores_null(self, empty_db, alice):
        new_id = db_module.create_expense(alice["id"], 5, "Food", "2026-01-01")
        (row,) = db_rows()
        assert row["description"] is None
        assert description_type(new_id) == "null"

    def test_create_expense_with_none_description_stores_null(self, empty_db, alice):
        new_id = db_module.create_expense(alice["id"], 5, "Food", "2026-01-01", None)
        assert db_rows()[0]["description"] is None
        assert description_type(new_id) == "null"

    def test_create_expense_fills_created_at_itself(self, empty_db, alice):
        db_module.create_expense(alice["id"], 5, "Food", "2026-01-01")
        assert db_rows()[0]["created_at"], "created_at should fill itself"

    def test_create_expense_does_not_check_its_arguments(self, empty_db, alice):
        # The route validates; the helper stores what it gets
        db_module.create_expense(alice["id"], 5, "Travel", "2026-01-01", "odd")
        assert db_rows()[0]["category"] == "Travel"

    def test_create_expense_keeps_sql_text_as_plain_text(self, empty_db, alice):
        text = "x'); DROP TABLE expenses;--"
        db_module.create_expense(alice["id"], 5, "Food", "2026-01-01", text)
        assert table_exists("expenses")
        assert db_rows()[0]["description"] == text

    def test_create_expense_saves_under_the_given_user_only(self, empty_db, alice):
        bob = make_user("Bob Other", "bob@example.com")
        db_module.create_expense(bob["id"], 5, "Food", "2026-01-01", "bob's")
        assert db_rows(alice["id"]) == []
        assert len(db_rows(bob["id"])) == 1


# --------------------------------------------------------------------------- #
# Auth guard                                                                  #
# --------------------------------------------------------------------------- #

class TestAuthGuard:
    def test_get_signed_out_redirects_to_login(self, client):
        response = client.get(url("add_expense"))
        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == url("login")

    def test_get_signed_out_shows_the_sign_in_page_not_the_form(self, client):
        response = client.get(url("add_expense"), follow_redirects=True)
        assert response.status_code == 200
        page = parse_page(response)
        assert page.find_all(attrs={"name": "email"}), "Expected the sign-in form"
        assert not page.find_all(attrs={"name": "amount"}), "The add form leaked"

    def test_post_valid_data_signed_out_redirects_to_login_and_adds_no_row(
        self, client, alice, today
    ):
        before = snapshot_db()
        response = post_add(client, valid_form(today))
        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == url("login")
        assert snapshot_db() == before, "A signed-out POST changed the database"
        assert db_rows() == []

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param({}, id="empty-body"),
            pytest.param({"amount": "abc", "category": "Travel", "date": "x"},
                         id="invalid-values"),
            pytest.param({"amount": "5", "category": "Food", "date": "2026-01-01",
                          "user_id": "1"}, id="forged-user-id"),
        ],
    )
    def test_post_other_data_signed_out_still_redirects_to_login(
        self, client, alice, data
    ):
        response = post_add(client, data)
        assert response.status_code == 302, (
            "The sign-in check must come before validation"
        )
        assert urlparse(response.headers["Location"]).path == url("login")
        assert db_rows() == []

    def test_get_signed_in_is_not_redirected(self, auth_client):
        assert auth_client.get(url("add_expense")).status_code == 200


# --------------------------------------------------------------------------- #
# GET /expenses/add                                                           #
# --------------------------------------------------------------------------- #

class TestAddExpenseForm:
    def test_get_returns_html_page(self, auth_client):
        response = auth_client.get(url("add_expense"))
        assert response.status_code == 200
        assert "text/html" in response.content_type

    def test_page_title_is_add_expense_spendly(self, form_page):
        titles = form_page.find_all("title")
        assert len(titles) == 1
        assert titles[0].text() == "Add expense — Spendly"

    def test_page_loads_expense_css_in_the_head(self, form_page):
        hrefs = [link.attrs.get("href") for link in form_page.find_all("link")
                 if link.attrs.get("rel") == "stylesheet"]
        assert url("static", filename="css/expense.css") in hrefs, hrefs

    def test_page_has_exactly_one_h1_add_expense(self, form_page):
        h1s = form_page.find_all("h1")
        assert len(h1s) == 1, f"Expected one <h1>, got {len(h1s)}"
        assert h1s[0].text() == "Add expense"
        assert "auth-title" in h1s[0].classes()

    def test_page_has_a_subtitle(self, form_page):
        subtitles = form_page.find_all(cls="auth-subtitle")
        assert len(subtitles) == 1
        assert subtitles[0].text(), "The subtitle is empty"

    def test_page_uses_the_single_card_auth_layout(self, form_page):
        form = add_form(form_page)
        card = ancestor(form, cls="auth-card")
        assert card is not None, "The form must sit in .auth-card"
        container = ancestor(card, cls="auth-container")
        assert container is not None, ".auth-card must sit in .auth-container"
        assert ancestor(container, cls="auth-section") is not None, (
            ".auth-container must sit in .auth-section"
        )
        headers = container.find_all(cls="auth-header")
        assert len(headers) == 1
        assert headers[0].find_all("h1"), "The <h1> belongs in .auth-header"

    def test_form_posts_back_to_the_add_expense_url(self, form_page):
        form = add_form(form_page)
        assert form.attrs.get("method", "").upper() == "POST"
        assert form.attrs.get("action") == url("add_expense")

    def test_form_has_four_form_groups_in_order(self, form_page):
        form = add_form(form_page)
        groups = form.find_all(cls="form-group")
        assert len(groups) == 4, f"Expected four .form-group blocks, got {len(groups)}"
        names = []
        for group in groups:
            controls = [n for n in group.descendants() if n.tag in ("input", "select")]
            assert len(controls) == 1, "Each .form-group holds one control"
            names.append(controls[0].attrs.get("name"))
        assert names == ["amount", "category", "date", "description"]

    @pytest.mark.parametrize(
        "name, label_text, tag",
        [
            ("amount", "Amount (₹)", "input"),
            ("category", "Category", "select"),
            ("date", "Date", "input"),
            ("description", "Description (optional)", "input"),
        ],
    )
    def test_each_control_has_its_own_label_for_it(
        self, form_page, name, label_text, tag
    ):
        ctl = control(form_page, name)
        assert ctl.tag == tag
        control_id = ctl.attrs.get("id")
        assert control_id, f"The {name} control needs an id for its label"
        labels = [lbl for lbl in form_page.find_all("label")
                  if lbl.attrs.get("for") == control_id]
        assert len(labels) == 1, f"Expected one <label for={control_id}>"
        assert labels[0].text() == label_text

    @pytest.mark.parametrize("name", ["amount", "category", "date", "description"])
    def test_each_control_uses_the_shared_form_input_class(self, form_page, name):
        assert "form-input" in control(form_page, name).classes()

    def test_amount_input_attributes(self, form_page):
        amount = control(form_page, "amount")
        assert amount.attrs.get("type") == "number"
        assert amount.attrs.get("step") == "0.01"
        assert amount.attrs.get("min") == "0.01"
        assert amount.attrs.get("inputmode") == "decimal"
        assert "required" in amount.attrs
        assert "autofocus" in amount.attrs
        assert amount.attrs.get("value", "") == "", "The amount starts empty"

    def test_category_select_is_required(self, form_page):
        assert "required" in control(form_page, "category").attrs

    def test_category_select_lists_placeholder_then_seven_categories_in_order(
        self, form_page
    ):
        opts = options(control(form_page, "category"))
        assert opts[0][0] == "", "The first option has an empty value"
        assert opts[0][1] == "Choose a category"
        assert [value for value, _t, _s in opts[1:]] == list(SPEC_CATEGORIES)
        assert [text for _v, text, _s in opts[1:]] == list(SPEC_CATEGORIES)
        assert len(opts) == 8

    def test_category_starts_with_no_category_selected(self, form_page):
        assert not [v for v in selected_categories(form_page) if v in SPEC_CATEGORIES]

    def test_date_input_is_prefilled_with_today_and_limited_to_today(
        self, auth_client, today
    ):
        page = parse_page(auth_client.get(url("add_expense")))
        ensure_same_day(today)
        date_input = control(page, "date")
        assert date_input.attrs.get("type") == "date"
        assert "required" in date_input.attrs
        assert date_input.attrs.get("value") == today.isoformat()
        assert date_input.attrs.get("max") == today.isoformat()

    def test_description_input_attributes(self, form_page):
        description = control(form_page, "description")
        assert description.attrs.get("type") == "text"
        assert description.attrs.get("maxlength") == "200"
        assert "required" not in description.attrs, "The description is optional"
        assert description.attrs.get("value", "") == ""

    def test_save_expense_submit_button_is_inside_the_form(self, form_page):
        form = add_form(form_page)
        buttons = [b for b in form.find_all("button") if b.text() == "Save expense"]
        assert len(buttons) == 1, "Expected one 'Save expense' button in the form"
        assert buttons[0].attrs.get("type", "submit") == "submit"
        assert "btn-submit" in buttons[0].classes()

    def test_cancel_link_points_to_the_profile_page(self, form_page):
        links = [a for a in form_page.find_all("a") if a.text() == "Cancel"]
        assert len(links) == 1, "Expected one 'Cancel' link"
        assert links[0].attrs.get("href") == url("profile")

    def test_cancel_link_opens_profile_and_saves_nothing(self, auth_client, form_page):
        cancel = [a for a in form_page.find_all("a") if a.text() == "Cancel"][0]
        response = auth_client.get(cancel.attrs["href"])
        assert response.status_code == 200
        assert "Recent expenses" in parse_page(response).text()
        assert db_rows() == []

    def test_old_placeholder_text_is_gone(self, auth_client):
        body = auth_client.get(url("add_expense")).get_data(as_text=True)
        assert "coming in Step 7" not in body
        assert "Add expense — coming" not in body

    def test_first_visit_shows_no_error_message(self, form_page):
        assert error_alerts(form_page) == []

    def test_form_has_no_user_id_field_hidden_or_otherwise(self, form_page):
        assert form_page.find_all(attrs={"name": "user_id"}) == []
        assert form_page.find_all(attrs={"id": "user_id"}) == []

    def test_page_extends_the_base_layout_for_a_signed_in_user(self, form_page):
        buttons = [b.text() for b in form_page.find_all("button")]
        assert "Sign out" in buttons, "Expected the signed-in navbar"
        links = [a.text() for a in form_page.find_all("a")]
        assert "Terms and Conditions" in links, "Expected the footer from base.html"

    def test_query_string_does_not_prefill_the_form(self, auth_client, today):
        response = auth_client.get(url("add_expense"), query_string={
            "amount": "99", "category": "Bills", "date": "2020-01-01",
            "description": "from the URL",
        })
        page = parse_page(response)
        ensure_same_day(today)
        assert response.status_code == 200
        assert field_value(page, "amount") == ""
        assert field_value(page, "description") == ""
        assert field_value(page, "date") == today.isoformat()
        assert not [v for v in selected_categories(page) if v in SPEC_CATEGORIES]

    def test_profile_add_expense_link_opens_the_form(self, auth_client):
        profile = parse_page(get_profile(auth_client))
        links = [a for a in profile.find_all("a")
                 if a.attrs.get("href") == url("add_expense")]
        assert links, "The profile page should link to /expenses/add"
        response = auth_client.get(links[0].attrs["href"])
        assert response.status_code == 200
        assert control(parse_page(response), "amount") is not None


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_valid_post_redirects_to_profile_with_no_date_range(
        self, auth_client, today
    ):
        response = post_add(auth_client, valid_form(today))
        assert response.status_code == 302
        location = urlparse(response.headers["Location"])
        assert location.path == url("profile")
        assert location.query == "", "The redirect must carry no date range"

    def test_valid_post_saves_one_row_with_the_posted_values(
        self, auth_client, alice, today
    ):
        post_add(auth_client, valid_form(today))
        rows = db_rows()
        assert len(rows) == 1, f"Expected one row, got {len(rows)}"
        row = rows[0]
        assert row["user_id"] == alice["id"]
        assert row["amount"] == pytest.approx(250.50)
        assert row["category"] == "Food"
        assert row["date"] == today.isoformat()
        assert row["description"] == "Lunch"

    def test_flash_is_shown_once_after_saving(self, auth_client, today):
        response = post_add(auth_client, valid_form(today), follow_redirects=True)
        assert response.status_code == 200
        page = parse_page(response)
        assert flash_texts(page) == [FLASH_TEXT]
        assert page.raw.count(FLASH_TEXT) == 1

    def test_flash_is_gone_after_refreshing_profile(self, auth_client, today):
        post_add(auth_client, valid_form(today), follow_redirects=True)
        refreshed = parse_page(get_profile(auth_client))
        assert flash_texts(refreshed) == []
        assert FLASH_TEXT not in refreshed.raw

    def test_refreshing_profile_does_not_add_a_second_row(self, auth_client, today):
        post_add(auth_client, valid_form(today), follow_redirects=True)
        get_profile(auth_client)
        page = parse_page(get_profile(auth_client))
        assert len(db_rows()) == 1
        assert len(table_rows(page)) == 1

    def test_profile_cards_show_the_new_expense(self, auth_client, today):
        page = parse_page(
            post_add(auth_client, valid_form(today), follow_redirects=True)
        )
        assert summary(page) == ("₹250.50", "1", "Food")

    def test_profile_table_shows_one_row_for_the_new_expense(
        self, auth_client, today
    ):
        page = parse_page(
            post_add(auth_client, valid_form(today), follow_redirects=True)
        )
        assert table_rows(page) == [[shown_date(today), "Lunch", "Food", "₹250.50"]]

    def test_second_expense_without_description_updates_cards_and_shows_dash(
        self, auth_client, today
    ):
        post_add(auth_client, valid_form(today))
        page = parse_page(post_add(
            auth_client,
            valid_form(today, amount="1200", category="Bills", description=""),
            follow_redirects=True,
        ))
        assert summary(page) == ("₹1,450.50", "2", "Bills")
        bills_rows = [r for r in table_rows(page) if r[2] == "Bills"]
        assert bills_rows == [[shown_date(today), EM_DASH, "Bills", "₹1,200.00"]]

    def test_second_expense_without_description_is_stored_as_null(
        self, auth_client, today
    ):
        post_add(auth_client, valid_form(today))
        post_add(auth_client, valid_form(today, amount="1200", category="Bills",
                                         description=""))
        last = db_rows()[-1]
        assert last["category"] == "Bills"
        assert last["description"] is None, "An empty description must be NULL"
        assert description_type(last["id"]) == "null"

    def test_each_save_creates_a_separate_row_for_the_same_user(
        self, auth_client, alice, today
    ):
        for _ in range(3):
            assert post_add(auth_client, valid_form(today)).status_code == 302
        rows = db_rows()
        assert len(rows) == 3
        assert len({row["id"] for row in rows}) == 3
        assert {row["user_id"] for row in rows} == {alice["id"]}

    @pytest.mark.parametrize("category", SPEC_CATEGORIES)
    def test_every_category_is_accepted_and_stored_as_sent(
        self, auth_client, today, category
    ):
        page = parse_page(post_add(
            auth_client, valid_form(today, category=category), follow_redirects=True
        ))
        assert [row["category"] for row in db_rows()] == [category]
        assert table_rows(page)[0][2] == category
        assert summary(page)[2] == category

    def test_expense_dated_in_the_past_is_accepted(self, auth_client, today):
        response = post_add(auth_client, valid_form(today, date="2024-02-29"))
        assert response.status_code == 302
        assert db_rows()[0]["date"] == "2024-02-29"


# --------------------------------------------------------------------------- #
# Values stored in the database                                               #
# --------------------------------------------------------------------------- #

class TestStoredValues:
    @pytest.mark.parametrize("description", ["", " ", "     ", "\t", " \t "], ids=_short)
    def test_blank_description_is_saved_as_null(
        self, auth_client, today, description
    ):
        response = post_add(auth_client, valid_form(today, description=description))
        assert response.status_code == 302
        (row,) = db_rows()
        assert row["description"] is None, (
            f"{description!r} must be saved as NULL, not {row['description']!r}"
        )
        assert description_type(row["id"]) == "null"

    def test_missing_description_field_is_saved_as_null(self, auth_client, today):
        response = post_add(auth_client, valid_form(today, description=None))
        assert response.status_code == 302, "The description is optional"
        (row,) = db_rows()
        assert row["description"] is None

    def test_blank_description_shows_a_dash_on_profile(self, auth_client, today):
        page = parse_page(post_add(
            auth_client, valid_form(today, description="   "), follow_redirects=True
        ))
        assert table_rows(page)[0][1] == EM_DASH

    def test_description_is_stored_without_surrounding_spaces(
        self, auth_client, today
    ):
        post_add(auth_client, valid_form(today, description="   Lunch   "))
        assert db_rows()[0]["description"].strip() == "Lunch"

    def test_description_with_unicode_is_stored_and_shown_unchanged(
        self, auth_client, today
    ):
        text = "Café ₹ 日本語 🍜"
        page = parse_page(post_add(
            auth_client, valid_form(today, description=text), follow_redirects=True
        ))
        assert db_rows()[0]["description"] == text
        assert table_rows(page)[0][1] == text

    @pytest.mark.parametrize(
        "field, padded, stored_column, stored",
        [
            ("amount", "  250.50  ", "amount", pytest.approx(250.5)),
            ("category", "  Food  ", "category", "Food"),
        ],
    )
    def test_fields_are_stripped_before_they_are_checked(
        self, auth_client, today, field, padded, stored_column, stored
    ):
        response = post_add(auth_client, valid_form(today, **{field: padded}))
        assert response.status_code == 302, f"A padded {field} should be accepted"
        assert db_rows()[0][stored_column] == stored

    def test_padded_date_is_accepted_and_stored_without_the_spaces(
        self, auth_client, today
    ):
        response = post_add(auth_client, valid_form(today, date="  2024-02-05  "))
        assert response.status_code == 302
        assert db_rows()[0]["date"] == "2024-02-05"

    def test_stored_date_is_zero_padded_year_month_day(self, auth_client, today):
        post_add(auth_client, valid_form(today, date="2024-03-05"))
        stored = db_rows()[0]["date"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", stored), stored
        assert stored == "2024-03-05"

    def test_date_without_zero_padding_is_never_stored_as_typed(
        self, auth_client, today
    ):
        # Either the date is refused or it is saved zero-padded; "2024-3-5" must
        # never reach the table, because Step 6 compares dates as text
        post_add(auth_client, valid_form(today, date="2024-3-5"))
        for row in db_rows():
            assert row["date"] == "2024-03-05", row["date"]

    def test_amount_is_stored_as_a_number(self, auth_client, today):
        post_add(auth_client, valid_form(today, amount="1234.5"))
        stored = db_rows()[0]["amount"]
        assert isinstance(stored, (int, float)), type(stored)
        assert stored == pytest.approx(1234.5)

    def test_created_at_is_filled_by_the_database(self, auth_client, today):
        post_add(auth_client, valid_form(today))
        assert db_rows()[0]["created_at"]


# --------------------------------------------------------------------------- #
# Validation errors, one rule at a time                                       #
# --------------------------------------------------------------------------- #

BAD_AMOUNTS = [
    "abc", "-5", "-0.50", "-0", "+5", "1e5", "1E5", "nan", "NaN", "inf", "-inf",
    "Infinity", "1,200", "10.999", "0.001", "5.", ".5", ".", "₹250", "$250",
    "250 rupees", "2 5", "1.2.3", "0x10", "1_000", "--5",
    "٣٠", "５０",
]

ZERO_AMOUNTS = ["0", "0.0", "0.00", "00", "000.00"]

TOO_BIG_AMOUNTS = [
    "10000000", "10000000.00", "10000000.01", "10000001", "99999999.99",
    "1" + "0" * 30, "9" * 400,
]

BAD_CATEGORIES = [
    "Travel", "food", "FOOD", "fOOD", "Foods", "Choose a category",
    "Food,Transport", "Food' OR '1'='1", "<b>Food</b>", "X" * 1000,
]

BAD_DATES = [
    "2026-13-45", "abc", "2026-02-30", "2025-02-29", "2026-00-10", "2026-09-31",
    "20260901", "2026/09/01", "09-01-2026", "2026-09-01T00:00:00", "2026-W36-2",
    "0000-01-01", "today", "2026-01-01 extra", "2026-01-01'; DROP TABLE expenses;--",
    "2026-01-01" * 100,
]

EMPTY_FIELD_CASES = [
    pytest.param({"amount": ""}, id="amount-empty"),
    pytest.param({"amount": "   "}, id="amount-spaces"),
    pytest.param({"amount": None}, id="amount-missing"),
    pytest.param({"category": ""}, id="category-empty-placeholder-option"),
    pytest.param({"category": "  "}, id="category-spaces"),
    pytest.param({"category": None}, id="category-missing"),
    pytest.param({"date": ""}, id="date-empty"),
    pytest.param({"date": "   "}, id="date-spaces"),
    pytest.param({"date": None}, id="date-missing"),
    pytest.param({"amount": "", "category": "", "date": ""}, id="all-three-empty"),
    pytest.param({"amount": None, "category": None, "date": None,
                  "description": None}, id="nothing-sent"),
]


class TestValidationErrors:
    @pytest.mark.parametrize("overrides", EMPTY_FIELD_CASES)
    def test_empty_amount_category_or_date_shows_the_fill_in_message(
        self, auth_client, today, overrides
    ):
        assert_rejected(auth_client, valid_form(today, **overrides), M_EMPTY, today)

    @pytest.mark.parametrize("amount", BAD_AMOUNTS, ids=_short)
    def test_amount_not_in_digits_dot_two_decimals_form_shows_valid_amount_message(
        self, auth_client, today, amount
    ):
        assert_rejected(auth_client, valid_form(today, amount=amount), M_AMOUNT, today)

    @pytest.mark.parametrize("amount", ZERO_AMOUNTS)
    def test_zero_amount_shows_greater_than_zero_message(
        self, auth_client, today, amount
    ):
        assert_rejected(auth_client, valid_form(today, amount=amount), M_ZERO, today)

    @pytest.mark.parametrize("amount", TOO_BIG_AMOUNTS, ids=_short)
    def test_amount_above_the_maximum_shows_cannot_be_more_than_message(
        self, auth_client, today, amount
    ):
        assert_rejected(auth_client, valid_form(today, amount=amount), M_MAX, today)

    @pytest.mark.parametrize("category", BAD_CATEGORIES, ids=_short)
    def test_category_outside_the_list_shows_choose_from_list_message(
        self, auth_client, today, category
    ):
        assert_rejected(
            auth_client, valid_form(today, category=category), M_CATEGORY, today
        )

    @pytest.mark.parametrize("bad_date", BAD_DATES, ids=_short)
    def test_date_that_is_not_a_real_date_shows_valid_date_message(
        self, auth_client, today, bad_date
    ):
        assert_rejected(auth_client, valid_form(today, date=bad_date), M_DATE, today)

    @pytest.mark.parametrize(
        "offset",
        [
            pytest.param("@+1", id="tomorrow"),
            pytest.param("@+2", id="day-after-tomorrow"),
            pytest.param("@+30", id="next-month"),
            pytest.param("@+365", id="next-year"),
            pytest.param("2999-01-01", id="year-2999"),
            pytest.param("9999-12-31", id="year-9999"),
        ],
    )
    def test_date_after_today_shows_cannot_be_in_the_future_message(
        self, auth_client, today, offset
    ):
        assert_rejected(auth_client, valid_form(today, date=offset), M_FUTURE, today)

    @pytest.mark.parametrize(
        "description",
        [
            pytest.param("x" * 201, id="201-chars"),
            pytest.param("x" * 202, id="202-chars"),
            pytest.param("x" * 1000, id="1000-chars"),
            pytest.param("x" * 10000, id="10000-chars"),
            pytest.param("é" * 201, id="201-accented-chars"),
            pytest.param("₹" * 201, id="201-rupee-signs"),
            pytest.param("word " * 40 + "x", id="201-chars-with-spaces"),
            pytest.param("  " + "x" * 201 + "  ", id="201-chars-padded"),
        ],
    )
    def test_description_longer_than_200_characters_shows_too_long_message(
        self, auth_client, today, description
    ):
        assert_rejected(
            auth_client, valid_form(today, description=description), M_DESC, today
        )

    def test_error_page_keeps_the_date_limit_at_today(self, auth_client, today):
        page = assert_rejected(
            auth_client, valid_form(today, amount="abc"), M_AMOUNT, today
        )
        assert control(page, "date").attrs.get("max") == today.isoformat()

    def test_error_page_still_lists_the_placeholder_and_seven_categories(
        self, auth_client, today
    ):
        page = assert_rejected(
            auth_client, valid_form(today, amount="abc"), M_AMOUNT, today
        )
        opts = options(control(page, "category"))
        assert [text for _v, text, _s in opts] == ["Choose a category", *SPEC_CATEGORIES]

    def test_error_message_sits_at_the_top_of_the_card_before_the_form(
        self, auth_client, today
    ):
        page = assert_rejected(
            auth_client, valid_form(today, amount="abc"), M_AMOUNT, today
        )
        form = add_form(page)
        card = ancestor(form, cls="auth-card")
        assert card is not None
        alert = error_alerts(page)[0]
        assert ancestor(alert, cls="auth-card") is card, "The alert belongs in the card"
        order = list(card.descendants())
        assert order.index(alert) < order.index(form)

    def test_error_page_has_no_old_placeholder_text(self, auth_client, today):
        page = assert_rejected(
            auth_client, valid_form(today, amount="abc"), M_AMOUNT, today
        )
        assert "coming in Step 7" not in page.raw

    def test_form_is_empty_again_on_a_fresh_visit_after_an_error(
        self, auth_client, today
    ):
        assert_rejected(auth_client, valid_form(today, amount="abc"), M_AMOUNT, today)
        page = parse_page(auth_client.get(url("add_expense")))
        assert error_alerts(page) == []
        assert field_value(page, "amount") == ""
        assert field_value(page, "description") == ""

    def test_corrected_form_saves_after_an_error(self, auth_client, today):
        assert_rejected(auth_client, valid_form(today, amount="abc"), M_AMOUNT, today)
        response = post_add(auth_client, valid_form(today))
        assert response.status_code == 302
        assert len(db_rows()) == 1

    def test_several_failed_posts_add_no_rows(self, auth_client, today):
        for overrides, message in [
            ({"amount": ""}, M_EMPTY),
            ({"amount": "abc"}, M_AMOUNT),
            ({"amount": "0"}, M_ZERO),
            ({"amount": "10000000"}, M_MAX),
            ({"category": "Travel"}, M_CATEGORY),
            ({"date": "abc"}, M_DATE),
            ({"date": "@+1"}, M_FUTURE),
            ({"description": LONG_DESCRIPTION}, M_DESC),
        ]:
            assert_rejected(auth_client, valid_form(today, **overrides), message, today)
        assert db_rows() == []


# --------------------------------------------------------------------------- #
# Rule order                                                                  #
# --------------------------------------------------------------------------- #

ALL_BAD_AFTER_AMOUNT = {"category": "Travel", "date": "abc", "description": LONG_DESCRIPTION}

RULE_ORDER_CASES = [
    pytest.param({"amount": "", "category": "Travel"}, M_EMPTY,
                 id="empty-amount-beats-bad-category"),
    pytest.param({"amount": "", **ALL_BAD_AFTER_AMOUNT}, M_EMPTY,
                 id="empty-amount-beats-everything"),
    pytest.param({"date": "", "amount": "abc"}, M_EMPTY,
                 id="empty-date-beats-bad-amount"),
    pytest.param({"category": "", "amount": "0"}, M_EMPTY,
                 id="empty-category-beats-zero-amount"),
    pytest.param({"amount": "abc", **ALL_BAD_AFTER_AMOUNT}, M_AMOUNT,
                 id="bad-amount-beats-category-date-description"),
    pytest.param({"amount": "0.001", "date": "@+1"}, M_AMOUNT,
                 id="three-decimals-is-a-format-error-not-zero"),
    pytest.param({"amount": "0", **ALL_BAD_AFTER_AMOUNT}, M_ZERO,
                 id="zero-beats-category-date-description"),
    pytest.param({"amount": "10000000", **ALL_BAD_AFTER_AMOUNT}, M_MAX,
                 id="too-big-beats-category-date-description"),
    pytest.param(ALL_BAD_AFTER_AMOUNT, M_CATEGORY,
                 id="bad-category-beats-date-description"),
    pytest.param({"category": "Travel", "date": "@+1", "description": LONG_DESCRIPTION},
                 M_CATEGORY, id="bad-category-beats-future-date"),
    pytest.param({"date": "abc", "description": LONG_DESCRIPTION}, M_DATE,
                 id="invalid-date-beats-description"),
    pytest.param({"date": "@+1", "description": LONG_DESCRIPTION}, M_FUTURE,
                 id="future-date-beats-description"),
]


class TestRuleOrder:
    @pytest.mark.parametrize("overrides, message", RULE_ORDER_CASES)
    def test_first_failing_rule_decides_the_message(
        self, auth_client, today, overrides, message
    ):
        assert_rejected(auth_client, valid_form(today, **overrides), message, today)

    def test_empty_amount_with_travel_category_shows_the_first_message_only(
        self, auth_client, today
    ):
        page = assert_rejected(
            auth_client,
            valid_form(today, amount="", category="Travel"),
            M_EMPTY,
            today,
        )
        assert M_CATEGORY not in page.raw


# --------------------------------------------------------------------------- #
# Boundaries                                                                  #
# --------------------------------------------------------------------------- #

ACCEPTED_AMOUNTS = [
    ("250", 250.0),
    ("250.5", 250.5),
    ("250.50", 250.5),
    ("5.00", 5.0),
    ("1", 1.0),
    ("0.01", 0.01),
    ("0.10", 0.10),
    ("007", 7.0),
    ("1234567.89", 1234567.89),
    ("9999999", 9999999.0),
    ("9999999.98", 9999999.98),
    ("9999999.99", 9999999.99),
]


class TestBoundaries:
    @pytest.mark.parametrize("text, expected", ACCEPTED_AMOUNTS, ids=_short)
    def test_valid_amount_is_accepted_stored_and_shown_on_profile(
        self, auth_client, today, text, expected
    ):
        response = post_add(
            auth_client, valid_form(today, amount=text), follow_redirects=True
        )
        assert response.status_code == 200
        assert len(db_rows()) == 1, f"{text!r} should have been accepted"
        assert db_rows()[0]["amount"] == pytest.approx(expected)
        page = parse_page(response)
        assert summary(page)[0] == money(expected)

    def test_maximum_amount_9999999_99_shows_as_formatted_rupees(
        self, auth_client, today
    ):
        page = parse_page(post_add(
            auth_client, valid_form(today, amount="9999999.99"), follow_redirects=True
        ))
        assert "₹9,999,999.99" in page.tokens()
        assert table_rows(page)[0][3] == "₹9,999,999.99"

    @pytest.mark.parametrize(
        "description",
        [
            pytest.param("x" * 200, id="200-chars"),
            pytest.param("x" * 199, id="199-chars"),
            pytest.param("é" * 200, id="200-accented-chars"),
            pytest.param("₹" * 200, id="200-rupee-signs"),
            pytest.param("word " * 39 + "x" * 5, id="200-chars-with-spaces"),
            pytest.param("  " + "x" * 200 + "  ", id="200-chars-padded-with-spaces"),
            pytest.param("a", id="1-char"),
        ],
    )
    def test_description_up_to_200_characters_is_accepted(
        self, auth_client, today, description
    ):
        response = post_add(auth_client, valid_form(today, description=description))
        assert response.status_code == 302, "A description of up to 200 characters is valid"
        (row,) = db_rows()
        assert row["description"].strip() == description.strip()

    def test_todays_date_is_accepted(self, auth_client, today):
        response = post_add(auth_client, valid_form(today, date=today.isoformat()))
        assert response.status_code == 302
        assert db_rows()[0]["date"] == today.isoformat()

    def test_yesterdays_date_is_accepted(self, auth_client, today):
        yesterday = (today - timedelta(days=1)).isoformat()
        response = post_add(auth_client, valid_form(today, date=yesterday))
        assert response.status_code == 302
        assert db_rows()[0]["date"] == yesterday

    def test_leap_day_is_accepted(self, auth_client, today):
        response = post_add(auth_client, valid_form(today, date="2024-02-29"))
        assert response.status_code == 302
        assert db_rows()[0]["date"] == "2024-02-29"


# --------------------------------------------------------------------------- #
# Security                                                                    #
# --------------------------------------------------------------------------- #

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><script>alert(1)</script>',
    "<img src=x onerror=alert(1)>",
    "' onfocus='alert(1)' x='",
    "&lt;b&gt;already escaped&lt;/b&gt;",
]

SQL_TEXTS = [
    "x'); DROP TABLE expenses;--",
    "'; DROP TABLE users;--",
    "Robert'); DELETE FROM expenses;--",
    "1 OR 1=1",
    '" OR ""="',
]

ECHO_PAYLOAD = '"><script>alert(2)</script>'


class TestSecurity:
    # -- whose expense ---------------------------------------------------- #

    def test_forged_user_id_form_field_saves_under_the_signed_in_user(
        self, client, empty_db, today
    ):
        victim = make_user("Victim", "victim@example.com")
        me = make_user("Mallory", "mallory@example.com")
        assert victim["id"] != me["id"]
        sign_in(client, me)
        response = post_add(client, valid_form(today, user_id=str(victim["id"])))
        assert response.status_code == 302
        assert db_rows(victim["id"]) == [], "The row went to the forged user"
        assert len(db_rows(me["id"])) == 1

    @pytest.mark.parametrize("forged", ["9999", "0", "-1", "abc", "1; DROP TABLE users"],
                             ids=_short)
    def test_any_forged_user_id_value_is_ignored(
        self, auth_client, alice, today, forged
    ):
        response = post_add(auth_client, valid_form(today, user_id=forged))
        assert response.status_code == 302
        rows = db_rows()
        assert [row["user_id"] for row in rows] == [alice["id"]]

    def test_user_id_in_the_query_string_is_ignored(self, client, empty_db, today):
        victim = make_user("Victim", "victim@example.com")
        me = make_user("Mallory", "mallory@example.com")
        sign_in(client, me)
        response = client.post(
            url("add_expense"),
            data=valid_form(today),
            query_string={"user_id": victim["id"]},
        )
        assert response.status_code == 302
        assert db_rows(victim["id"]) == []
        assert len(db_rows(me["id"])) == 1

    def test_forged_user_id_does_not_change_a_rejected_post(
        self, auth_client, today
    ):
        assert_rejected(
            auth_client,
            valid_form(today, amount="abc", user_id="1"),
            M_AMOUNT,
            today,
        )

    # -- HTML in typed values -------------------------------------------- #

    @pytest.mark.parametrize("payload", XSS_PAYLOADS, ids=_short)
    def test_html_in_description_is_stored_as_text_and_escaped_on_profile(
        self, auth_client, today, payload
    ):
        response = post_add(
            auth_client, valid_form(today, description=payload), follow_redirects=True
        )
        assert response.status_code == 200
        (row,) = db_rows()
        assert row["description"] == payload
        page = parse_page(response)
        assert payload not in page.raw, "The description reached the page unescaped"
        assert_no_active_content(page)
        assert table_rows(page)[0][1] == payload, (
            "The table should show the description as plain text"
        )

    def test_script_tag_in_description_appears_escaped_in_the_page_source(
        self, auth_client, today
    ):
        response = post_add(
            auth_client,
            valid_form(today, description="<script>alert(1)</script>"),
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body

    @pytest.mark.parametrize(
        "overrides, message",
        [
            pytest.param({"amount": ECHO_PAYLOAD}, M_AMOUNT, id="amount"),
            pytest.param({"category": ECHO_PAYLOAD}, M_CATEGORY, id="category"),
            pytest.param({"date": ECHO_PAYLOAD}, M_DATE, id="date"),
            pytest.param({"description": ECHO_PAYLOAD, "amount": "abc"}, M_AMOUNT,
                         id="description-with-other-error"),
            pytest.param({"description": ECHO_PAYLOAD * 10}, M_DESC,
                         id="description-too-long"),
        ],
    )
    def test_html_typed_into_any_field_is_escaped_when_echoed_into_the_form(
        self, auth_client, today, overrides, message
    ):
        page = assert_rejected(
            auth_client, valid_form(today, **overrides), message, today
        )
        assert ECHO_PAYLOAD not in page.raw, "A typed value was printed unescaped"
        assert_no_active_content(page)

    @pytest.mark.parametrize("payload", XSS_PAYLOADS, ids=_short)
    def test_description_payload_survives_a_round_trip_through_the_form(
        self, auth_client, today, payload
    ):
        page = assert_rejected(
            auth_client,
            valid_form(today, description=payload, amount="abc"),
            M_AMOUNT,
            today,
        )
        assert field_value(page, "description") == payload
        assert payload not in page.raw
        assert_no_active_content(page)

    # -- SQL in typed values --------------------------------------------- #

    @pytest.mark.parametrize("text", SQL_TEXTS, ids=_short)
    def test_sql_text_in_description_is_stored_as_plain_text(
        self, auth_client, today, text
    ):
        response = post_add(
            auth_client, valid_form(today, description=text), follow_redirects=True
        )
        assert response.status_code == 200
        assert table_exists("expenses"), "The expenses table was dropped"
        assert table_exists("users"), "The users table was dropped"
        (row,) = db_rows()
        assert row["description"] == text
        assert table_rows(parse_page(response))[0][1] == text

    def test_adding_still_works_after_a_sql_text_description(self, auth_client, today):
        post_add(auth_client, valid_form(today, description="x'); DROP TABLE expenses;--"))
        post_add(auth_client, valid_form(today, description="second"))
        assert [row["description"] for row in db_rows()] == [
            "x'); DROP TABLE expenses;--", "second",
        ]

    @pytest.mark.parametrize(
        "overrides, message",
        [
            pytest.param({"amount": "1; DROP TABLE expenses"}, M_AMOUNT, id="amount"),
            pytest.param({"category": "Food'; DROP TABLE expenses;--"}, M_CATEGORY,
                         id="category"),
            pytest.param({"date": "2026-01-01'; DROP TABLE expenses;--"}, M_DATE,
                         id="date"),
        ],
    )
    def test_sql_text_in_other_fields_is_rejected_and_tables_survive(
        self, auth_client, today, overrides, message
    ):
        assert_rejected(auth_client, valid_form(today, **overrides), message, today)
        assert table_exists("expenses")
        assert table_exists("users")

    # -- other users' data ------------------------------------------------ #

    def test_each_user_sees_only_their_own_new_expenses(self, spendly_app, empty_db, today):
        alice = make_user("Alice Tester", "alice@example.com")
        bob = make_user("Bob Other", "bob@example.com")
        alice_client = sign_in(spendly_app.test_client(), alice)
        bob_client = sign_in(spendly_app.test_client(), bob)
        post_add(alice_client, valid_form(today, amount="100", description="alice-only"))
        post_add(bob_client, valid_form(today, amount="7", category="Bills",
                                        description="bob-only"))

        alice_page = parse_page(get_profile(alice_client))
        bob_page = parse_page(get_profile(bob_client))
        assert summary(alice_page) == ("₹100.00", "1", "Food")
        assert summary(bob_page) == ("₹7.00", "1", "Bills")
        assert [r[1] for r in table_rows(alice_page)] == ["alice-only"]
        assert [r[1] for r in table_rows(bob_page)] == ["bob-only"]
        assert "bob-only" not in alice_page.raw
        assert "alice-only" not in bob_page.raw

    def test_demo_user_does_not_see_the_new_users_expense_and_the_reverse(
        self, spendly_app, empty_db, today
    ):
        db_module.seed_db()
        demo = db_module.get_user_by_email("demo@spendly.com")
        assert demo is not None, "seed_db() should create the demo user"
        demo_rows_before = db_rows(demo["id"])
        newcomer = make_user("New Person", "new@example.com")
        new_client = sign_in(spendly_app.test_client(), newcomer)
        post_add(new_client, valid_form(today, amount="321", description="newcomer-only"))

        demo_client = sign_in(
            spendly_app.test_client(),
            {"email": "demo@spendly.com", "password": "demo123"},
        )
        demo_page = parse_page(get_profile(demo_client))
        assert "newcomer-only" not in demo_page.raw
        assert summary(demo_page)[1] == str(len(demo_rows_before))
        assert db_rows(demo["id"]) == demo_rows_before, "Demo data changed"

        new_page = parse_page(get_profile(new_client))
        assert summary(new_page) == ("₹321.00", "1", "Food")
        assert [r[1] for r in table_rows(new_page)] == ["newcomer-only"]


# --------------------------------------------------------------------------- #
# Other methods                                                               #
# --------------------------------------------------------------------------- #

class TestOtherMethods:
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_other_methods_signed_in_answer_405_and_save_nothing(
        self, auth_client, today, method
    ):
        response = getattr(auth_client, method)(
            url("add_expense"), data=valid_form(today)
        )
        assert response.status_code == 405
        allowed = {m.strip() for m in response.headers.get("Allow", "").split(",")}
        assert {"GET", "POST"} <= allowed, f"Allow header was {allowed}"
        assert db_rows() == []

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_other_methods_signed_out_answer_405_and_save_nothing(
        self, client, alice, today, method
    ):
        response = getattr(client, method)(url("add_expense"), data=valid_form(today))
        assert response.status_code == 405
        assert db_rows() == []


# --------------------------------------------------------------------------- #
# Neighbouring placeholder routes                                             #
# --------------------------------------------------------------------------- #

class TestNeighbourRoutesUnchanged:
    def test_edit_expense_still_returns_its_placeholder_text(self, auth_client):
        response = auth_client.get("/expenses/1/edit")
        assert response.status_code == 200
        assert "Edit expense — coming in Step 8" in response.get_data(as_text=True)

    def test_delete_expense_still_returns_its_placeholder_text(self, auth_client):
        response = auth_client.get("/expenses/1/delete")
        assert response.status_code == 200
        assert "Delete expense — coming in Step 9" in response.get_data(as_text=True)

    @pytest.mark.parametrize("path", ["/expenses/1/edit", "/expenses/1/delete"])
    def test_edit_and_delete_signed_out_still_redirect_to_login(self, client, path):
        response = client.get(path)
        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == url("login")

    def test_a_saved_expense_is_not_touched_by_visiting_edit_or_delete(
        self, auth_client, today
    ):
        post_add(auth_client, valid_form(today))
        before = db_rows()
        row_id = before[0]["id"]
        auth_client.get(f"/expenses/{row_id}/edit")
        auth_client.get(f"/expenses/{row_id}/delete")
        assert db_rows() == before


# --------------------------------------------------------------------------- #
# Step 6 interaction: the date filter                                         #
# --------------------------------------------------------------------------- #

class TestDateFilterInteraction:
    @staticmethod
    def _last_month_day(today):
        first_of_month = today.replace(day=1)
        return (first_of_month - timedelta(days=1)).replace(day=15)

    def test_last_month_expense_is_counted_on_the_unfiltered_profile(
        self, auth_client, today
    ):
        last_month = self._last_month_day(today)
        page = parse_page(post_add(
            auth_client, valid_form(today, date=last_month.isoformat()),
            follow_redirects=True,
        ))
        assert summary(page) == ("₹250.50", "1", "Food")
        assert table_rows(page)[0][0] == shown_date(last_month)

    def test_last_month_expense_is_left_out_by_a_range_from_the_first_of_this_month(
        self, auth_client, today
    ):
        last_month = self._last_month_day(today)
        post_add(auth_client, valid_form(today, date=last_month.isoformat()))
        first_of_month = today.replace(day=1).isoformat()
        page = parse_page(get_profile(auth_client, date_from=first_of_month))
        ensure_same_day(today)
        assert summary(page) == ("₹0.00", "0", EM_DASH)
        assert table_rows(page) == []

    def test_last_month_expense_is_left_out_by_the_this_month_preset(
        self, auth_client, today
    ):
        last_month = self._last_month_day(today)
        post_add(auth_client, valid_form(today, date=last_month.isoformat()))
        unfiltered = parse_page(get_profile(auth_client))
        href = preset_link(unfiltered, "This month").attrs["href"]
        page = parse_page(auth_client.get(href))
        ensure_same_day(today)
        assert summary(page) == ("₹0.00", "0", EM_DASH)
        assert table_rows(page) == []

    def test_this_month_range_keeps_todays_expense_and_drops_last_months(
        self, auth_client, today
    ):
        last_month = self._last_month_day(today)
        post_add(auth_client, valid_form(today, amount="100", description="now"))
        post_add(auth_client, valid_form(today, amount="40", category="Bills",
                                         date=last_month.isoformat(),
                                         description="before"))
        first_of_month = today.replace(day=1).isoformat()
        page = parse_page(get_profile(auth_client, date_from=first_of_month))
        ensure_same_day(today)
        assert summary(page) == ("₹100.00", "1", "Food")
        assert [r[1] for r in table_rows(page)] == ["now"]

    def test_range_ending_last_month_includes_the_last_month_expense(
        self, auth_client, today
    ):
        last_month = self._last_month_day(today)
        post_add(auth_client, valid_form(today, date=last_month.isoformat()))
        last_day = (today.replace(day=1) - timedelta(days=1)).isoformat()
        page = parse_page(get_profile(auth_client, date_to=last_day))
        ensure_same_day(today)
        assert summary(page) == ("₹250.50", "1", "Food")

    def test_one_day_range_finds_an_expense_saved_on_that_day(self, auth_client, today):
        post_add(auth_client, valid_form(today, date="2024-02-05"))
        page = parse_page(
            get_profile(auth_client, date_from="2024-02-05", date_to="2024-02-05")
        )
        assert summary(page) == ("₹250.50", "1", "Food")


# --------------------------------------------------------------------------- #
# Stylesheet                                                                  #
# --------------------------------------------------------------------------- #

class TestStylesheet:
    def test_expense_css_is_served(self, client):
        response = client.get(url("static", filename="css/expense.css"))
        assert response.status_code == 200
        assert response.get_data(as_text=True).strip(), "expense.css is empty"

    def test_expense_css_starts_with_a_banner_comment(self, client):
        css = client.get(url("static", filename="css/expense.css")).get_data(as_text=True)
        assert css.lstrip().startswith("/*"), "Expected a banner comment at the top"

    def test_expense_css_contains_no_hex_colour_values(self, client):
        css = client.get(url("static", filename="css/expense.css")).get_data(as_text=True)
        assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == []


# --------------------------------------------------------------------------- #
# The spec's "Definition of done" walk-through                                #
# --------------------------------------------------------------------------- #

class TestSpecWalkthrough:
    def test_register_sign_in_then_add_two_expenses(self, spendly_app, empty_db, today):
        client = spendly_app.test_client()
        registered = client.post(url("register"), data={
            "name": "Dana Walker", "email": "dana@example.com", "password": PASSWORD,
        })
        assert registered.status_code == 302
        assert urlparse(registered.headers["Location"]).path == url("login")
        signed_in = client.post(url("login"), data={
            "email": "dana@example.com", "password": PASSWORD,
        })
        assert signed_in.status_code == 302
        user_id = db_module.get_user_by_email("dana@example.com")["id"]

        # The empty state links to the form
        profile = parse_page(get_profile(client))
        assert summary(profile) == ("₹0.00", "0", EM_DASH)
        assert table_rows(profile) == []
        links = [a for a in profile.find_all("a")
                 if a.attrs.get("href") == url("add_expense")]
        assert links, "The profile page should link to /expenses/add"

        # Open the form through the link
        form_response = client.get(links[0].attrs["href"])
        assert form_response.status_code == 200
        assert "coming in Step 7" not in form_response.get_data(as_text=True)

        # First expense
        first = parse_page(post_add(
            client, valid_form(today, amount="250.50", category="Food",
                               description="Lunch"),
            follow_redirects=True,
        ))
        assert flash_texts(first) == [FLASH_TEXT]
        assert summary(first) == ("₹250.50", "1", "Food")
        assert table_rows(first) == [[shown_date(today), "Lunch", "Food", "₹250.50"]]

        # Refresh: no second row, no message
        refreshed = parse_page(get_profile(client))
        assert flash_texts(refreshed) == []
        assert len(table_rows(refreshed)) == 1

        # Second expense, description left empty
        second = parse_page(post_add(
            client, valid_form(today, amount="1200", category="Bills", description=""),
            follow_redirects=True,
        ))
        assert summary(second) == ("₹1,450.50", "2", "Bills")
        assert [EM_DASH] == [r[1] for r in table_rows(second) if r[2] == "Bills"]

        # What is in the table
        rows = db_rows()
        assert len(rows) == 2
        assert rows[-1]["description"] is None
        assert {row["user_id"] for row in rows} == {user_id}
        for row in rows:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]), row["date"]
