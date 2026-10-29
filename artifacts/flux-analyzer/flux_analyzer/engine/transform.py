"""Generic declarative transforms; no domain-specific financial logic."""
import re
import pandas as pd
from .expr import filter_mask
from .money import decimal, total

def apply_scope(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    """Select rows meeting every explicit scope filter."""
    return df.loc[filter_mask(df, filters)].copy()

def derive(df: pd.DataFrame, derive_specs: list[dict]) -> pd.DataFrame:
    """Apply ordered rule, extraction, mapping, ratio, concat and bucket specs."""
    result = df.copy()
    for spec in derive_specs:
        kind, name = spec["type"], spec["name"]
        if kind == "rules":
            result[name] = spec.get("default", "")
            unmatched = pd.Series(True, index=result.index)
            for rule in spec.get("rules", []):
                conditions = rule["when"] if isinstance(rule["when"], list) else [rule["when"]]
                match = filter_mask(result, conditions) & unmatched
                result.loc[match, name] = rule["then"]
                unmatched &= ~match
        elif kind == "regex_extract":
            pattern = spec["pattern"]
            if len(pattern) > 500:
                raise ValueError("Regex pattern too long.")
            output = pd.Series(None, index=result.index, dtype="object")
            sources = spec["source"] if isinstance(spec["source"], list) else [spec["source"]]
            for col in sources:
                text = result[col].fillna("").astype(str)
                if spec.get("strip_suffix"):
                    text = text.str.replace(spec["strip_suffix"], "", regex=True)
                extracted = text.str.extract(pattern, expand=False)
                if isinstance(extracted, pd.DataFrame):
                    extracted = extracted.iloc[:, 0]
                output = output.combine_first(extracted)
            result[name] = output.fillna(spec.get("default", "UNMATCHED"))
        elif kind == "map":
            result[name] = result[spec["source"]].astype(str).map(spec.get("mapping", spec.get("map", {}))).fillna(spec.get("default", "UNMATCHED"))
        elif kind == "ratio":
            result[name] = [None if decimal(d) == 0 else decimal(n) / decimal(d) for n, d in zip(result[spec["numerator"]], result[spec["denominator"]])]
        elif kind == "concat":
            result[name] = result[spec["source"]].fillna("").astype(str).agg(spec.get("separator", " ").join, axis=1)
        elif kind == "bucket_numeric":
            result[name] = pd.cut(pd.to_numeric(result[spec["source"]], errors="raise"), bins=spec["bins"], labels=spec.get("labels"), include_lowest=True).astype(str)
        else:
            raise ValueError(f"Unsupported derived type '{kind}'.")
    return result

def classify_text(df: pd.DataFrame, col: str, keyword_map: dict, target_col: str, value_col: str | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Apply user-approved keyword mappings and rank unclassified terms."""
    result = df.copy()
    result[target_col] = "UNMATCHED"
    for keyword, category in keyword_map.items():
        mask = result[col].fillna("").astype(str).str.contains(str(keyword), case=False, regex=False) & result[target_col].eq("UNMATCHED")
        result.loc[mask, target_col] = category
    unmatched = []
    for text, frame in result.loc[result[target_col] == "UNMATCHED"].groupby(col, dropna=False):
        unmatched.append({"text": str(text)[:120], "abs_value": abs(total(frame[value_col])) if value_col else 0, "n": len(frame)})
    return result, sorted(unmatched, key=lambda x: x["abs_value"], reverse=True)
