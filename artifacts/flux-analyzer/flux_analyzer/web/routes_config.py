"""Agent suggestions, explicit approval, rule previews and reusable specs."""
import copy
import json
from pathlib import Path
import uuid
from flask import Blueprint, jsonify, request, session
from agent.steps import build_envelope, STEPS
from agent.client import invoke_agent, validate_response
from config import WORKSPACE
from engine.spec import validate_spec, save_spec, load_spec, validate_spec_against_data
from engine.presets import get_preset, apply_defaults
from engine.transform import derive, apply_scope
from engine.money import total
from engine.pipeline import preflight
from agent.proposals import proposal_to_spec, candidate_for_response
from .state import get_project, save_project, public_state, datasets, start_job, JOBS, LOCK, bind_sources, saved_specs, project_id, project_path, apply_spec_change, restore_spec_history, csrf_token, now

bp = Blueprint("configuration", __name__)

def json_input() -> dict:
    """Require JSON object inputs, not arbitrary scalar JSON."""
    value = request.get_json()
    if not isinstance(value, dict):
        raise ValueError("Send a JSON object for this action.")
    return value

def merge_proposal(spec: dict, step: str, proposal: dict) -> dict:
    """Copy only the fields owned by the confirmed wizard step."""
    return proposal_to_spec(spec, step, proposal)


def apply_agent_result(state: dict, response: dict, expected_spec: dict | None = None) -> dict:
    """Apply all valid confidence levels atomically, or leave the spec intact."""
    result = copy.deepcopy(response)
    result["applied"] = False
    before_count = len(state.get("change_log", []))
    if expected_spec is not None and state["spec"] != expected_spec:
        result.setdefault("warnings", []).append("Settings changed while this request was running. The response was not applied; retry with the latest settings.")
    else:
        candidate = candidate_for_response(state["spec"], result)
        if candidate is not None:
            reason = (result.get("summary") or result.get("proposal", {}).get("summary") or result.get("rationale") or "Applied agent configuration")[:1000]
            apply_spec_change(state, candidate, "agent", reason)
            result["applied"] = len(state.get("change_log", [])) > before_count
    if result.get("confidence") == "low":
        result.setdefault("warnings", []).append("Please check: this is a low-confidence suggestion.")
    events = state.get("change_log", [])[before_count:]
    def readable(value):
        if isinstance(value, dict):
            return "; ".join(f"{key}: {readable(item)}" for key, item in list(value.items())[:6])
        if isinstance(value, list):
            return ", ".join(readable(item) for item in value[:5]) + (f" (+{len(value)-5} more)" if len(value) > 5 else "")
        return "not set" if value is None else str(value)
    result.setdefault("summary", result.get("proposal", {}).get("summary") or result.get("rationale", ""))
    result["changes"] = [{"setting": item["path"], "from": readable(item["from"]), "to": readable(item["to"]), "reason": item["reason"]} for item in events]
    if events:
        result["patch"] = [{"op": item["op"], "path": item["path"], **({"value": item["to"]} if item["op"] != "remove" else {})} for item in events]
    state["latest_proposal"] = copy.deepcopy(result)
    state.setdefault("agent_history", []).append({"timestamp": now(), "response": copy.deepcopy(result)})
    return result


def prepare_agent_suggestion(state: dict, response: dict, expected_spec: dict | None = None) -> dict:
    """Build and validate a displayable candidate without changing saved settings."""
    preview_state = copy.deepcopy(state)
    result = apply_agent_result(preview_state, response, expected_spec)
    result["applied"] = False
    result["suggested"] = bool(preview_state["spec"] != state["spec"])
    if result["suggested"]:
        result["draft_spec"] = preview_state["spec"]
    return result


@bp.get("/state")
def state_view() -> object:
    """Retrieve all browser project state."""
    return jsonify(public_state())

@bp.post("/config/<step>/suggest")
def suggest(step: str) -> object:
    """Return immediately; only background workers call the AI Engine."""
    if step not in ("detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules"):
        raise ValueError("Choose a valid configuration step.")
    data, state = json_input(), get_project()
    token = csrf_token()
    # Dataset loading is background work too, so the request stays short.
    def operation() -> dict:
        df, _ = datasets(state)
        envelope = build_envelope(step, state["spec"], df, str(data.get("user_message", "")))
        log_dir = WORKSPACE / "runs" / f"config_{state['project_id']}"
        result = invoke_agent(envelope, log_dir=log_dir)
        with LOCK:
            current = get_project(state["project_id"])
            result = prepare_agent_suggestion(current, result, state["spec"])
        return result
    job_id = start_job(state["project_id"], {"detect_flux": "The agent is reviewing your analysis context…", "map_columns": "The agent is reviewing your columns…", "define_comparison": "The agent is reviewing your periods…", "derive_columns": "The agent is reviewing value counts…", "classify_terms": "The agent is reviewing consolidated terms…", "define_rules": "The agent is preparing editable rules…"}.get(step, "Preparing a suggestion…"), operation)
    return jsonify({"job_id": job_id}), 202

