import os

import psycopg2
import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    statement_id INTEGER NOT NULL REFERENCES statements(id),
    date DATE NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    customer_code TEXT
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS customer_code TEXT;
CREATE INDEX IF NOT EXISTS idx_transactions_customer_code ON transactions (customer_code);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);

CREATE TABLE IF NOT EXISTS rules (
    id SERIAL PRIMARY KEY,
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
    database_url = os.environ["DATABASE_URL"]
    return psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute("SELECT COUNT(*) AS count FROM rules")
    if cur.fetchone()["count"] == 0:
        cur.executemany(
            "INSERT INTO rules (keyword, category) VALUES (%s, %s)", DEFAULT_RULES
        )
    conn.commit()
    cur.close()
    conn.close()
