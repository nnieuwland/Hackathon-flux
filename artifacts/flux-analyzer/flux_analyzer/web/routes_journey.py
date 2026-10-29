"""Simple-mode journey: plan from a description, plain step forms and style."""
import copy
from flask import Blueprint, jsonify, request
from agent.client import invoke_agent
from agent.contracts import JOURNEY_STEPS, sanitize_style_profile, STYLE_AUDIENCES, STYLE_LENGTHS, STYLE_TONES, STYLE_INCLUDE
from agent.steps import build_envelope
from config import WORKSPACE
from engine.ingest import preview, detect_header_row
from .routes_config import json_input, apply_if_current, ui_context
from .state import csrf_token, get_project, save_project, public_state, datasets, start_job, LOCK, apply_spec_change, load_defined, bind_sources, source_path, auto_map_sources, now

bp = Blueprint("journey", __name__)

DEFAULT_CONTROLS = [
    {"id": "required_columns", "severity": "stop"},
    {"id": "periods_present", "severity": "stop"},
    {"id": "no_duplicate_periods_across_files", "severity": "stop"},
    {"id": "new_or_removed_members", "severity": "warn"},
    {"id": "drivers_reconcile", "severity": "stop"},
]


def _columns(state: dict) -> list[str]:
    if not any(item.get("defined") and item.get("role") != "lookup" for item in state["sources"]):
        raise ValueError("Upload your data file first.")
    frame, _ = datasets(state)
    return [str(column) for column in frame.columns if not str(column).startswith("__")]


def ensure_report_defaults(spec: dict) -> dict:
    """Fill the minimum report structure a Simple-mode user never has to see."""
    output = copy.deepcopy(spec)
    roles = output.get("roles", {})
    output.setdefault("measures", {})
    measure = output.get("drivers", {}).get("measure") or "amount"
    if measure not in output["measures"] and roles.get("value"):
        output["measures"][measure] = {"agg": "sum", "col": "{roles.value}"}
    drivers = output.setdefault("drivers", {})
    drivers.setdefault("measure", measure)
    view_name = drivers.get("view") or "by_dimension"
    if not any(view.get("name") == view_name for view in output.get("views", [])) and roles.get("dimensions"):
        output.setdefault("views", []).append({"name": view_name, "keys": roles["dimensions"][:1], "measures": [measure], "compare": True})
    if any(view.get("name") == view_name for view in output.get("views", [])):
        drivers["view"] = view_name
    if roles.get("driver_text") and not output.get("drill", {}).get("group_by"):
        output.setdefault("drill", {"top_n": 5})["group_by"] = "{roles.driver_text}"
    if not output.get("controls"):
        output["controls"] = copy.deepcopy(DEFAULT_CONTROLS)
    return output


def _comparison_type(base: list[str], current: list[str], scenarios: bool) -> str:
    if scenarios:
        return "Actual vs Forecast"
    if len(base) == len(current) == 1:
        return "MoM"
    if len(base) == len(current) == 3:
        return "QoQ"
    if len(base) == len(current) == 12:
        return "YoY"
    return "custom"