@bp.get("/jobs/<job_id>")
def job_status(job_id: str) -> object:
    """Expose only jobs belonging to this browser session."""
    with LOCK:
        job = copy.deepcopy(JOBS.get(job_id))
    if not job or job["project_id"] != project_id():
        return jsonify({"error": "Job not found. If the server restarted, please retry the action."}), 404
    job.pop("project_id", None)
    return jsonify(job)

@bp.post("/config/<step>/accept")
def accept(step: str) -> object:
    """Apply an explicitly accepted, possibly edited, schema-validated proposal."""
    state, data = get_project(), json_input()
    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("The edited suggestion must be a JSON object.")
    from agent.client import SCHEMAS
    from jsonschema import validate
    if step not in SCHEMAS or step == "write_commentary":
        raise ValueError("Unknown configuration step.")
    validate(proposal, SCHEMAS[step])
    candidate = merge_proposal(state["spec"], step, proposal)
    apply_spec_change(state, candidate, "agent", f"Accepted {step} proposal")
    if step == "classify_terms" and proposal.get("mappings"):
        mapping = {m["keyword_rule"] or m["term"]: m["category"] for m in proposal["mappings"]}
        from .state import write_json
        write_json(WORKSPACE / "specs" / "maps" / f"{state['project_id']}.json", mapping)
    state["latest_proposal"] = None
    save_project(state)
    return jsonify(public_state(state))

@bp.post("/config/update")
def update_spec() -> object:
    """Manual settings are validated by the same full FluxSpec schema."""
    data, state = json_input(), get_project()
    candidate = validate_spec(data.get("spec"))
    from .state import source_bindings
    candidate["sources"] = source_bindings(state)
    apply_spec_change(state, candidate, "user", str(data.get("reason") or "Edited settings in the configuration editor"))
    save_project(state)
    return jsonify(public_state(state))


@bp.post("/config/draft/preview")
def preview_draft() -> object:
    """Return derived UI state for an unsaved, validated settings draft."""
    from .state import source_bindings
    state, data = get_project(), json_input()
    candidate = validate_spec(data.get("spec"))
    candidate["sources"] = source_bindings(state)
    temporary = copy.deepcopy(state)
    temporary["spec"] = candidate
    temporary["controls"] = []
    return jsonify(public_state(temporary, csrf_token()))


@bp.post("/config/draft/patch")
def patch_draft() -> object:
    """Edit an uncommitted draft with the same RFC6902 validator as saved settings."""
    from engine.patches import apply_patch
    from .state import source_bindings
    state, data = get_project(), json_input()
    if data.get("base_spec") != state["spec"]:
        raise ValueError("The saved settings changed while this draft was open. Discard it and try again.")
    draft = validate_spec(data.get("draft_spec"))
    candidate = apply_patch(draft, data.get("patch"), "user", str(data.get("reason") or "Edited a suggested draft"))
    candidate["sources"] = source_bindings(state)
    temporary = copy.deepcopy(state)
    temporary["spec"] = candidate
    temporary["controls"] = []
    return jsonify(public_state(temporary, csrf_token()))


@bp.post("/config/draft/accept")
def accept_draft() -> object:
    """Atomically validate and save the complete settings draft after confirmation."""
    from .state import source_bindings
    state, data = get_project(), json_input()
    if data.get("base_spec") != state["spec"]:
        raise ValueError("The saved settings changed while this draft was open. Refresh the page and review the latest settings.")
    candidate = validate_spec(data.get("spec"))
    candidate["sources"] = source_bindings(state)
    apply_spec_change(state, candidate, "user", str(data.get("reason") or "Accepted reviewed configuration")[:1000])
    state["controls"] = []
    save_project(state)
    return jsonify(public_state(state))

@bp.post("/spec/undo")
def undo_spec() -> object:
    state = get_project()
    restore_spec_history(state, "undo")
    save_project(state)
    return jsonify(public_state(state))

@bp.post("/spec/redo")
def redo_spec() -> object:
    state = get_project()
    restore_spec_history(state, "redo")
    save_project(state)
    return jsonify(public_state(state))


