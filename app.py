import os
import re
import secrets
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from database.db import (
    CATEGORIES,
    authenticate_user,
    create_expense,
    create_user,
    get_category_totals,
    get_expense_stats,
    get_recent_expenses,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)

app = Flask(__name__)

# Signs the session cookie. Without SECRET_KEY in the environment a new key is
# made on every start, so restarting the server signs everyone out
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Create the tables and demo data before any route is used
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Signed-in user                                                      #
# ------------------------------------------------------------------ #

@app.before_request
def load_user():
    g.user = None
    # CSS and JS requests do not need to know who is signed in
    if request.endpoint == "static":
        return

    user_id = session.get("user_id")
    if user_id is None:
        return

    g.user = get_user_by_id(user_id)
    if g.user is None:
        # The account is gone (for example the database file was deleted)
        session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


# ------------------------------------------------------------------ #
# Template filters                                                    #
# ------------------------------------------------------------------ #

@app.template_filter("format_money")
def format_money(value):
    # 3610.49 becomes ₹3,610.49
    return f"₹{value:,.2f}"


@app.template_filter("format_date")
def format_date(value, fmt="%d %b %Y"):
    # Takes the text SQLite stores: "2026-09-24" or "2026-09-24 18:05:00"
    if not value:
        return ""
    return datetime.fromisoformat(value).strftime(fmt)


# ------------------------------------------------------------------ #
# Date filter                                                         #
# ------------------------------------------------------------------ #

