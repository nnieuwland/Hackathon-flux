"""Pure orchestration: execute any validated spec without flux-type branches."""
import copy
from statistics import median
import pandas as pd
from .spec import validate_spec, resolve_tokens
from .periods import normalize_periods, resolve_comparison, available_months, months_for_period
from .transform import apply_scope, derive
from .compare import pivot_compare, apply_joins, decompose, slice_mask, compute_measure
from .flags import apply_flags, apply_gates
from .drivers import select_drivers, drill, materiality_threshold
from .controls import run_controls
from .evidence import build_evidence_pack, finalize_evidence
from .evidence_context import driver_rows
from .money import clean, money, decimal, total
from .expr import filter_mask
from .v2rules import apply_value_rules, apply_classification
from .joins import apply_source_joins

def prepare(df: pd.DataFrame, spec: dict, lookups: dict[str, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, dict, dict]:
    """Validate and prepare all rows for deterministic execution."""
    spec = validate_spec(spec)
    frame = derive(df, spec.get("derive", []))
    frame = apply_value_rules(frame, spec)
    frame, join_audit = apply_source_joins(frame, spec.get("joins", []), lookups)
    frame = apply_classification(frame, spec.get("classification"), spec["roles"])
    frame = apply_scope(frame, spec.get("scope", []))
    if spec.get("classification"):
        frame = apply_classification(frame, spec["classification"], spec["roles"])
    if frame.empty:
        raise ValueError("No rows remain after scope filters. Adjust your scope rules.")
    period_col = spec["roles"].get("period")
    if period_col:
        if period_col not in frame:
            raise ValueError(f"Period column '{period_col}' not found. Remap columns.")
        frame = normalize_periods(frame, period_col, spec.get("periods", {}).get("calendar", "calendar"), spec.get("period_format", "auto"))
    available = available_months(frame[period_col].dropna().unique(), spec.get("periods", {}).get("calendar", "calendar"), spec.get("period_format", "auto")) if period_col else []
    comparison = resolve_comparison(spec["comparison"], available, spec.get("periods", {}).get("calendar", "calendar"))
    period_counts = frame["__month"].value_counts().to_dict() if "__month" in frame else {}
    nonzero_counts = [count for count in period_counts.values() if count > 0]
    median_count = median(nonzero_counts) if nonzero_counts else 0
    declared = {month for label in spec.get("partial_periods", []) for month in months_for_period(label, spec.get("periods", {}).get("calendar", "calendar"))}
    inferred = {month for month, count in period_counts.items() if median_count and count < median_count * .5}
    partial_months = sorted((declared | inferred) & (set(comparison["base"]["months"]) | set(comparison["current"]["months"])))
    comparison["partial_months_used"] = partial_months
    comparison["monthly_row_counts"] = {str(month): int(count) for month, count in sorted(period_counts.items())}
    frame.attrs["join_audit"] = join_audit
    frame.attrs["period_counts"] = comparison["monthly_row_counts"]
    frame.attrs["partial_months_used"] = partial_months
    resolved = resolve_tokens(spec, comparison)
    # Filters using a period role must compare against canonical month keys.
    for measure in resolved.get("measures", {}).values():
        for condition in measure.get("filter", []):
            if condition["col"] == period_col and "__month" in frame:
                condition["col"] = "__month"
    return frame, resolved, comparison

def preflight(df: pd.DataFrame, spec: dict, lookups: dict[str, pd.DataFrame] | None = None) -> list[dict]:
    """Run stop/warn controls without creating outputs."""
    frame, resolved, comparison = prepare(df, spec, lookups)
    return run_controls({"df": frame, "spec": resolved, "comparison": comparison}, spec.get("controls", []))

def execute(df: pd.DataFrame, spec: dict, lookups: dict[str, pd.DataFrame] | None = None) -> dict:
    """Execute measures, flags, joins, drivers and evidence for a generic spec."""
    spec = validate_spec(spec)
    frame, resolved, comparison = prepare(df, spec, lookups)
    context = {"df": frame, "spec": resolved, "comparison": comparison}
    controls = run_controls(context, spec.get("controls", []))
    stopped = [c for c in controls if c["status"] == "stop"]
    if stopped:
        raise ValueError("Run blocked: " + " ".join(c["message"] for c in stopped))
    measures = resolved.get("measures", {})
    if not measures or not resolved.get("views"):
        raise ValueError("Define at least one measure and view in Rules before running.")
    all_views, flags, exceptions, flag_counts = {}, [], [], []
    for view in resolved["views"]:
        selected = {}
        for name in view["measures"]:
            if name not in measures:
                raise ValueError(f"View '{view['name']}' references unknown measure '{name}'.")
            selected[name] = measures[name]
        output = pivot_compare(frame, view["keys"], selected, comparison["base"], comparison["current"], resolved["roles"], view.get("compare", True))
        output = apply_joins(output, view.get("joins", []), lookups or {})
        if resolved.get("decompose") and view.get("compare", True):
            decomposition = resolved["decompose"]
            if not decomposition.get("view") or decomposition["view"] == view["name"]:
                output = decompose(output, decomposition)
        for rule in resolved.get("flags", []):
            if rule["view"] == view["name"]:
                output, counts = apply_flags(output, rule)
                flag_counts.append({"n_rows": len(output), "counts": counts})
                flags.extend({"view": view["name"], **r} for r in output.to_dict("records"))
        for gate in resolved.get("gates", []):
            if gate["view"] == view["name"]:
                exceptions.extend({"view": view["name"], "gate": gate["name"], **r} for r in apply_gates(output, gate).to_dict("records"))
        all_views[view["name"]] = output
    settings = resolved.get("drivers", {})
    view_name = settings.get("view", resolved["views"][0]["name"])
    measure = settings.get("measure", next(iter(measures)))
    if view_name not in all_views:
        raise ValueError(f"Driver view '{view_name}' not found.")
    view = next(v for v in resolved["views"] if v["name"] == view_name)
    compared = all_views[view_name]
    driver_columns = view["keys"] + [f"{measure}_{suffix}" for suffix in ("base", "current", "delta", "delta_pct")]
    base = total(compared[f"{measure}_base"]) if not compared.empty else 0.0
    current = total(compared[f"{measure}_current"]) if not compared.empty else 0.0
    delta = money(decimal(current) - decimal(base))
    threshold = materiality_threshold(settings.get("materiality", settings.get("materiality_abs")), base, current)
    drivers = select_drivers(compared[driver_columns], measure, threshold, settings.get("top_n", 15), settings.get("others_label", "Other items"))
    label_styles = resolved.get("commentary", {}).get("dimension_label_style", {})
    for driver in drivers:
        if driver.get("dimensions"):
            labels = []
            for column, value in driver["dimensions"].items():
                style = label_styles.get(column)
                labels.append(str(style.get(value, value)) if isinstance(style, dict) else value)
            driver["label"] = " / ".join(labels)
    drills = {}
    if measures[measure]["agg"] != "sum":
        raise ValueError("Driver measures must be additive sums to provide reconciling transaction evidence. Use mean/ratio measures alongside a sum amount measure.")
    measure_frame = frame.loc[filter_mask(frame, measures[measure].get("filter", []))]
    for driver in drivers:
        drills[driver["driver_id"]] = drill(measure_frame, driver, view["keys"], comparison["base"], comparison["current"], resolved.get("drill", {}).get("group_by", resolved["roles"].get("driver_text", [])), resolved.get("drill", {}).get("top_n", 5), measures[measure]["col"], resolved["roles"])
        selected = frame
        for key, value in driver.get("dimensions", {}).items():
            selected = selected.loc[selected[key].fillna("(empty)").astype(str).eq(value)]
        for excluded in driver.get("excluded_dimensions", []):
            mask = pd.Series(True, index=selected.index)
            for key, value in excluded.items():
                mask &= selected[key].fillna("(empty)").astype(str).eq(value)
            selected = selected.loc[~mask]
        driver["flags"], driver["flag_counts"] = [], []
        for rule in resolved.get("flags", []):
            definition = next(item for item in resolved["views"] if item["name"] == rule["view"])
            keys = definition["keys"]
            if not all(key in selected for key in keys):
                continue
            key_frame = selected[keys].fillna("(empty)").astype(str)
            for join in definition.get("joins", []):
                if join.get("key_normalise") and join["left_on"] in key_frame:
                    from .joins import _normalize
                    key_frame[join["left_on"]] = key_frame[join["left_on"]].map(lambda value: _normalize(value, join["key_normalise"]))
            members = set(key_frame.itertuples(index=False, name=None))
            counts = {}
            for row in all_views[rule["view"]].to_dict("records"):
                if tuple(str(row[key]) for key in keys) in members:
                    label = str(row[rule["name"]])
                    counts[label] = counts.get(label, 0) + 1
            driver["flags"].extend(f"{rule['name']}: {label} ({count})" for label, count in counts.items())
            driver["flag_counts"].extend({"rule": rule["name"], "label": label, "count": count} for label, count in counts.items())
    sections = []
    if resolved.get("sections"):
        col = resolved["sections"]["split_by"]
        section_measure = resolved["sections"].get("must_reconcile_to", measure)
        section_table = pivot_compare(frame, [col], {section_measure: measures[section_measure]}, comparison["base"], comparison["current"], resolved["roles"])
        sections = [{"label": str(r[col]), "base": r[f"{section_measure}_base"], "current": r[f"{section_measure}_current"], "delta": r[f"{section_measure}_delta"]} for r in section_table.to_dict("records")]
        order = resolved["sections"].get("order", [])
        sections.sort(key=lambda r: order.index(r["label"]) if r["label"] in order else len(order))
    description_columns = resolved.get("drill", {}).get("group_by", resolved["roles"].get("driver_text", []))
    description_columns = [description_columns] if isinstance(description_columns, str) else list(description_columns or [])
    evidence_context = {
        "rows_for": lambda driver: driver_rows(measure_frame, driver), "comparison": comparison, "roles": resolved["roles"], "value_col": measures[measure]["col"],
        "available": set(frame["__month"].dropna().astype(str)) if "__month" in frame else set(), "partial": set(comparison["partial_months_used"]),
        "compared": compared, "keys": view["keys"], "measure": measure, "decompose": resolved.get("decompose"), "classification": resolved.get("classification"), "threshold": threshold,
        "top_n": settings.get("top_n", 15), "others_label": settings.get("others_label", "Other items"), "description_columns": [c for c in description_columns if c in frame],
    }
    evidence = build_evidence_pack(resolved, drivers, drills, sections, evidence_context)
    drivers = [{**driver, **item} for driver, item in zip(drivers, evidence["drivers"])]
    context.update(drivers=drivers, delta=delta, sections=sections, flag_counts=flag_counts)
    controls.extend(run_controls(context, spec.get("controls", []), post=True))
    if any(c["status"] == "stop" for c in controls):
        raise ValueError("Post-run reconciliation failed. Outputs were not released.")
    join_audit = frame.attrs.get("join_audit", [])
    finalize_evidence(evidence, controls, join_audit, frame.attrs.get("classification", {}), comparison["partial_months_used"], evidence_context["description_columns"])
    return clean({"name": spec["flux_name"], "base": base, "current": current, "delta": delta, "delta_pct": delta / abs(base) * 100 if base else None, "n_drivers": len(drivers), "n_exceptions": len(exceptions), "drivers": drivers, "views": {k: v.to_dict("records") for k, v in all_views.items()}, "drills": drills, "flags": flags, "exceptions": exceptions, "sections": sections, "controls": controls, "spec": copy.deepcopy(spec), "evidence": evidence, "materiality_threshold": threshold, "classification": frame.attrs.get("classification", {}), "classification_review": frame.attrs.get("classification_review", []), "join_audit": join_audit, "monthly_row_counts": comparison["monthly_row_counts"], "partial_months_used": comparison["partial_months_used"], "warnings": [c["message"] for c in controls if c["status"] == "warn"]})
