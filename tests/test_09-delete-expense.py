"""Tests for Step 9: Delete Expense.

Based on .claude/specs/09-delete-expense.md.

Test plan
---------
* remove_expense(expense_id, user_id): True when a row went, False when none
  matched, filters on id and user_id, deletes one row only, missing id, a second
  call, ids never reused, SQL text as arguments, no schema change.
* Route set-up: the delete_expense endpoint, its expense_id variable, GET and
  POST only.
* Auth guard: signed-out GET and POST go to /login and delete nothing.
* GET confirmation page for the user's own expense: title, one <h1>, "This
  cannot be undone", the summary list (date, description or the dash, category,
  amount), the POST form and its single button, the Cancel link, no inputs, no
  autofocus, no placeholder text, no dialog or confirm().
* GET never deletes: repeated GETs, HEAD, prefetch headers, query strings.
* POST: redirect to /profile with no query string, the row gone, exactly one
  row gone, "Expense deleted." flashed once, profile cards / table / category
  breakdown updated, the empty state after the last delete, body and query
  fields ignored, ids not reused.
* Second POST for the same expense: 404, nothing flashed, nothing else deleted.
  GET after a delete: 404.
* Ownership: GET and POST for another user's expense (a registered user and the
  seeded demo user) answer 404, show none of its values, leave the row, give the
  same answer as a missing id and never reach remove_expense().
* Ids: a missing id, an id above 2**63 - 1 and a non-numeric id answer 404.
* Other methods (PUT, PATCH, DELETE) answer 405.
* Profile page: a "Delete" link beside "Edit" in every row, its classes, label,
  icon and text, no form in the row, the link opens the confirmation page.
* Escaping on the confirmation page and in the link's aria-label.
* Date range: the links stay on a filtered profile, the redirect carries no
  range.
* Neighbours: /expenses/add and /expenses/<id>/edit still flash their messages
  and the edit page has no delete control.
* Static checks the spec lists: no "execute" and no "coming in Step" in
  app.py, no hex colours in expense.css and profile.css, the new template.
* A walk through the spec's "Definition of done" set-up.

Safety: database.db.DB_PATH is pointed at a throwaway file before app.py is
imported (importing it runs init_db() and seed_db()) and again, per test, at a
fresh file under tmp_path. The developer's expense_tracker.db is never opened.
"""

import atexit
import inspect
import re
import shutil
import sys
import tempfile
from datetime import date
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
_IMPORT_TMP = tempfile.mkdtemp(prefix="spendly-import-09-")
atexit.register(shutil.rmtree, _IMPORT_TMP, ignore_errors=True)
if "app" not in sys.modules or Path(db_module.DB_PATH).resolve() == _REAL_DB_PATH:
    db_module.DB_PATH = Path(_IMPORT_TMP) / "import_time.db"

import app as app_module  # noqa: E402

PASSWORD = "password123"
DEMO_EMAIL = "demo@spendly.com"
DEMO_PASSWORD = "demo123"
EM_DASH = "—"
SPEC_CATEGORIES = (
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
)

PAGE_TITLE = "Delete expense — Spendly"
FLASH_DELETED = "Expense deleted."
FLASH_ADDED = "Expense added."
FLASH_UPDATED = "Expense updated."

# A fixed past date, so what the pages print does not depend on today
SAMPLE_DAY = "2026-09-24"
SAMPLE_SHOWN = "24 Sep 2026"

MAX_SQLITE_ID = 2**63 - 1

# Text that must never reach a page unescaped
PAYLOADS = [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "' onmouseover='alert(1)",
    '" autofocus onfocus="alert(1)',
    "&lt;b&gt;bold&lt;/b&gt;",
]


# --------------------------------------------------------------------------- #
# A tiny HTML tree, so tests read the page by structure and not by raw text   #
# --------------------------------------------------------------------------- #

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
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


def position(page, node):
    """Index of a node in document order, to check what comes before what."""
    for index, candidate in enumerate(page.descendants()):
        if candidate is node:
            return index
    raise AssertionError(f"<{node.tag}> is not in the page")


def assert_no_active_content(page):
    for node in page.descendants():
        on_attrs = [a for a in node.attrs if a.startswith("on")]
        assert not on_attrs, f"<{node.tag}> carries an event handler: {on_attrs}"
        assert node.tag != "img", "An <img> was injected into the page"
        assert "autofocus" not in node.attrs, f"<{node.tag}> has autofocus"
        if node.tag == "script":
            assert not any(
                "alert" in child for child in node.children if isinstance(child, str)
            ), "An injected <script> reached the page"


# --------------------------------------------------------------------------- #
# Page readers                                                                #
# --------------------------------------------------------------------------- #

DELETE_HREF = re.compile(r"^/expenses/(\d+)/delete$")
EDIT_HREF = re.compile(r"^/expenses/(\d+)/edit$")


def page_title(page):
    titles = page.find_all("title")
    assert len(titles) == 1, f"Expected one <title>, got {len(titles)}"
    return titles[0].text()


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
            # Date, description, category, amount. The fifth cell is the
            # Actions column, read separately
            rows.append(cells[:4])
    return rows


def category_names(page):
    return [node.text() for node in page.find_all(cls="profile-category-name")]


def summary_rows(page):
    """The (label, value) pairs of the confirmation page's <dl>."""
    lists = page.find_all("dl", cls="expense-summary")
    assert len(lists) == 1, f"Expected one dl.expense-summary, got {len(lists)}"
    terms = lists[0].find_all("dt")
    values = lists[0].find_all("dd")
    assert len(terms) == len(values) == 4, "Expected four <dt>/<dd> rows"
    return [(dt.text(), dd.text()) for dt, dd in zip(terms, values)]


def delete_form(page, expense_id):
    action = delete_url(expense_id)
    forms = [
        form
        for form in page.find_all("form")
        if urlparse(form.attrs.get("action", "")).path == action
    ]
    assert len(forms) == 1, f"Expected one form posting to {action}, got {len(forms)}"
    return forms[0]


def delete_links(page):
    """Every (expense id, <a>) pair whose href is a delete URL."""
    found = []
    for link in page.find_all("a"):
        match = DELETE_HREF.match(urlparse(link.attrs.get("href", "")).path)
        if match:
            found.append((int(match.group(1)), link))
    return found


def delete_link_for(page, expense_id):
    links = [link for found_id, link in delete_links(page) if found_id == expense_id]
    assert len(links) == 1, f"Expected one Delete link for {expense_id}: {len(links)}"
    return links[0]


def edit_link_for(page, expense_id):
    links = []
    for link in page.find_all("a"):
        match = EDIT_HREF.match(urlparse(link.attrs.get("href", "")).path)
        if match and int(match.group(1)) == expense_id:
            links.append(link)
    assert len(links) == 1, f"Expected one Edit link for {expense_id}: {len(links)}"
    return links[0]


def action_cell(page, expense_id):
    cell = ancestor(delete_link_for(page, expense_id), tag="td")
    assert cell is not None, "The Delete link is not inside a table cell"
    return cell


def money(amount):
    return f"₹{amount:,.2f}"


def shown_date(day):
    # What the format_date filter prints by default, e.g. "24 Sep 2026"
    return day.strftime("%d %b %Y")


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


def url(endpoint, **values):
    with app_module.app.test_request_context():
        return url_for(endpoint, **values)


def delete_url(expense_id):
    return url("delete_expense", expense_id=expense_id)


def raw_delete_url(segment):
    """The delete URL with any text in place of the id, for non-numeric ids."""
    return delete_url(7).replace("/7/", f"/{segment}/")


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


# seed_db() does nothing once a user exists, so the demo user comes first and
# every other user depends on this fixture. Registered users get ids 9 and up,
# as in the spec's "Definition of done"
@pytest.fixture
def demo(empty_db):
    db_module.seed_db()
    row = db_module.get_user_by_email(DEMO_EMAIL)
    assert row is not None, "seed_db() should create the demo user"
    return {
        "id": row["id"],
        "name": row["name"],
        "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD,
    }


@pytest.fixture
def alice(demo):
    return make_user("Alice Tester", "alice@example.com")


@pytest.fixture
def bob(alice):
    return make_user("Bob Tester", "bob@example.com")


@pytest.fixture
def auth_client(client, alice):
    """A test client signed in as Alice."""
    return sign_in(client, alice)


@pytest.fixture
def bob_client(spendly_app, bob):
    return sign_in(spendly_app.test_client(), bob)


@pytest.fixture
def demo_client(spendly_app, demo):
    return sign_in(spendly_app.test_client(), demo)


def add_row(
    user,
    amount=250.50,
    category="Food",
    day=SAMPLE_DAY,
    description="Lunch",
):
    """Save an expense straight into the database and describe it."""
    expense_id = db_module.create_expense(
        user["id"], amount, category, day, description
    )
    return {
        "id": expense_id,
        "user_id": user["id"],
        "amount": amount,
        "category": category,
        "date": day,
        "description": description,
    }


