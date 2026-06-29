import re

import pandas as pd

DATE_CANDIDATES = ["date", "transaction date", "posted date", "value date"]
DESC_CANDIDATES = ["description", "narrative", "details", "memo", "particulars"]
AMOUNT_CANDIDATES = ["amount", "value", "net amount"]
DEBIT_CANDIDATES = ["debit", "withdrawal", "money out"]
CREDIT_CANDIDATES = ["credit", "deposit", "money in"]
CUSTOMER_CANDIDATES = [
    "counterparty code",
    "customer code",
    "cu number",
    "customer account number",
]
CATEGORY_CANDIDATES = ["category"]

ISO_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
CU_CODE_RE = re.compile(r"Cu\s?(\d{2,})", re.IGNORECASE)


def _extract_customer_code(description):
    matches = CU_CODE_RE.findall(description)
    if not matches:
        return None
    return f"Cu{matches[-1]}"


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


def parse_statement_xlsx(file_path):
    try:
        xls = pd.ExcelFile(file_path)
    except Exception as exc:
        raise ValueError(f"Could not read Excel file: {exc}") from exc

    sheet_name = "Transactions" if "Transactions" in xls.sheet_names else xls.sheet_names[0]
    df = xls.parse(sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    columns = list(df.columns)

    date_col = _find_column(columns, DATE_CANDIDATES)
    desc_col = _find_column(columns, DESC_CANDIDATES)
    debit_col = _find_column(columns, DEBIT_CANDIDATES)
    credit_col = _find_column(columns, CREDIT_CANDIDATES)
    amount_col = None if debit_col or credit_col else _find_column(columns, AMOUNT_CANDIDATES)
    customer_col = _find_column(columns, CUSTOMER_CANDIDATES)
    category_col = _find_column(columns, CATEGORY_CANDIDATES)

    if date_col is None or desc_col is None:
        raise ValueError(
            f"Could not detect required columns (date, description) in sheet '{sheet_name}'."
        )

    records = []
    for _, row in df.iterrows():
        date_val = row[date_col]
        if pd.isna(date_val):
            continue
        desc_val = str(row[desc_col]).strip()

        if debit_col is not None or credit_col is not None:
            debit = _safe_float(row.get(debit_col)) if debit_col else 0.0
            credit = _safe_float(row.get(credit_col)) if credit_col else 0.0
            amount = credit - debit
        elif amount_col is not None:
            amount = _safe_float(row.get(amount_col))
        else:
            continue

        if not amount:
            continue

        customer_code = _extract_customer_code(desc_val)
        if customer_code is None and customer_col is not None:
            val = row.get(customer_col)
            if pd.notna(val) and str(val).strip():
                customer_code = str(val).strip()

        category = None
        if category_col is not None:
            val = row.get(category_col)
            if pd.notna(val) and str(val).strip():
                category = str(val).strip()

        records.append(
            {
                "date": _normalize_date(date_val),
                "description": desc_val,
                "amount": abs(amount),
                "type": "income" if amount > 0 else "expense",
                "customer_code": customer_code,
                "category": category,
            }
        )

    if not records:
        raise ValueError(f"No transactions found in sheet '{sheet_name}'.")
    return records


def _safe_float(val):
    try:
        if val is None or str(val).strip() == "" or str(val).lower() == "nan":
            return 0.0
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _normalize_date(date_val):
    try:
        dayfirst = not ISO_DATE_RE.match(str(date_val).strip())
        return pd.to_datetime(date_val, dayfirst=dayfirst).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return date_val


def categorize(description, rules):
    desc_lower = description.lower()
    for keyword, category in rules:
        if keyword.lower() in desc_lower:
            return category
    return "Uncategorized"
