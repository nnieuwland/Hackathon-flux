"""Bounded, aggregated data descriptions: no raw records sent to an agent."""
import re
import pandas as pd
from .money import total, clean

def profile(df: pd.DataFrame) -> dict:
    """Describe each column using at most five short unique values."""
    columns = []
    for col in df.columns:
        series = df[col].dropna()
        samples = [str(x)[:60] for x in series.drop_duplicates().head(5)]
        numeric = pd.to_numeric(series.astype(str).str.replace(",", ""), errors="coerce")
        guess = "number" if len(series) and numeric.notna().mean() > .9 else "text"
        if any(re.search(r"(?i)(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[- ]\d{2,4}|^\d{4}-\d{2}$|^Q[1-4] ", s) for s in samples):
            guess = "period-like"
        elif re.search(r"(?i)(date|timestamp)", col):
            guess = "date"
        elif re.search(r"(?i)(^id$|_id$|number|code)", col):
            guess = "id-like"
        columns.append(dict(name=str(col), dtype_guess=guess, pct_empty=round(float(df[col].isna().mean()) * 100, 1), n_unique=int(series.nunique()), samples=samples))
    return {"n_rows": len(df), "columns": columns}

def distinct_values(df: pd.DataFrame, col: str, top_n: int = 50, value_col: str | None = None) -> list[dict]:
    """Return top distinct values with counts and optional exact totals."""
    result = []
    for value, count in df[col].fillna("(empty)").value_counts().head(top_n).items():
        entry = {"value": str(value)[:120], "count": int(count)}
        if value_col:
            entry["sum_value"] = total(df.loc[df[col].fillna("(empty)") == value, value_col])
        result.append(entry)
    return result

def value_counts_combo(df: pd.DataFrame, cols: list[str], top_n: int = 40, value_col: str | None = None) -> list[dict]:
    """Aggregate combinations, never include individual transaction rows."""
    result = []
    for keys, frame in df.groupby(cols, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        item = {col: str(value)[:60] for col, value in zip(cols, keys)}
        item["count"] = len(frame)
        if value_col:
            item["sum_value"] = total(frame[value_col])
        result.append(item)
    return sorted(clean(result), key=lambda r: r["count"], reverse=True)[:top_n]
