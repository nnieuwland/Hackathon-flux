"""Extensible control registry. Stops always block execution."""
from typing import Callable
import pandas as pd
from .money import total, decimal
from .spec import validate_spec_against_data
from .compare import slice_mask

REGISTRY: dict[str, Callable] = {}

def control(name: str) -> Callable:
    """Register a pure, deterministic control function."""
    def register(fn: Callable) -> Callable:
        REGISTRY[name] = fn
        return fn
    return register

def outcome(name: str, ok: bool, message: str, severity: str = "stop", details: object = None) -> dict:
    """Create a standard control result."""
    return {"id": name, "status": "pass" if ok else severity, "message": message, "details": details or {}}

@control("required_columns")
def required_columns(context: dict, cfg: dict) -> dict:
    """All mapped and declared source columns exist."""
    missing = validate_spec_against_data(context["spec"], list(context["df"].columns))
    roles = context["spec"]["roles"]
    if not roles.get("value"):
        missing.append("Value role (not mapped)")
    return outcome("required_columns", not missing, "All required columns are available." if not missing else f"Missing columns: {', '.join(missing)}. Remap columns before running.", cfg.get("severity", "stop"), {"missing": missing})

@control("periods_present")
def periods_present(context: dict, cfg: dict) -> dict:
    """Both comparison slices must contain data, without missing months."""
    missing = context.get("comparison", {}).get("partial_periods", [])
    counts = {}
    for name in ("base", "current"):
        item = context["comparison"][name]
        counts[name] = int(slice_mask(context["df"], item, context["spec"]["roles"]).sum())
    ok = not missing and all(counts.values())
    return outcome("periods_present", bool(ok), "Both comparison slices contain data." if ok else "One or more selected months/scenarios are missing. Adjust comparison or upload the missing data.", cfg.get("severity", "stop"), {"missing": missing, "rows": counts})

@control("no_duplicate_periods_across_files")
def no_duplicate_periods_across_files(context: dict, cfg: dict) -> dict:
    """Detect overlapping periods in files explicitly stacked by period."""
    df = context["df"]
    if "__source" not in df or "__month" not in df:
        return outcome("no_duplicate_periods_across_files", True, "No overlapping period sources.")
    cols = ["__month"] + ([context["spec"]["roles"]["scenario"]] if context["spec"]["roles"].get("scenario") else [])
    counts = df.groupby(cols, dropna=False)["__source"].nunique()
    overlaps = [str(k) for k, v in counts.items() if v > 1]
    return outcome("no_duplicate_periods_across_files", not overlaps, "No periods overlap across stacked sources." if not overlaps else "Periods overlap across files. Confirm each period appears in only one stacked source.", cfg.get("severity", "stop"), {"periods": overlaps})

@control("sections_reconcile")
def sections_reconcile(context: dict, cfg: dict) -> dict:
    """Section movements equal total movement within explicit tolerance."""
    if not context.get("sections"):
        return outcome("sections_reconcile", True, "No section split configured.")
    difference = abs(decimal(total(r["delta"] for r in context["sections"])) - decimal(context["delta"]))
    return outcome("sections_reconcile", difference <= decimal(cfg.get("tolerance", .01)), "Sections reconcile to total movement." if difference <= decimal(cfg.get("tolerance", .01)) else "Sections do not reconcile.", cfg.get("severity", "stop"), {"difference": float(difference)})

@control("flags_sum_to_rows")
def flags_sum_to_rows(context: dict, cfg: dict) -> dict:
    """Every flagged view's counts sum to its row count."""
    ok = all(sum(item["counts"].values()) == item["n_rows"] for item in context.get("flag_counts", []))
    return outcome("flags_sum_to_rows", ok, "Flag counts reconcile to view rows." if ok else "Flag count mismatch.", cfg.get("severity", "stop"))

@control("drivers_reconcile")
def drivers_reconcile(context: dict, cfg: dict) -> dict:
    """Drivers including other items equal total delta exactly."""
    ok = "drivers" not in context or total(r["delta"] for r in context["drivers"]) == context["delta"]
    return outcome("drivers_reconcile", ok, "Drivers and other items reconcile to the movement." if ok else "Driver movement does not reconcile.", cfg.get("severity", "stop"))

