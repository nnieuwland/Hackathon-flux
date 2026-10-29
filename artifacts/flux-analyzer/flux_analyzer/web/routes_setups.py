"""Shared, versioned saved setups.

A setup is a named FluxSpec without file bindings, run stamps or pasted
examples. Every save of an existing setup creates a new version; older
versions stay readable and loadable. Writes use optimistic version checks so
two people saving at once cannot silently overwrite each other.
"""
import copy
import json
import re
import threading
import uuid
from flask import Blueprint, jsonify, request, Response
from config import WORKSPACE
from engine.spec import validate_spec
from engine.describe import describe_spec
from .routes_config import json_input
from .state import get_project, save_project, public_state, write_json, apply_spec_change, bind_sources, datasets, now

bp = Blueprint("setups", __name__)
SETUP_LOCK = threading.Lock()
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def setups_dir():
    directory = WORKSPACE / "setups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def setup_path(setup_id: str):
    if not ID_PATTERN.fullmatch(str(setup_id)):
        raise ValueError("Saved setup not found.")
    return setups_dir() / f"{setup_id}.json"


def read_setup(setup_id: str) -> dict:
    path = setup_path(setup_id)
    if not path.is_file():
        raise ValueError("Saved setup not found. It may have been deleted.")
    return json.loads(path.read_text())


def portable_spec(spec: dict) -> dict:
    """Strip anything tied to one person's files or one run."""
    output = validate_spec(copy.deepcopy(spec))
    output["sources"] = {}
    output.pop("run_stamp", None)
    return validate_spec(output)


def _text(value, label: str, limit: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"Enter a {label}.")
    if len(text) > limit:
        raise ValueError(f"Keep the {label} under {limit} characters.")
    return text


def summary(record: dict) -> dict:
    """List-view metadata; specs stay on the server until a version is loaded."""
    latest = record["versions"][-1]
    return {"id": record["id"], "name": record["name"], "description": latest.get("description", ""), "current_version": record["current_version"],
            "created_at": record["created_at"], "created_by": record.get("created_by", ""), "updated_at": record["updated_at"], "updated_by": record.get("updated_by", ""),
            "flux_name": latest["spec"].get("flux_name"), "versions": [{key: item.get(key) for key in ("version", "saved_at", "saved_by", "note", "description")} for item in record["versions"]]}


def all_setups() -> list[dict]:
    records = []
    for path in setups_dir().glob("*.json"):
        try:
            records.append(summary(json.loads(path.read_text())))
        except (ValueError, KeyError, IndexError):
            continue
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)


def _name_taken(name: str, except_id: str | None = None) -> bool:
    return any(item["name"].casefold() == name.casefold() and item["id"] != except_id for item in all_setups())


def create_setup(name: str, description: str, saved_by: str, spec: dict, note: str = "First version") -> dict:
    with SETUP_LOCK:
        if _name_taken(name):
            raise ValueError(f"A saved setup called '{name}' already exists. Save a new version of it, or choose another name.")
        timestamp = now()
        record = {"id": uuid.uuid4().hex, "name": name, "created_at": timestamp, "created_by": saved_by, "updated_at": timestamp, "updated_by": saved_by, "current_version": 1,
                  "versions": [{"version": 1, "saved_at": timestamp, "saved_by": saved_by, "note": note, "description": description, "spec": portable_spec(spec)}]}
        write_json(setup_path(record["id"]), record)
    return record


@bp.get("/setups")
def list_setups() -> object:
    return jsonify(all_setups())


@bp.get("/setups/<setup_id>")
def get_setup(setup_id: str) -> object:
    record = read_setup(setup_id)
    version = int(request.args.get("version") or record["current_version"])
    selected = next((item for item in record["versions"] if item["version"] == version), None)
    if selected is None:
        raise ValueError("That version does not exist.")
    return jsonify({**summary(record), "selected_version": version, "rule_descriptions": [card["sentence"] for card in describe_spec(selected["spec"])]})


@bp.post("/setups")
def save_new_setup() -> object:
    data, state = json_input(), get_project()
    record = create_setup(_text(data.get("name"), "name", 120), _text(data.get("description"), "description", 1000, False), _text(data.get("saved_by"), "your name", 80, False) or "Unnamed", state["spec"])
    state["loaded_setup"] = {"id": record["id"], "name": record["name"], "version": 1}
    save_project(state)
    return jsonify({"setup": summary(record), "setups": all_setups(), "state": public_state(state)})


