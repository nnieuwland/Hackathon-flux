"""Generic sliced measures, lookup joins, sections and volume/rate splits."""
from decimal import Decimal
import pandas as pd
from .expr import filter_mask
from .money import decimal, money, total

def slice_mask(df: pd.DataFrame, item: dict, roles: dict | None = None) -> pd.Series:
    """Select a month/scenario/custom-filter slice."""
    mask = pd.Series(True, index=df.index)
    if item.get("months"):
        mask &= df["__month"].isin(item["months"])
    if item.get("scenario"):
        column = (roles or {}).get("scenario") or item.get("scenario_col")
        if not column or column not in df:
            raise ValueError("Map a scenario column before using Actual vs Forecast.")
        values = item["scenario"] if isinstance(item["scenario"], list) else [item["scenario"]]
        mask &= df[column].astype(str).isin(values)
    return mask & filter_mask(df, item.get("filters", []))

def compute_measure(df: pd.DataFrame, measure: dict, slice_filter: dict | None = None, roles: dict | None = None) -> float:
    """Compute a whitelisted aggregation using exact Decimal amounts."""
    selected = df
    if measure.get("slice") != "none" and slice_filter is not None:
        selected = selected.loc[slice_mask(selected, slice_filter, roles)]
    filters = measure.get("filter", [])
    # Period measure filters are resolved to canonical month keys by pipeline.
    selected = selected.loc[filter_mask(selected, filters)]
    col, agg = measure["col"], measure["agg"]
    if col not in selected:
        raise ValueError(f"Measure column '{col}' is missing. Check column mappings.")
    if agg == "count":
        return float(selected[col].count())
    if agg == "nunique":
        return float(selected[col].nunique())
    values = [decimal(v) for v in selected[col] if pd.notna(v)]
    if not values:
        return 0.0
    if agg == "sum":
        return money(sum(values, Decimal(0)))
    if agg == "mean":
        return float(sum(values, Decimal(0)) / len(values))
    if agg == "min":
        return float(min(values))
    if agg == "max":
        return float(max(values))
    raise ValueError(f"Unsupported aggregation '{agg}'.")

def pivot_compare(df: pd.DataFrame, keys: list[str], measures: dict, base: dict, current: dict, roles: dict | None = None, compare: bool = True) -> pd.DataFrame:
    """Produce a full outer comparison, retaining new and removed members."""
    missing = set(keys) - set(df.columns)
    if missing:
        raise ValueError(f"View columns missing: {', '.join(sorted(missing))}.")
    groups = df.groupby(keys, dropna=False, sort=False) if keys else [((), df)]
    rows = []
    for group, frame in groups:
        group = group if isinstance(group, tuple) else (group,)
        row = {key: str(value) if pd.notna(value) else "(empty)" for key, value in zip(keys, group)}
        for name, measure in measures.items():
            if compare:
                b = compute_measure(frame, measure, base, roles)
                c = compute_measure(frame, measure, current, roles)
                delta = money(decimal(c) - decimal(b))
                row.update({f"{name}_base": b, f"{name}_current": c, f"{name}_delta": delta, f"{name}_delta_pct": float(decimal(delta) / abs(decimal(b)) * 100) if b else None})
            else:
                selected = base if measure.get("slice") == "base" else current if measure.get("slice") == "current" else None
                row[name] = compute_measure(frame, measure, selected, roles)
        rows.append(row)
    return pd.DataFrame(rows)

def apply_joins(view_df: pd.DataFrame, joins: list[dict], lookups: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join lookup existence/value summaries without multiplying view rows."""
    result = view_df.copy()
    for join in joins:
        if join["lookup"] not in lookups:
            if join.get("optional"):
                for name, field in join.get("fields", {}).items():
                    result[name] = False if field["type"] in ("exists", "exists_where") else None
                continue
            raise ValueError(f"Lookup '{join['lookup']}' is missing. Upload and define it first.")
        source = lookups[join["lookup"]].copy()
        if join.get("key_normalise"):
            from .joins import _normalize
            source[join["right_on"]] = source[join["right_on"]].map(lambda value: _normalize(value, join["key_normalise"]))
            result[join["left_on"]] = result[join["left_on"]].map(lambda value: _normalize(value, join["key_normalise"]))
        for name, field in join.get("fields", {}).items():
            selected = source.loc[filter_mask(source, field.get("filter", []))]
            if field["type"] in ("exists", "exists_where"):
                result[name] = result[join["left_on"]].astype(str).isin(selected[join["right_on"]].astype(str))
            elif field["type"] == "value":
                if selected[join["right_on"]].duplicated().any():
                    raise ValueError("Lookup has duplicate keys; use exists or aggregate the lookup.")
                mapping = selected.set_index(join["right_on"])[field["col"]]
                result[name] = result[join["left_on"]].map(mapping)
            else:
                raise ValueError(f"Unknown lookup field type '{field['type']}'.")
    return result

def decompose(view_df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Volume at base rate, residual rate impact, exactly reconciling to delta."""
    if spec.get("method") != "volume_at_base_rate":
        raise ValueError("Only volume_at_base_rate decomposition is supported.")
    result = view_df.copy()
    volume, rate, measure = spec["volume"], spec["rate"], spec.get("measure", "amount")
    for col in (f"{volume}_base", f"{volume}_current", f"{rate}_base", f"{measure}_delta"):
        if col not in result:
            raise ValueError(f"Decomposition needs measure '{col}'. Add it to the view.")
    result["volume_impact"] = [money((decimal(c) - decimal(b)) * decimal(r)) for c, b, r in zip(result[f"{volume}_current"], result[f"{volume}_base"], result[f"{rate}_base"])]
    result["rate_impact"] = [money(decimal(t) - decimal(v)) for t, v in zip(result[f"{measure}_delta"], result["volume_impact"])]
    return result

def build_sections(df: pd.DataFrame, sections: dict | None, value_col: str | None = None) -> list[dict]:
    """Aggregate an exhaustive section split and validate any requested order."""
    if not sections:
        return []
    col = sections["split_by"]
    if col not in df:
        raise ValueError(f"Section column '{col}' is missing.")
    measure = value_col or sections.get("value_col", "delta")
    rows = [{"label": str(k), "total": total(g[measure])} for k, g in df.groupby(col, dropna=False)]
    order = sections.get("order", [])
    return sorted(rows, key=lambda x: order.index(x["label"]) if x["label"] in order else len(order))
