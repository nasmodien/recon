import hashlib
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from db import get_connection, init_db
from parser import parse_statement_xlsx, parse_client_directory, categorize

BASE_DIR = Path(__file__).parent
STATEMENT_FILES = [
    ("FNB", BASE_DIR / "data" / "fnb_statement.xlsx"),
    ("ABSA", BASE_DIR / "data" / "absa_statement.xlsx"),
]
CLIENT_DIRECTORY_FILE = BASE_DIR / "data" / "client_directory.xlsx"

app = Flask(__name__, static_folder=str(BASE_DIR / "public" / "static"))
app.secret_key = "recon-dev-secret"


@app.template_filter("currency")
def currency_filter(value):
    return f"R {float(value):,.2f}"


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_client_directory():
    if not CLIENT_DIRECTORY_FILE.exists():
        return 0
    clients = parse_client_directory(CLIENT_DIRECTORY_FILE)
    conn = get_connection()
    cur = conn.cursor()
    for code, name in clients.items():
        cur.execute(
            """
            INSERT INTO clients (customer_code, name) VALUES (%s, %s)
            ON CONFLICT (customer_code) DO UPDATE SET name = excluded.name
            """,
            (code, name),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(clients)


def _load_one_statement_file(cur, source, path, replace=False):
    if not path.exists():
        return 0

    current_hash = _file_hash(path)

    if not replace:
        cur.execute(
            "SELECT file_hash FROM statements WHERE source = %s ORDER BY id DESC LIMIT 1",
            (source,),
        )
        row = cur.fetchone()
        if row is not None and row["file_hash"] == current_hash:
            return None

    cur.execute(
        "DELETE FROM transactions WHERE statement_id IN (SELECT id FROM statements WHERE source = %s)",
        (source,),
    )
    cur.execute("DELETE FROM statements WHERE source = %s", (source,))

    records = parse_statement_xlsx(path, source=source)

    cur.execute("SELECT keyword, category FROM rules")
    rules = [(r["keyword"], r["category"]) for r in cur.fetchall()]

    cur.execute(
        "INSERT INTO statements (filename, file_hash, source) VALUES (%s, %s, %s) RETURNING id",
        (path.name, current_hash, source),
    )
    statement_id = cur.fetchone()["id"]

    for rec in records:
        category = rec.get("category") or categorize(rec["description"], rules)
        if category == "Uncategorized" and rec["type"] == "income":
            category = "Income"
        cur.execute(
            """
            INSERT INTO transactions (statement_id, date, description, amount, type, category, customer_code, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                statement_id,
                rec["date"],
                rec["description"],
                rec["amount"],
                rec["type"],
                category,
                rec.get("customer_code"),
                source,
            ),
        )

    return len(records)


def _load_statement_file(replace=False):
    conn = get_connection()
    cur = conn.cursor()

    total = 0
    any_loaded = False
    for source, path in STATEMENT_FILES:
        count = _load_one_statement_file(cur, source, path, replace=replace)
        if count is not None:
            any_loaded = True
            total += count

    conn.commit()
    cur.close()
    conn.close()
    return total if any_loaded else None


init_db()
_load_statement_file()
_load_client_directory()


@app.route("/")
def index():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM statements ORDER BY uploaded_at DESC")
    statements = cur.fetchall()

    cur.execute(
        """
        SELECT type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY type
        """
    )
    income_total = 0.0
    expense_total = 0.0
    for row in cur.fetchall():
        if row["type"] == "income":
            income_total = float(row["total"])
        else:
            expense_total = float(row["total"])

    cur.execute(
        """
        SELECT category, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE type = 'expense'
        GROUP BY category
        ORDER BY total DESC
        """
    )
    by_category = cur.fetchall()

    cur.execute(
        """
        SELECT to_char(date, 'YYYY-MM') AS month, type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY month, type
        ORDER BY month
        """
    )
    by_month = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "index.html",
        statements=statements,
        income_total=income_total,
        expense_total=expense_total,
        net_total=income_total - expense_total,
        by_category=by_category,
        by_month=by_month,
    )


@app.route("/reload", methods=["POST"])
def reload_statement_file():
    try:
        count = _load_statement_file(replace=True)
        _load_client_directory()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))

    flash(f"Reloaded {count} transactions from the bundled statement files.", "success")
    return redirect(url_for("index"))


@app.route("/transactions")
def transactions():
    statement_id = request.args.get("statement_id")
    type_filter = request.args.get("type")
    category_filter = request.args.get("category")
    search = request.args.get("search", "").strip()
    source_filter = request.args.get("source")

    query = "SELECT t.*, s.filename FROM transactions t JOIN statements s ON t.statement_id = s.id WHERE 1=1"
    params = []
    if statement_id:
        query += " AND t.statement_id = %s"
        params.append(statement_id)
    if type_filter:
        query += " AND t.type = %s"
        params.append(type_filter)
    if category_filter:
        query += " AND t.category = %s"
        params.append(category_filter)
    if search:
        query += " AND t.description ILIKE %s"
        params.append(f"%{search}%")
    if source_filter in ("FNB", "ABSA"):
        query += " AND t.source = %s"
        params.append(source_filter)
    query += " ORDER BY t.date DESC, t.id DESC"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

    income_total = sum(float(r["amount"]) for r in rows if r["type"] == "income")
    expense_total = sum(float(r["amount"]) for r in rows if r["type"] == "expense")

    cur.execute("SELECT DISTINCT category FROM transactions ORDER BY category")
    categories = [r["category"] for r in cur.fetchall()]

    cur.execute("SELECT id, filename FROM statements")
    statements = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "transactions.html",
        transactions=rows,
        categories=categories,
        statements=statements,
        statement_id=statement_id,
        type_filter=type_filter,
        category_filter=category_filter,
        search=search,
        source_filter=source_filter,
        income_total=income_total,
        expense_total=expense_total,
        net_total=income_total - expense_total,
    )


@app.route("/transactions/<int:txn_id>/category", methods=["POST"])
def update_category(txn_id):
    new_category = request.form.get("category", "").strip()
    if not new_category:
        flash("Category cannot be empty.", "error")
        return redirect(url_for("transactions"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT description FROM transactions WHERE id = %s", (txn_id,))
    txn = cur.fetchone()
    cur.execute(
        "UPDATE transactions SET category = %s WHERE id = %s", (new_category, txn_id)
    )

    remember = request.form.get("remember")
    if remember and txn:
        keyword = txn["description"].split()[0].lower() if txn["description"] else None
        if keyword:
            cur.execute(
                """
                INSERT INTO rules (keyword, category) VALUES (%s, %s)
                ON CONFLICT (keyword) DO UPDATE SET category = excluded.category
                """,
                (keyword, new_category),
            )

    conn.commit()
    cur.close()
    conn.close()
    flash("Category updated.", "success")
    return redirect(request.referrer or url_for("transactions"))


@app.route("/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(txn_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE id = %s", (txn_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Transaction deleted.", "success")
    return redirect(request.referrer or url_for("transactions"))


@app.route("/statements/<int:statement_id>/delete", methods=["POST"])
def delete_statement(statement_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM transactions WHERE statement_id = %s", (statement_id,))
    cur.execute("DELETE FROM statements WHERE id = %s", (statement_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Statement and its transactions removed.", "success")
    return redirect(url_for("index"))


@app.route("/customers")
def customers():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            t.customer_code,
            c.name AS client_name,
            COALESCE(SUM(t.amount) FILTER (WHERE t.type = 'income'), 0) AS received,
            COALESCE(SUM(t.amount) FILTER (WHERE t.type = 'expense'), 0) AS paid,
            COUNT(*) AS txn_count,
            MIN(t.date) AS first_date,
            MAX(t.date) AS last_date
        FROM transactions t
        LEFT JOIN clients c ON UPPER(t.customer_code) = c.customer_code
        WHERE t.customer_code IS NOT NULL
        GROUP BY t.customer_code, c.name
        ORDER BY (COALESCE(SUM(t.amount) FILTER (WHERE t.type = 'income'), 0)
                  + COALESCE(SUM(t.amount) FILTER (WHERE t.type = 'expense'), 0)) DESC
        """
    )
    customer_rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("customers.html", customers=customer_rows)


@app.route("/customers/<code>")
def customer_detail(code):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM transactions WHERE customer_code = %s ORDER BY date, id",
        (code,),
    )
    txns = cur.fetchall()

    cur.execute("SELECT name FROM clients WHERE customer_code = %s", (code.upper(),))
    client_row = cur.fetchone()
    cur.close()
    conn.close()

    if not txns:
        flash(f"No transactions found for customer code {code}.", "error")
        return redirect(url_for("customers"))

    received = sum(float(t["amount"]) for t in txns if t["type"] == "income")
    paid = sum(float(t["amount"]) for t in txns if t["type"] == "expense")

    return render_template(
        "customer_detail.html",
        code=code,
        client_name=client_row["name"] if client_row else None,
        transactions=txns,
        received=received,
        paid=paid,
        net=received - paid,
    )