@bp.post("/spec/patch")
def patch_spec() -> object:
    from engine.patches import apply_patch
    data, state = json_input(), get_project()
    reason = str(data.get("reason") or "Edited a rule card")[:1000]
    candidate = apply_patch(state["spec"], data.get("patch"), "user", reason)
    apply_spec_change(state, candidate, "user", reason)
    save_project(state)
    return jsonify(public_state(state))


def ui_context(state: dict, data: dict) -> dict:
    """Request context captured when a job starts; used to reject stale results."""
    return {"spec_revision": int(state.get("spec_revision", 0)), "source_profile_id": ",".join(sorted(source["id"] for source in state.get("sources", []) if source.get("defined")))[:500], "run_id": data.get("run_id"), "ui_step": str(data.get("ui_step") or "review"), "mode": data.get("mode") or "simple", "locale": "en-GB"}


def apply_if_current(pid: str, started_revision: int, response: dict) -> dict:
    """Apply a validated response only if nothing changed while the AI worked."""
    with LOCK:
        current = get_project(pid)
        if int(current.get("spec_revision", 0)) != started_revision:
            result = copy.deepcopy(response)
            result.update(applied=False, obsolete=True, changes=[])
            result.setdefault("warnings", []).append("Your setup changed while the assistant was working, so this answer was not applied. Send the request again to use the latest setup.")
            return result
        result = apply_agent_result(current, response)
        result["revision"] = int(current.get("spec_revision", 0))
        result["undo_available"] = bool(result["applied"])
        save_project(current)
    return result


@bp.post("/instruction")
def instruction() -> object:
    """Auto-apply a validated, permitted change with a summary and Undo."""
    data, state = json_input(), get_project()
    message = str(data.get("instruction") or "").strip()
    if not message or len(message) > 3000:
        raise ValueError("Describe the change in 1–3,000 characters.")
    target = data.get("target_step") if data.get("target_step") in ("data", "compare", "include", "group", "important", "explain") else None
    context = ui_context(state, data)
    def operation():
        import pandas as pd
        frame = datasets(state)[0] if any(item.get("defined") and item.get("role") != "lookup" for item in state["sources"]) else pd.DataFrame()
        envelope = build_envelope("apply_instruction", state["spec"], frame, message, context=context, extra={"target_step": target})
        envelope["payload"]["target"] = str(data.get("target") or "")[:200]
        envelope["payload"]["available_columns"] = [column for column in frame if not str(column).startswith("__")]
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        return apply_if_current(state["project_id"], context["spec_revision"], response)
    return jsonify({"job_id": start_job(state["project_id"], "Reading your request and checking it against your data…", operation)}), 202


@bp.post("/questions")
def answer_question() -> object:
    import re
    data, state = json_input(), get_project()
    question = str(data.get("question") or "").strip()
    if not question or len(question) > 1000:
        raise ValueError("Ask a question in 1–1,000 characters.")
    evidence = None
    if data.get("run_id"):
        from .routes_run import read_run
        evidence = read_run(state, str(data["run_id"]))["evidence"]
    def operation():
        envelope = build_envelope("answer_question", state["spec"], user_message=question, evidence=evidence)
        response = invoke_agent(envelope, log_dir=WORKSPACE / "runs" / f"config_{state['project_id']}")
        text = response.get("proposal", {}).get("answer", "")
        allowed = {value.replace(",", "") for value in re.findall(r"(?<!\w)\d+(?:[.,]\d+)*", json.dumps(envelope))}
        numbers = {value.replace(",", "") for value in re.findall(r"(?<!\w)\d+(?:[.,]\d+)*", text)}
        if numbers - allowed:
            raise ValueError("The answer included unsupported numbers. Review the local evidence and rules instead.")
        with LOCK:
            current = get_project(state["project_id"])
            current.setdefault("agent_history", []).append({"timestamp": now(), "response": response})
            current["last_answer"] = {**response, "question": question, "timestamp": now()}
            save_project(current)
        return response
    return jsonify({"job_id": start_job(state["project_id"], "Answering from the current spec and evidence…", operation)}), 202


@bp.post("/classification/preview")
def classification_preview() -> object:
    from engine.v2rules import apply_classification, apply_value_rules
    from engine.joins import apply_source_joins
    state = get_project()
    frame, lookups = datasets(state)
    spec = copy.deepcopy(state["spec"])
    frame = apply_value_rules(derive(frame, spec.get("derive", [])), spec)
    frame, _ = apply_source_joins(frame, spec.get("joins", []), lookups)
    frame = apply_classification(frame, spec.get("classification"), spec["roles"])
    frame = apply_scope(frame, spec.get("scope", []))
    frame = apply_classification(frame, spec.get("classification"), spec["roles"])
    return jsonify({"stats": frame.attrs.get("classification", {}), "rows": frame.attrs.get("classification_review", [])})