def simple_update(state: dict, step: str, data: dict) -> dict:
    """Map a Simple-mode form onto the setup without discarding advanced settings."""
    spec = copy.deepcopy(state["spec"])
    columns = _columns(state)
    derived = {item.get("name") for item in spec.get("derive", [])} | ({spec["classification"].get("target_col")} if spec.get("classification") else set())
    def column(name, label, optional=False):
        if name in (None, "") and optional:
            return None
        if name not in columns and name not in derived:
            raise ValueError(f"Choose a {label} column from your data.")
        return name
    if step == "data":
        roles = spec["roles"]
        roles["value"] = column(data.get("amount"), "amount")
        roles["period"] = column(data.get("month"), "month")
        description = column(data.get("description"), "description", optional=True)
        roles["driver_text"] = [description] if description else []
        grouping = data.get("grouping", roles.get("dimensions", []))
        if not isinstance(grouping, list) or len(grouping) > 8:
            raise ValueError("Choose up to eight grouping fields.")
        roles["dimensions"] = [column(item, "grouping") for item in dict.fromkeys(grouping)]
        spec = ensure_report_defaults(spec)
    elif step == "compare":
        periods = public_state(state)["periods"]
        base, current = list(data.get("base_months") or []), list(data.get("current_months") or [])
        if not base or not current:
            raise ValueError("Choose at least one month for each period.")
        unknown = [month for month in base + current if month not in periods]
        if unknown:
            raise ValueError("These months are not in your data: " + ", ".join(unknown) + ".")
        if set(base) & set(current) and not (data.get("base_scenario") or data.get("current_scenario")):
            raise ValueError("The two periods overlap. Choose different months, or compare versions such as actual and forecast.")
        comparison = spec.get("comparison", {})
        new_base, new_current = {**comparison.get("base", {}), "months": sorted(base)}, {**comparison.get("current", {}), "months": sorted(current)}
        for key, target in (("base_scenario", new_base), ("current_scenario", new_current)):
            if data.get(key):
                target["scenario"] = str(data[key])
            else:
                target.pop("scenario", None)
        spec["comparison"] = {"type": _comparison_type(base, current, bool(data.get("base_scenario"))), "base": new_base, "current": new_current}
        if "partial_periods" in data:
            spec["partial_periods"] = [month for month in data["partial_periods"] if month in periods]
    elif step == "include":
        filters = data.get("filters", [])
        if not isinstance(filters, list) or len(filters) > 10:
            raise ValueError("Use up to ten filters.")
        touched = {item.get("col") for item in filters} | set(data.get("clear", []))
        scope = [rule for rule in spec.get("scope", []) if not (rule.get("col") in touched and rule.get("op") in ("eq", "in"))]
        for item in filters:
            values = [str(value) for value in item.get("values", []) if str(value).strip()]
            if not values:
                continue
            col = column(item.get("col"), "filter")
            scope.append({"col": col, "op": "eq", "val": values[0]} if len(values) == 1 else {"col": col, "op": "in", "val": values})
        spec["scope"] = scope
    elif step == "group":
        keys = data.get("keys", [])
        if not isinstance(keys, list) or not keys or len(keys) > 4:
            raise ValueError("Choose one to four grouping fields.")
        keys = [column(item, "grouping") for item in dict.fromkeys(keys)]
        spec["roles"]["dimensions"] = list(dict.fromkeys([*keys, *spec["roles"].get("dimensions", [])]))
        spec = ensure_report_defaults(spec)
        name = spec["drivers"].get("view") or "by_dimension"
        view = next((item for item in spec.get("views", []) if item.get("name") == name), None)
        if view is None:
            spec.setdefault("views", []).append({"name": name, "keys": keys, "measures": [spec["drivers"].get("measure", "amount")], "compare": True})
            spec["drivers"]["view"] = name
        else:
            view["keys"] = keys
    elif step == "important":
        drivers = spec.setdefault("drivers", {})
        if data.get("threshold") is not None:
            threshold = float(data["threshold"])
            if threshold < 0:
                raise ValueError("The threshold cannot be negative.")
            materiality = drivers.get("materiality") or {}
            if materiality.get("mode", "abs") != "abs" and not data.get("replace_rule"):
                raise ValueError("This setup uses a percentage threshold. Open details to change it, or confirm replacing it with a fixed amount.")
            drivers["materiality"] = {"mode": "abs", "abs": threshold}
        if data.get("top_n") is not None:
            top = int(data["top_n"])
            if not 1 <= top <= 50:
                raise ValueError("Show between 1 and 50 movements.")
            drivers["top_n"] = top
        if data.get("others_label") is not None:
            label = str(data["others_label"]).strip()[:60]
            if not label:
                raise ValueError("Give the remaining movements a label.")
            drivers["others_label"] = label
    elif step == "explain":
        profile = sanitize_style_profile(spec.get("commentary", {}).get("style_profile") or {})
        for key, allowed in (("audience", STYLE_AUDIENCES), ("length", STYLE_LENGTHS), ("tone", STYLE_TONES)):
            if key in data:
                if data[key] not in allowed:
                    raise ValueError(f"Choose a valid {key}.")
                profile[key] = data[key]
        if "structure_type" in data:
            split = data.get("split_by") or None
            if data["structure_type"] == "split":
                profile["structure"] = {"type": "split", "split_by": column(split, "split")}
            else:
                profile["structure"] = {"type": "overall", "split_by": None}
        if "instructions" in data:
            profile["instructions"] = str(data["instructions"])[:3000]
        if "objective" in data:
            profile["objective"] = str(data["objective"] or "").strip()[:300]
        if "business_context" in data:
            profile["business_context"] = str(data["business_context"] or "").strip()[:2000]
        if "include" in data:
            profile["include"] = [item for item in data["include"] if item in STYLE_INCLUDE]
        if data.get("clear_example"):
            profile["example_style"] = {"summary_of_style": "", "sample_phrases": []}
        spec.setdefault("commentary", {})["style_profile"] = profile
    else:
        raise ValueError("Choose a valid step.")
    label = {"data": "Data", "compare": "Compare", "include": "Include", "group": "Group", "important": "Important", "explain": "Explain"}[step]
    apply_spec_change(state, spec, "user", f"Changed the {label} step")
    return state


