"""First-match flags and explicit exception gates."""
import pandas as pd
from .expr import evaluate

def apply_flags(view_df: pd.DataFrame, ordered: dict) -> tuple[pd.DataFrame, dict]:
    """Apply ordered IFS rules and assert every row receives a label."""
    result = view_df.copy()
    name = ordered["name"]
    result[name] = ordered.get("default", "Unclassified")
    unmatched = pd.Series(True, index=result.index)
    for item in ordered.get("ordered", []):
        mask = evaluate(item["if"], result)
        if not isinstance(mask, pd.Series):
            mask = pd.Series(bool(mask), index=result.index)
        match = mask.fillna(False) & unmatched
        result.loc[match, name] = item["label"]
        unmatched &= ~match
    counts = {str(k): int(v) for k, v in result[name].value_counts(dropna=False).items()}
    if sum(counts.values()) != len(result):
        raise ValueError("Flag counts do not reconcile to the view row count.")
    return result, counts

def apply_gates(view_df: pd.DataFrame, gate: dict) -> pd.DataFrame:
    """Return only records meeting an approved exception expression."""
    mask = evaluate(gate["if"], view_df)
    if not isinstance(mask, pd.Series):
        mask = pd.Series(bool(mask), index=view_df.index)
    return view_df.loc[mask.fillna(False)].copy()