@pytest.fixture
def lunch(alice):
    return add_row(alice)


@pytest.fixture
def transport(alice, lunch):
    return add_row(alice, 80.0, "Transport", SAMPLE_DAY, None)


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


def row_count(expense_id):
    conn = db_module.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def user_count():
    conn = db_module.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def table_names():
    conn = db_module.get_db()
    try:
        return {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()


def column_names(table):
    conn = db_module.get_db()
    try:
        return [
            row["name"]
            for row in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))
        ]
    finally:
        conn.close()


def get_profile(test_client, **params):
    return test_client.get(url("profile"), query_string=params)


def profile_page(test_client, **params):
    response = get_profile(test_client, **params)
    assert response.status_code == 200, "The profile page should answer 200"
    return parse_page(response)


def post_delete(test_client, expense_id, **kwargs):
    return test_client.post(delete_url(expense_id), **kwargs)


def assert_redirects_to(response, endpoint):
    assert response.status_code == 302, f"Expected 302, got {response.status_code}"
    assert urlparse(response.headers["Location"]).path == url(endpoint)


@pytest.fixture
def remove_calls(monkeypatch):
    """Record every call the route makes to remove_expense(), then run it."""
    real = app_module.remove_expense
    signature = inspect.signature(db_module.remove_expense)
    calls = []

    def spy(*args, **kwargs):
        calls.append(dict(signature.bind(*args, **kwargs).arguments))
        return real(*args, **kwargs)

    monkeypatch.setattr(app_module, "remove_expense", spy)
    return calls


# --------------------------------------------------------------------------- #
# remove_expense() in database/db.py                                          #
# --------------------------------------------------------------------------- #


class TestRemoveExpense:
    def test_takes_expense_id_then_user_id(self):
        params = list(inspect.signature(db_module.remove_expense).parameters)
        assert params == ["expense_id", "user_id"], f"Parameters were {params}"

    def test_helper_is_not_named_delete_expense(self):
        assert not hasattr(
            db_module, "delete_expense"
        ), "The helper is remove_expense; delete_expense is the view's name"

    def test_returns_true_when_a_row_was_deleted(self, alice):
        row = add_row(alice)
        result = db_module.remove_expense(row["id"], alice["id"])
        assert result is True, f"Expected True, got {result!r}"

    def test_the_row_is_gone_afterwards(self, alice):
        row = add_row(alice)
        db_module.remove_expense(row["id"], alice["id"])
        assert row_count(row["id"]) == 0
        assert db_module.get_expense(row["id"], alice["id"]) is None

    def test_deletes_one_row_only(self, alice):
        first = add_row(alice, description="First")
        middle = add_row(alice, description="Middle")
        last = add_row(alice, description="Last")
        before = len(db_rows())
        db_module.remove_expense(middle["id"], alice["id"])
        assert len(db_rows()) == before - 1
        assert [r["id"] for r in db_rows(alice["id"])] == [first["id"], last["id"]]

    def test_identical_twin_rows_keep_the_one_not_asked_for(self, alice):
        twin_a = add_row(alice)
        twin_b = add_row(alice)
        assert db_module.remove_expense(twin_a["id"], alice["id"]) is True
        assert [r["id"] for r in db_rows(alice["id"])] == [twin_b["id"]]

    def test_returns_false_for_a_missing_id(self, alice):
        add_row(alice)
        before = db_rows()
        result = db_module.remove_expense(999999, alice["id"])
        assert result is False, f"Expected False, got {result!r}"
        assert db_rows() == before

    def test_returns_false_for_a_second_call_on_the_same_id(self, alice):
        row = add_row(alice)
        assert db_module.remove_expense(row["id"], alice["id"]) is True
        assert db_module.remove_expense(row["id"], alice["id"]) is False

    def test_leaves_another_users_expense_alone_and_returns_false(self, alice, bob):
        theirs = add_row(bob, description="Bob's")
        before = db_rows()
        result = db_module.remove_expense(theirs["id"], alice["id"])
        assert result is False, f"Expected False, got {result!r}"
        assert db_rows() == before, "Another user's expense must not be deleted"

    def test_leaves_a_demo_expense_alone_when_asked_by_someone_else(self, alice, demo):
        demo_ids = [r["id"] for r in db_rows(demo["id"])]
        assert len(demo_ids) == 8, "The demo user should have 8 expenses"
        for demo_id in demo_ids:
            assert db_module.remove_expense(demo_id, alice["id"]) is False
        assert [r["id"] for r in db_rows(demo["id"])] == demo_ids

    def test_owner_can_still_remove_it_after_a_refused_attempt(self, alice, bob):
        theirs = add_row(bob)
        assert db_module.remove_expense(theirs["id"], alice["id"]) is False
        assert db_module.remove_expense(theirs["id"], bob["id"]) is True

    def test_a_nonexistent_id_does_not_delete_the_users_other_rows(self, alice):
        keep = add_row(alice)
        assert db_module.remove_expense(keep["id"] + 1000, alice["id"]) is False
        assert row_count(keep["id"]) == 1

    def test_a_user_id_that_matches_nobody_deletes_nothing(self, alice):
        row = add_row(alice)
        assert db_module.remove_expense(row["id"], 987654) is False
        assert row_count(row["id"]) == 1

    def test_no_user_id_deletes_nothing(self, alice):
        row = add_row(alice)
        assert db_module.remove_expense(row["id"], None) is False
        assert row_count(row["id"]) == 1

    @pytest.mark.parametrize(
        "payload",
        ["1 OR 1=1", "1; DROP TABLE expenses", "' OR '1'='1", "id"],
    )
    def test_sql_text_as_the_id_deletes_nothing(self, alice, payload):
        add_row(alice)
        before = db_rows()
        assert db_module.remove_expense(payload, alice["id"]) is False
        assert db_rows() == before
        assert "expenses" in table_names()

    @pytest.mark.parametrize(
        "payload",
        ["1 OR 1=1", "x' OR '1'='1", "alice@example.com' --"],
    )
    def test_sql_text_as_the_user_id_deletes_nothing(self, alice, payload):
        row = add_row(alice)
        before = db_rows()
        assert db_module.remove_expense(row["id"], payload) is False
        assert db_rows() == before

    def test_does_not_touch_the_users_table(self, alice):
        row = add_row(alice)
        before = user_count()
        db_module.remove_expense(row["id"], alice["id"])
        assert user_count() == before

    def test_id_of_a_deleted_expense_is_never_given_to_a_later_one(self, alice):
        add_row(alice)
        highest = add_row(alice)
        db_module.remove_expense(highest["id"], alice["id"])
        newer = add_row(alice)
        assert newer["id"] > highest["id"], "AUTOINCREMENT ids must not be reused"

    def test_no_new_table_or_column_and_the_row_is_not_archived(self, alice):
        row = add_row(alice)
        tables_before = table_names()
        db_module.remove_expense(row["id"], alice["id"])
        assert table_names() == tables_before == {"users", "expenses"}
        assert column_names("expenses") == [
            "id",
            "user_id",
            "amount",
            "category",
            "date",
            "description",
            "created_at",
        ], "No deleted_at or other column may be added"
        assert row_count(row["id"]) == 0, "The row must really be gone"


# --------------------------------------------------------------------------- #
# Route set-up                                                                #
# --------------------------------------------------------------------------- #


class TestRouteSetup:
    def test_delete_endpoint_builds_the_expenses_delete_url(self):
        assert url("delete_expense", expense_id=7) == "/expenses/7/delete"

    def test_rule_takes_expense_id_and_accepts_get_and_post_only(self, spendly_app):
        rules = [
            rule
            for rule in spendly_app.url_map.iter_rules()
            if rule.endpoint == "delete_expense"
        ]
        assert len(rules) == 1, f"Expected one delete_expense rule, got {len(rules)}"
        rule = rules[0]
        assert rule.arguments == {"expense_id"}, f"Variables: {rule.arguments}"
        methods = rule.methods - {"HEAD", "OPTIONS"}
        assert methods == {"GET", "POST"}, f"Methods were {methods}"

    def test_app_imports_remove_expense_by_name(self):
        assert callable(
            getattr(app_module, "remove_expense", None)
        ), "app.py should import remove_expense from database.db"


# --------------------------------------------------------------------------- #
# Auth guard                                                                  #
# --------------------------------------------------------------------------- #