@bp.post("/journey/simple/<step>")
def simple_step(step: str) -> object:
    if step not in JOURNEY_STEPS:
        raise ValueError("Choose a valid step.")
    state = simple_update(get_project(), step, json_input())
    save_project(state)
    return jsonify(public_state(state))


@bp.get("/journey/values")
def column_values() -> object:
    """Distinct values of one column (most common first) for the Include step."""
    state = get_project()
    name = request.args.get("col", "")
    frame, _ = datasets(state)
    if name not in frame.columns or name.startswith("__"):
        raise ValueError("Choose a column from your data.")
    counts = frame[name].dropna().astype(str).value_counts()
    return jsonify({"column": name, "n_distinct": int(len(counts)), "values": [{"value": value, "rows": int(count)} for value, count in counts.head(300).items()]})


@bp.post("/journey/stop-assistant")
def stop_assistant() -> object:
    """The user stopped waiting: any answer still in flight becomes obsolete and is never applied."""
    with LOCK:
        state = get_project()
        state["spec_revision"] = int(state.get("spec_revision", 0)) + 1
        save_project(state)
    return jsonify({"revision": state["spec_revision"]})


@bp.post("/journey/step/<step>/ok")
def step_ok(step: str) -> object:
    """The user checked a step the plan flagged; clear the flag without changing settings."""
    if step not in JOURNEY_STEPS:
        raise ValueError("Choose a valid step.")
    state = get_project()
    (state.get("plan_state") or {}).get("steps", {}).pop(step, None)
    save_project(state)
    return jsonify(public_state(state))


@bp.post("/journey/stage")
def set_stage() -> object:
    """Remember where the user is so a reload returns to the same screen."""
    from agent.contracts import STAGES
    stage = json_input().get("stage")
    if stage not in STAGES:
        raise ValueError("Unknown stage.")
    state = get_project()
    state["stage"] = stage
    save_project(state)
    return jsonify({"stage": stage})


@bp.post("/sources/auto-define")
def auto_define() -> object:
    """Define every new file using the detected header row, so Simple users skip the grid."""
    state = get_project()
    errors = []
    for source in state["sources"]:
        if source.get("defined"):
            continue
        definition = source["definition"]
        try:
            grid = preview(source_path(state["project_id"], source), definition.get("sheet") or source["sheets"][0])
            definition["header_row"] = detect_header_row(grid)
            frame = load_defined(state["project_id"], source)
            source.update(defined=True, role=definition.get("role", "primary"), columns=list(frame.columns), n_rows=len(frame))
        except (ValueError, IndexError) as exc:
            errors.append(f"{source['name']}: {exc}")
    state["controls"] = []
    bind_sources(state)
    auto_map_sources(state)
    save_project(state)
    return jsonify({**public_state(state), "define_errors": errors})


