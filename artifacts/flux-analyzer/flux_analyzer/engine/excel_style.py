"""Shared formats, names and safe-writing helpers for the Excel review pack."""
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

MAX_EXPORT_ROWS = 50_000
MAX_FORMULA_LINES = 2_000
TOLERANCE = 0.005
STATUS_TEXT = {"needs_explanation": "Needs explanation", "ai_review": "Explained by AI — please review", "confirmed": "Confirmed", "below_threshold": "Below threshold"}
PRIMARY = ["Summary", "Needs Explanation", "Commentary", "Drill-down", "Data checks", "Data", "Settings"]
NAVY, RED, GREY = "#1B2A41", "#C8102E", "#9AA0A6"
MONEY = '#,##0.00;(#,##0.00);"–"'
PCT = '0.0%;(0.0%);"–"'
INTEGER = "#,##0"
DATE = "yyyy-mm-dd hh:mm"
SUMMARY_DRIVERS = 10
GROUP_COLOURS = {"Review": NAVY, "Evidence and reconciliation": "#3D6A9E", "Supporting detail": "#8BA6C9", "Audit trail": GREY}
PRIMARY_GROUPS = {"Summary": "Review", "Needs Explanation": "Review", "Commentary": "Review", "Drill-down": "Evidence and reconciliation",
                  "Data checks": "Evidence and reconciliation", "Data": "Evidence and reconciliation", "Settings": "Evidence and reconciliation"}
PRIMARY_DESCRIPTIONS = {
    "Summary": "This overview: totals, explanation status, key drivers and a guide to the tabs.",
    "Needs Explanation": "Movements that still need a person to write or check the explanation.",
    "Commentary": "Every reported movement with its amounts, status, explanation and who confirmed it.",
    "Drill-down": "Every line of the comparison, largest change first, and which movement it is reported in.",
    "Data checks": "Reconciliation: the workbook's formulas must agree with the engine's totals.",
    "Data": "The grouped source amounts every formula adds up.",
    "Settings": "Months, versions and the threshold the formulas use. Change Threshold to test sensitivity.",
}


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
# A signed amount at the start of a sentence ("+$1.2M — Germany", "-4.5% vs plan") cannot run anything;
# it is kept as typed and protected by Excel's own hidden quote prefix instead of a visible apostrophe.
SIGNED_AMOUNT = re.compile(r"^[+-]\s?[$€£¥]?\d[\d.,]*\s?[%KMBkmb]?(?=\s|$)")


def excel_safe(value: object) -> object:
    """Prevent formula injection from uploaded labels or edited commentary.

    Text that could be read as a formula gets a visible leading apostrophe, so it stays inert
    even if copied out of the workbook into another tool.
    """
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(FORMULA_START) and not (SIGNED_AMOUNT.match(value) and not any(char in value for char in "|(=@!")):
        return "'" + value
    return value