class TestAuthGuard:
    @pytest.mark.parametrize("method", ["get", "post"])
    def test_signed_out_request_redirects_to_login_and_deletes_nothing(
        self, client, lunch, method
    ):
        before = db_rows()
        response = getattr(client, method)(delete_url(lunch["id"]))
        assert_redirects_to(response, "login")
        assert db_rows() == before, "A signed-out request must delete nothing"
        assert row_count(lunch["id"]) == 1

    @pytest.mark.parametrize("method", ["get", "post"])
    @pytest.mark.parametrize("expense_id", [999999, 99999999999999999999999])
    def test_signed_out_request_for_a_missing_id_also_redirects(
        self, client, alice, method, expense_id
    ):
        response = getattr(client, method)(delete_url(expense_id))
        assert_redirects_to(response, "login")

    def test_signed_out_post_with_a_body_deletes_nothing(self, client, lunch, alice):
        before = db_rows()
        response = post_delete(
            client, lunch["id"], data={"user_id": alice["id"], "confirm": "yes"}
        )
        assert_redirects_to(response, "login")
        assert db_rows() == before

    def test_signed_out_post_reaches_neither_the_database_nor_a_flash(
        self, client, lunch, remove_calls
    ):
        response = post_delete(client, lunch["id"], follow_redirects=True)
        assert response.status_code == 200
        assert remove_calls == [], "remove_expense() ran for a signed-out request"
        assert FLASH_DELETED not in response.get_data(as_text=True)

    def test_after_signing_out_the_delete_is_refused(self, auth_client, lunch):
        logout = auth_client.post(url("logout"))
        assert logout.status_code == 302
        response = post_delete(auth_client, lunch["id"])
        assert_redirects_to(response, "login")
        assert row_count(lunch["id"]) == 1


# --------------------------------------------------------------------------- #
# GET: the confirmation page                                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def confirm_response(auth_client, lunch):
    return auth_client.get(delete_url(lunch["id"]))


@pytest.fixture
def confirm_page(confirm_response):
    assert confirm_response.status_code == 200
    return parse_page(confirm_response)


def confirm_page_for(test_client, user, **row_values):
    """Save an expense, open its confirmation page, return (page, row)."""
    row = add_row(user, **row_values)
    response = test_client.get(delete_url(row["id"]))
    assert response.status_code == 200, f"Got {response.status_code}"
    return parse_page(response), row


class TestConfirmationPage:
    def test_own_expense_answers_200(self, confirm_response):
        assert confirm_response.status_code == 200

    def test_title_is_delete_expense_spendly(self, confirm_page):
        assert page_title(confirm_page) == PAGE_TITLE

    def test_page_has_one_h1_reading_delete_expense(self, confirm_page):
        headings = confirm_page.find_all("h1")
        assert len(headings) == 1, f"Expected one <h1>, got {len(headings)}"
        assert headings[0].text() == "Delete expense"
        assert "auth-title" in headings[0].classes()

    def test_page_says_in_text_that_it_cannot_be_undone(self, confirm_page):
        assert "This cannot be undone" in confirm_page.text()

    def test_subtitle_holds_the_warning(self, confirm_page):
        subtitles = confirm_page.find_all(cls="auth-subtitle")
        assert [s.text() for s in subtitles] == ["This cannot be undone"]

    @pytest.mark.parametrize(
        "class_name", ["auth-section", "auth-container", "auth-header", "auth-card"]
    )
    def test_uses_the_expense_form_layout(self, confirm_page, class_name):
        assert confirm_page.find_all(cls=class_name), f"No .{class_name} on the page"

    def test_loads_expense_css(self, confirm_page):
        hrefs = [
            link.attrs.get("href", "")
            for link in confirm_page.find_all("link")
            if link.attrs.get("rel") == "stylesheet"
        ]
        assert any(
            href.endswith("css/expense.css") for href in hrefs
        ), f"expense.css is not loaded: {hrefs}"

    def test_summary_has_four_labels_in_order(self, confirm_page):
        labels = [label for label, _value in summary_rows(confirm_page)]
        assert labels == ["Date", "Description", "Category", "Amount"]

    def test_summary_shows_the_expenses_values(self, confirm_page):
        assert dict(summary_rows(confirm_page)) == {
            "Date": SAMPLE_SHOWN,
            "Description": "Lunch",
            "Category": "Food",
            "Amount": "₹250.50",
        }

    def test_summary_sits_inside_the_card(self, confirm_page):
        summary_list = confirm_page.find_all("dl", cls="expense-summary")[0]
        assert ancestor(summary_list, cls="auth-card") is not None

    def test_form_posts_to_this_expenses_delete_url(self, confirm_page, lunch):
        form = delete_form(confirm_page, lunch["id"])
        assert form.attrs.get("method", "").upper() == "POST"
        assert "expense-form" in form.classes()

    def test_form_holds_one_submit_button_reading_delete_expense(
        self, confirm_page, lunch
    ):
        form = delete_form(confirm_page, lunch["id"])
        buttons = form.find_all("button")
        assert len(buttons) == 1, f"Expected one button, got {len(buttons)}"
        button = buttons[0]
        assert button.attrs.get("type") == "submit"
        assert {"btn-submit", "expense-delete-button"} <= set(button.classes())
        assert button.text() == "Delete expense"

    def test_form_has_no_inputs_visible_or_hidden(self, confirm_page, lunch):
        form = delete_form(confirm_page, lunch["id"])
        for tag in ("input", "select", "textarea"):
            assert form.find_all(tag) == [], f"The form holds a <{tag}>"

    def test_card_has_no_inputs_at_all(self, confirm_page):
        card = confirm_page.find_all(cls="auth-card")[0]
        for tag in ("input", "select", "textarea"):
            assert card.find_all(tag) == [], f"The card holds a <{tag}>"

    def test_nothing_on_the_page_has_autofocus(self, confirm_page):
        focused = [n.tag for n in confirm_page.descendants() if "autofocus" in n.attrs]
        assert focused == [], f"autofocus found on: {focused}"
        assert "autofocus" not in confirm_page.raw.lower()

    def test_cancel_link_goes_to_profile(self, confirm_page):
        links = confirm_page.find_all("a", cls="expense-cancel")
        assert len(links) == 1, f"Expected one Cancel link, got {len(links)}"
        assert urlparse(links[0].attrs.get("href", "")).path == url("profile")
        assert links[0].text() == "Cancel"

    def test_cancel_link_is_under_the_form_not_inside_it(self, confirm_page, lunch):
        form = delete_form(confirm_page, lunch["id"])
        link = confirm_page.find_all("a", cls="expense-cancel")[0]
        assert ancestor(link, tag="form") is None, "Cancel must not be in a form"
        summary_list = confirm_page.find_all("dl", cls="expense-summary")[0]
        order = [position(confirm_page, node) for node in (summary_list, form, link)]
        assert order == sorted(order), "Expected summary, then form, then Cancel"

    def test_old_placeholder_text_is_gone(self, confirm_page):
        text = confirm_page.text().lower()
        assert "coming in step" not in text
        assert "step 9" not in text

    def test_confirmation_is_a_page_not_a_dialog_or_confirm_call(self, confirm_page):
        assert confirm_page.find_all("dialog") == [], "Use a page, not a <dialog>"
        assert "confirm(" not in confirm_page.raw
        handlers = [
            (node.tag, attr)
            for node in confirm_page.descendants()
            for attr in node.attrs
            if attr.startswith("on")
        ]
        assert handlers == [], f"Inline event handlers found: {handlers}"

    def test_the_page_shows_only_the_asked_for_expense(
        self, auth_client, lunch, transport
    ):
        response = auth_client.get(delete_url(transport["id"]))
        page = parse_page(response)
        assert dict(summary_rows(page)) == {
            "Date": SAMPLE_SHOWN,
            "Description": EM_DASH,
            "Category": "Transport",
            "Amount": "₹80.00",
        }
        assert "Lunch" not in page.text()
        assert delete_form(page, transport["id"])
        assert delete_url(lunch["id"]) not in page.raw

    def test_a_null_description_shows_a_dash(self, auth_client, alice):
        page, _row = confirm_page_for(auth_client, alice, description=None)
        assert dict(summary_rows(page))["Description"] == EM_DASH

    @pytest.mark.parametrize(
        ("stored", "shown"),
        [
            ("2026-09-24", "24 Sep 2026"),
            ("2024-03-05", "05 Mar 2024"),
            ("2024-02-29", "29 Feb 2024"),
            ("2026-01-01", "01 Jan 2026"),
            ("2025-12-31", "31 Dec 2025"),
        ],
    )
    def test_date_goes_through_the_default_date_format(
        self, auth_client, alice, stored, shown
    ):
        page, _row = confirm_page_for(auth_client, alice, day=stored)
        assert dict(summary_rows(page))["Date"] == shown

    @pytest.mark.parametrize(
        ("amount", "shown"),
        [
            (250.50, "₹250.50"),
            (80, "₹80.00"),
            (0.01, "₹0.01"),
            (1234.5, "₹1,234.50"),
            (1234567.89, "₹1,234,567.89"),
            (9999999.99, "₹9,999,999.99"),
        ],
    )
    def test_amount_goes_through_the_money_format(
        self, auth_client, alice, amount, shown
    ):
        page, _row = confirm_page_for(auth_client, alice, amount=amount)
        assert dict(summary_rows(page))["Amount"] == shown

    @pytest.mark.parametrize("category", SPEC_CATEGORIES)
    def test_every_category_is_shown(self, auth_client, alice, category):
        page, _row = confirm_page_for(auth_client, alice, category=category)
        assert dict(summary_rows(page))["Category"] == category

    def test_a_200_character_description_is_shown_in_full(self, auth_client, alice):
        long_text = "x" * 200
        page, _row = confirm_page_for(auth_client, alice, description=long_text)
        assert dict(summary_rows(page))["Description"] == long_text

    def test_a_description_with_odd_characters_is_shown_as_typed(
        self, auth_client, alice
    ):
        text = 'Café & crème — 50% off, "quoted" it\'s'
        page, _row = confirm_page_for(auth_client, alice, description=text)
        assert dict(summary_rows(page))["Description"] == text


