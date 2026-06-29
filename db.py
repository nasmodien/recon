import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "instance" / "recon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    FOREIGN KEY (statement_id) REFERENCES statements(id)
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);
"""

DEFAULT_RULES = [
    ("salary", "Income"),
    ("payroll", "Income"),
    ("interest", "Income"),
    ("refund", "Income"),
    ("grocery", "Groceries"),
    ("woolworths", "Groceries"),
    ("checkers", "Groceries"),
    ("pick n pay", "Groceries"),
    ("uber", "Transport"),
    ("bolt", "Transport"),
    ("fuel", "Transport"),
    ("petrol", "Transport"),
    ("rent", "Housing"),
    ("electricity", "Utilities"),
    ("water", "Utilities"),
    ("netflix", "Subscriptions"),
    ("spotify", "Subscriptions"),
    ("insurance", "Insurance"),
    ("restaurant", "Dining"),
    ("takealot", "Shopping"),
    ("atm", "Cash Withdrawal"),
    ("transfer", "Transfer"),
]


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    cur = conn.execute("SELECT COUNT(*) FROM rules")
    if cur.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO rules (keyword, category) VALUES (?, ?)", DEFAULT_RULES
        )
    conn.commit()
    conn.close()
