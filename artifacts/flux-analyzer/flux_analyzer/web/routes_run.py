"""Async deterministic runs, validated commentary, audit and downloads."""
import copy
import json
from pathlib import Path
import uuid
from flask import Blueprint, jsonify, request, render_template, send_file
from config import WORKSPACE, AGENT_MOCK
from engine.pipeline import execute
from engine.excel_pack import render_excel
from engine.audit import stamp_run
from engine.narrative_check import check_narrative
from agent.client import invoke_agent
from agent.steps import build_envelope
from .state import get_project, save_project, public_state, datasets, start_job, now, write_json, LOCK, apply_spec_change, source_bindings

bp = Blueprint("runs", __name__)

def run_path(state: dict, run_id: str) -> Path:
    """Authorize every result/download using the active project's run list."""
    if not any(r["id"] == run_id for r in state["runs"]):
        raise ValueError("This run was not found in your project.")
    return WORKSPACE / "runs" / run_id

def read_run(state: dict, run_id: str) -> dict:
    """Read a completed, owned result."""
    return json.loads((run_path(state, run_id) / "result.json").read_text())

def narrative(run: dict, directory: Path, driver_id: str | None = None) -> dict:
    """Validate narrative evidence with one content repair attempt."""
    evidence = copy.deepcopy(run["evidence"])
    if driver_id:
        evidence["drivers"] = [driver for driver in evidence["drivers"] if driver["driver_id"] == driver_id]
        if not evidence["drivers"]:
            raise ValueError("Driver not found in this run.")
    envelope = build_envelope("write_commentary", run["spec"], evidence=evidence)
    result, checked = None, None
    for attempt in range(2):
        result = invoke_agent(envelope, log_dir=directory)
        checked = check_narrative(result, evidence)
        if checked["ok"]:
            break
        envelope["user_message"] = "Correct these narrative issues; copy only the provided evidence: " + "; ".join(checked["issues"])
        envelope["request_id"] = str(uuid.uuid4())
    return {"envelope": result, "validation": checked}

def narrative_text(response: dict) -> str:
    """Join a verified response without inventing any amounts or explanations."""
    proposal = response["proposal"]
    return "\n\n".join(filter(None, [proposal.get("headline", ""), *[line["text"] for line in proposal.get("lines", [])], proposal.get("others_summary", "")]))

@bp.post("/run")
def run_flux() -> object:
    """Queue a run; all control stops block release and no request blocks."""
    state = get_project()
    run_id = uuid.uuid4().hex
    def operation() -> dict:
        directory = WORKSPACE / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        frame, lookups = datasets(state)
        spec = copy.deepcopy(state["spec"])
        spec.pop("run_stamp", None)
        result = execute(frame, spec, lookups)
        result.update(id=run_id, created=now())
        from agent.writing_context import attach
        attach(result["evidence"], spec)
        from engine.pipeline import prepare
        from engine.excel_pack import build_export_data
        prepared, resolved, comparison = prepare(frame, spec, lookups)
        result["export_data"] = build_export_data(prepared, resolved, comparison, result)
        result["run_stamp"] = stamp_run(run_id, result["created"], spec, state["sources"], WORKSPACE / "uploads" / state["project_id"])
        result["change_log"] = copy.deepcopy(state.get("change_log", []))
        result["agent_logs"] = copy.deepcopy(state.get("agent_history", []))
        config_log = WORKSPACE / "runs" / f"config_{state['project_id']}" / "agent_log.jsonl"
        if config_log.exists():
            result["agent_logs"].extend({"transport_attempt": json.loads(line)} for line in config_log.read_text().splitlines() if line.strip())
        tag = result["evidence"]["commentary_rules"].get("verify_tag", "[TO VERIFY]")
        lines = [{"driver_id": driver["driver_id"], "text": f"{driver['delta_fmt']} — {driver['label']}. {tag} Confirm the business cause."} for driver in result["drivers"]]
        proposal = {"lines": lines, "headline": result["evidence"].get("headline_hint") or "", "others_summary": ""}
        validation = check_narrative(proposal, result["evidence"])
        result["commentary"] = {"text": narrative_text({"proposal": proposal}), "lines": lines, "headline": proposal["headline"], "issues": validation["issues"], "validation": validation, "verified": validation["ok"], "mock": AGENT_MOCK, "source": "deterministic_evidence"}
        write_json(directory / "result.json", result)
        write_json(directory / "spec.json", {**spec, "run_stamp": result["run_stamp"]})
        write_json(directory / "audit.json", {key: result[key] for key in ("run_stamp", "change_log", "agent_logs")})
        render_excel(result, directory)
        with LOCK:
            current = get_project(state["project_id"])
            current["runs"].insert(0, {"id": run_id, "name": result["name"], "created": result["created"], "status": "complete", "delta": result["delta"], "run_stamp": result["run_stamp"]})
            current["result"] = {key: value for key, value in result.items() if key != "export_data"}
            current["step"] = "results"
            current["stage"] = "results"
            save_project(current)
        return {"run_id": run_id}
    job_id = start_job(state["project_id"], "Running controls, calculating movements, and reconciling every driver…", operation)
    return jsonify({"job_id": job_id}), 202

