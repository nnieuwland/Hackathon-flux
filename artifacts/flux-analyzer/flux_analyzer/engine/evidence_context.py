"""Deterministic context that helps commentary explain a movement: history, mix, coverage and data quality.

Everything here is calculated and worded by Python from aggregates. No source row is copied out;
descriptions only ever reach the commentary as grouped, truncated drill-down text.
"""
from decimal import Decimal
import re
import pandas as pd
from .compare import slice_mask
from .money import decimal, money, total

TREND_POINTS = 6          # the reported period plus up to five earlier periods of the same length
STEADY_SHARE = 0.25       # an earlier step smaller than this share of the movement counts as flat
MAX_CATEGORIES = 4
MAX_QUALITY_ITEMS = 12
MONTH = re.compile(r"^\d{4}-\d{2}$")

PATTERN_NOTES = {
    "one_period": "The earlier periods were broadly stable; the change appears in the latest period only.",
    "continuing": "The amount also moved in the same direction in each of the two periods before, so the change continues an earlier pattern.",
    "reversal": "The period before moved by a similar or larger amount in the opposite direction; this movement goes the other way.",
    "mixed": "The earlier periods moved in both directions; there is no consistent pattern.",
    "no_movement": "There is no movement in the latest period.",
    "insufficient_history": "Too few earlier periods are available to tell a one-period change from a continuing pattern.",
    "not_assessed": "The comparison is not between consecutive periods of the same version, so the history is context only.",
    "partial_period": "A period in the history is incomplete, so no pattern is assessed.",
}


def _month_number(month: str) -> int:
    year, number = month.split("-")
    return int(year) * 12 + int(number) - 1


def _month_label(number: int) -> str:
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def driver_rows(frame: pd.DataFrame, driver: dict) -> pd.DataFrame:
    """Rows belonging to one reported movement (Other items excludes every listed movement)."""
    selected = frame
    for key, value in driver.get("dimensions", {}).items():
        if key in selected:
            selected = selected.loc[selected[key].fillna("(empty)").astype(str).eq(value)]
    for excluded in driver.get("excluded_dimensions", []):
        mask = pd.Series(True, index=selected.index)
        for key, value in excluded.items():
            if key in selected:
                mask &= selected[key].fillna("(empty)").astype(str).eq(value)
        selected = selected.loc[~mask]
    return selected


def history_windows(current_months: list[str], available: set[str]) -> list[list[str]]:
    """Consecutive windows the same length as the current period, oldest first, ending with it."""
    if not current_months or not all(MONTH.match(str(month)) for month in current_months):
        return []
    numbers = [_month_number(month) for month in current_months]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return []
    windows = []
    for step in range(TREND_POINTS):
        window = [_month_label(number - step * len(numbers)) for number in numbers]
        if not all(month in available for month in window):
            break
        windows.append(window)
    return list(reversed(windows))


def _same_slice(base: dict, current: dict) -> bool:
    ignore = {"months", "first_month", "last_month", "period"}
    return {k: v for k, v in base.items() if k not in ignore} == {k: v for k, v in current.items() if k not in ignore}


