"""
email_extractor.py
──────────────────
Requirements doc Section 4b — Key Columns:
  Col F  (index 6, 0-based=5) → Company Name
  Col H  (index 8, 0-based=7) → Email
  Col AF (index 32, 0-based=31) → Website

Returns:
  extract_records_from_file() → list of {"email", "website", "company_name"}
  extract_emails_from_file()  → list of str (legacy compatibility)

Strategy:
  1. If file is Apollo-format xlsx (has header with email + website cols) → read
     Col F, H, AF by fixed index, fall back to header-name scan.
  2. Otherwise → generic scan of all cells for any email address.
"""

import csv
import re
import io
from typing import List, Dict

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Apollo fixed column indices (1-based Excel = 0-based Python list)
APOLLO_COL_COMPANY = 5   # Col F
APOLLO_COL_EMAIL   = 7   # Col H
APOLLO_COL_WEBSITE = 31  # Col AF


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_records_from_file(content: bytes, ext: str) -> List[Dict]:
    """
    Returns list of dicts: {"email": str, "website": str|None, "company_name": str|None}
    Only rows with a non-empty email are included.
    """
    try:
        if ext in ("xls", "xlsx"):
            return _from_excel(content)
        elif ext == "csv":
            return _from_csv(content)
    except Exception as e:
        print(f"[Extractor] Error: {e}")
    return []


def extract_emails_from_file(content: bytes, ext: str) -> list:
    """Legacy wrapper — returns just email strings."""
    return [r["email"] for r in extract_records_from_file(content, ext) if r.get("email")]


# ── Excel ──────────────────────────────────────────────────────────────────────

def _from_excel(content: bytes) -> List[Dict]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip().lower() if c else "" for c in rows[0]]
    apollo = _is_apollo(header)

    results = []
    data_rows = rows[1:] if apollo else rows   # skip header row if Apollo

    for row in data_rows:
        if apollo:
            rec = _parse_apollo_row(row, header)
        else:
            rec = _parse_generic_row(row)
        if rec:
            results.append(rec)

    return results


def _is_apollo(header: list) -> bool:
    """True if header contains at least 2 of: email, website, company."""
    markers = {"email", "website", "company"}
    return sum(1 for h in header if any(m in h for m in markers)) >= 2


def _parse_apollo_row(row: tuple, header: list) -> Dict | None:
    row = list(row)

    # Try fixed Apollo column positions first
    email_val   = _cell(row, APOLLO_COL_EMAIL)
    website_val = _cell(row, APOLLO_COL_WEBSITE)
    company_val = _cell(row, APOLLO_COL_COMPANY)

    # If fixed index didn't yield an email, fall back to header name search
    if not email_val or not EMAIL_RE.search(str(email_val)):
        email_val, website_val, company_val = _find_by_header(row, header)

    if not email_val:
        return None

    emails_found = EMAIL_RE.findall(str(email_val))
    if not emails_found:
        return None

    return {
        "email":        emails_found[0].strip().lower(),
        "website":      _clean_url(website_val),
        "company_name": str(company_val).strip() if company_val else None,
    }


def _parse_generic_row(row: tuple) -> Dict | None:
    """For non-Apollo files: scan all cells for any email."""
    for cell in row:
        if cell:
            found = EMAIL_RE.findall(str(cell))
            if found:
                return {
                    "email":        found[0].strip().lower(),
                    "website":      None,
                    "company_name": None,
                }
    return None


def _find_by_header(row: list, header: list):
    email = website = company = None
    for i, h in enumerate(header):
        if i >= len(row):
            break
        val = _cell(row, i)
        if not val:
            continue
        if "email" in h and not email:
            email = val
        if "website" in h and not website:
            website = val
        if "company" in h and not company:
            company = val
    return email, website, company


# ── CSV ────────────────────────────────────────────────────────────────────────

def _from_csv(content: bytes) -> List[Dict]:
    text   = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows   = list(reader)
    if not rows:
        return []

    header = [h.strip().lower() for h in rows[0]]
    apollo = _is_apollo(header)

    results = []
    for row in rows[1:]:
        if apollo:
            rec = _parse_apollo_row(tuple(row), header)
        else:
            rec = _parse_generic_row(tuple(row))
        if rec:
            results.append(rec)

    return results


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cell(row: list, idx: int):
    try:
        v = row[idx]
        s = str(v).strip() if v is not None else ""
        return s if s and s.lower() not in ("none", "nan", "") else None
    except IndexError:
        return None


def _clean_url(raw) -> str | None:
    """Strip protocol + www + trailing path → bare domain."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s or s in ("none", "nan"):
        return None
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("/")[0].split("?")[0].split("#")[0].strip()
    return s or None