def parse_filter_date(text):
    # Returns a date, or None when the text is not a real YYYY-MM-DD date.
    # The add-expense form checks its date with this too.
    # strptime, not date.fromisoformat, which also takes week dates (2026-W36-2)
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def get_date_presets(today):
    # The ranges offered as links on the profile page; each one ends today

    def first_of_month(months_back):
        # Months counted as one number, so January steps back into last year
        index = today.year * 12 + today.month - 1 - months_back
        return date(index // 12, index % 12 + 1, 1).isoformat()

    end = today.isoformat()
    return [
        {"label": "This month", "date_from": first_of_month(0), "date_to": end},
        {"label": "Last 3 months", "date_from": first_of_month(2), "date_to": end},
        {"label": "Last 6 months", "date_from": first_of_month(5), "date_to": end},
        {"label": "All time", "date_from": None, "date_to": None},
    ]


# ------------------------------------------------------------------ #
# Expense form                                                        #
# ------------------------------------------------------------------ #

# The limits the form checks; the messages below quote them
MAX_AMOUNT = 9_999_999.99
MAX_DESCRIPTION_LENGTH = 200

# Digits, then at most two decimals. Checked before float(), which would
# also take "nan", "inf", "1e5" and a minus sign. [0-9], not \d, which also
# matches digits from other scripts
AMOUNT_PATTERN = re.compile(r"[0-9]+(\.[0-9]{1,2})?")


def check_expense_form(amount_text, category, date_text, description, today):
    # Returns (error, amount, expense_date) for values that are already
    # stripped. The first rule that fails decides the message. When every
    # rule passes, error is None and the other two hold the values to save
    if not amount_text or not category or not date_text:
        return "Please fill in the amount, category and date.", None, None

    if not AMOUNT_PATTERN.fullmatch(amount_text):
        return "Please enter a valid amount, like 250 or 250.50.", None, None

    amount = float(amount_text)
    if amount == 0:
        return "Amount must be greater than zero.", None, None
    if amount > MAX_AMOUNT:
        return f"Amount cannot be more than {format_money(MAX_AMOUNT)}.", None, None

    if category not in CATEGORIES:
        return "Please choose a category from the list.", None, None

    expense_date = parse_filter_date(date_text)
    if expense_date is None:
        return "Please enter a valid date.", None, None
    if expense_date > today:
        return "The date cannot be in the future.", None, None

    if len(description) > MAX_DESCRIPTION_LENGTH:
        return (
            f"Description cannot be longer than {MAX_DESCRIPTION_LENGTH} characters.",
            None,
            None,
        )

    return None, amount, expense_date


def render_expense_form(today, **values):
    # The add-expense page. values holds what the fields show, and the error
    return render_template(
        "add_expense.html",
        categories=CATEGORIES,
        today=today.isoformat(),
        **values,
    )


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        # Someone already signed in has no use for this form
        if g.user:
            return redirect(url_for("landing"))
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    # Looked up and saved in lower case, so Demo@x.com and demo@x.com are one account
    email_lower = email.lower()

    before_at, at_sign, after_at = email.partition("@")
    email_taken = "An account with this email already exists."

    # The first rule that fails decides the message
    error = None
    if not name or not email or not password:
        error = "Please fill in your name, email and password."
    elif not (before_at and at_sign and after_at):
        error = "Please enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif get_user_by_email(email_lower):
        error = email_taken

    if error is None:
        try:
            create_user(name, email_lower, password)
        except sqlite3.IntegrityError:
            # Same email registered between the check above and this insert
            error = email_taken

    if error:
        return render_template("register.html", error=error, name=name, email=email)

    # Redirect, so refreshing the next page cannot submit the form again
    flash("Account created. Please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if g.user:
            return redirect(url_for("landing"))
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    # The first rule that fails decides the message
    error = None
    user = None
    if not email or not password:
        error = "Please enter your email and password."
    else:
        # Same message for an unknown email and a wrong password, so the form
        # does not reveal which emails have accounts
        user = authenticate_user(email.lower(), password)
        if user is None:
            error = "Invalid email or password."

    if error:
        return render_template("login.html", error=error, email=email)

    # Start from an empty session, so nothing from before sign-in is kept
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for("profile"))


@app.route("/logout", methods=["POST"])
def logout():
    # Clear first: the flash message is stored in the session too
    session.clear()
    flash("You have been signed out.")
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/profile")
@login_required
def profile():
    # An empty value (the form was sent with the input left blank) is not given
    typed_from = request.args.get("date_from", "").strip()
    typed_to = request.args.get("date_to", "").strip()
    start = parse_filter_date(typed_from) if typed_from else None
    end = parse_filter_date(typed_to) if typed_to else None

    # The first rule that fails decides the message
    filter_error = None
    if (typed_from and start is None) or (typed_to and end is None):
        filter_error = "Please enter valid dates."
    elif start and end and start > end:
        filter_error = "The start date cannot be after the end date."

    # The range the queries use. Always the parsed date written out again,
    # never the text from the URL. A bad range filters nothing
    date_from = date_to = None
    if filter_error is None:
        date_from = start.isoformat() if start else None
        date_to = end.isoformat() if end else None
    filter_active = date_from is not None or date_to is not None

    # Totals for the signed-in user only, over the expenses in the range
    stats = get_expense_stats(g.user["id"], date_from, date_to)

    # Newest first, ten at most; rows have the expenses table column names
    expenses = get_recent_expenses(g.user["id"], date_from=date_from, date_to=date_to)

    # Largest total first, with each category's share of the total in the range
    categories = get_category_totals(g.user["id"], date_from, date_to)

    # "All time" has no dates, so it is the active one when nothing is filtered
    presets = get_date_presets(date.today())
    for preset in presets:
        preset["active"] = (
            preset["date_from"] == date_from and preset["date_to"] == date_to
        )

    return render_template(
        "profile.html",
        stats=stats,
        expenses=expenses,
        categories=categories,
        # What the inputs show: after an error, what the user typed
        date_from=typed_from if filter_error else date_from,
        date_to=typed_to if filter_error else date_to,
        filter_active=filter_active,
        filter_error=filter_error,
        presets=presets,
    )


@app.route("/analytics")
@login_required
def analytics():
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    today = date.today()

    if request.method == "GET":
        return render_expense_form(today, date=today.isoformat())

    amount_text = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date_text = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip()

    error, amount, expense_date = check_expense_form(
        amount_text, category, date_text, description, today
    )

    if error:
        return render_expense_form(
            today,
            error=error,
            # What the user typed, so nothing has to be entered again
            amount=amount_text,
            category=category,
            date=date_text,
            description=description,
        )

    # The owner is always the signed-in user, never a value from the form.
    # The date is the parsed one written out again, so it is always
    # zero-padded YYYY-MM-DD. An empty description is saved as NULL
    create_expense(
        g.user["id"],
        amount,
        category,
        expense_date.isoformat(),
        description or None,
    )

    # Redirect, so refreshing the next page cannot submit the form again
    flash("Expense added.")
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit")
@login_required
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
@login_required
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
