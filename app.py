import sqlite3

from flask import Flask, redirect, render_template, request, url_for

from database.db import create_user, get_db, get_user_by_email, init_db, seed_db

app = Flask(__name__)

# Create the tables and demo data before any route is used
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
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
    return redirect(url_for("login"))


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