@bp.get("/results/<run_id>")
def results(run_id: str) -> object:
    """Serve JSON to Alpine or render the Jinja results page directly."""
    state = get_project()
    result = read_run(state, run_id)
    if request.args.get("format") == "json":
        # Drills/evidence remain on the backend until explicitly requested.
        from engine.explanations import explanation_items, counts
        items = explanation_items(result)
        payload = {k: v for k, v in result.items() if k not in ("drills", "evidence", "export_data")}
        payload.update(explanations=items, explanation_counts=counts(items))
        return jsonify(payload)
    state["result"] = {key: value for key, value in result.items() if key != "export_data"}
    return render_template("index.html", initial=public_state(state), step="results", stage="results")

@bp.get("/results/<run_id>/drill/<driver_id>")
def drill_evidence(run_id: str, driver_id: str) -> object:
    """Return locally calculated consolidated evidence for one driver."""
    run = read_run(get_project(), run_id)
    if driver_id not in run["drills"]:
        raise ValueError("Driver evidence not found.")
    return jsonify(run["drills"][driver_id])

@bp.post("/results/<run_id>/narrative")
def propose_narrative(run_id: str) -> object:
    """Generate only a proposal; no commentary is silently replaced."""
    state = get_project()
    run = read_run(state, run_id)
    driver_id = (request.get_json(silent=True) or {}).get("driver_id")
    directory = run_path(state, run_id)
    def operation() -> dict:
        result = narrative(run, directory, driver_id)
        response = {**result["envelope"], "validation": result["validation"]}
        from engine.explanations import protected_ids
        protected = protected_ids(run)
        previous = run.get("commentary", {}).get("lines", [])
        if driver_id:
            replacement = {line["driver_id"]: line for line in response.get("proposal", {}).get("lines", [])}
            response["proposal"]["lines"] = [replacement.get(line["driver_id"], line) for line in previous]
            response["proposal"]["headline"] = run.get("commentary", {}).get("headline", "")
            from engine.explanations import protected_ids as people
            response["validation"] = check_narrative(response, run["evidence"], people=people(run) | ({line["driver_id"] for line in previous} - {driver_id} if run.get("commentary", {}).get("source") == "analyst_edited" else set()))
        response["applied"] = False
        replacements = []
        if response["validation"]["ok"] and protected:
            # Text a person wrote or confirmed stays; the AI draft is only offered as a preview.
            kept = {line["driver_id"]: line for line in previous}
            lines = []
            for line in response["proposal"]["lines"]:
                if line["driver_id"] in protected and line["driver_id"] in kept:
                    if kept[line["driver_id"]].get("text") != line.get("text"):
                        replacements.append({"driver_id": line["driver_id"], "text": line.get("text", "")})
                    lines.append(kept[line["driver_id"]])
                else:
                    lines.append(line)
            response["proposal"]["lines"] = lines
        if response["validation"]["ok"]:
            with LOCK:
                current_run = read_run(state, run_id)
                if current_run.get("commentary") == run.get("commentary"):
                    current_run["commentary"] = {"text": narrative_text(response), "lines": response["proposal"]["lines"], "headline": response["proposal"].get("headline", ""), "validation": response["validation"], "issues": [], "verified": True, "source": "agent", "mock": AGENT_MOCK, "pending_replacements": replacements}
                    current_run.setdefault("agent_logs", []).append({"timestamp": now(), "response": response})
                    write_json(directory / "result.json", current_run)
                    current = get_project(state["project_id"])
                    if (current.get("result") or {}).get("id") == run_id:
                        current["result"] = {key: value for key, value in current_run.items() if key != "export_data"}
                        save_project(current)
                    response["applied"] = True
                else:
                    response.setdefault("warnings", []).append("Commentary changed while the draft was generated; it was not replaced.")
        write_json(directory / "narrative_proposal.json", response)
        return response
    job_id = start_job(state["project_id"], "The agent is drafting commentary from checked evidence…", operation)
    return jsonify({"job_id": job_id}), 202

