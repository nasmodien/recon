from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from db import get_connection, init_db
from parser import parse_statement_csv, categorize

BASE_DIR = Path(__file__).parent

app = Flask(__name__)
app.secret_key = "recon-dev-secret"

init_db()


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
    cur = conn.cursor()

    cur.execute("SELECT keyword, category FROM rules")
    rules = [(r["keyword"], r["category"]) for r in cur.fetchall()]

    cur.execute(
        "INSERT INTO statements (filename) VALUES (%s) RETURNING id", (file.filename,)
    )
    statement_id = cur.fetchone()["id"]

    for rec in records:
        category = categorize(rec["description"], rules)
        if category == "Uncategorized" and rec["type"] == "income":
            category = "Income"
        cur.execute(
            """
            INSERT INTO transactions (statement_id, date, description, amount, type, category)
            VALUES (%s, %s, %s, %s, %s, %s)
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
    cur.close()
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
        query += " AND t.statement_id = %s"
        params.append(statement_id)
    if type_filter:
        query += " AND t.type = %s"
        params.append(type_filter)
    if category_filter:
        query += " AND t.category = %s"
        params.append(category_filter)
    query += " ORDER BY t.date DESC, t.id DESC"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()

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