# --------------------------------------------------------------------------- #
# GET never deletes                                                           #
# --------------------------------------------------------------------------- #


class TestGetNeverDeletes:
    def test_repeated_gets_delete_nothing(self, auth_client, lunch):
        before = db_rows()
        for _ in range(5):
            response = auth_client.get(delete_url(lunch["id"]))
            assert response.status_code == 200
        assert db_rows() == before, "GET must never delete"
        page = profile_page(auth_client)
        assert lunch["id"] in [found for found, _link in delete_links(page)]

    def test_get_flashes_nothing(self, auth_client, lunch):
        auth_client.get(delete_url(lunch["id"]))
        assert flash_texts(profile_page(auth_client)) == []

    def test_head_request_deletes_nothing(self, auth_client, lunch):
        before = db_rows()
        response = auth_client.head(delete_url(lunch["id"]))
        assert response.status_code == 200
        assert db_rows() == before

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Purpose": "prefetch"},
            {"Sec-Purpose": "prefetch"},
            {"X-Moz": "prefetch"},
            {"Referer": "http://other-site.example/page"},
        ],
    )
    def test_prefetch_style_gets_delete_nothing(self, auth_client, lunch, headers):
        before = db_rows()
        response = auth_client.get(delete_url(lunch["id"]), headers=headers)
        assert response.status_code == 200
        assert db_rows() == before

    def test_query_string_flags_do_not_make_a_get_delete(self, auth_client, lunch):
        before = db_rows()
        response = auth_client.get(
            delete_url(lunch["id"]),
            query_string={
                "confirm": "1",
                "delete": "yes",
                "action": "delete",
                "_method": "POST",
                "user_id": lunch["user_id"],
            },
        )
        assert response.status_code == 200
        assert db_rows() == before

    def test_getting_every_confirmation_page_deletes_nothing(
        self, auth_client, lunch, transport
    ):
        before = db_rows()
        for row in (lunch, transport):
            assert auth_client.get(delete_url(row["id"])).status_code == 200
        assert db_rows() == before

    def test_a_get_does_not_call_remove_expense(self, auth_client, lunch, remove_calls):
        auth_client.get(delete_url(lunch["id"]))
        assert remove_calls == [], "The DELETE must run on a POST only"


# --------------------------------------------------------------------------- #
# POST: deleting                                                              #
# --------------------------------------------------------------------------- #


class TestDeletePost:
    def test_redirects_to_profile_with_no_query_string(self, auth_client, lunch):
        response = post_delete(auth_client, lunch["id"])
        assert_redirects_to(response, "profile")
        assert urlparse(response.headers["Location"]).query == ""

    def test_the_row_is_removed_from_the_database(self, auth_client, lunch):
        post_delete(auth_client, lunch["id"])
        assert row_count(lunch["id"]) == 0

    def test_exactly_one_row_is_removed(self, auth_client, lunch, transport):
        before = db_rows()
        post_delete(auth_client, lunch["id"])
        after = db_rows()
        assert len(after) == len(before) - 1
        assert after == [r for r in before if r["id"] != lunch["id"]]

    def test_the_middle_of_three_is_removed_and_the_others_stay(
        self, auth_client, alice
    ):
        first = add_row(alice, description="First")
        middle = add_row(alice, description="Middle")
        last = add_row(alice, description="Last")
        post_delete(auth_client, middle["id"])
        assert [r["id"] for r in db_rows(alice["id"])] == [first["id"], last["id"]]

    def test_an_identical_twin_row_is_not_removed(self, auth_client, alice):
        twin_a = add_row(alice)
        twin_b = add_row(alice)
        post_delete(auth_client, twin_a["id"])
        assert [r["id"] for r in db_rows(alice["id"])] == [twin_b["id"]]

    def test_other_users_expenses_are_not_touched(self, auth_client, lunch, demo, bob):
        bobs = add_row(bob)
        others_before = db_rows(demo["id"]) + db_rows(bob["id"])
        post_delete(auth_client, lunch["id"])
        assert db_rows(demo["id"]) + db_rows(bob["id"]) == others_before
        assert row_count(bobs["id"]) == 1

    def test_the_user_stays_signed_in(self, auth_client, lunch):
        post_delete(auth_client, lunch["id"])
        response = get_profile(auth_client)
        assert response.status_code == 200, "The user should still be signed in"

    def test_following_the_redirect_lands_on_profile(self, auth_client, lunch):
        response = post_delete(auth_client, lunch["id"], follow_redirects=True)
        assert response.status_code == 200
        assert response.request.path == url("profile")

    def test_flash_shows_once_and_is_gone_after_a_refresh(self, auth_client, lunch):
        response = post_delete(auth_client, lunch["id"], follow_redirects=True)
        assert flash_texts(parse_page(response)) == [FLASH_DELETED]
        assert flash_texts(profile_page(auth_client)) == [], "Flash must show once"

    def test_flash_message_is_not_shown_before_anything_is_deleted(
        self, auth_client, lunch
    ):
        assert FLASH_DELETED not in profile_page(auth_client).text()

    def test_profile_cards_table_and_breakdown_reflect_the_delete(
        self, auth_client, lunch, transport
    ):
        before = profile_page(auth_client)
        assert summary(before) == ("₹330.50", "2", "Food")
        assert sorted(category_names(before)) == ["Food", "Transport"]

        response = post_delete(auth_client, lunch["id"], follow_redirects=True)
        page = parse_page(response)
        assert summary(page) == ("₹80.00", "1", "Transport")
        assert table_rows(page) == [[SAMPLE_SHOWN, EM_DASH, "Transport", "₹80.00"]]
        assert category_names(page) == ["Transport"]
        assert [found for found, _link in delete_links(page)] == [transport["id"]]

    def test_deleting_the_last_expense_shows_the_empty_state(self, auth_client, lunch):
        response = post_delete(auth_client, lunch["id"], follow_redirects=True)
        page = parse_page(response)
        assert summary(page) == ("₹0.00", "0", EM_DASH)
        assert "No expenses yet" in page.text()
        assert table_rows(page) == []
        assert delete_links(page) == []
        assert category_names(page) == []
        assert not any("By category" in token for token in page.tokens())

    def test_deleting_both_expenses_one_after_the_other(
        self, auth_client, lunch, transport
    ):
        first = post_delete(auth_client, lunch["id"], follow_redirects=True)
        assert flash_texts(parse_page(first)) == [FLASH_DELETED]
        second = post_delete(auth_client, transport["id"], follow_redirects=True)
        page = parse_page(second)
        assert flash_texts(page) == [FLASH_DELETED]
        assert summary(page) == ("₹0.00", "0", EM_DASH)
        assert db_rows(lunch["user_id"]) == []

    def test_no_form_fields_are_needed(self, auth_client, lunch):
        response = auth_client.post(delete_url(lunch["id"]), data={})
        assert_redirects_to(response, "profile")
        assert row_count(lunch["id"]) == 0

    @pytest.mark.parametrize(
        "body",
        [
            {"amount": "1", "category": "Other", "date": "2020-01-01"},
            {"description": "changed", "confirm": "no"},
            {"_method": "GET", "delete": "false"},
            {"id": "1", "expense": "1"},
        ],
    )
    def test_fields_in_the_body_are_ignored(self, auth_client, lunch, demo, body):
        demo_before = db_rows(demo["id"])
        response = post_delete(auth_client, lunch["id"], data=body)
        assert_redirects_to(response, "profile")
        assert row_count(lunch["id"]) == 0
        assert db_rows(demo["id"]) == demo_before

    def test_user_id_and_expense_id_in_the_body_are_ignored(
        self, auth_client, lunch, demo
    ):
        demo_expense = db_rows(demo["id"])[0]
        demo_before = db_rows(demo["id"])
        response = post_delete(
            auth_client,
            lunch["id"],
            data={"user_id": demo["id"], "expense_id": demo_expense["id"]},
        )
        assert_redirects_to(response, "profile")
        assert row_count(lunch["id"]) == 0, "The URL's expense should be deleted"
        assert db_rows(demo["id"]) == demo_before, "The body's ids must be ignored"

    def test_user_id_and_expense_id_in_the_query_string_are_ignored(
        self, auth_client, lunch, demo
    ):
        demo_expense = db_rows(demo["id"])[0]
        demo_before = db_rows(demo["id"])
        response = post_delete(
            auth_client,
            lunch["id"],
            query_string={"user_id": demo["id"], "expense_id": demo_expense["id"]},
        )
        assert_redirects_to(response, "profile")
        assert row_count(lunch["id"]) == 0
        assert db_rows(demo["id"]) == demo_before

    def test_the_route_asks_remove_expense_for_the_signed_in_user(
        self, auth_client, alice, lunch, demo, remove_calls
    ):
        post_delete(auth_client, lunch["id"], data={"user_id": demo["id"]})
        assert remove_calls == [{"expense_id": lunch["id"], "user_id": alice["id"]}]

    @pytest.mark.parametrize("category", SPEC_CATEGORIES)
    def test_an_expense_of_every_category_can_be_deleted(
        self, auth_client, alice, category
    ):
        row = add_row(alice, category=category)
        response = post_delete(auth_client, row["id"])
        assert_redirects_to(response, "profile")
        assert row_count(row["id"]) == 0

    def test_an_expense_without_a_description_can_be_deleted(self, auth_client, alice):
        row = add_row(alice, description=None)
        assert_redirects_to(post_delete(auth_client, row["id"]), "profile")
        assert row_count(row["id"]) == 0

    def test_a_new_expense_never_gets_a_deleted_id(self, auth_client, alice, today):
        first = add_row(alice)
        second = add_row(alice)
        post_delete(auth_client, first["id"])
        post_delete(auth_client, second["id"])
        auth_client.post(
            url("add_expense"),
            data={
                "amount": "12.00",
                "category": "Other",
                "date": today.isoformat(),
                "description": "After deleting",
            },
        )
        ids = [r["id"] for r in db_rows(alice["id"])]
        assert len(ids) == 1
        assert ids[0] > max(first["id"], second["id"]), f"Id {ids[0]} was reused"

    def test_remove_expense_returning_false_answers_404_and_flashes_nothing(
        self, auth_client, lunch, monkeypatch
    ):
        # The row "went away between the check and the delete"
        monkeypatch.setattr(app_module, "remove_expense", lambda *a, **k: False)
        response = post_delete(auth_client, lunch["id"])
        assert response.status_code == 404
        assert flash_texts(profile_page(auth_client)) == []