@bp.post("/results/<run_id>/commentary")
def save_commentary(run_id: str) -> object:
    """Persist analyst edits and keep visible provenance of manual changes."""
    state = get_project()
    run = read_run(state, run_id)
    data = request.get_json()
    text = str(data.get("text", ""))
    if len(text) > 100000:
        raise ValueError("Commentary is too long; keep it under 100,000 characters.")
    lines = data.get("lines")
    if lines is not None and (not isinstance(lines, list) or any(not isinstance(line, dict) or not isinstance(line.get("text"), str) or not isinstance(line.get("driver_id"), str) for line in lines)):
        raise ValueError("Provide commentary lines with driver_id and text.")
    proposal = {"lines": lines or [], "headline": run.get("commentary", {}).get("headline", ""), "others_summary": ""}
    validation = check_narrative(proposal, run["evidence"], author="person") if lines is not None else {"ok": False, "issues": ["Free-text commentary has no aligned driver lines."], "line_results": []}
    if lines is not None:
        text = narrative_text({"proposal": proposal})
    run["commentary"] = {"text": text, "lines": lines or [], "headline": proposal["headline"], "validation": validation, "issues": validation["issues"] + ["Analyst-edited commentary: review business claims before distribution."], "verified": False, "mock": AGENT_MOCK, "source": "analyst_edited"}
    edited = {line["driver_id"]: line["text"] for line in lines or []}
    for reviewed in list(run.get("reviews", {})):
        if edited.get(reviewed) != run["reviews"][reviewed].get("text"):
            # Free-text edits replace a confirmed explanation; it needs confirming again.
            run["reviews"].pop(reviewed)
    run.setdefault("commentary_log", []).append({"timestamp": now(), "actor": "user", "text": text, "validation": validation})
    directory = run_path(state, run_id)
    write_json(directory / "result.json", run)
    if (state.get("result") or {}).get("id") == run_id:
        state["result"] = {key: value for key, value in run.items() if key != "export_data"}
        save_project(state)
    return jsonify({"ok": True, "commentary": run["commentary"], "validation": validation})


def _store_run(state: dict, run_id: str, run: dict) -> None:
    write_json(run_path(state, run_id) / "result.json", run)
    if (state.get("result") or {}).get("id") == run_id:
        state["result"] = {key: value for key, value in run.items() if key != "export_data"}
        save_project(state)


def _explanations_payload(run: dict) -> dict:
    from engine.explanations import explanation_items, counts
    items = explanation_items(run)
    return {"explanations": items, "explanation_counts": counts(items), "commentary": run.get("commentary", {})}


