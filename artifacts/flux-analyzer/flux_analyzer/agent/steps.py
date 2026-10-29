"""Single audited path from local data to bounded agent metadata."""
from datetime import date
import uuid
from engine.profile import profile, distinct_values, value_counts_combo
from engine.periods import available_months, parse_period
from engine.money import total
from engine.presets import get_preset, list_presets, agent_payload as preset_agent_payload

from .contracts import CONTRACT_VERSION, STAGES, allowed_paths_for, default_style_profile, STYLE_AUDIENCES, STYLE_LENGTHS, STYLE_TONES

STEPS = {"detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules", "write_commentary", "apply_instruction", "explain_spec", "answer_question", "plan_from_description", "extract_commentary_style", "describe_setup"}
WRITE_STEPS = {"detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules", "apply_instruction", "plan_from_description", "extract_commentary_style"}

# A short legend sent with commentary requests so the model reads the evidence pack as intended.
EVIDENCE_GUIDE = {
    "observations": "Amounts, history (trend), categories, volume/rate effects, flags and descriptions are checked facts; cite their evidence_ref.",
    "trend": "Use trend.pattern only: one_period, continuing or reversal wording is allowed only when that is the pattern; no trend object means no history claims.",
    "categories": "Only 'approved' categories come from rules a person reviewed; call the others suggested.",
    "materiality": "is_material and materiality_policy come from the engine; never judge materiality yourself.",
    "coverage": "coverage, coverage_notes and data_quality limit what can be claimed; mention material limits.",
    "business_context": "Stated by a person or preset, not checked; attribute it ('you told us', 'per the preset') and cite its context ref.",
    "causes": "Descriptions and categories show where a movement sits, not why. A cause, timing or one-off judgement is a possible_explanation: add verify_tag and support needs_verification unless it repeats cited business context.",
    "numbers": "Quote only *_fmt amounts and allowed_numeric_tokens; never calculate.",
}


def file_profiles(df: object) -> list[dict]:
    """Contract-shaped column profile for the combined primary data."""
    if df is None or not len(getattr(df, "columns", [])):
        return []
    described = profile(df.loc[:, [c for c in df.columns if not str(c).startswith("__")]])
    rows = described["n_rows"]
    columns = [{"name": c["name"], "dtype": c["dtype_guess"], "null_count": int(round(c["pct_empty"] * rows / 100)), "distinct_count": c["n_unique"], "samples": c["samples"][:5]} for c in described["columns"]]
    return [{"source_id": "primary", "name": "Main data", "columns": columns, "row_count": rows, "months": [], "source_guess": None}]


def months_for(df: object, spec: dict) -> list[str]:
    col = spec.get("roles", {}).get("period")
    if df is None or not col or col not in getattr(df, "columns", []):
        return []
    try:
        return available_months(df[col].dropna().unique(), spec.get("periods", {}).get("calendar", "calendar"), spec.get("period_format", "auto"))
    except ValueError:
        return []


def guess_months(df: object, calendar: str = "calendar") -> list[str]:
    """Months in the most likely month column, for describing a flux before columns are mapped."""
    import re
    if df is None:
        return []
    columns = [str(c) for c in getattr(df, "columns", []) if not str(c).startswith("__")]
    columns.sort(key=lambda name: 0 if re.search(r"month|period|date|posting", name, re.I) else 1)
    for name in columns:
        try:
            months = available_months(df[name].dropna().unique(), calendar, "auto")
        except (ValueError, TypeError):
            continue
        if months:
            return months
    return []


