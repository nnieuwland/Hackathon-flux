import json

from engine.spec import default_spec
import engine.presets as presets
from engine.presets import agent_payload, apply_defaults, export_preset, get_preset, list_presets, save_preset
from app import create_app


def test_builtin_presets_are_data_only_and_apply_valid_defaults() -> None:
    catalog = {item["id"] for item in list_presets()}
    assert {"generic_flux", "rm_flux", "benefits_flux", "opex_flux"} <= catalog
    spec = default_spec()
    for preset_id in ("generic_flux", "rm_flux", "benefits_flux", "opex_flux"):
        preset = get_preset(preset_id)
        configured = apply_defaults(spec, preset)
        assert configured["preset"]["id"] == preset_id
        assert configured["spec_version"] == "2.0"
    assert spec == default_spec()


def test_agent_receives_step_specific_preset_guidance() -> None:
    preset = get_preset("rm_flux")
    rules = agent_payload(preset, "define_rules")
    classification = agent_payload(preset, "classify_terms")
    assert rules["id"] == "rm_flux" and rules["guidance"]
    assert "drivers" in rules["defaults"] and "roles" not in rules["defaults"]
    assert classification["categories"] and "drivers" not in classification["defaults"]
    assert len(rules["guidance"].split()) <= 800


def test_user_preset_export_import_and_versioning(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(presets, "WORKSPACE", tmp_path)
    source = save_preset(
        "team_costs", "Team costs", "Finance", "Cost review",
        "Confirm the period and sign convention.", default_spec(),
        categories=["Facilities", "Travel"],
    )
    exported = export_preset(source)
    assert exported["guidance"] == "Confirm the period and sign convention."
    assert exported["categories"] == ["Facilities", "Travel"]
    manifest = json.loads((tmp_path / "presets/team_costs/1.0.0/preset.json").read_text())
    assert manifest["owner"] == "Finance" and manifest["updated_at"]

    second = save_preset(
        "team_costs", "Team costs", "Finance", "Cost review",
        "Use the updated rule.", default_spec(),
    )
    assert second["version"] == "1.0.1"
    assert get_preset("team_costs")["guidance"] == "Use the updated rule."
    assert get_preset("generic_flux")["id"] == "generic_flux"


def test_preset_api_apply_export_and_undo() -> None:
    client = create_app({"TESTING": True, "SECRET_KEY": "preset-test-only"}).test_client()
    client.get("/")
    state = client.get("/state").get_json()
    headers = {"X-CSRF-Token": state["csrf_token"]}
    applied = client.post("/presets/apply", json={"id": "rm_flux"}, headers=headers)
    assert applied.status_code == 200
    state = applied.get_json()
    assert state["spec"]["preset"]["id"] == "rm_flux" and state["can_undo"]
    exported = client.get("/presets/rm_flux/export")
    assert exported.status_code == 200
    assert exported.get_json()["guidance"].startswith("# Repairs and maintenance")
    undone = client.post("/spec/undo", json={}, headers=headers)
    assert undone.status_code == 200 and undone.get_json()["spec"]["preset"]["id"] == "generic_flux"


def test_rm_preset_golden_fixture_end_to_end(golden):
    from engine.pipeline import execute
    import pandas as pd
    frame = golden.copy()
    frame["Account"] = "54100"
    frame["Po_Number"] = frame["Base_PO"]
    frame["FAH_Event_Type"] = frame["Bucket"]
    frame["FAH_Line_Description"] = frame["Description"]
    frame["Accounted_Dr"] = frame["Functional_Net"].clip(lower=0)
    frame["Accounted_Cr"] = -frame["Functional_Net"].clip(upper=0)
    configured = apply_defaults(default_spec(), get_preset("rm_flux"))
    result = execute(frame, configured, {"open_po": pd.DataFrame({"PO Num": ["800001"], "GAO Comment": ["GAO booked"]})})
    assert result["views"]["po"][0]["M1_base"] == 1835.16
    assert result["views"]["po"][0]["M1_curr"] == -42.98
    assert all(control["status"] != "stop" for control in result["controls"])
    assert result["classification"]["value_coverage"] > 0
    optional = execute(frame, configured)
    assert any(control["id"] == "join_unmatched_keys" and control["status"] == "warn" for control in optional["controls"])


def test_no_python_domain_branches():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for directory in ("engine", "agent", "web"):
        assert all("rm_flux" not in path.read_text() for path in (root / directory).rglob("*.py"))
