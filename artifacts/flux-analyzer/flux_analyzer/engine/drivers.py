"""Rank variance drivers and preserve every cent in remainder lines."""
import pandas as pd
from .money import money, total, decimal
from .compare import slice_mask

def select_drivers(compare_df: pd.DataFrame, measure: str, materiality_abs: float, top_n: int, others_label: str = "Other items") -> list[dict]:
    """Keep top material movements and combine all excluded rows into others."""
    if compare_df.empty:
        return []
    delta_col = f"{measure}_delta"
    if delta_col not in compare_df:
        raise ValueError("Driver view must be a compared view with the selected measure.")
    frame = compare_df.copy()
    frame["__abs"] = frame[delta_col].abs()
    ranked = frame.sort_values("__abs", ascending=False, kind="stable")
    chosen = ranked.loc[ranked["__abs"] >= materiality_abs].head(top_n)
    other = ranked.drop(index=chosen.index)
    dims = [c for c in frame.columns if not c.startswith("__") and not c.endswith(("_base", "_current", "_delta", "_delta_pct")) and (pd.api.types.is_object_dtype(frame[c]) or pd.api.types.is_string_dtype(frame[c]))]
    rows = []
    for i, (_, row) in enumerate(chosen.iterrows()):
        dimensions = {k: str(row[k]) for k in dims}
        rows.append({"driver_id": f"d{i + 1}", "label": " / ".join(dimensions.values()) or "Total movement", "dimensions": dimensions, "base": float(row[f"{measure}_base"]), "current": float(row[f"{measure}_current"]), "delta": float(row[delta_col])})
    if not other.empty:
        rows.append({"driver_id": "others", "label": others_label, "dimensions": {}, "base": total(other[f"{measure}_base"]), "current": total(other[f"{measure}_current"]), "delta": total(other[delta_col]), "excluded_dimensions": [{k: str(r[k]) for k in dims} for _, r in chosen.iterrows()]})
    if money(sum(decimal(r["delta"]) for r in rows)) != total(compare_df[delta_col]):
        raise ValueError("Drivers do not reconcile to the total movement.")
    return rows

def materiality_threshold(config: dict | float | None, base: float, current: float) -> float:
    """Resolve absolute, percentage, max-of, and min-of driver thresholds."""
    if isinstance(config, (int, float)):
        return max(0.0, float(config))
    config = config or {"mode": "abs", "abs": 0}
    mode = config.get("mode", "abs")
    def threshold(item: dict) -> float:
        if item.get("type", "abs") == "abs":
            return float(item.get("value", item.get("abs", 0)))
        basis = item.get("basis", "total_delta")
        amount = abs(current - base) if basis in ("total_delta", "abs_total_movement") else abs(base if basis in ("total_base", "abs_total_base") else current)
        return amount * float(item.get("value", item.get("pct", 0)))
    if mode == "abs":
        return max(0.0, float(config.get("abs", 0)))
    if mode == "pct_of_total":
        return threshold({"type": "pct_of_total", "value": config.get("pct", 0), "basis": config.get("basis", "abs_total_movement")})
    values = [threshold(item) for item in config.get("thresholds", [])]
    if not values:
        values = [float(config.get("abs", 0)), threshold({"type": "pct_of_total", "value": config.get("pct", 0), "basis": config.get("basis", "abs_total_movement")})]
    if len(values) < 2:
        raise ValueError(f"Materiality mode '{mode}' requires at least two thresholds.")
    return max(values) if mode == "max_of" else min(values)

def drill(df: pd.DataFrame, driver_row: dict, view_keys: list[str], base: dict, current: dict, group_by: str | list[str], top_n: int, value_col: str | None = None, roles: dict | None = None) -> list[dict]:
    """Consolidate transaction text behind a driver, including a remainder."""
    selected = df.copy()
    for key, value in driver_row.get("dimensions", {}).items():
        if key in view_keys:
            selected = selected.loc[selected[key].fillna("(empty)").astype(str) == str(value)]
    if driver_row.get("excluded_dimensions"):
        for dims in driver_row["excluded_dimensions"]:
            mask = pd.Series(True, index=selected.index)
            for key, value in dims.items():
                if key in view_keys:
                    mask &= selected[key].fillna("(empty)").astype(str).eq(value)
            selected = selected.loc[~mask]
    columns = [group_by] if isinstance(group_by, str) else group_by
    columns = [c for c in columns if c in selected]
    value_col = value_col or (roles or {}).get("value")
    if not value_col:
        raise ValueError("Choose a value column before drilling.")
    selected = selected.copy()
    selected["__text"] = selected[columns].fillna("").astype(str).agg(" / ".join, axis=1) if columns else "All transactions"
    rows = []
    for text, frame in selected.groupby("__text", dropna=False):
        b = total(frame.loc[slice_mask(frame, base, roles), value_col])
        c = total(frame.loc[slice_mask(frame, current, roles), value_col])
        rows.append({"text": str(text), "base": b, "current": c, "delta": money(decimal(c) - decimal(b)), "n_lines": len(frame)})
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    if len(rows) > top_n:
        rest = rows[top_n:]
        rows = rows[:top_n] + [{"text": "Remaining transactions", "base": total(r["base"] for r in rest), "current": total(r["current"] for r in rest), "delta": total(r["delta"] for r in rest), "n_lines": sum(r["n_lines"] for r in rest)}]
    if total(r["delta"] for r in rows) != money(driver_row["delta"]):
        raise ValueError("Drill evidence does not reconcile to the driver. Use additive sum measures for transaction evidence.")
    return rows
