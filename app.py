from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from db import get_connection, init_db
from parser import parse_statement_csv, categorize

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "recon-dev-secret"

init_db()


@app.route("/")
def index():
    conn = get_connection()
    statements = conn.execute(
        "SELECT * FROM statements ORDER BY uploaded_at DESC"
    ).fetchall()

    totals = conn.execute(
        """
        SELECT type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY type
        """
    ).fetchall()
    income_total = 0.0
    expense_total = 0.0
    for row in totals:
        if row["type"] == "income":
            income_total = row["total"]
        else:
            expense_total = row["total"]

    by_category = conn.execute(
        """
        SELECT category, type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE type = 'expense'
        GROUP BY category
        ORDER BY total DESC
        """
    ).fetchall()

    by_month = conn.execute(
        """
        SELECT strftime('%Y-%m', date) AS month, type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY month, type
        ORDER BY month
        """
    ).fetchall()

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


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("statement")
    if not file or file.filename == "":
        flash("Please choose a CSV file to upload.", "error")
        return redirect(url_for("index"))

    if not file.filename.lower().endswith(".csv"):
        flash("Only CSV files are supported right now.", "error")
        return redirect(url_for("index"))

    try:
        records = parse_statement_csv(file.stream)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))

    if not records:
        flash("No transactions could be parsed from that file.", "error")
        return redirect(url_for("index"))

    conn = get_connection()
    rules = [
        (r["keyword"], r["category"])
        for r in conn.execute("SELECT keyword, category FROM rules").fetchall()
    ]

    cur = conn.execute(
        "INSERT INTO statements (filename) VALUES (?)", (file.filename,)
    )
    statement_id = cur.lastrowid

    for rec in records:
        category = categorize(rec["description"], rules)
        if category == "Uncategorized" and rec["type"] == "income":
            category = "Income"
        conn.execute(
            """
            INSERT INTO transactions (statement_id, date, description, amount, type, category)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                statement_id,
                rec["date"],
                rec["description"],
                rec["amount"],
                rec["type"],
                category,
            ),
        )

    conn.commit()
    conn.close()

    flash(f"Imported {len(records)} transactions from {file.filename}.", "success")
    return redirect(url_for("transactions"))


@app.route("/transactions")
def transactions():
    statement_id = request.args.get("statement_id")
    type_filter = request.args.get("type")
    category_filter = request.args.get("category")

    query = "SELECT t.*, s.filename FROM transactions t JOIN statements s ON t.statement_id = s.id WHERE 1=1"
    params = []
    if statement_id:
        query += " AND t.statement_id = ?"
        params.append(statement_id)
    if type_filter:
        query += " AND t.type = ?"
        params.append(type_filter)
    if category_filter:
        query += " AND t.category = ?"
        params.append(category_filter)
    query += " ORDER BY t.date DESC, t.id DESC"

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    categories = [
        r["category"]
        for r in conn.execute(
            "SELECT DISTINCT category FROM transactions ORDER BY category"
        ).fetchall()
    ]
    statements = conn.execute("SELECT id, filename FROM statements").fetchall()
    conn.close()

    return render_template(
        "transactions.html",
        transactions=rows,
        categories=categories,
        statements=statements,
        statement_id=statement_id,
        type_filter=type_filter,
        category_filter=category_filter,
    )


@app.route("/transactions/<int:txn_id>/category", methods=["POST"])
def update_category(txn_id):
    new_category = request.form.get("category", "").strip()
    if not new_category:
        flash("Category cannot be empty.", "error")
        return redirect(url_for("transactions"))

    conn = get_connection()
    txn = conn.execute(
        "SELECT description FROM transactions WHERE id = ?", (txn_id,)
    ).fetchone()
    conn.execute(
        "UPDATE transactions SET category = ? WHERE id = ?", (new_category, txn_id)
    )

    remember = request.form.get("remember")
    if remember and txn:
        keyword = txn["description"].split()[0].lower() if txn["description"] else None
        if keyword:
            conn.execute(
                """
                INSERT INTO rules (keyword, category) VALUES (?, ?)
                ON CONFLICT(keyword) DO UPDATE SET category = excluded.category
                """,
                (keyword, new_category),
            )

    conn.commit()
    conn.close()
    flash("Category updated.", "success")
    return redirect(request.referrer or url_for("transactions"))


@app.route("/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(txn_id):
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()
    conn.close()
    flash("Transaction deleted.", "success")
    return redirect(request.referrer or url_for("transactions"))


@app.route("/statements/<int:statement_id>/delete", methods=["POST"])
def delete_statement(statement_id):
    conn = get_connection()
    conn.execute("DELETE FROM transactions WHERE statement_id = ?", (statement_id,))
    conn.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
    conn.commit()
    conn.close()
    flash("Statement and its transactions removed.", "success")
    return redirect(url_for("index"))


@app.route("/rules")
def rules():
    conn = get_connection()
    rule_rows = conn.execute("SELECT * FROM rules ORDER BY category, keyword").fetchall()
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
    conn.execute(
        """
        INSERT INTO rules (keyword, category) VALUES (?, ?)
        ON CONFLICT(keyword) DO UPDATE SET category = excluded.category
        """,
        (keyword, category),
    )
    conn.commit()
    conn.close()
    flash("Rule saved.", "success")
    return redirect(url_for("rules"))


@app.route("/rules/<int:rule_id>/delete", methods=["POST"])
def delete_rule(rule_id):
    conn = get_connection()
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    flash("Rule deleted.", "success")
    return redirect(url_for("rules"))


@app.route("/api/summary")
def api_summary():
    conn = get_connection()
    by_month = conn.execute(
        """
        SELECT strftime('%Y-%m', date) AS month, type, COALESCE(SUM(amount), 0) AS total
        FROM transactions
        GROUP BY month, type
        ORDER BY month
        """
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in by_month])


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
