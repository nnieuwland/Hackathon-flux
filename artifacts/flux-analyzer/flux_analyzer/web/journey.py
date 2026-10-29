"""Deterministic readiness, summaries and provenance for the six Simple-mode steps.

The AI plan may flag a step as needing input, but whether a step is usable is
always decided here from the validated setup and the uploaded columns.
"""
from agent.contracts import STEP_PATCH_PATHS, JOURNEY_STEPS, sanitize_style_profile
from engine.describe import filter_sentence
from .terms import STEPS, AUDIENCE_LABELS, LENGTH_LABELS, TONE_LABELS

ACTOR_LABELS = {"agent": "Set by AI", "user": "Set by you", "preset": "From a saved setup", "system": "Set automatically", "undo": "Restored with Undo", "redo": "Restored with Redo"}


def _money(value: float) -> str:
    value = float(value or 0)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M".replace(".0M", "M")
    if abs(value) >= 1_000:
        return f"{value / 1_000:,.0f}k"
    return f"{value:,.0f}"


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_label(month: str) -> str:
    year, _, number = str(month).partition("-")
    return f"{_MONTHS[int(number) - 1]} {year}" if number.isdigit() and 1 <= int(number) <= 12 else str(month)


def _month_range(months: list[str]) -> str:
    if not months:
        return "not chosen"
    labels = [_month_label(month) for month in months]
    try:
        index = [int(m[:4]) * 12 + int(m[5:7]) for m in months]
        contiguous = all(b - a == 1 for a, b in zip(index, index[1:]))
    except ValueError:
        contiguous = False
    if len(labels) == 1:
        return labels[0]
    if contiguous and len(labels) >= 3:
        return f"{labels[0]} to {labels[-1]}"
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def materiality_text(materiality: dict | None) -> str:
    value = materiality or {}
    mode = value.get("mode", "abs")
    if mode == "abs":
        return f"Movements of {_money(value.get('abs', 0))} or more need explaining."
    percent = f"{value.get('pct', 0) * 100:g}%"
    if mode == "pct_of_total":
        return f"Movements of at least {percent} of the total movement need explaining."
    word = "larger" if mode == "max_of" else "smaller"
    return f"Movements need explaining above the {word} of {_money(value.get('abs', 0))} and {percent} of the total movement."


def is_simple_materiality(materiality: dict | None) -> bool:
    return (materiality or {}).get("mode", "abs") == "abs"


def driver_view(spec: dict) -> dict | None:
    name = spec.get("drivers", {}).get("view")
    return next((view for view in spec.get("views", []) if view.get("name") == name), None)


def provenance(change_log: list[dict], step: str) -> str | None:
    prefixes = STEP_PATCH_PATHS[step]
    for event in reversed(change_log or []):
        path = event.get("path", "")
        if path and any(path == prefix or path.startswith(prefix + "/") or prefix.startswith(path + "/") for prefix in prefixes):
            return ACTOR_LABELS.get(event.get("actor"), "Set by you")
    return None