@app.route("/payments")
def payments():
    customer_code = request.args.get("customer_code") or None
    type_filter = request.args.get("type") or None
    category_filter = request.args.get("category") or None
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None

    query = "SELECT date, description, amount, type, category, customer_code FROM transactions WHERE 1=1"
    params = []
    if customer_code:
        query += " AND customer_code = %s"
        params.append(customer_code)
    if type_filter:
        query += " AND type = %s"
        params.append(type_filter)
    if category_filter:
        query += " AND category = %s"
        params.append(category_filter)
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)
    query += " ORDER BY date, customer_code"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

    cur.execute(
        "SELECT DISTINCT customer_code FROM transactions WHERE customer_code IS NOT NULL ORDER BY customer_code"
    )
    customer_codes = [r["customer_code"] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT category FROM transactions ORDER BY category")
    categories = [r["category"] for r in cur.fetchall()]

    cur.close()
    conn.close()

    timeline = [
        {
            "date": row["date"].isoformat(),
            "amount": float(row["amount"]) if row["type"] == "income" else -float(row["amount"]),
            "type": row["type"],
            "description": row["description"],
            "category": row["category"],
            "customer_code": row["customer_code"],
        }
        for row in rows
    ]

    received_total = sum(p["amount"] for p in timeline if p["type"] == "income")
    paid_total = -sum(p["amount"] for p in timeline if p["type"] == "expense")

    return render_template(
        "payments.html",
        payments=rows,
        timeline=timeline,
        customer_codes=customer_codes,
        categories=categories,
        customer_code=customer_code,
        type_filter=type_filter,
        category_filter=category_filter,
        start_date=start_date,
        end_date=end_date,
        received_total=received_total,
        paid_total=paid_total,
    )


@app.route("/rules")
def rules():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rules ORDER BY category, keyword")
    rule_rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("rules.html", rules=rule_rows)


@app.route("/rules/add", methods=["POST"])
def add_rule():
    keyword = request.form.get("keyword", "").strip().lower()
    category = request.form.get("category", "").strip()
    if not keyword or not category:
        flash("Both keyword and category are required.", "error")
        return redirect(url_for("rules"))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rules (keyword, category) VALUES (%s, %s)
        ON CONFLICT (keyword) DO UPDATE SET category = excluded.category
        """,
        (keyword, category),
    )
    conn.commit()
    cur.close()
    conn.close()
    flash("Rule saved.", "success")
    return redirect(url_for("rules"))


@app.route("/rules/<int:rule_id>/delete", methods=["POST"])
def delete_rule(rule_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM rules WHERE id = %s", (rule_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash("Rule deleted.", "success")
    return redirect(url_for("rules"))


@app.route("/api/summary")
def api_summary():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT to_char(date, 'YYYY-MM') AS month, type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY month, type
        ORDER BY month
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([dict(row) for row in rows])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