# --------------------------------------------------------------------------- #
# Deleting twice                                                              #
# --------------------------------------------------------------------------- #


class TestDeletingTwice:
    def test_second_post_answers_404(self, auth_client, lunch):
        assert_redirects_to(post_delete(auth_client, lunch["id"]), "profile")
        response = post_delete(auth_client, lunch["id"])
        assert response.status_code == 404, f"Got {response.status_code}"

    def test_second_post_flashes_nothing(self, auth_client, lunch):
        first = post_delete(auth_client, lunch["id"], follow_redirects=True)
        assert flash_texts(parse_page(first)) == [FLASH_DELETED]
        assert post_delete(auth_client, lunch["id"]).status_code == 404
        assert flash_texts(profile_page(auth_client)) == []

    def test_a_double_click_flashes_the_message_only_once(self, auth_client, lunch):
        post_delete(auth_client, lunch["id"])
        assert post_delete(auth_client, lunch["id"]).status_code == 404
        assert flash_texts(profile_page(auth_client)) == [FLASH_DELETED]

    def test_second_post_deletes_nothing_else(self, auth_client, lunch, transport):
        post_delete(auth_client, lunch["id"])
        after_first = db_rows()
        post_delete(auth_client, lunch["id"])
        assert db_rows() == after_first
        assert row_count(transport["id"]) == 1

    def test_second_post_never_reaches_remove_expense(
        self, auth_client, lunch, remove_calls
    ):
        post_delete(auth_client, lunch["id"])
        post_delete(auth_client, lunch["id"])
        assert len(remove_calls) == 1, f"remove_expense() calls: {remove_calls}"

    def test_get_after_a_delete_answers_404(self, auth_client, lunch):
        post_delete(auth_client, lunch["id"])
        response = auth_client.get(delete_url(lunch["id"]))
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Whose expense                                                               #
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["demo", "bob"])
def foreign_row(request, demo, bob):
    """An expense that belongs to someone other than Alice."""
    if request.param == "demo":
        row = db_rows(demo["id"])[0]
        return {
            "id": row["id"],
            "user_id": demo["id"],
            "description": row["description"],
            "amount": row["amount"],
            "date": row["date"],
        }
    return add_row(bob, 4321.09, "Health", "2023-06-17", "Bobs secret note")


class TestOwnership:
    @pytest.mark.parametrize("method", ["get", "post"])
    def test_another_users_expense_answers_404(self, auth_client, foreign_row, method):
        response = getattr(auth_client, method)(delete_url(foreign_row["id"]))
        assert (
            response.status_code == 404
        ), f"Expected 404 (not 403 and not a redirect), got {response.status_code}"

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_none_of_its_values_is_shown(self, auth_client, foreign_row, method):
        response = getattr(auth_client, method)(delete_url(foreign_row["id"]))
        body = response.get_data(as_text=True)
        assert foreign_row["description"] not in body
        assert f"{foreign_row['amount']:,.2f}" not in body
        assert "This cannot be undone" not in body

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_the_row_stays_in_the_database(self, auth_client, foreign_row, method):
        before = db_rows()
        getattr(auth_client, method)(delete_url(foreign_row["id"]))
        assert db_rows() == before
        assert row_count(foreign_row["id"]) == 1

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_the_answer_matches_the_answer_for_a_missing_id(
        self, auth_client, foreign_row, method
    ):
        theirs = getattr(auth_client, method)(delete_url(foreign_row["id"]))
        missing = getattr(auth_client, method)(delete_url(999999))
        assert theirs.status_code == missing.status_code == 404
        assert theirs.get_data() == missing.get_data(), "The 404s must look alike"

    def test_post_flashes_nothing(self, auth_client, foreign_row):
        post_delete(auth_client, foreign_row["id"])
        assert flash_texts(profile_page(auth_client)) == []

    def test_post_never_reaches_remove_expense(
        self, auth_client, foreign_row, remove_calls
    ):
        post_delete(auth_client, foreign_row["id"])
        assert remove_calls == [], "The ownership check must come first"

    @pytest.mark.parametrize("claimed", ["alice", "owner"])
    def test_a_user_id_in_the_body_does_not_grant_access(
        self, auth_client, alice, foreign_row, claimed
    ):
        claimed_id = alice["id"] if claimed == "alice" else foreign_row["user_id"]
        before = db_rows()
        response = post_delete(
            auth_client,
            foreign_row["id"],
            data={"user_id": claimed_id, "expense_id": foreign_row["id"]},
        )
        assert response.status_code == 404
        assert db_rows() == before

    def test_the_users_own_expenses_are_not_touched_by_a_refused_delete(
        self, auth_client, lunch, foreign_row
    ):
        before = db_rows(lunch["user_id"])
        post_delete(auth_client, foreign_row["id"])
        assert db_rows(lunch["user_id"]) == before

    def test_every_demo_expense_is_refused_for_get_and_post(
        self, auth_client, alice, demo
    ):
        demo_before = db_rows(demo["id"])
        assert len(demo_before) == 8
        for row in demo_before:
            assert auth_client.get(delete_url(row["id"])).status_code == 404
            assert post_delete(auth_client, row["id"]).status_code == 404
        assert db_rows(demo["id"]) == demo_before

    def test_a_second_user_cannot_delete_alices_expense(self, bob_client, lunch):
        assert bob_client.get(delete_url(lunch["id"])).status_code == 404
        assert post_delete(bob_client, lunch["id"]).status_code == 404
        assert row_count(lunch["id"]) == 1

    def test_the_owner_can_delete_it_after_the_refusals(
        self, auth_client, bob_client, lunch
    ):
        assert post_delete(bob_client, lunch["id"]).status_code == 404
        assert_redirects_to(post_delete(auth_client, lunch["id"]), "profile")
        assert row_count(lunch["id"]) == 0


# --------------------------------------------------------------------------- #
# Ids                                                                         #
# --------------------------------------------------------------------------- #