@bp.post("/sources/<sid>/role")
def source_role(sid: str) -> object:
    """Change a file's type (main data, lookup, forecast) without touching its layout."""
    state, data = get_project(), json_input()
    role = data.get("role")
    if role not in ("primary", "lookup", "forecast"):
        raise ValueError("Choose main data, lookup or forecast.")
    source = next((item for item in state["sources"] if item["id"] == sid), None)
    if source is None:
        raise ValueError("Source not found in this project.")
    source["definition"]["role"] = role
    source["role"] = role
    state["controls"] = []
    bind_sources(state)
    save_project(state)
    return jsonify(public_state(state))


@bp.post("/journey/plan")
def plan() -> object:
    """Describe your flux: the assistant sets up as many steps as it can, then routes you."""
    data, state = json_input(), get_project()
    description = str(data.get("description") or "").strip()
    if not description or len(description) > 3000:
        raise ValueError("Describe your flux in 1–3,000 characters.")
    context = ui_context(state, {**data, "ui_step": "path"})
    existing = {item["id"]: item["status"] for item in public_state(state)["journey"]["steps"]}
    token = csrf_token()
    def operation():
        frame, _ = datasets(state)
        envelope = build_envelope("plan_from_description", state["spec"], frame, description, context=context, extra={"existing_step_state": existing})
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        result = apply_if_current(state["project_id"], context["spec_revision"], response)
        if not result.get("obsolete"):
            with LOCK:
                current = get_project(state["project_id"])
                states = response.get("proposal", {}).get("step_states", [])
                current["plan_state"] = {"created": now(), "summary": response.get("summary", ""), "warnings": response.get("warnings", [])[:10], "questions": response.get("questions", []),
                                         "steps": {item["step"]: {"reason": item.get("reason", ""), "question_ids": item.get("question_ids", [])} for item in states if item.get("status") == "needs_input"}}
                save_project(current)
                result["journey"] = public_state(current, token)["journey"]
        return result
    return jsonify({"job_id": start_job(state["project_id"], "Reading your description and matching it to your columns and months…", operation)}), 202


@bp.post("/journey/suggest/<step>")
def suggest_and_apply(step: str) -> object:
    """Ask the assistant to fill one step; valid suggestions apply with Undo."""
    allowed = {"data": "map_columns", "compare": "define_comparison", "group": "define_rules", "important": "define_rules"}
    if step not in allowed:
        raise ValueError("The assistant cannot suggest this step. Use the controls instead.")
    data, state = json_input(), get_project()
    context = ui_context(state, {**data, "ui_step": step})
    def operation():
        frame, _ = datasets(state)
        envelope = build_envelope(allowed[step], state["spec"], frame, "", context=context)
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        return apply_if_current(state["project_id"], context["spec_revision"], response)
    return jsonify({"job_id": start_job(state["project_id"], "Looking at your columns and months…", operation)}), 202


@bp.post("/style/extract")
def extract_style() -> object:
    """Learn the writing style of a pasted example. The example itself is never saved."""
    data, state = json_input(), get_project()
    example = str(data.get("example_text") or "").strip()
    if not example or len(example) > 6000:
        raise ValueError("Paste an example of 1–6,000 characters.")
    context = ui_context(state, {**data, "ui_step": "explain"})
    def operation():
        envelope = build_envelope("extract_commentary_style", state["spec"], None, "", context=context, extra={"example_text": example})
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        return apply_if_current(state["project_id"], context["spec_revision"], response)
    return jsonify({"job_id": start_job(state["project_id"], "Reading the style of your example (not its numbers or names)…", operation)}), 202


@bp.post("/setup/describe")
def describe_setup() -> object:
    """Suggest an editable name and description. Nothing is saved automatically."""
    data, state = json_input(), get_project()
    context = ui_context(state, {**data, "ui_step": "save"})
    def operation():
        envelope = build_envelope("describe_setup", state["spec"], None, "", context=context, extra={"existing_name": data.get("name", ""), "existing_description": data.get("description", ""), "purpose": "save"})
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        return {"suggested_name": response.get("proposal", {}).get("suggested_name", ""), "description": response.get("proposal", {}).get("description", ""), "status": response["status"], "summary": response.get("summary", "")}
    return jsonify({"job_id": start_job(state["project_id"], "Writing a name and description for this setup…", operation)}), 202