@bp.post("/config/preview/<section>")
def preview_rules(section: str) -> object:
    """Run accepted transforms locally and expose grouped preview totals."""
    if section not in ("scope", "derive", "joins", "value_rules"):
        raise ValueError("Choose scope, derived columns, value rules or joins.")
    state = get_project()
    from engine.v2rules import apply_value_rules, apply_classification
    from engine.joins import apply_source_joins
    spec = copy.deepcopy(state["spec"])
    frame, lookups = datasets(state)
    frame = apply_value_rules(derive(frame, spec.get("derive", [])), spec)
    original_count, original_value = len(frame), total(frame["__flux_value"])
    frame, audit = apply_source_joins(frame, spec.get("joins", []), lookups)
    frame = apply_classification(frame, spec.get("classification"), spec["roles"])
    frame = apply_scope(frame, spec.get("scope", []))
    value = "__flux_value"
    rows = []
    names = [d["name"] for d in state["spec"].get("derive", [])]
    for col in names:
        for val, group in frame.groupby(col, dropna=False):
            rows.append({"column": col, "value": str(val), "count": len(group), "total": total(group[value]) if value else None})
    if not names:
        rows.append({"value": "Selected rows", "count": len(frame), "total": total(frame[value]) if value else None})
    if section == "joins":
        rows = [{"column": item["lookup"], "value": "Unmatched lookup records", "count": item.get("unmatched_rows", 0), "total": item.get("unmatched_value", 0)} for item in audit]
    return jsonify({"n_rows": len(frame), "columns": list(frame.columns), "totals": rows[:100], "excluded_rows": original_count - len(frame), "excluded_value": original_value - total(frame[value]), "join_audit": audit})

@bp.post("/review/controls")
def review_controls() -> object:
    """Run deterministic controls and preserve clear stop reasons."""
    state = get_project()
    try:
        frame, lookups = datasets(state)
        controls = preflight(frame, state["spec"], lookups)
    except (ValueError, KeyError) as exc:
        controls = [{"id": "configuration_ready", "status": "stop", "message": str(exc), "details": {}}]
    state["controls"] = controls
    save_project(state)
    return jsonify({"controls": controls})

@bp.get("/specs")
def list_specs() -> object:
    """List local reusable configurations."""
    return jsonify(saved_specs())

@bp.post("/specs/save")
def save_configuration() -> object:
    """Save the current spec with a user-provided name."""
    state, data = get_project(), json_input()
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 120:
        raise ValueError("Enter a configuration name with 1–120 characters.")
    candidate = copy.deepcopy(state["spec"])
    candidate["flux_name"] = name
    apply_spec_change(state, candidate, "user", "Renamed FluxSpec")
    bind_sources(state)
    save_spec(state["spec"], WORKSPACE / "specs", name)
    save_project(state)
    return jsonify(public_state(state))

def apply_saved(state: dict, spec: dict) -> dict:
    """Rebind the spec to active files and identify missing/renamed columns."""
    candidate = validate_spec(spec)
    apply_spec_change(state, candidate, "preset", "Loaded a saved FluxSpec")
    bind_sources(state)
    try:
        frame, _ = datasets(state)
        missing = validate_spec_against_data(spec, list(frame.columns))
    except ValueError:
        missing = ["Primary data source (upload and define it first)"]
    state["controls"], state["latest_proposal"] = [], None
    state["step"] = "columns" if missing else "review"
    save_project(state)
    return {**public_state(state), "missing_columns": missing}

@bp.post("/specs/load")
def load_configuration() -> object:
    """Load a selected basename only, not an arbitrary server file."""
    state, data = get_project(), json_input()
    name = str(data.get("file", ""))
    if Path(name).name != name or not name.endswith(".json"):
        raise ValueError("Choose a saved configuration from the list.")
    path = WORKSPACE / "specs" / name
    if not path.is_file():
        raise ValueError("That saved configuration could not be found.")
    return jsonify(apply_saved(state, load_spec(path)))

@bp.post("/specs/import")
def import_configuration() -> object:
    """Import plain JSON only and validate before accepting."""
    return jsonify(apply_saved(get_project(), json_input().get("spec")))

@bp.post("/project/new")
def new_project() -> object:
    """Switch browser projects without deleting any historical outputs."""
    session["project_id"] = uuid.uuid4().hex
    return jsonify(public_state(get_project()))