def trend(rows: pd.DataFrame, driver: dict, comparison: dict, roles: dict, value_col: str, available: set[str], partial: set[str], fmt) -> dict | None:
    """Earlier periods of the same length and version, with a pattern decided by fixed rules."""
    windows = history_windows(comparison["current"].get("months", []), available)
    if len(windows) < 2:
        return None
    current_slice = {**comparison["current"], "months": []}
    selected = rows.loc[slice_mask(rows, current_slice, roles)] if len(rows) else rows
    by_month = {}
    if len(selected):
        for month, part in selected.groupby("__month"):
            by_month[str(month)] = total(part[value_col])
    values = [money(sum((decimal(by_month.get(month, 0)) for month in window), decimal(0))) for window in windows]
    if abs(values[-1] - float(driver["current"])) > 0.005:
        return None  # the history must end exactly at the reported current amount
    driver_id = driver["driver_id"]
    points = [{"period": window[0] if len(window) == 1 else f"{window[0]} to {window[-1]}", "amount_fmt": fmt(value), **({"partial": True} if set(window) & partial else {})} for window, value in zip(windows, values)]
    comparable = windows[-2] == list(comparison["base"].get("months", [])) and _same_slice(comparison["base"], comparison["current"])
    if not comparable:
        pattern = "not_assessed"
    elif any(point.get("partial") for point in points):
        pattern = "partial_period"
    else:
        steps = [decimal(after) - decimal(before) for before, after in zip(values, values[1:])]
        latest, earlier = steps[-1], steps[:-1]
        floor = abs(latest) * decimal(STEADY_SHARE)
        if latest == 0:
            pattern = "no_movement"
        elif len(earlier) < 2:
            pattern = "insufficient_history"
        elif all(abs(step) < floor for step in earlier):
            pattern = "one_period"
        elif all(step * latest > 0 and abs(step) >= floor for step in earlier[-2:]):
            pattern = "continuing"
        elif earlier[-1] * latest < 0 and abs(earlier[-1]) >= abs(latest):
            pattern = "reversal"
        else:
            pattern = "mixed"
    return {"comparability": "comparable" if comparable else "limited", "pattern": pattern, "points": points, "note": PATTERN_NOTES[pattern], "evidence_ref": f"trend:{driver_id}"}


def decomposition(compared: pd.DataFrame, keys: list[str], driver: dict, fmt, measure: str | None = None, settings: dict | None = None) -> dict | None:
    """Volume and rate effects already calculated for the movement view.

    Only offered when the decomposition was configured for the same measure as the movement and
    its effects add up exactly to this movement; otherwise it would explain a different number.
    """
    if compared is None or "volume_impact" not in compared or "rate_impact" not in compared or not settings:
        return None
    if measure is None or settings.get("measure", "amount") != measure or f"{measure}_delta" not in compared:
        return None
    rows = driver_rows(compared, {**driver, "dimensions": {k: v for k, v in driver.get("dimensions", {}).items() if k in keys}})
    if rows.empty:
        return None
    volume, rate, movement = (decimal(total(rows[column])) for column in ("volume_impact", "rate_impact", f"{measure}_delta"))
    target = decimal(driver.get("delta", 0))
    if abs(movement - target) > Decimal("0.01") or abs(volume + rate - target) > Decimal("0.01"):
        return None
    driver_id = driver["driver_id"]
    components = [{"label": label, "delta_fmt": fmt(money(value)), "evidence_ref": f"decomp:{driver_id}:{name}"} for name, label, value in (("volume", "Volume effect", volume), ("rate", "Rate effect", rate))]
    return {"method": "volume_rate", "measure": measure, "components": components,
            "note": "Volume effect uses base rates; rate effect is the remainder, so the two add up to the movement."}


def categories(rows: pd.DataFrame, driver: dict, comparison: dict, roles: dict, value_col: str, config: dict | None, fmt) -> dict | None:
    """Movement split by classification category, with whether the rules behind it were approved."""
    target = (config or {}).get("target_col") or (config or {}).get("target_column")
    if not target or target not in rows or rows.empty:
        return None
    fallback = config.get("fallback", "UNMATCHED")
    base_mask, current_mask = slice_mask(rows, comparison["base"], roles), slice_mask(rows, comparison["current"], roles)
    in_scope = rows.loc[base_mask | current_mask]
    items = []
    for category, part in in_scope.groupby(target, dropna=False):
        delta = money(decimal(total(part.loc[current_mask.loc[part.index], value_col])) - decimal(total(part.loc[base_mask.loc[part.index], value_col])))
        reviewed = part["__classification_reviewed"] if "__classification_reviewed" in part else pd.Series(False, index=part.index)
        approval = "unclassified" if str(category) == str(fallback) else "approved" if bool(reviewed.all()) else "partly_approved" if bool(reviewed.any()) else "not_approved"
        items.append({"category": str(category)[:80], "delta": delta, "lines": int(len(part)), "approval": approval})
    items.sort(key=lambda item: abs(item["delta"]), reverse=True)
    shown, rest = items[:MAX_CATEGORIES], items[MAX_CATEGORIES:]
    if rest:
        shown.append({"category": "Other categories", "delta": total(item["delta"] for item in rest), "lines": sum(item["lines"] for item in rest), "approval": "mixed"})
    driver_id = driver["driver_id"]
    output = [{"category": item["category"], "delta_fmt": fmt(item["delta"]), "lines": item["lines"], "approval": item["approval"], "evidence_ref": f"category:{driver_id}:{index}"} for index, item in enumerate(shown, 1)]
    return {"column": str(target), "items": output}


