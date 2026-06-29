# Bank Recon

A small Flask app for reconciling bank statements: reads transactions directly from a bundled bookkeeping workbook, auto-categorizes them as income or expenses, matches customer account (CU) numbers to track what was received from / paid to each customer, and shows a payments timeline. Backed by Postgres so it works on Vercel's serverless functions.

## Data source

The app reads exclusively from `data/bank_statement.xlsx`, a workbook committed to this repo. There is no upload feature. To update the data, replace that file and redeploy (or re-run locally), then click **Reload from file** on the dashboard to re-import it — this replaces all existing transactions.

The workbook is expected to have a `Transactions` sheet (or the first sheet) with columns for date, description, and either an amount column or separate debit/credit columns. Optional columns:

- A counterparty/customer code column (e.g. "Counterparty Code", "Customer Code", "CU Number") used to group transactions by customer.
- A `Category` column, used as-is if present; otherwise transactions are auto-categorized using keyword rules.

## Local setup

Requires a Postgres database (local or hosted).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://user:password@localhost:5432/recon"
.venv/bin/python app.py
```

Visit http://localhost:5000. On first run, the app automatically loads `data/bank_statement.xlsx` into the database.

## Deploying to Vercel

1. Push this repo to GitHub and import it in Vercel.
2. In the Vercel project, add a **Postgres** store (Storage tab → Create Database → Postgres). This automatically sets a `DATABASE_URL` (or `POSTGRES_URL`) environment variable for the project — if Vercel names it differently, add an env var `DATABASE_URL` pointing at the same connection string.
3. Deploy. `vercel.json` routes all requests to `api/index.py`, which exposes the Flask app as a serverless function and bundles `templates/` and `data/` alongside it; `/static/*` is served directly from `public/static`.

## Usage

1. The **Dashboard** shows income/expense totals, spend by category, a monthly breakdown, and the currently loaded statement file. Use **Reload from file** to re-import the bundled workbook (e.g. after replacing it and redeploying).
2. Transactions are auto-categorized using keyword rules (editable under **Categorization Rules**); positive amounts are treated as income, negative as expenses.
3. Fine-tune individual transactions on the **Transactions** page — edit the category inline and optionally check "remember" to save it as a new rule.
4. The **Customers** page lists each customer/counterparty code with totals received, paid, and net, linking to a detail page with their full transaction history.
5. The **Payments** page lets you filter transactions by customer, type, category, and date range, and shows a timeline chart of payments received vs. paid over time.