class TestIds:
    @pytest.mark.parametrize("method", ["get", "post"])
    @pytest.mark.parametrize(
        "expense_id",
        [999999, 0, MAX_SQLITE_ID, MAX_SQLITE_ID + 1, 99999999999999999999999],
    )
    def test_missing_or_oversized_id_answers_404(
        self, auth_client, lunch, method, expense_id
    ):
        before = db_rows()
        response = getattr(auth_client, method)(delete_url(expense_id))
        assert response.status_code == 404, f"Got {response.status_code}, not 404"
        assert db_rows() == before

    @pytest.mark.parametrize("method", ["get", "post"])
    @pytest.mark.parametrize(
        "segment", ["abc", "1.5", "-1", "1abc", "0x10", "%20", "true"]
    )
    def test_non_numeric_id_answers_404(self, auth_client, lunch, method, segment):
        before = db_rows()
        response = getattr(auth_client, method)(raw_delete_url(segment))
        assert response.status_code == 404, f"Got {response.status_code}, not 404"
        assert db_rows() == before

    @pytest.mark.parametrize("expense_id", [999999, MAX_SQLITE_ID + 1, 10**23])
    def test_post_for_a_missing_or_oversized_id_flashes_nothing(
        self, auth_client, lunch, expense_id
    ):
        post_delete(auth_client, expense_id)
        assert flash_texts(profile_page(auth_client)) == []

    @pytest.mark.parametrize("expense_id", [999999, MAX_SQLITE_ID + 1, 10**23])
    def test_remove_expense_is_not_called_for_a_missing_or_oversized_id(
        self, auth_client, lunch, remove_calls, expense_id
    ):
        post_delete(auth_client, expense_id)
        assert remove_calls == [], "The existence check must run first"

    def test_an_oversized_id_answers_the_same_404_as_a_missing_one(
        self, auth_client, lunch
    ):
        missing = post_delete(auth_client, 999999)
        huge = post_delete(auth_client, 99999999999999999999999)
        assert missing.status_code == huge.status_code == 404
        assert missing.get_data() == huge.get_data()


# --------------------------------------------------------------------------- #
# Other methods                                                               #
# --------------------------------------------------------------------------- #


class TestOtherMethods:
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_other_methods_signed_in_answer_405_and_delete_nothing(
        self, auth_client, lunch, method
    ):
        before = db_rows()
        response = getattr(auth_client, method)(delete_url(lunch["id"]))
        assert response.status_code == 405, f"Got {response.status_code}"
        allowed = {m.strip() for m in response.headers.get("Allow", "").split(",")}
        assert {"GET", "POST"} <= allowed, f"Allow header was {allowed}"
        assert not {"PUT", "PATCH", "DELETE"} & allowed, f"Allow was {allowed}"
        assert db_rows() == before

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_other_methods_on_a_demo_expense_answer_405_and_delete_nothing(
        self, auth_client, demo, method
    ):
        before = db_rows(demo["id"])
        response = getattr(auth_client, method)(delete_url(before[0]["id"]))
        assert response.status_code == 405
        assert db_rows(demo["id"]) == before

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_other_methods_signed_out_answer_405_and_delete_nothing(
        self, client, lunch, method
    ):
        before = db_rows()
        response = getattr(client, method)(delete_url(lunch["id"]))
        assert response.status_code == 405
        assert db_rows() == before


# --------------------------------------------------------------------------- #
# The profile page: the "Delete" link                                         #
# --------------------------------------------------------------------------- #


@pytest.fixture
def two_rows_page(auth_client, lunch, transport):
    return profile_page(auth_client)


class TestProfileDeleteLink:
    def test_every_row_has_a_delete_link(self, two_rows_page, lunch, transport):
        found = sorted(expense_id for expense_id, _link in delete_links(two_rows_page))
        assert found == sorted([lunch["id"], transport["id"]])

    def test_the_link_leads_to_that_rows_delete_url(self, two_rows_page, lunch):
        link = delete_link_for(two_rows_page, lunch["id"])
        assert urlparse(link.attrs["href"]).path == delete_url(lunch["id"])
        assert urlparse(link.attrs["href"]).query == "", "The link carries no range"

    def test_the_link_sits_in_the_row_of_its_expense(
        self, two_rows_page, lunch, transport
    ):
        lunch_row = ancestor(delete_link_for(two_rows_page, lunch["id"]), tag="tr")
        transport_row = ancestor(
            delete_link_for(two_rows_page, transport["id"]), tag="tr"
        )
        assert "Lunch" in lunch_row.text() and "Food" in lunch_row.text()
        assert "Transport" in transport_row.text()
        assert "Lunch" not in transport_row.text()

    def test_the_actions_cell_has_the_profile_actions_class(self, two_rows_page, lunch):
        assert "profile-actions" in action_cell(two_rows_page, lunch["id"]).classes()

    def test_edit_comes_first_and_delete_second_in_the_actions_cell(
        self, two_rows_page, lunch
    ):
        cell = action_cell(two_rows_page, lunch["id"])
        links = cell.find_all("a")
        assert [link.text() for link in links] == ["Edit", "Delete"]
        assert urlparse(links[0].attrs["href"]).path == url(
            "edit_expense", expense_id=lunch["id"]
        )
        assert urlparse(links[1].attrs["href"]).path == delete_url(lunch["id"])

    def test_delete_link_has_the_row_action_and_danger_classes(
        self, two_rows_page, lunch
    ):
        link = delete_link_for(two_rows_page, lunch["id"])
        assert {"profile-row-action", "profile-row-action-danger"} <= set(
            link.classes()
        )

    def test_edit_link_is_unchanged(self, two_rows_page, lunch):
        edit = edit_link_for(two_rows_page, lunch["id"])
        assert "profile-row-action" in edit.classes()
        assert "profile-row-action-danger" not in edit.classes()
        assert edit.text() == "Edit"
        assert edit.attrs.get("aria-label") == f"Edit Lunch, {SAMPLE_SHOWN}"

    def test_delete_link_shows_the_visible_text_delete(self, two_rows_page, lunch):
        assert delete_link_for(two_rows_page, lunch["id"]).text() == "Delete"

    def test_delete_link_has_a_trash_icon_beside_its_text(self, two_rows_page, lunch):
        link = delete_link_for(two_rows_page, lunch["id"])
        icons = link.find_all("i", attrs={"data-lucide": "trash-2"})
        assert len(icons) == 1, f"Expected one trash-2 icon, got {len(icons)}"
        assert "profile-icon" in icons[0].classes()

    def test_aria_label_matches_the_spec_example(self, two_rows_page, lunch):
        link = delete_link_for(two_rows_page, lunch["id"])
        assert link.attrs.get("aria-label") == "Delete Lunch, 24 Sep 2026"

    def test_aria_label_uses_the_category_when_there_is_no_description(
        self, two_rows_page, transport
    ):
        link = delete_link_for(two_rows_page, transport["id"])
        assert link.attrs.get("aria-label") == f"Delete Transport, {SAMPLE_SHOWN}"

    @pytest.mark.parametrize(
        ("description", "category", "day", "shown"),
        [
            ("Coffee", "Food", "2024-03-05", "05 Mar 2024"),
            (None, "Bills", "2025-12-31", "31 Dec 2025"),
            ("Gift wrap, card and ribbon", "Other", "2026-01-01", "01 Jan 2026"),
        ],
    )
    def test_aria_label_is_visible_text_then_subject_then_date(
        self, auth_client, alice, description, category, day, shown
    ):
        row = add_row(alice, 10.0, category, day, description)
        link = delete_link_for(profile_page(auth_client), row["id"])
        label = link.attrs.get("aria-label", "")
        subject = description or category
        assert label.startswith("Delete "), f"Label was {label!r}"
        assert label == f"Delete {subject}, {shown}", f"Label was {label!r}"

    def test_delete_label_mirrors_the_edit_label(self, two_rows_page, lunch, transport):
        for row in (lunch, transport):
            edit_label = edit_link_for(two_rows_page, row["id"]).attrs["aria-label"]
            delete_label = delete_link_for(two_rows_page, row["id"]).attrs["aria-label"]
            assert delete_label == edit_label.replace("Edit", "Delete", 1)

    def test_the_delete_control_is_a_link_not_a_form_or_button(
        self, two_rows_page, lunch
    ):
        row = ancestor(delete_link_for(two_rows_page, lunch["id"]), tag="tr")
        assert row.find_all("form") == [], "A table row must not hold a form"
        assert row.find_all("button") == [], "A table row must not hold a button"
        link = delete_link_for(two_rows_page, lunch["id"])
        assert link.tag == "a"

    def test_the_actions_column_header_is_unchanged(self, two_rows_page):
        headers = [th.text() for th in two_rows_page.find_all("th")]
        assert headers == ["Date", "Description", "Category", "Amount", "Actions"]

    def test_following_the_link_opens_the_confirmation_page_and_deletes_nothing(
        self, auth_client, two_rows_page, lunch
    ):
        link = delete_link_for(two_rows_page, lunch["id"])
        before = db_rows()
        response = auth_client.get(link.attrs["href"])
        assert response.status_code == 200
        page = parse_page(response)
        assert page.find_all("h1")[0].text() == "Delete expense"
        assert dict(summary_rows(page))["Description"] == "Lunch"
        assert db_rows() == before

    def test_a_user_without_expenses_sees_no_delete_links(self, bob_client):
        page = profile_page(bob_client)
        assert delete_links(page) == []
        assert "No expenses yet" in page.text()

    def test_only_the_users_own_expenses_are_linked(
        self, two_rows_page, lunch, transport, demo
    ):
        demo_ids = {row["id"] for row in db_rows(demo["id"])}
        linked = {expense_id for expense_id, _link in delete_links(two_rows_page)}
        assert linked == {lunch["id"], transport["id"]}
        assert not linked & demo_ids

    def test_another_signed_in_user_sees_delete_links_for_their_own_rows(
        self, bob_client, bob
    ):
        row = add_row(bob, 5.0, "Other", SAMPLE_DAY, "Bobs row")
        page = profile_page(bob_client)
        assert delete_link_for(page, row["id"]).text() == "Delete"


