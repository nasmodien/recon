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
    "account number",
]
CATEGORY_CANDIDATES = ["category"]

LINE_DATE_RE = re.compile(r"^(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|\d{4}-\d{2}-\d{2})")
LINE_AMOUNT_RE = re.compile(r"-?\d[\d,]*\.\d{2}")


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


def _parse_dataframe(df):
    df.columns = [str(c).strip() for c in df.columns]
    columns = list(df.columns)

    date_col = _find_column(columns, DATE_CANDIDATES)
    desc_col = _find_column(columns, DESC_CANDIDATES)
    amount_col = _find_column(columns, AMOUNT_CANDIDATES)
    debit_col = _find_column(columns, DEBIT_CANDIDATES)
    credit_col = _find_column(columns, CREDIT_CANDIDATES)

    if date_col is None or desc_col is None:
        return []

    records = []
    for _, row in df.iterrows():
        date_val = str(row[date_col]).strip()
        desc_val = str(row[desc_col]).strip()
        if not date_val or date_val.lower() == "nan":
            continue

        amount = None
        if amount_col is not None:
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
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


def parse_statement_csv(file_stream):
    df = pd.read_csv(file_stream)
    records = _parse_dataframe(df)
    if not records:
        raise ValueError(
            "Could not detect required columns (date, description) in CSV."
        )
    return records


def parse_statement_xlsx(file_stream):
    try:
        xls = pd.ExcelFile(file_stream)
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

        customer_code = None
        if customer_col is not None:
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


def parse_statement_pdf(file_stream):
    import pdfplumber

    records = []
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                header, *rows = table
                header = [str(c).strip() if c else f"col{i}" for i, c in enumerate(header)]
                try:
                    df = pd.DataFrame(rows, columns=header)
                except ValueError:
                    continue
                records.extend(_parse_dataframe(df))

    if records:
        return records

    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.split("\n"):
                rec = _parse_statement_line(line)
                if rec:
                    records.append(rec)

    if not records:
        raise ValueError(
            "Could not find any transactions in that PDF. It may be a scanned "
            "image or use a layout this app doesn't recognize yet."
        )
    return records


def _parse_statement_line(line):
    line = line.strip()
    date_match = LINE_DATE_RE.match(line)
    if not date_match:
        return None

    rest = line[date_match.end():].strip()
    amounts = LINE_AMOUNT_RE.findall(rest)
    if not amounts:
        return None

    # Many statements list amount followed by a running balance; prefer the
    # second-to-last number when there's more than one candidate.
    amount_str = amounts[-2] if len(amounts) >= 2 else amounts[-1]
    try:
        amount = float(amount_str.replace(",", ""))
    except ValueError:
        return None

    desc = LINE_AMOUNT_RE.sub("", rest).strip()
    desc = re.sub(r"\s{2,}", " ", desc)
    if not desc:
        return None

    txn_type = "income" if amount >= 0 else "expense"
    if re.search(r"\bDR\b", rest, re.IGNORECASE):
        txn_type = "expense"
    elif re.search(r"\bCR\b", rest, re.IGNORECASE):
        txn_type = "income"

    return {
        "date": _normalize_date(date_match.group(0)),
        "description": desc,
        "amount": abs(amount),
        "type": txn_type,
    }


def _safe_float(val):
    try:
        if val is None or str(val).strip() == "" or str(val).lower() == "nan":
            return 0.0
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


ISO_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")


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
