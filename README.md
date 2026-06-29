# Bank Recon

A small Flask app for reconciling bank statements: upload CSV exports, auto-categorize transactions as income or expenses, and review spending by category and month. Backed by Postgres so it works on Vercel's serverless functions.

## Local setup

Requires a Postgres database (local or hosted).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://user:password@localhost:5432/recon"
.venv/bin/python app.py
```

Visit http://localhost:5000.

## Deploying to Vercel

1. Push this repo to GitHub and import it in Vercel.
2. In the Vercel project, add a **Postgres** store (Storage tab → Create Database → Postgres). This automatically sets a `DATABASE_URL` (or `POSTGRES_URL`) environment variable for the project — if Vercel names it differently, add an env var `DATABASE_URL` pointing at the same connection string.
3. Deploy. `vercel.json` routes all requests to `api/index.py`, which exposes the Flask app as a serverless function; `/static/*` is served directly.

## Usage

1. **Upload** a CSV bank statement (needs a date + description column, plus either an amount column or separate debit/credit columns).
2. Transactions are auto-categorized using keyword rules (editable under **Categorization Rules**); positive amounts are treated as income, negative as expenses.
3. Review the **Dashboard** for income/expense totals, spend by category, and a monthly breakdown.
4. Fine-tune individual transactions on the **Transactions** page — edit the category inline and optionally check "remember" to save it as a new rule.