def parse_time(value: object) -> datetime | None:
    """ISO timestamps become naive UTC datetimes so Excel can sort and format them."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


def month_label(month: object) -> str:
    text = str(month)
    try:
        return datetime.strptime(text[:7], "%Y-%m").strftime("%b %Y") if len(text) == 7 else text
    except ValueError:
        return text


def months_text(months: list) -> str:
    labels = [month_label(month) for month in months if str(month)]
    if not labels:
        return "—"
    return " and ".join(labels) if len(labels) <= 2 else f"{labels[0]} to {labels[-1]}"


def sheet_name(name: str, taken: set[str]) -> str:
    """A valid, unique Excel sheet name."""
    clean = "".join(char for char in str(name) if char not in "[]:*?/\\'").strip()[:31] or "Sheet"
    candidate, n = clean, 1
    while candidate.casefold() in {item.casefold() for item in taken}:
        n += 1
        candidate = f"{clean[:27]} ({n})"
    taken.add(candidate)
    return candidate


class Pack:
    def __init__(self, path: Path, currency: str = ""):
        self.book = xlsxwriter.Workbook(str(path), {"strings_to_formulas": False, "strings_to_urls": False, "strings_to_numbers": False, "nan_inf_to_errors": False})
        book = self.book
        base = {"valign": "top", "font_name": "Calibri", "font_size": 10}
        self._options, self._quoted = {}, {}
        def fmt(**options):
            created = book.add_format({**base, **options})
            self._options[id(created)] = {**base, **options}
            return created
        symbol = "".join(char for char in str(currency or "") if char not in '"\\')[:4]
        self.header = fmt(bold=True, font_color="#FFFFFF", bg_color=NAVY, text_wrap=True)
        self.title = fmt(bold=True, font_size=18, font_color=NAVY, valign="vcenter")
        self.subtitle = fmt(font_size=11, font_color="#5F6368")
        self.section = fmt(bold=True, font_size=12, font_color=NAVY, bottom=2, bottom_color=NAVY)
        self.label = fmt(bold=True, font_color=NAVY)
        self.kpi_label = fmt(font_color="#5F6368", text_wrap=True, top=1, top_color="#D0D5DD")
        self.text = fmt(text_wrap=True)
        self.muted = fmt(text_wrap=True, font_color="#5F6368", italic=True)
        self.link = fmt(font_color="#1F5FAD", underline=1)
        money = f'"{symbol}"#,##0.00;("{symbol}"#,##0.00);"{symbol}"0.00' if symbol else MONEY
        self.money = fmt(num_format=MONEY)
        self.money_bold = fmt(num_format=MONEY, bold=True)
        self.kpi = fmt(num_format=money, bold=True, font_size=14, font_color=NAVY)
        self.kpi_pct = fmt(num_format=PCT, bold=True, font_size=14, font_color=NAVY)
        self.kpi_count = fmt(num_format=INTEGER, bold=True, font_size=14, font_color=NAVY, align="left")
        self.number = fmt(num_format="#,##0.00")
        self.integer = fmt(num_format=INTEGER)
        self.pct = fmt(num_format=PCT)
        self.date = fmt(num_format=DATE)
        self.warn = fmt(bold=True, font_color=RED, text_wrap=True)
        self.ok = fmt(bold=True, font_color="#1E7B34")
        self.kinds = {"money": self.money, "pct": self.pct, "pct100": self.pct, "int": self.integer, "number": self.number, "date": self.date, "text": self.text}
        self.symbol = symbol
        self.sheets = {}

    def sheet(self, name: str, colour: str | None = None):
        worksheet = self.book.add_worksheet(name)
        if colour:
            worksheet.set_tab_color(colour)
        self.sheets[name] = worksheet
        return worksheet

    def text_cell(self, worksheet, row: int, col: int, value, fmt=None) -> None:
        """Untrusted text: always a string, never something Excel would run."""
        if value is None:
            value = ""
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        text = str(excel_safe(str(value)))[:32000]
        fmt = fmt or self.text
        if text.startswith(FORMULA_START):
            fmt = self.quoted(fmt)
        worksheet.write_string(row, col, text, fmt)

    def quoted(self, fmt):
        """The same format with Excel's hidden quote prefix, so editing the cell never turns it into a formula."""
        if id(fmt) not in self._quoted:
            self._quoted[id(fmt)] = self.book.add_format({**self._options.get(id(fmt), {}), "quote_prefix": True})
        return self._quoted[id(fmt)]

    def value(self, worksheet, row: int, col: int, value, kind: str = "text") -> None:
        fmt = self.kinds.get(kind, self.text)
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            worksheet.write_blank(row, col, None, fmt)
        elif isinstance(value, bool):
            worksheet.write_boolean(row, col, value, self.text)
        elif isinstance(value, (int, float, Decimal)):
            number = float(value) / 100 if kind == "pct100" else float(value)
            worksheet.write_number(row, col, number, fmt if kind != "text" else self.number)
        elif kind == "date" and parse_time(value):
            worksheet.write_datetime(row, col, parse_time(value), self.date)
        else:
            self.text_cell(worksheet, row, col, value)

    def headers(self, worksheet, row: int, names: list[str], widths: list[int] | None = None) -> None:
        for col, name in enumerate(names):
            worksheet.write_string(row, col, str(excel_safe(str(name))), self.header)
            worksheet.set_column(col, col, (widths or [])[col] if widths and col < len(widths) else 18)

    def link_to(self, worksheet, row: int, col: int, target: str, text: str | None = None) -> None:
        worksheet.write_url(row, col, f"internal:'{target}'!A1", self.link, string=text or target)


def ref(sheet: str, row: int, col: int, absolute: bool = True) -> str:
    return f"'{sheet}'!{xl_rowcol_to_cell(row, col, row_abs=absolute, col_abs=absolute)}"


def landscape(worksheet, repeat_header: bool = True) -> None:
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 0)
    if repeat_header:
        worksheet.repeat_rows(0)
