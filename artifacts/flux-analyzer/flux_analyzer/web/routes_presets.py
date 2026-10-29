"""Preset discovery, explicit application, and versioned portable exports."""
import json
from flask import Blueprint, jsonify, request, make_response
from engine.presets import get_preset, list_presets, apply_defaults, save_preset, export_preset
from .state import get_project, save_project, public_state, apply_spec_change, source_bindings

bp = Blueprint("presets", __name__)


@bp.get("/presets")
def presets_list() -> object:
    return jsonify(list_presets())


@bp.get("/presets/<preset_id>")
def preset_detail(preset_id: str) -> object:
    preset = get_preset(preset_id)
    if preset["id"] != preset_id:
        return jsonify({"error": "Preset not found."}), 404
    from engine.describe import describe_spec
    from engine.spec import default_spec
    return jsonify({**export_preset(preset), "rule_cards": describe_spec(apply_defaults(default_spec(), preset))})


@bp.get("/presets/<preset_id>/export")
def preset_export(preset_id: str) -> object:
    preset = get_preset(preset_id)
    if preset["id"] != preset_id:
        return jsonify({"error": "Preset not found."}), 404
    response = make_response(json.dumps(export_preset(preset), ensure_ascii=False, indent=2))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{preset_id}-{preset["version"]}.json"'
    return response


@bp.post("/presets/apply")
def preset_apply() -> object:
    data, state = request.get_json(), get_project()
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with a preset ID.")
    preset = get_preset(str(data.get("id", "")))
    if preset["id"] != data.get("id"):
        raise ValueError("Choose a preset from the list.")
    candidate = apply_defaults(state["spec"], preset)
    candidate["sources"] = source_bindings(state)
    apply_spec_change(state, candidate, "preset", f"Applied {preset['name']} {preset['version']}")
    state["latest_proposal"] = None
    save_project(state)
    return jsonify(public_state(state))


@bp.post("/presets/save")
def preset_save() -> object:
    data, state = request.get_json(), get_project()
    if not isinstance(data, dict):
        raise ValueError("Send preset metadata as a JSON object.")
    preset = save_preset(
        str(data.get("id", "")),
        str(data.get("name", "")),
        str(data.get("owner", "")),
        str(data.get("description", "")),
        str(data.get("guidance", "")),
        state["spec"],
        categories=data.get("categories"),
    )
    candidate = dict(state["spec"], preset={"id": preset["id"], "version": preset["version"]})
    apply_spec_change(state, candidate, "user", f"Saved current settings as preset {preset['id']}@{preset['version']}")
    save_project(state)
    return jsonify({"preset": export_preset(preset), "state": public_state(state)})


@bp.post("/presets/import")
def preset_import() -> object:
    data = request.get_json()
    if not isinstance(data, dict):
        raise ValueError("Import a preset JSON object.")
    identifier, name = str(data.get("id", "")), str(data.get("name", ""))
    raw_defaults = data.get("defaults", {})
    if not isinstance(raw_defaults, dict):
        raise ValueError("Preset defaults must be a JSON object.")
    candidate = apply_defaults(get_project()["spec"], {
        "id": identifier,
        "name": name or identifier,
        "version": str(data.get("version", "1.0.0")),
        "defaults": raw_defaults,
    })
    # Validate imported defaults before persisting any preset files.
    preset = save_preset(
        identifier, name, str(data.get("owner", "")), str(data.get("description", "")),
        str(data.get("guidance", "")), candidate, categories=data.get("categories"),
    )
    return jsonify({"preset": export_preset(preset), "presets": list_presets()}), 201


@bp.post("/presets/rename")
def preset_rename() -> object:
    data, state = request.get_json(), get_project()
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError("Enter the new analysis name.")
    candidate = dict(state["spec"], flux_name=str(data["name"])[:120])
    apply_spec_change(state, candidate, "user", "Renamed analysis")
    save_project(state)
    return jsonify(public_state(state))