# --------------------------------------------------------------------------- #
# The seeded demo user                                                        #
# --------------------------------------------------------------------------- #


class TestDemoUser:
    def test_profile_shows_eight_delete_links(self, demo_client, demo):
        page = profile_page(demo_client)
        found = sorted(expense_id for expense_id, _link in delete_links(page))
        assert found == sorted(row["id"] for row in db_rows(demo["id"]))
        assert len(found) == 8

    def test_each_link_opens_the_right_expense(self, demo_client, demo):
        page = profile_page(demo_client)
        stored = {row["id"]: row for row in db_rows(demo["id"])}
        for expense_id, link in delete_links(page):
            row = ancestor(link, tag="tr")
            assert stored[expense_id]["description"] in row.text()
            opened = demo_client.get(link.attrs["href"])
            assert opened.status_code == 200
            shown = dict(summary_rows(parse_page(opened)))
            assert shown["Description"] == stored[expense_id]["description"]
            assert shown["Category"] == stored[expense_id]["category"]

    def test_deleting_headphones_removes_shopping_and_lowers_the_total(
        self, demo_client, demo
    ):
        headphones = next(
            row for row in db_rows(demo["id"]) if row["description"] == "Headphones"
        )
        before = profile_page(demo_client)
        assert summary(before)[:2] == ("₹3,610.49", "8")
        assert "Shopping" in category_names(before)

        response = post_delete(demo_client, headphones["id"], follow_redirects=True)
        page = parse_page(response)
        assert summary(page)[:2] == ("₹2,610.50", "7")
        assert "Shopping" not in category_names(page)
        assert flash_texts(page) == [FLASH_DELETED]
        assert row_count(headphones["id"]) == 0

    def test_the_demo_user_deleting_leaves_other_users_alone(
        self, demo_client, demo, lunch
    ):
        first = db_rows(demo["id"])[0]
        post_delete(demo_client, first["id"])
        assert row_count(first["id"]) == 0
        assert db_rows(lunch["user_id"]) == [
            r for r in db_rows() if r["id"] == lunch["id"]
        ]


# --------------------------------------------------------------------------- #
# Escaping                                                                    #
# --------------------------------------------------------------------------- #


class TestEscaping:
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_description_is_escaped_on_the_confirmation_page(
        self, auth_client, alice, payload
    ):
        page, _row = confirm_page_for(auth_client, alice, description=payload)
        assert dict(summary_rows(page))["Description"] == payload
        assert payload not in page.raw, "The description reached the page unescaped"
        assert_no_active_content(page)

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_category_is_escaped_on_the_confirmation_page(
        self, auth_client, alice, payload
    ):
        page, _row = confirm_page_for(auth_client, alice, category=payload)
        assert dict(summary_rows(page))["Category"] == payload
        assert payload not in page.raw, "The category reached the page unescaped"
        assert_no_active_content(page)

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_description_is_escaped_in_the_delete_links_aria_label(
        self, auth_client, alice, payload
    ):
        row = add_row(alice, description=payload)
        page = profile_page(auth_client)
        link = delete_link_for(page, row["id"])
        assert link.attrs.get("aria-label") == f"Delete {payload}, {SAMPLE_SHOWN}"
        assert payload not in page.raw, "The description reached the page unescaped"
        assert_no_active_content(page)

    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_category_is_escaped_in_the_label_when_there_is_no_description(
        self, auth_client, alice, payload
    ):
        row = add_row(alice, category=payload, description=None)
        page = profile_page(auth_client)
        link = delete_link_for(page, row["id"])
        assert link.attrs.get("aria-label") == f"Delete {payload}, {SAMPLE_SHOWN}"
        assert payload not in page.raw
        assert_no_active_content(page)

    def test_script_text_is_escaped_in_the_raw_html(self, auth_client, alice):
        payload = "<script>alert(1)</script>"
        page, _row = confirm_page_for(auth_client, alice, description=payload)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.raw

    def test_the_delete_action_stays_a_clean_url_whatever_the_description(
        self, auth_client, alice
    ):
        payload = '"><script>alert(1)</script>'
        page, row = confirm_page_for(auth_client, alice, description=payload)
        form = delete_form(page, row["id"])
        assert form.attrs["action"] == delete_url(row["id"])

    def test_the_payload_row_can_still_be_deleted(self, auth_client, alice):
        row = add_row(alice, description="<script>alert(1)</script>")
        assert_redirects_to(post_delete(auth_client, row["id"]), "profile")
        assert row_count(row["id"]) == 0


# --------------------------------------------------------------------------- #
# Date range on the profile page                                              #
# --------------------------------------------------------------------------- #

RANGE = {"date_from": "2024-06-01", "date_to": "2024-06-30"}


@pytest.fixture
def spread(alice):
    early = add_row(alice, 100.0, "Food", "2024-01-10", "Early")
    middle = add_row(alice, 200.0, "Transport", "2024-06-15", "Middle")
    late = add_row(alice, 300.0, "Bills", "2025-02-01", "Late")
    return early, middle, late


class TestDateRange:
    def test_delete_links_are_still_there_with_a_range(self, auth_client, spread):
        _early, middle, _late = spread
        page = profile_page(auth_client, **RANGE)
        assert table_rows(page) == [["15 Jun 2024", "Middle", "Transport", "₹200.00"]]
        link = delete_link_for(page, middle["id"])
        assert urlparse(link.attrs["href"]).path == delete_url(middle["id"])
        assert link.text() == "Delete"

    def test_the_link_in_a_filtered_table_opens_the_confirmation_page(
        self, auth_client, spread
    ):
        _early, middle, _late = spread
        page = profile_page(auth_client, **RANGE)
        response = auth_client.get(delete_link_for(page, middle["id"]).attrs["href"])
        assert response.status_code == 200
        assert dict(summary_rows(parse_page(response)))["Description"] == "Middle"

    def test_the_redirect_after_a_delete_carries_no_range(self, auth_client, spread):
        _early, middle, _late = spread
        response = post_delete(auth_client, middle["id"], query_string=RANGE)
        assert_redirects_to(response, "profile")
        assert urlparse(response.headers["Location"]).query == ""
        assert "date_from" not in response.headers["Location"]

    def test_the_page_after_a_delete_shows_all_expenses_again(
        self, auth_client, spread
    ):
        early, middle, late = spread
        response = post_delete(
            auth_client, middle["id"], query_string=RANGE, follow_redirects=True
        )
        page = parse_page(response)
        assert summary(page) == ("₹400.00", "2", "Bills")
        assert sorted(found for found, _link in delete_links(page)) == sorted(
            [early["id"], late["id"]]
        )
        assert page.find_all(cls="profile-filter-summary") == []
        assert flash_texts(page) == [FLASH_DELETED]

    def test_a_delete_outside_the_range_still_works(self, auth_client, spread):
        early, _middle, _late = spread
        response = post_delete(auth_client, early["id"], query_string=RANGE)
        assert_redirects_to(response, "profile")
        assert row_count(early["id"]) == 0


# --------------------------------------------------------------------------- #
# Neighbouring routes                                                         #
# --------------------------------------------------------------------------- #