@control("debit_minus_credit_equals_value")
def debit_minus_credit_equals_value(context: dict, cfg: dict) -> dict:
    """Check debit less credit against the value column, row by row."""
    df, roles = context["df"], context["spec"]["roles"]
    params = cfg.get("params", {})
    debit, credit = params.get("debit", roles.get("debit")), params.get("credit", roles.get("credit"))
    if not debit or not credit or debit not in df or credit not in df:
        return outcome("debit_minus_credit_equals_value", False, "Debit/credit columns are not mapped. Map them or remove this optional control.", cfg.get("severity", "warn"))
    bad = sum(abs(decimal(d) - decimal(c) - decimal(v)) > decimal(cfg.get("tolerance", .01)) for d, c, v in zip(df[debit], df[credit], df[roles["value"]]))
    return outcome("debit_minus_credit_equals_value", bad == 0, "Debit less credit matches value." if not bad else f"{bad} rows do not reconcile debit less credit.", cfg.get("severity", "warn"), {"n_rows": bad})

@control("new_or_removed_members")
def new_or_removed_members(context: dict, cfg: dict) -> dict:
    """Report dimension members found in only one slice."""
    df, spec, comp = context["df"], context["spec"], context["comparison"]
    changes = {}
    for col in spec["roles"].get("dimensions", []):
        if col not in df:
            continue
        b = set(df.loc[slice_mask(df, comp["base"], spec["roles"]), col].astype(str))
        c = set(df.loc[slice_mask(df, comp["current"], spec["roles"]), col].astype(str))
        if b != c:
            changes[col] = {"new": sorted(c - b), "removed": sorted(b - c)}
    return outcome("new_or_removed_members", not changes, "Dimension membership is consistent." if not changes else "New or removed dimension members were found; see details.", cfg.get("severity", "warn"), changes)

@control("join_unmatched_keys")
def join_unmatched_keys(context: dict, cfg: dict) -> dict:
    """Report lookup keys with no left-join match."""
    audits = context["df"].attrs.get("join_audit", [])
    active = [item for item in audits if item.get("unmatched_rows") and item.get("severity") != "allow"]
    severity = "stop" if any(item.get("severity") == "stop" for item in active) else cfg.get("severity", "warn")
    details = {item["lookup"]: {"keys": item.get("unmatched_keys", []), "rows": item.get("unmatched_rows", 0), "value": item.get("unmatched_value", 0)} for item in active}
    return outcome("join_unmatched_keys", not active, "All lookup keys matched." if not active else "Some source keys had no lookup match.", severity, details)

@control("join_fanout")
def join_fanout(context: dict, cfg: dict) -> dict:
    """Ensure left joins do not multiply source rows or hide duplicate keys."""
    audits = context["df"].attrs.get("join_audit", [])
    issues = [item for item in audits if item.get("fanout")]
    details = {item["lookup"]: {"duplicate_keys": item.get("duplicate_keys", []), "fanout": item.get("fanout", False)} for item in issues}
    return outcome("join_fanout", not issues, "Lookup joins preserve one row per source row." if not issues else "Duplicate lookup keys were deduplicated; review the selected first-match records.", cfg.get("severity", "warn"), details)

@control("classification_coverage")
def classification_coverage(context: dict, cfg: dict) -> dict:
    """Report how much source text received a rule-based classification."""
    stats = context["df"].attrs.get("classification", {})
    minimum = float(cfg.get("params", {}).get("minimum_percentage", 95))
    active = bool(context["spec"].get("classification"))
    coverage = float(stats.get("value_coverage", stats.get("coverage", 100)))
    ok = not active or coverage >= minimum
    return outcome("classification_coverage", ok, "Classification coverage meets the configured minimum." if ok else f"Classification coverage is {coverage:.1f}%, below {minimum:.1f}%.", cfg.get("severity", "warn"), stats)

@control("partial_period_used")
def partial_period_used(context: dict, cfg: dict) -> dict:
    """Warn if the selected comparison includes a short-coverage month."""
    months = context.get("comparison", {}).get("partial_months_used", [])
    counts = context["df"].attrs.get("period_counts", {})
    return outcome("partial_period_used", not months, "No detected partial months are selected." if not months else "Selected months have fewer than half the median row count; verify period completeness.", cfg.get("severity", "warn"), {"months": months, "row_counts": {month: counts.get(month) for month in months}})

def run_controls(context: dict, configs: list[dict], post: bool = False) -> list[dict]:
    """Execute requested controls, plus non-optional safety controls."""
    required = ["required_columns", "periods_present", "no_duplicate_periods_across_files", "join_fanout"] if not post else ["drivers_reconcile", "sections_reconcile", "flags_sum_to_rows"]
    config_map = {c["id"]: c for c in configs}
    for name in required:
        config_map[name] = {**config_map.get(name, {}), "id": name, "severity": "stop"}
    results = []
    post_names = {"drivers_reconcile", "sections_reconcile", "flags_sum_to_rows"}
    for name, cfg in config_map.items():
        if (name in post_names) != post:
            continue
        if name not in REGISTRY:
            raise ValueError(f"Unknown control '{name}'. Register a supported control.")
        results.append(REGISTRY[name](context, cfg))
    return results
