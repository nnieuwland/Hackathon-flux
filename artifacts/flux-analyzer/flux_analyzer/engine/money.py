"""Exact decimal accounting arithmetic and safe serialization."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import pandas as pd

def decimal(value: object) -> Decimal:
    """Convert numbers to Decimal without binary floating point summation."""
    if value is None or str(value) in ("nan", "<NA>", "NaT", ""):
        return Decimal(0)
    text = str(value).strip().replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        result = Decimal(text)
        if not result.is_finite():
            raise ValueError("Non-finite financial value.")
        return result
    except InvalidOperation as exc:
        raise ValueError(f"'{str(value)[:50]}' is not a valid number. Check the value column.") from exc

def money(value: object) -> float:
    """Round an output amount to cents using accounting half-up rounding."""
    return float(decimal(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))

def total(values: object) -> float:
    """Sum exactly, then round once at the output boundary."""
    return money(sum((decimal(v) for v in values), Decimal(0)))

def clean(value: object) -> object:
    """Convert engine objects to strict JSON-compatible values."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value