def coverage(rows: pd.DataFrame, driver: dict, drill_rows: list[dict], comparison: dict, roles: dict, partial: set[str], classification: dict | None) -> dict:
    """What the drill-down shows and what it leaves out for this movement."""
    in_scope = rows.loc[slice_mask(rows, comparison["base"], roles) | slice_mask(rows, comparison["current"], roles)] if len(rows) else rows
    shown = [item for item in drill_rows if item.get("text") != "Remaining transactions"]
    truncated = len(shown) != len(drill_rows)
    unmatched = 0
    for column in [c for c in in_scope.columns if str(c).startswith("__join_unmatched_")]:
        unmatched = max(unmatched, int(in_scope[column].fillna(False).astype(bool).sum()))
    target = (classification or {}).get("target_col") or (classification or {}).get("target_column")
    unclassified = int(in_scope[target].astype(str).eq(str(classification.get("fallback", "UNMATCHED"))).sum()) if target and target in in_scope else 0
    months = set(comparison["base"].get("months", [])) | set(comparison["current"].get("months", []))
    partial_used = sorted(partial & months)
    notes = [f"{len(in_scope)} source lines in the compared periods, grouped into {len(drill_rows)} descriptions."]
    if truncated:
        notes.append("Smaller descriptions are combined as 'Remaining transactions'.")
    if unmatched:
        notes.append(f"{unmatched} lines had no match in a lookup table.")
    if unclassified:
        notes.append(f"{unclassified} lines fell into the fallback category.")
    if partial_used:
        notes.append("Includes an incomplete period: " + ", ".join(partial_used) + ".")
    return {"source_lines": int(len(in_scope)), "shown_description_count": len(shown), "truncated": truncated, "unmatched_lookup_lines": unmatched,
            "unclassified_lines": unclassified, "partial_periods": partial_used, "note": " ".join(notes), "evidence_ref": f"coverage:{driver['driver_id']}"}


def data_quality(controls: list[dict], join_audit: list[dict], classification: dict, partial: list[str]) -> list[dict]:
    """Findings that limit what commentary can claim, each with its scope and count."""
    items = []
    for control in controls:
        if control.get("status") in ("warn", "stop"):
            items.append({"id": f"control:{control['id']}", "severity": control["status"], "scope": "whole report", "message": str(control.get("message", ""))[:300], "evidence_refs": [f"control:{control['id']}"]})
    for audit in join_audit:
        if audit.get("unmatched_rows"):
            name = str(audit.get("lookup", "lookup"))[:60]
            items.append({"id": f"lookup:{name}", "severity": "warn", "scope": f"lookup '{name}'", "message": f"{int(audit['unmatched_rows'])} lines had no match in '{name}'.", "evidence_refs": [f"lookup:{name}"]})
    if classification and classification.get("unreviewed_rows"):
        items.append({"id": "classification:unreviewed", "severity": "warn", "scope": "categories", "message": f"{int(classification['unreviewed_rows'])} of {int(classification.get('total', 0))} lines are categorised by rules nobody has approved yet (or not categorised).", "evidence_refs": ["classification:unreviewed"]})
    for month in partial:
        items.append({"id": f"partial:{month}", "severity": "warn", "scope": f"period {month}", "message": f"{month} has noticeably fewer lines than other months or was marked incomplete.", "evidence_refs": [f"partial:{month}"]})
    return items[:MAX_QUALITY_ITEMS]
