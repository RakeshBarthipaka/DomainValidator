"""
excel_writer.py
───────────────
Requirements Section 4c + 5b — Write results back to source Excel file.

Rules:
  • Find last used column dynamically (ws.max_column)
  • Write to FIRST EMPTY column after last used (never hardcoded)
  • Output column header: "Validation Status"
  • Colour-code cells per status

Output status labels (Section 5b):
  Domain Mismatch      → yellow
  Skipped – Missing Data → grey
  Valid                → green
  Invalid              → red
  Catch-all            → yellow
  Unknown              → blue
  API Error            → red
"""

import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from typing import List, Dict

# Internal result → Excel label
RESULT_LABEL = {
    "domain_mismatch": "Domain Mismatch",
    "skipped_missing": "Skipped – Missing Data",
    "valid":           "Valid",
    "invalid":         "Invalid",
    "catch_all":       "Catch-all",
    "catchall":        "Catch-all",
    "unknown":         "Unknown",
    "api_error":       "API Error",
    "disposable":      "Invalid",
}

# Background fill colours (hex, no #)
RESULT_COLOR = {
    "Valid":                   "C6EFCE",  # green
    "Invalid":                 "FFC7CE",  # red
    "Catch-all":               "FFEB9C",  # yellow
    "Unknown":                 "DDEBF7",  # blue
    "Domain Mismatch":         "FFEB9C",  # yellow
    "Skipped – Missing Data":  "D9D9D9",  # grey
    "API Error":               "FFC7CE",  # red
}

RESULT_FONT_COLOR = {
    "Valid":                   "276221",
    "Invalid":                 "9C0006",
    "Catch-all":               "7D5A00",
    "Unknown":                 "1F4E79",
    "Domain Mismatch":         "7D5A00",
    "Skipped – Missing Data":  "444444",
    "API Error":               "9C0006",
}


def write_results_to_excel(source_path: str, results: List[Dict], output_path: str = None) -> str:
    """
    Open source_path, add Validation Status column, save.

    Args:
        source_path:  Path to the original uploaded .xlsx file
        results:      All result dicts {"email": str, "result": str}
        output_path:  Save path (defaults to source_path — overwrites in place)

    Returns:
        Path where file was saved.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source file not found: {source_path}")

    wb = openpyxl.load_workbook(source_path)
    ws = wb.active

    # ── 1. Find last used column → write to next one ───────────────────────────
    last_col = ws.max_column or 1
    out_col  = last_col + 1
    col_letter = get_column_letter(out_col)
    print(f"[ExcelWriter] Output column: {col_letter} (index {out_col})")

    # ── 2. Write header ────────────────────────────────────────────────────────
    hdr = ws.cell(row=1, column=out_col)
    hdr.value = "Validation Status"
    hdr.font  = Font(name="Arial", bold=True, size=9, color="FFFFFF")
    hdr.fill  = PatternFill("solid", start_color="0F172A")
    hdr.alignment = Alignment(horizontal="center", vertical="center")

    # ── 3. Build email → label lookup ──────────────────────────────────────────
    label_map: Dict[str, str] = {}
    for r in results:
        email = str(r.get("email", "")).strip().lower()
        raw   = str(r.get("result", "")).strip().lower()
        label = RESULT_LABEL.get(raw, raw.replace("_", " ").title())
        if email:
            label_map[email] = label

    # ── 4. Detect email column ────────────────────────────────────────────────
    email_col = _find_email_col(ws)
    print(f"[ExcelWriter] Email column detected at index {email_col}")

    # ── 5. Write result for each data row ─────────────────────────────────────
    written = 0
    for row_idx in range(2, ws.max_row + 1):
        email_cell = ws.cell(row=row_idx, column=email_col)
        email_val  = str(email_cell.value or "").strip().lower()

        if not email_val:
            label = "Skipped – Missing Data"
        else:
            label = label_map.get(email_val, "")

        if not label:
            continue

        out_cell       = ws.cell(row=row_idx, column=out_col)
        out_cell.value = label
        out_cell.alignment = Alignment(horizontal="center", vertical="center")

        bg = RESULT_COLOR.get(label, "FFFFFF")
        fg = RESULT_FONT_COLOR.get(label, "000000")
        out_cell.fill = PatternFill("solid", start_color=bg)
        out_cell.font = Font(name="Arial", size=9, color=fg)
        written += 1

    # ── 6. Auto-width output column ───────────────────────────────────────────
    ws.column_dimensions[col_letter].width = 24

    # ── 7. Save ────────────────────────────────────────────────────────────────
    save_to = output_path or source_path
    wb.save(save_to)
    wb.close()
    print(f"[ExcelWriter] Wrote {written} rows → {save_to} col {col_letter}")
    return save_to


def _find_email_col(ws) -> int:
    """
    Find the column index containing emails.
    Priority:
      1. Header named 'email' (case-insensitive)
      2. Apollo default: column H = index 8
      3. First column in row 2 that contains @
    """
    hdr_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    if hdr_row:
        for i, h in enumerate(hdr_row[0]):
            if h and "email" in str(h).lower():
                return i + 1  # 1-based

    # Apollo default: column H = 8
    cell_h = ws.cell(row=2, column=8)
    if cell_h.value and "@" in str(cell_h.value):
        return 8

    # Scan row 2
    row2 = list(ws.iter_rows(min_row=2, max_row=2, values_only=True))
    if row2:
        for i, v in enumerate(row2[0]):
            if v and "@" in str(v):
                return i + 1

    return 8  # fallback to Apollo column H