def step_checks(state: dict) -> dict:
    """Return {step: (ready, reason, summary_sentences, complex_note)}."""
    spec, columns = state["spec"], {c["name"] for c in state.get("profile", {}).get("columns", [])}
    periods = state.get("periods", [])
    derived = {item.get("name") for item in spec.get("derive", [])}
    if spec.get("classification"):
        derived.add(spec["classification"].get("target_col"))
    roles = spec.get("roles", {})
    has_data = any(item.get("defined") and item.get("role") != "lookup" for item in state.get("sources", []))
    output = {}

    if not has_data:
        output["data"] = (False, "Upload your data file first.", ["No data uploaded yet."], None)
    elif not roles.get("value") or roles["value"] not in columns:
        output["data"] = (False, "Choose the column that holds the amounts.", [f"Months: {roles.get('period') or 'not chosen'}."], None)
    elif not roles.get("period") or roles["period"] not in columns:
        output["data"] = (False, "Choose the column that holds the months.", [f"Amounts: {roles['value']}."], None)
    else:
        sentences = [f"Amounts come from {roles['value']} and months from {roles['period']}."]
        if roles.get("driver_text"):
            sentences.append("Descriptions come from " + ", ".join(roles["driver_text"]) + ".")
        if roles.get("dimensions"):
            sentences.append("Grouping fields available: " + ", ".join(roles["dimensions"]) + ".")
        complex_note = "Amounts are calculated as debit minus credit." if spec.get("value_rules", {}).get("source") == "debit_minus_credit" else None
        output["data"] = (True, "", sentences, complex_note)
    data_ready = output["data"][0]

    comparison = spec.get("comparison", {})
    base, current = comparison.get("base", {}), comparison.get("current", {})
    missing = [month for month in base.get("months", []) + current.get("months", []) if periods and month not in periods]
    if not data_ready:
        output["compare"] = (False, "Finish the Data step first.", ["Periods are chosen after the month column is known."], None)
    elif not current.get("months") or not (base.get("months") or base.get("scenario")):
        output["compare"] = (False, "Choose the months to compare.", ["No periods chosen yet."], None)
    elif missing:
        output["compare"] = (False, "Some chosen months are not in your data: " + ", ".join(missing) + ".", [], None)
    else:
        sentences = [f"Compare {_month_range(current.get('months', []))} with {_month_range(base.get('months', []))}."]
        if base.get("scenario") or current.get("scenario"):
            sentences.append(f"Versions: {current.get('scenario') or 'all'} against {base.get('scenario') or 'all'}.")
        complex_note = "Extra filters apply to one side of the comparison." if base.get("filters") or current.get("filters") else None
        output["compare"] = (True, "", sentences, complex_note)

    scope = spec.get("scope", [])
    unknown = [rule["col"] for rule in scope if rule.get("col") not in columns | derived]
    simple_scope = all(rule.get("op") in ("eq", "in") for rule in scope)
    if not data_ready:
        output["include"] = (False, "Finish the Data step first.", [], None)
    elif unknown:
        output["include"] = (False, "A filter uses a column that is not in your data: " + ", ".join(unknown) + ".", [], None)
    else:
        sentences = ["Include every row."] if not scope else ["Only rows where " + "; and ".join(filter_sentence(rule) for rule in scope) + "."]
        extras = [label for label, present in (("calculated fields", spec.get("derive")), ("matched lookups", spec.get("joins"))) if present]
        note = None
        if not simple_scope or extras:
            note = "This setup also uses " + (", ".join(extras) if extras else "advanced filters") + ". Open details to change this."
        output["include"] = (True, "", sentences, note)

    view = driver_view(spec)
    measure = spec.get("measures", {}).get(spec.get("drivers", {}).get("measure", "amount"))
    keys = (view or {}).get("keys", [])
    bad_keys = [key for key in keys if key not in columns | derived]
    if not data_ready:
        output["group"] = (False, "Finish the Data step first.", [], None)
    elif not view or not keys:
        output["group"] = (False, "Choose at least one grouping field.", ["No grouping chosen yet."], None)
    elif bad_keys:
        output["group"] = (False, "A grouping field is not in your data: " + ", ".join(bad_keys) + ".", [], None)
    elif not measure:
        output["group"] = (False, "The amount measure is missing. Open details to fix it.", [], None)
    else:
        sentences = ["One movement line per " + " and ".join(keys) + "."]
        if spec.get("classification"):
            sentences.append(f"Descriptions are sorted into {spec['classification'].get('target_col')} categories.")
        note = None
        if len(spec.get("views", [])) > 1 or spec.get("sections") or spec.get("flags") or len(spec.get("measures", {})) > 1:
            note = "This setup also has extra views, sections or flags. Open details to change this."
        output["group"] = (True, "", sentences, note)

    drivers = spec.get("drivers", {})
    sentences = [materiality_text(drivers.get("materiality")), f"Show up to {drivers.get('top_n', 15)} movements; the rest are grouped as '{drivers.get('others_label', 'Other items')}'."]
    note = None if is_simple_materiality(drivers.get("materiality")) else "The threshold uses a percentage rule. Open details to change this."
    output["important"] = (True, "", sentences, note) if drivers.get("materiality") else (False, "Choose an importance threshold.", sentences[1:], None)

    style = spec.get("commentary", {}).get("style_profile")
    if style:
        profile = sanitize_style_profile(style)
        sentences = [f"{AUDIENCE_LABELS[profile['audience']]} audience, {LENGTH_LABELS[profile['length']].lower()}, {TONE_LABELS[profile['tone']].lower()} tone."]
        if profile["structure"]["type"] == "split":
            sentences.append(f"Split by {profile['structure']['split_by']}.")
        if profile.get("objective"):
            sentences.append("Purpose: " + profile["objective"])
        if profile.get("business_context"):
            count = len([line for line in profile["business_context"].splitlines() if line.strip()])
            sentences.append(f"{count} known business fact{'s' if count != 1 else ''} stated by you, used as attributed context only.")
        if profile["example_style"]["summary_of_style"]:
            sentences.append("Writing style from your example: " + profile["example_style"]["summary_of_style"])
    else:
        sentences = ["Neutral, amount-first commentary (default)."]
    output["explain"] = (True, "", sentences, None)
    return output


def journey_state(state: dict) -> dict:
    """Combine deterministic readiness with any outstanding plan questions."""
    checks = step_checks(state)
    plan = state.get("plan_state") or {}
    flagged = plan.get("steps", {})
    questions = {item["id"]: item for item in plan.get("questions", [])}
    steps = []
    for meta in STEPS:
        step = meta["id"]
        ready, reason, summary, note = checks[step]
        status = "ready" if ready else "needs_input"
        step_questions = []
        if ready and step in flagged:
            status = "needs_input"
            reason = flagged[step].get("reason") or "Please check this step."
            step_questions = [questions[qid] for qid in flagged[step].get("question_ids", []) if qid in questions]
        steps.append({**meta, "status": status, "reason": reason, "summary": summary, "complex_note": note, "provenance": provenance(state.get("change_log", []), step), "questions": step_questions})
    open_steps = [item["id"] for item in steps if item["status"] != "ready"]
    has_data = any(item.get("defined") and item.get("role") != "lookup" for item in state.get("sources", []))
    return {"steps": steps, "first_open": open_steps[0] if open_steps else None, "ready_for_review": not open_steps, "has_data": has_data, "plan_summary": plan.get("summary"), "plan_warnings": plan.get("warnings", [])}


__all__ = ["journey_state", "JOURNEY_STEPS", "materiality_text"]
