import pandas as pd

DATE_CANDIDATES = ["date", "transaction date", "posted date", "value date"]
DESC_CANDIDATES = ["description", "narrative", "details", "memo", "particulars"]
AMOUNT_CANDIDATES = ["amount", "value"]
DEBIT_CANDIDATES = ["debit", "withdrawal", "money out"]
CREDIT_CANDIDATES = ["credit", "deposit", "money in"]


def _find_column(columns, candidates):
    lower = {c.lower().strip(): c for c in columns}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    for cand in candidates:
        for low, orig in lower.items():
            if cand in low:
                return orig
    return None


def parse_statement_csv(file_stream):
    df = pd.read_csv(file_stream)
    df.columns = [str(c).strip() for c in df.columns]
    columns = list(df.columns)

    date_col = _find_column(columns, DATE_CANDIDATES)
    desc_col = _find_column(columns, DESC_CANDIDATES)
    amount_col = _find_column(columns, AMOUNT_CANDIDATES)
    debit_col = _find_column(columns, DEBIT_CANDIDATES)
    credit_col = _find_column(columns, CREDIT_CANDIDATES)

    if date_col is None or desc_col is None:
        raise ValueError(
            "Could not detect required columns (date, description) in CSV."
        )

    records = []
    for _, row in df.iterrows():
        date_val = str(row[date_col]).strip()
        desc_val = str(row[desc_col]).strip()
        if not date_val or date_val.lower() == "nan":
            continue

        amount = None
        if amount_col is not None:
            try:
                amount = float(row[amount_col])
            except (ValueError, TypeError):
                amount = None
        elif debit_col is not None or credit_col is not None:
            debit = _safe_float(row.get(debit_col)) if debit_col else 0.0
            credit = _safe_float(row.get(credit_col)) if credit_col else 0.0
            amount = (credit or 0.0) - (debit or 0.0)

        if amount is None:
            continue

        txn_type = "income" if amount > 0 else "expense"
        records.append(
            {
                "date": _normalize_date(date_val),
                "description": desc_val,
                "amount": abs(amount),
                "type": txn_type,
            }
        )

    return records


def _safe_float(val):
    try:
        if val is None or str(val).strip() == "" or str(val).lower() == "nan":
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _normalize_date(date_val):
    try:
        return pd.to_datetime(date_val, dayfirst=True).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_val


def categorize(description, rules):
    desc_lower = description.lower()
    for keyword, category in rules:
        if keyword.lower() in desc_lower:
            return category
    return "Uncategorized"
