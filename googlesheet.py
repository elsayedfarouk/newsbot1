"""Google Sheets helpers (service-account credentials come from GOOGLE_CREDENTIALS_B64)."""
import base64
import json
import os
from functools import lru_cache

import gspread


@lru_cache(maxsize=1)
def get_client() -> gspread.Client:
    encoded = os.getenv("GOOGLE_CREDENTIALS_B64")
    if not encoded:
        raise RuntimeError("GOOGLE_CREDENTIALS_B64 is not set")
    return gspread.service_account_from_dict(json.loads(base64.b64decode(encoded)))


def open_worksheet(spreadsheet_name: str, sheet_name: str) -> gspread.Worksheet:
    """Named worksheet, falling back to the first sheet when it does not exist."""
    spreadsheet = get_client().open(spreadsheet_name)
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.sheet1


def add_row(row: list, spreadsheet_name: str, sheet_name: str) -> None:
    open_worksheet(spreadsheet_name, sheet_name).append_row(row)


def text_in_column(spreadsheet_name: str, sheet_name: str, text: str, column: int) -> bool:
    """Case-insensitive, whitespace-trimmed exact match of `text` against a 1-based column."""
    if not text:
        return False
    target = text.strip().lower()
    values = open_worksheet(spreadsheet_name, sheet_name).col_values(column)
    return any(target == str(value or "").strip().lower() for value in values)


def test_add_row(spreadsheet_name: str = "TrendingNewsToday", sheet_name: str = "Trending") -> None:
    """Append one demo row (same 11 columns the pipeline writes) to verify credentials and access."""
    demo_row = [
        "test", "Trending", "US", "Demo headline - safe to delete", "2026-01-01",
        "Demo summary text for testing the Google Sheets connection.",
        "https://example.com/image.jpg", "example.com", "https://example.com/demo-story",
        "output/20260101/demo.mp4", "Demo caption #test",
    ]
    add_row(demo_row, spreadsheet_name, sheet_name)
    print(f"Demo row added to '{spreadsheet_name}' / '{sheet_name}'")
    print(f"Duplicate check finds it: {text_in_column(spreadsheet_name, sheet_name, demo_row[3], 4)}")


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    test_add_row()
