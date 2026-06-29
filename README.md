# Bank Recon

A small Flask app for reconciling bank statements: upload CSV exports, auto-categorize transactions as income or expenses, and review spending by category and month.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Visit http://localhost:5000.

## Usage

1. **Upload** a CSV bank statement (needs a date + description column, plus either an amount column or separate debit/credit columns).
2. Transactions are auto-categorized using keyword rules (editable under **Categorization Rules**); positive amounts are treated as income, negative as expenses.
3. Review the **Dashboard** for income/expense totals, spend by category, and a monthly breakdown.
4. Fine-tune individual transactions on the **Transactions** page — edit the category inline and optionally check "remember" to save it as a new rule.

Data is stored locally in `instance/recon.db` (SQLite).