class TestNeighbourRoutes:
    def test_adding_an_expense_still_flashes_expense_added(self, auth_client, today):
        response = auth_client.post(
            url("add_expense"),
            data={
                "amount": "250.50",
                "category": "Food",
                "date": today.isoformat(),
                "description": "Lunch",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert flash_texts(parse_page(response)) == [FLASH_ADDED]

    def test_editing_an_expense_still_flashes_expense_updated(
        self, auth_client, lunch, today
    ):
        response = auth_client.post(
            url("edit_expense", expense_id=lunch["id"]),
            data={
                "amount": "300.00",
                "category": "Bills",
                "date": today.isoformat(),
                "description": "Edited",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert flash_texts(parse_page(response)) == [FLASH_UPDATED]
        stored = db_rows(lunch["user_id"])[0]
        assert (stored["amount"], stored["category"]) == (300.0, "Bills")

    def test_the_edit_page_has_no_delete_control(self, auth_client, lunch):
        response = auth_client.get(url("edit_expense", expense_id=lunch["id"]))
        assert response.status_code == 200
        page = parse_page(response)
        assert delete_links(page) == []
        assert not any(
            "Delete" in token for token in page.tokens()
        ), "The edit page must get no Delete control in this step"

    def test_the_edit_page_still_works_after_deleting_a_neighbour(
        self, auth_client, lunch, transport
    ):
        post_delete(auth_client, transport["id"])
        response = auth_client.get(url("edit_expense", expense_id=lunch["id"]))
        assert response.status_code == 200

    def test_editing_a_deleted_expense_answers_404(self, auth_client, lunch):
        post_delete(auth_client, lunch["id"])
        response = auth_client.get(url("edit_expense", expense_id=lunch["id"]))
        assert response.status_code == 404

    def test_signed_out_edit_still_redirects_to_login(self, client, lunch):
        response = client.get(url("edit_expense", expense_id=lunch["id"]))
        assert_redirects_to(response, "login")


# --------------------------------------------------------------------------- #
# Static checks the spec lists                                                #
# --------------------------------------------------------------------------- #

HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def read_source(*parts):
    path = ROOT.joinpath(*parts)
    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


class TestSourceChecks:
    def test_app_py_contains_no_execute_call(self):
        assert "execute" not in read_source("app.py"), "All SQL belongs in db.py"

    def test_app_py_has_no_coming_in_step_text(self):
        assert "coming in Step" not in read_source("app.py")

    def test_app_py_has_no_placeholder_routes_section(self):
        assert "placeholder routes" not in read_source("app.py").lower()

    @pytest.mark.parametrize("name", ["expense.css", "profile.css"])
    def test_stylesheet_has_no_hex_colour_values(self, name):
        css = read_source("static", "css", name)
        assert HEX_COLOUR.findall(css) == [], f"Hex colours in {name}"

    def test_delete_template_exists_and_extends_base(self):
        template = read_source("templates", "expense_delete.html")
        assert re.search(r"{%-?\s*extends\s+[\"']base\.html[\"']\s*-?%}", template)

    def test_delete_template_does_not_turn_off_autoescaping(self):
        template = read_source("templates", "expense_delete.html")
        assert "|safe" not in template.replace(" ", "")
        assert "autoescape" not in template

    def test_delete_template_has_no_script_dialog_or_confirm(self):
        template = read_source("templates", "expense_delete.html").lower()
        for banned in ("<script", "<dialog", "confirm(", "autofocus"):
            assert banned not in template, f"{banned!r} found in the template"

    def test_profile_template_does_not_turn_off_autoescaping(self):
        template = read_source("templates", "profile.html")
        assert "|safe" not in template.replace(" ", "")

    def test_expense_css_styles_the_delete_page(self):
        css = read_source("static", "css", "expense.css")
        assert ".expense-summary" in css
        assert re.search(r"\.expense-delete-button\s*\{", css)
        assert re.search(
            r"\.expense-delete-button:hover", css
        ), "The button needs its own :hover rule"
        assert re.search(
            r"\.expense-delete-button[^{]*\{[^}]*var\(--danger\)", css
        ), "The button background should be var(--danger)"
        assert "overflow-wrap: anywhere" in css

    def test_expense_css_banner_names_the_delete_page(self):
        css = read_source("static", "css", "expense.css").lstrip()
        assert css.startswith("/*"), "Expected a banner comment at the top"
        # The run of comments before the first rule is the banner
        banner = re.match(r"(?:\s*/\*.*?\*/)+", css, re.DOTALL).group(0).lower()
        assert "delete" in banner, "The banner should also name the delete page"

    def test_profile_css_styles_the_delete_link(self):
        css = read_source("static", "css", "profile.css")
        assert ".profile-actions" in css
        assert re.search(
            r"\.profile-row-action-danger[^{]*\{[^}]*var\(--danger\)", css
        ), "The danger link should use var(--danger)"

    def test_danger_token_is_defined_in_style_css(self):
        css = read_source("static", "css", "style.css")
        assert re.search(r"--danger\s*:", css), "--danger is not defined"


# --------------------------------------------------------------------------- #
# The spec's "Definition of done" walk-through                                #
# --------------------------------------------------------------------------- #


class TestSpecWalkthrough:
    def test_the_definition_of_done_set_up_and_checks(self, spendly_app, demo, today):
        client = spendly_app.test_client()
        registered = client.post(
            url("register"),
            data={
                "name": "Dana Walker",
                "email": "dana@example.com",
                "password": PASSWORD,
            },
        )
        assert_redirects_to(registered, "login")
        signed_in = client.post(
            url("login"), data={"email": "dana@example.com", "password": PASSWORD}
        )
        assert_redirects_to(signed_in, "profile")
        dana_id = db_module.get_user_by_email("dana@example.com")["id"]

        for data in (
            {
                "amount": "250.50",
                "category": "Food",
                "date": today.isoformat(),
                "description": "Lunch",
            },
            {
                "amount": "80",
                "category": "Transport",
                "date": today.isoformat(),
                "description": "",
            },
        ):
            assert_redirects_to(client.post(url("add_expense"), data=data), "profile")
        assert [r["id"] for r in db_rows(dana_id)] == [9, 10]

        # Signed out: redirect to /login and the row is still there
        stranger = spendly_app.test_client()
        assert_redirects_to(stranger.get(delete_url(9)), "login")
        assert_redirects_to(stranger.post(delete_url(9)), "login")
        assert row_count(9) == 1

        # The table: Edit and Delete in every row, the Lunch link opens id 9
        page = profile_page(client)
        assert (
            urlparse(delete_link_for(page, 9).attrs["href"]).path
            == "/expenses/9/delete"
        )
        assert [found for found, _link in delete_links(page)] == [10, 9]

        # The confirmation pages
        lunch_page = parse_page(client.get(delete_url(9)))
        assert page_title(lunch_page) == PAGE_TITLE
        assert dict(summary_rows(lunch_page)) == {
            "Date": shown_date(today),
            "Description": "Lunch",
            "Category": "Food",
            "Amount": "₹250.50",
        }
        assert "This cannot be undone" in lunch_page.text()
        assert "coming in Step 9" not in lunch_page.raw
        transport_page = parse_page(client.get(delete_url(10)))
        assert dict(summary_rows(transport_page))["Description"] == EM_DASH

        # Refreshing and Cancel delete nothing
        for _ in range(3):
            assert client.get(delete_url(9)).status_code == 200
        assert client.get(url("profile")).status_code == 200
        assert row_count(9) == 1

        # Delete expense 9
        response = client.post(delete_url(9), follow_redirects=True)
        page = parse_page(response)
        assert flash_texts(page) == [FLASH_DELETED]
        assert summary(page) == ("₹80.00", "1", "Transport")
        assert len(table_rows(page)) == 1
        assert category_names(page) == ["Transport"]
        assert flash_texts(profile_page(client)) == []
        assert row_count(9) == 0
        assert len(db_rows()) == 9, "One row went, no other"

        # A second delete and a GET now answer 404
        assert client.get(delete_url(9)).status_code == 404
        assert client.post(delete_url(9)).status_code == 404
        assert flash_texts(profile_page(client)) == []
        assert len(db_rows()) == 9

        # Delete expense 10 as well: the empty state
        page = parse_page(client.post(delete_url(10), follow_redirects=True))
        assert summary(page) == ("₹0.00", "0", EM_DASH)
        assert "No expenses yet" in page.text()
        assert category_names(page) == []

        # A new expense gets id 11
        client.post(
            url("add_expense"),
            data={
                "amount": "5",
                "category": "Other",
                "date": today.isoformat(),
                "description": "",
            },
        )
        assert [r["id"] for r in db_rows(dana_id)] == [11]

        # The demo user's expense 1 is out of reach
        assert client.get(delete_url(1)).status_code == 404
        assert client.post(delete_url(1)).status_code == 404
        assert row_count(1) == 1

        # The body cannot redirect the delete to expense 1
        response = client.post(delete_url(11), data={"user_id": 1, "expense_id": 1})
        assert_redirects_to(response, "profile")
        assert row_count(11) == 0
        assert row_count(1) == 1
