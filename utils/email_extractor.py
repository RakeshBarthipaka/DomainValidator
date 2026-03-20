import csv
import openpyxl
import re
from io import StringIO, BytesIO

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_emails_from_file(content: bytes, ext: str) -> list:
    """
    Extract emails from CSV or Excel file
    """
    emails = set()

    if ext == "csv":
        text = content.decode("utf-8", errors="ignore")
        reader = csv.reader(StringIO(text))

        for row in reader:
            for cell in row:
                if cell:
                    matches = EMAIL_REGEX.findall(cell)
                    emails.update(matches)

    elif ext in ["xls", "xlsx"]:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)

        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if isinstance(cell, str):
                        matches = EMAIL_REGEX.findall(cell)
                        emails.update(matches)

    return list(emails)