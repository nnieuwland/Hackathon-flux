"""Deterministic rule application for validated FluxSpec v2 settings."""
from __future__ import annotations

import re
import pandas as pd

from .expr import filter_mask
from .money import decimal, money, total


def apply_value_rules(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Create one canonical value column with null and sign rules applied."""
    result = df.copy()
    roles, rules = spec["roles"], spec.get("value_rules", {})
    source = rules.get("source", "column")
    null_as_zero = rules.get("null_as_zero", True)
    if source == "debit_minus_credit":
        debit = rules.get("debit") or roles.get("debit")
        credit = rules.get("credit") or roles.get("credit")
        if not debit or not credit or debit not in result or credit not in result:
            raise ValueError("Debit-minus-credit value rule needs mapped debit and credit columns.")
        values = []
        for debit_value, credit_value in zip(result[debit], result[credit]):
            if not null_as_zero and (pd.isna(debit_value) or pd.isna(credit_value)):
                raise ValueError("Debit/credit values contain nulls; enable null_as_zero or repair the source.")
            values.append(decimal(debit_value) - decimal(credit_value))
    else:
        column = rules.get("column") or roles.get("value")
        if not column or column not in result:
            raise ValueError("Map a value column before applying value rules.")
        values = []
        for value in result[column]:
            if pd.isna(value) and not null_as_zero:
                raise ValueError(f"Value column '{column}' contains nulls; enable null_as_zero or repair the source.")
            values.append(decimal(value))
    result["__flux_value"] = values
    for rule in rules.get("flip_sign_when", []):
        mask = filter_mask(result, [rule.get("when", rule)])
        result.loc[mask, "__flux_value"] = [-decimal(value) for value in result.loc[mask, "__flux_value"]]
    roles["value"] = "__flux_value"
    return result


def apply_classification(df: pd.DataFrame, config: dict | None, roles: dict | None = None) -> pd.DataFrame:
    """Apply ordered, auditable text rules and attach only aggregate metadata."""
    result = df.copy()
    if not config:
        result.attrs["classification"] = {}
        return result
    sources = config.get("source_cols", [config.get("source_column")])
    sources = [column for source in sources for column in ((roles or {}).get("driver_text", []) if source == "{roles.driver_text}" else [source])]
    target = config.get("target_col") or config.get("target_column")
    if not sources or any(source not in result for source in sources):
        raise ValueError("Classification source column is missing. Map a text column first.")
    if not target:
        raise ValueError("Classification needs a target column name.")
    fallback = config.get("fallback", "UNMATCHED")
    case_sensitive = config.get("case_sensitive", False)
    first_match = config.get("first_match", True)
    texts = result[sources].fillna("").astype(str).agg(" / ".join, axis=1)
    values = [None] * len(result)
    reviewed_rows = [False] * len(result)
    for rule in config.get("rules", []):
        keyword = rule["keyword"]
        match_mode = rule["match"]
        flags = 0 if case_sensitive else re.IGNORECASE
        matcher = None
        if match_mode == "regex":
            if len(keyword) > 160:
                raise ValueError("Classification regular expressions are limited to 160 characters.")
            try:
                matcher = re.compile(keyword, flags)
            except re.error as exc:
                raise ValueError(f"Invalid classification regular expression: {exc}") from exc
        def matches(value: str) -> bool:
            left, right = (value, keyword) if case_sensitive else (value.casefold(), keyword.casefold())
            if match_mode == "contains":
                return right in left
            if match_mode == "eq":
                return left == right
            if match_mode == "startswith":
                return left.startswith(right)
            return bool(matcher and matcher.search(value))
        for index, text in enumerate(texts.tolist()):
            if (not first_match or values[index] is None) and matches(text):
                values[index] = rule["category"]
                reviewed_rows[index] = bool(rule.get("reviewed", False))
    categories = [value if value is not None else fallback for value in values]
    result[target] = categories
    matched = sum(value is not None for value in values)
    reviewed = sum(value in set(config.get("review_flags", [])) for value in categories)
    amounts = [abs(decimal(value)) for value in result.get("__flux_value", pd.Series(0, index=result.index))]
    total_value = sum(amounts)
    matched_value = sum(amount for amount, category in zip(amounts, categories) if category != fallback)
    matched = sum(category != fallback for category in categories)
    result["__classification_reviewed"] = reviewed_rows
    result.attrs["classification"] = {
        "matched": matched,
        "total": len(result),
        "coverage": round(matched * 100 / len(result), 2) if len(result) else 100.0,
        "review_count": reviewed,
        "fallback": fallback,
        "row_coverage": round(matched * 100 / len(result), 2) if len(result) else 100.0,
        "value_coverage": float(matched_value * 100 / total_value) if total_value else 100.0,
        "total_abs_value": money(total_value),
        "classified_abs_value": money(matched_value),
        "unreviewed_rows": sum(not item for item in reviewed_rows),
    }
    review = pd.DataFrame({"text": texts.to_numpy(), "category": categories, "reviewed": reviewed_rows, "abs_value": [float(value) for value in amounts]})
    result.attrs["classification_review"] = review.groupby(["text", "category", "reviewed"], dropna=False).agg(rows=("text", "size"), abs_value=("abs_value", "sum")).reset_index().to_dict("records")
    return result