@bp.post("/results/<run_id>/explanations/confirm-all")
def confirm_all_explanations(run_id: str) -> object:
    """Confirm every valid AI draft still awaiting review. Needs-explanation items are untouched."""
    from engine.explanations import explanation_items, record_review
    state, data = get_project(), request.get_json(silent=True) or {}
    actor = str(data.get("confirmed_by") or "").strip()
    with LOCK:
        run = read_run(state, run_id)
        targets = [item for item in explanation_items(run) if item["status"] == "ai_review" and (not data.get("driver_ids") or item["driver_id"] in data["driver_ids"])]
        for item in targets:
            record_review(run, item["driver_id"], item["text"], actor, confirm=True)
        _store_run(state, run_id, run)
    return jsonify({**_explanations_payload(run), "confirmed": len(targets)})


@bp.post("/results/<run_id>/explanations/<driver_id>")
def review_explanation(run_id: str, driver_id: str) -> object:
    """A person saves and/or confirms one explanation; AI can never call this."""
    from engine.explanations import explanation_items, record_review
    state, data = get_project(), request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("save", "confirm", "use_ai_draft"):
        raise ValueError("Choose save, confirm or use the AI draft.")
    with LOCK:
        run = read_run(state, run_id)
        current = next((item for item in explanation_items(run) if item["driver_id"] == driver_id), None)
        if current is None:
            raise ValueError("This movement is not part of the report.")
        actor = str(data.get("confirmed_by") or "")
        if action == "use_ai_draft":
            if not current.get("pending_replacement"):
                raise ValueError("There is no newer AI draft for this movement.")
            record_review(run, driver_id, current["pending_replacement"], actor, confirm=False)
        else:
            text = str(data["text"]) if data.get("text") is not None else current["text"]
            tag = run["evidence"].get("commentary_rules", {}).get("verify_tag", "[TO VERIFY]")
            from engine.explanations import check_line
            valid = check_line(run, driver_id, text.strip())["ok"] and tag not in text if text.strip() else False
            # Saving valid text you wrote is a confirmation; otherwise it is kept as a draft that still needs work.
            record_review(run, driver_id, text, actor, confirm=action == "confirm" or (valid and bool(actor.strip())))
        _store_run(state, run_id, run)
    return jsonify(_explanations_payload(run))


@bp.post("/runs/<run_id>/reuse")
def reuse_run(run_id: str) -> object:
    from engine.mapping import remap_columns
    state = get_project()
    spec = copy.deepcopy(read_run(state, run_id)["spec"])
    spec.pop("run_stamp", None)
    spec["sources"] = source_bindings(state)
    if any(source.get("defined") and source.get("role") != "lookup" for source in state["sources"]):
        frame, _ = datasets(state)
        spec, _, state["mapping_warnings"] = remap_columns(spec, list(frame.columns))
    apply_spec_change(state, spec, "user", f"Reused saved settings from run {run_id}")
    state["step"] = "review"
    save_project(state)
    return jsonify(public_state(state))

@bp.get("/download/<run_id>/<kind>")
def download(run_id: str, kind: str) -> object:
    """Build owned exports from current commentary and audited run data."""
    state = get_project()
    directory = run_path(state, run_id)
    run = read_run(state, run_id)
    if kind == "excel":
        path = render_excel(run, directory)
    elif kind == "spec":
        path = directory / "spec.json"
        write_json(path, {**run["spec"], "run_stamp": run.get("run_stamp", {})})
    elif kind in ("docx", "markdown"):
        raise ValueError("Word and Markdown downloads have been retired. The Excel review pack now carries the commentary, its status and the audit trail.")
    else:
        raise ValueError("Choose the Excel review pack or the setup file (FluxSpec JSON).")
    return send_file(path, as_attachment=True, download_name=path.name)