@bp.post("/setups/<setup_id>/versions")
def save_version(setup_id: str) -> object:
    """Append a version; refuse if someone else saved since you loaded it."""
    data, state = json_input(), get_project()
    with SETUP_LOCK:
        record = read_setup(setup_id)
        expected = data.get("expected_version")
        if expected is None or int(expected) != record["current_version"]:
            raise ValueError(f"'{record['name']}' was updated to version {record['current_version']} by {record.get('updated_by') or 'someone else'} since you loaded it. Load the latest version first, or save yours as a new setup.")
        saved_by = _text(data.get("saved_by"), "your name", 80, False) or "Unnamed"
        version = record["current_version"] + 1
        description = _text(data.get("description", record["versions"][-1].get("description", "")), "description", 1000, False)
        record["versions"].append({"version": version, "saved_at": now(), "saved_by": saved_by, "note": _text(data.get("note"), "change note", 300, False), "description": description, "spec": portable_spec(state["spec"])})
        record.update(current_version=version, updated_at=now(), updated_by=saved_by)
        write_json(setup_path(setup_id), record)
    state["loaded_setup"] = {"id": setup_id, "name": record["name"], "version": version}
    save_project(state)
    return jsonify({"setup": summary(record), "setups": all_setups(), "state": public_state(state)})


@bp.post("/setups/<setup_id>/rename")
def rename_setup(setup_id: str) -> object:
    data = json_input()
    name = _text(data.get("name"), "name", 120)
    with SETUP_LOCK:
        record = read_setup(setup_id)
        if _name_taken(name, setup_id):
            raise ValueError(f"A saved setup called '{name}' already exists.")
        record.update(name=name, updated_at=now())
        write_json(setup_path(setup_id), record)
    return jsonify({"setup": summary(record), "setups": all_setups()})


@bp.post("/setups/<setup_id>/duplicate")
def duplicate_setup(setup_id: str) -> object:
    data = json_input()
    source = read_setup(setup_id)
    latest = source["versions"][-1]
    name = _text(data.get("name") or f"{source['name']} (copy)", "name", 120)
    record = create_setup(name, latest.get("description", ""), _text(data.get("saved_by"), "your name", 80, False) or "Unnamed", latest["spec"], f"Copied from {source['name']} version {source['current_version']}")
    return jsonify({"setup": summary(record), "setups": all_setups()})


@bp.delete("/setups/<setup_id>")
def delete_setup(setup_id: str) -> object:
    """Deletion is explicit: the request must repeat the setup's name."""
    data = request.get_json(silent=True) or {}
    with SETUP_LOCK:
        record = read_setup(setup_id)
        if str(data.get("confirm_name", "")).strip() != record["name"]:
            raise ValueError("Type the setup's exact name to confirm deleting it.")
        setup_path(setup_id).unlink()
    return jsonify({"setups": all_setups()})


@bp.post("/setups/<setup_id>/load")
def load_setup(setup_id: str) -> object:
    """Apply a version to the current files, mapping renamed columns where unambiguous."""
    from engine.mapping import remap_columns
    data, state = json_input(), get_project()
    record = read_setup(setup_id)
    version = int(data.get("version") or record["current_version"])
    selected = next((item for item in record["versions"] if item["version"] == version), None)
    if selected is None:
        raise ValueError("That version does not exist.")
    candidate = validate_spec(copy.deepcopy(selected["spec"]))
    candidate["sources"] = state["spec"].get("sources", {})
    renamed, unresolved = {}, []
    if any(item.get("defined") and item.get("role") != "lookup" for item in state["sources"]):
        frame, _ = datasets(state)
        candidate, renamed, unresolved = remap_columns(candidate, [str(column) for column in frame.columns])
    apply_spec_change(state, candidate, "preset", f"Loaded saved setup '{record['name']}' version {version}")
    bind_sources(state)
    state["mapping_warnings"] = unresolved
    state["loaded_setup"] = {"id": setup_id, "name": record["name"], "version": version}
    state["plan_state"] = None
    save_project(state)
    return jsonify({**public_state(state), "renamed_columns": renamed, "missing_columns": unresolved})


@bp.get("/setups/<setup_id>/export")
def export_setup(setup_id: str) -> object:
    record = read_setup(setup_id)
    version = int(request.args.get("version") or record["current_version"])
    selected = next((item for item in record["versions"] if item["version"] == version), None)
    if selected is None:
        raise ValueError("That version does not exist.")
    body = {"format": "flux-saved-setup", "name": record["name"], "description": selected.get("description", ""), "version": version, "saved_by": selected.get("saved_by"), "saved_at": selected.get("saved_at"), "spec": selected["spec"]}
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", record["name"])[:60] or "setup"
    return Response(json.dumps(body, indent=2), mimetype="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}_v{version}.json"'})


@bp.post("/setups/import")
def import_setup() -> object:
    """Accept an exported setup or a bare FluxSpec; always validated before saving."""
    data = json_input()
    payload = data.get("setup")
    if not isinstance(payload, dict):
        raise ValueError("Choose a setup file exported from Flux Analyzer.")
    spec = payload.get("spec") if payload.get("format") == "flux-saved-setup" else payload
    name = _text(data.get("name") or payload.get("name") or spec.get("flux_name"), "name", 120)
    record = create_setup(name, _text(payload.get("description"), "description", 1000, False), _text(data.get("saved_by"), "your name", 80, False) or "Unnamed", spec, "Imported")
    return jsonify({"setup": summary(record), "setups": all_setups()})