def build_envelope(step: str, spec: dict, df: object = None, user_message: str = "", evidence: dict | None = None, context: dict | None = None, extra: dict | None = None) -> dict:
    """Build each allowed payload from aggregations, not records/raw columns."""
    if step not in STEPS:
        raise ValueError("Unknown agent step.")
    from engine.spec import validate_spec
    spec = validate_spec(spec)
    roles = spec.get("roles", {})
    extra = extra or {}
    payload = {}
    if step == "detect_flux":
        payload = {
            "headers": [str(c) for c in df.columns if not str(c).startswith("__")],
            "user_text": user_message,
            "available_presets": list_presets(),
        }
    elif step == "map_columns":
        payload = {"profile": profile(df.loc[:, [c for c in df.columns if not str(c).startswith("__")]]), "previous_roles": roles}
    elif step == "define_comparison":
        col = roles.get("period")
        payload = {"period_values": distinct_values(df, col) if col else [], "today": date.today().isoformat(), "available_months": []}
        if col:
            payload["available_months"] = available_months(df[col].dropna().unique(), spec.get("periods", {}).get("calendar", "calendar"), spec.get("period_format", "auto"))
            counts = {}
            for value in df[col].dropna():
                month = parse_period(value, spec.get("periods", {}).get("calendar", "calendar"), spec.get("period_format", "auto"))
                counts[month] = counts.get(month, 0) + 1
            median_count = sorted(counts.values())[len(counts) // 2] if counts else 0
            payload["monthly_row_counts"] = counts
            payload["partial_period_candidates"] = [month for month, count in sorted(counts.items()) if median_count and count < median_count * .5]
        if roles.get("scenario"):
            payload["scenario_values"] = distinct_values(df, roles["scenario"])
    elif step == "derive_columns":
        columns = (roles.get("dimensions", []) + roles.get("driver_text", []))[:2]
        payload = {"value_counts": value_counts_combo(df, columns, value_col=roles.get("value")) if columns else [], "roles": roles}
    elif step == "classify_terms":
        text_col = next(iter(roles.get("driver_text", [])), None)
        terms = []
        if text_col:
            for text, frame in df.groupby(text_col, dropna=False):
                terms.append({"text": str(text)[:120], "abs_value": abs(total(frame[roles["value"]])) if roles.get("value") else 0, "n": len(frame)})
            terms.sort(key=lambda r: r["abs_value"], reverse=True)
        payload = {"allowed_categories": [], "terms": terms[:100]}
    elif step == "define_rules":
        payload = {"spec_so_far": spec}
    elif step == "write_commentary":
        from .writing_context import writing_guidance
        payload = {"evidence_pack": evidence, "commentary_rules": spec.get("commentary", {}),
                   "writing_guidance": (evidence or {}).get("writing_guidance") or writing_guidance(spec), "evidence_guide": EVIDENCE_GUIDE}
    elif step == "apply_instruction":
        payload = {"instruction": user_message[:3000], "target_step": extra.get("target_step") or None}
        from engine.describe import describe_spec
        payload["rule_descriptions"] = [{"id": card["path"], "sentence": card["sentence"]} for card in describe_spec(spec)]
    elif step == "plan_from_description":
        from engine.describe import describe_spec
        payload = {"description": user_message[:3000], "file_profiles": file_profiles(df), "column_profile": profile(df.loc[:, [c for c in df.columns if not str(c).startswith("__")]]) if df is not None and len(df.columns) else {"n_rows": 0, "columns": []}, "available_presets": [{"id": item.get("id"), "version": str(item.get("version", "")), "name": item.get("name", ""), "description": item.get("description", "")} for item in list_presets()], "existing_step_state": extra.get("existing_step_state", {}), "rule_descriptions": [{"id": card["path"], "sentence": card["sentence"]} for card in describe_spec(spec)]}
        if roles.get("scenario") and df is not None and roles["scenario"] in df:
            payload["scenario_values"] = distinct_values(df, roles["scenario"])
    elif step == "extract_commentary_style":
        payload = {"example_text": str(extra.get("example_text", ""))[:6000], "current_style_profile": spec.get("commentary", {}).get("style_profile"), "style_constraints": {"audience": list(STYLE_AUDIENCES), "length": list(STYLE_LENGTHS), "tone": list(STYLE_TONES), "forbidden_terms": spec.get("commentary", {}).get("forbidden_terms", [])}}
    elif step == "describe_setup":
        from engine.describe import describe_spec
        payload = {"rule_descriptions": [{"id": card["path"], "sentence": card["sentence"]} for card in describe_spec(spec)], "existing_name": str(extra.get("existing_name", ""))[:120], "existing_description": str(extra.get("existing_description", ""))[:1000], "purpose": extra.get("purpose", "save"), "allowed_display_tokens": []}
    elif step == "explain_spec":
        payload = {"target": user_message[:500]}
    elif step == "answer_question":
        payload = {"question": user_message[:1000], "evidence_pack": evidence}
        from engine.describe import describe_spec
        payload["rule_descriptions"] = [card["sentence"] for card in describe_spec(spec)]
    selected = get_preset((spec.get("preset") or {}).get("id"), (spec.get("preset") or {}).get("version"))
    payload["preset"] = preset_agent_payload(selected, step)
    ui = context or {}
    payload["context"] = {"spec_revision": int(ui.get("spec_revision", 0)), "source_profile_id": str(ui.get("source_profile_id", "")), "run_id": ui.get("run_id"), "ui_step": ui.get("ui_step") if ui.get("ui_step") in STAGES else "review", "mode": "advanced" if ui.get("mode") == "advanced" else "simple", "locale": str(ui.get("locale") or "en-GB")[:20]}
    payload["allowed_patch_paths"] = allowed_paths_for(None) if step in WRITE_STEPS else []
    payload["allowed_columns"] = [str(c) for c in getattr(df, "columns", []) if not str(c).startswith("__")] if df is not None else []
    payload["available_months"] = months_for(df, spec)
    if step == "plan_from_description" and not payload["available_months"]:
        payload["available_months"] = guess_months(df, spec.get("periods", {}).get("calendar", "calendar"))
    from .client import SCHEMAS
    payload["response_schema"] = {"envelope": SCHEMAS["envelope"], "proposal": SCHEMAS[step]}
    return {"contract_version": CONTRACT_VERSION, "request_id": str(uuid.uuid4()), "step": step, "user_message": user_message[:3000] if step != "extract_commentary_style" else "", "spec_so_far": spec, "payload": payload}
