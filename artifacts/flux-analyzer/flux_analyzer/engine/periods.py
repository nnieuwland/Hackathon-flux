"""Calendar and fiscal month normalization and generic slice resolution."""
import re
from datetime import date, datetime
import pandas as pd

INPUT_FORMATS = {
    "YYYY-MM": "%Y-%m",
    "MON-YY": "%b-%y",
    "MON-YYYY": "%b-%Y",
    "MM/YYYY": "%m/%Y",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
}

def parse_period(value: object, calendar: str | dict = "calendar", input_format: str = "auto") -> str:
    """Normalize a common period/date to YYYY-MM (quarter -> first month)."""
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value).strip()
    quarter = re.fullmatch(r"(?i)(?:Q([1-4])\s+(\d{4})|FY(\d{2,4})\s+Q([1-4]))", text)
    if quarter:
        q = int(quarter[1] or quarter[4])
        year = int(quarter[2] or quarter[3])
        year += 2000 if year < 100 else 0
        start = int(calendar.get("start_month", 1)) if isinstance(calendar, dict) else 1
        offset = start - 1 + (q - 1) * 3
        return f"{year + offset // 12:04d}-{offset % 12 + 1:02d}"
    formats = ([INPUT_FORMATS[input_format]] if input_format in INPUT_FORMATS else []) + ["%b-%y", "%b-%Y", "%Y-%m", "%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"]
    for fmt in dict.fromkeys(formats):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    raise ValueError(f"Period '{text[:60]}' is not recognized. Use JAN-26, 2026-01, or a valid date.")

def months_for_period(value: object, calendar: str | dict = "calendar", input_format: str = "auto") -> list[str]:
    """Expand a quarter label into three calendar months."""
    first = parse_period(value, calendar, input_format)
    if re.search(r"(?i)\bQ[1-4]\b", str(value)):
        year, month = map(int, first.split("-"))
        return [f"{year + (month - 1 + i) // 12:04d}-{(month - 1 + i) % 12 + 1:02d}" for i in range(3)]
    return [first]

def resolve_comparison(comparison: dict, available_months: list[str], calendar: str | dict = "calendar") -> dict:
    """Resolve both user-confirmed slices and identify missing months."""
    resolved = {"partial_periods": []}
    for name in ("base", "current"):
        item = comparison.get(name, {})
        months = sorted(set(m for v in item.get("months", []) for m in months_for_period(v, calendar)))
        if not months and item.get("period"):
            months = months_for_period(item["period"], calendar)
        if not months and not item.get("scenario") and not item.get("filters"):
            raise ValueError(f"Choose months or a scenario for the {name} slice.")
        missing = [m for m in months if m not in available_months]
        resolved["partial_periods"].extend(f"{name}: {m}" for m in missing)
        resolved[name] = {**item, "months": months, "first_month": months[0] if months else None, "last_month": months[-1] if months else None}
    return resolved

def available_months(values: object, calendar: str | dict = "calendar", input_format: str = "auto") -> list[str]:
    """Represent quarter-labeled sources as full quarter coverage, not partials."""
    return sorted({month for value in values for month in months_for_period(value, calendar, input_format)})

def normalize_periods(df: pd.DataFrame, column: str, calendar: str | dict = "calendar", input_format: str = "auto") -> pd.DataFrame:
    """Add a private canonical month column without changing raw data."""
    result = df.copy()
    result["__month"] = result[column].map(lambda x: parse_period(x, calendar, input_format))
    return result
