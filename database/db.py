import sqlite3
from datetime import date
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# Database file lives in the project root, next to app.py
DB_PATH = Path(__file__).resolve().parent.parent / "expense_tracker.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # SQLite leaves foreign keys off by default, per connection
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                amount      REAL NOT NULL,
                category    TEXT NOT NULL,
                date        TEXT NOT NULL,
                description TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users (id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def seed_db():
    conn = get_db()
    try:
        # Already seeded — do nothing, so repeated runs never duplicate data
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return

        today = date.today()

        # (day of month, category, amount, description)
        sample_expenses = [
            (1, "Bills", 1200.00, "Electricity bill"),
            (3, "Food", 250.50, "Groceries"),
            (5, "Transport", 80.00, "Metro card recharge"),
            (8, "Health", 450.00, "Pharmacy"),
            (12, "Entertainment", 300.00, "Movie tickets"),
            (15, "Shopping", 999.99, "Headphones"),
            (19, "Food", 180.00, "Lunch with friends"),
            (24, "Other", 150.00, "Gift wrap and card"),
        ]

        # One transaction: user and expenses are saved together or not at all
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
            )
            user_id = cursor.lastrowid

            conn.executemany(
                "INSERT INTO expenses (user_id, amount, category, date, description)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        user_id,
                        amount,
                        category,
                        # Current month, YYYY-MM-DD, never later than today
                        today.replace(day=min(day, today.day)).isoformat(),
                        description,
                    )
                    for day, category, amount, description in sample_expenses
                ],
            )
    finally:
        conn.close()


def get_user_by_email(email):
    # Returns the user's row, or None when no account uses this email
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()


def create_user(name, email, password):
    conn = get_db()
    try:
        # Saved on success; a duplicate email raises sqlite3.IntegrityError
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_id(user_id):
    # Returns the user's row, or None when no account has this id
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def authenticate_user(email, password):
    # Returns the user's row when the email and password match, else None.
    # Expects an email that is already lower-cased, like get_user_by_email()
    user = get_user_by_email(email)
    if user is None:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user
