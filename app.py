import os
import secrets
import sqlite3
from datetime import datetime
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
    authenticate_user,
    create_user,
    get_db,
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
    # Sample values for the design step. Step 5 replaces all three with
    # queries on the expenses table, in this same shape
    stats = {
        "total_spent": 3610.49,
        "transaction_count": 8,
        "top_category": "Bills",
    }

    # Newest first; same keys as the expenses table columns
    expenses = [
        {"date": "2026-09-24", "description": "Gift wrap and card",
         "category": "Other", "amount": 150.00},
        {"date": "2026-09-19", "description": "Lunch with friends",
         "category": "Food", "amount": 180.00},
        {"date": "2026-09-15", "description": "Headphones",
         "category": "Shopping", "amount": 999.99},
        {"date": "2026-09-12", "description": "Movie tickets",
         "category": "Entertainment", "amount": 300.00},
        {"date": "2026-09-08", "description": "Pharmacy",
         "category": "Health", "amount": 450.00},
        {"date": "2026-09-05", "description": "Metro card recharge",
         "category": "Transport", "amount": 80.00},
        {"date": "2026-09-03", "description": "Groceries",
         "category": "Food", "amount": 250.50},
        {"date": "2026-09-01", "description": "Electricity bill",
         "category": "Bills", "amount": 1200.00},
    ]

    # Largest first; percent is the share of total_spent, rounded
    categories = [
        {"name": "Bills", "total": 1200.00, "percent": 33},
        {"name": "Shopping", "total": 999.99, "percent": 28},
        {"name": "Health", "total": 450.00, "percent": 12},
        {"name": "Food", "total": 430.50, "percent": 12},
        {"name": "Entertainment", "total": 300.00, "percent": 8},
        {"name": "Other", "total": 150.00, "percent": 4},
        {"name": "Transport", "total": 80.00, "percent": 2},
    ]

    return render_template(
        "profile.html", stats=stats, expenses=expenses, categories=categories
    )


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
@login_required
def add_expense():
    return "Add expense — coming in Step 7"


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
