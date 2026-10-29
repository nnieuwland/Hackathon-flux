import copy
import json
import pytest
from agent.client import validate_response, bound_envelope
from agent.mock import mock_response
from agent.steps import build_envelope
from agent.proposals import candidate_for_response
from engine.spec import default_spec
from engine.describe import describe_spec
from web.routes_config import apply_agent_result


def response(status="ok", confidence="medium", proposal=None, step="map_columns"):
    return {"request_id": "test", "step": step, "status": status, "proposal": proposal or {"roles": {"value": "Amount"}}, "confidence": confidence, "rationale": "Mapped the supplied amount header.", "questions": [], "warnings": []}


@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_all_valid_confidence_levels_auto_apply_and_log(confidence):
    state = {"spec": default_spec(), "change_log": []}
    result = apply_agent_result(state, response(confidence=confidence))
    assert result["applied"] and state["spec"]["roles"]["value"] == "Amount"
    assert state["change_log"][0]["actor"] == "agent"
    assert bool(result["warnings"]) == (confidence == "low")


def test_needs_input_applies_only_partial_and_cannot_do_preserves_spec():
    state = {"spec": default_spec(), "change_log": []}
    result = apply_agent_result(state, response(status="needs_input"))
    assert result["applied"] and "period" in state["spec"]["roles"]
    original = copy.deepcopy(state["spec"])
    assert not apply_agent_result(state, response(status="cannot_do"))["applied"]
    assert state["spec"] == original
    stale = copy.deepcopy(original)
    stale["flux_name"] = "Earlier state"
    assert not apply_agent_result(state, response(), stale)["applied"]


@pytest.mark.parametrize("instruction,path,expected", [
    ("Only EMEA", "scope", [{"col": "Region", "op": "eq", "val": "EMEA"}]),
    ("Set materiality to 250k", "drivers", 250000),
    ("Compare May vs April", "comparison", ["2026-05"]),
])
def test_mock_instruction_round_trip(instruction, path, expected):
    spec = default_spec()
    spec["roles"]["dimensions"] = ["Region"]
    spec["comparison"]["current"]["months"] = ["2026-06"]
    envelope = build_envelope("apply_instruction", spec, user_message=instruction)
    result = validate_response(mock_response(envelope), "apply_instruction", envelope["request_id"])
    candidate = candidate_for_response(spec, result)
    actual = candidate[path]
    if path == "drivers":
        actual = actual["materiality"]["abs"]
    elif path == "comparison":
        actual = actual["current"]["months"]
    assert actual == expected


def test_invalid_patch_is_atomic_and_all_response_errors_are_reported():
    state = {"spec": default_spec(), "change_log": []}
    bad = response(step="apply_instruction", proposal={"patch": [{"op": "replace", "path": "/flux_name", "value": ""}]})
    with pytest.raises(ValueError):
        apply_agent_result(state, bad)
    assert state["spec"] == default_spec() and not state["change_log"]
    bad = response()
    bad["confidence"], bad["status"] = "unknown", "unknown"
    with pytest.raises(ValueError) as error:
        validate_response(bad, "map_columns")
    assert "confidence" in str(error.value) and "status" in str(error.value)


def test_sample_caps_and_canonical_months_in_every_request():
    spec = default_spec()
    spec["comparison"]["base"]["months"] = ["JAN-26", "2026-02", "MAR-26"]
    envelope = build_envelope("apply_instruction", spec, user_message="Only EMEA")
    envelope["payload"]["profile"] = {"columns": [{"samples": list(range(100))}]}
    bounded = bound_envelope(envelope)
    assert len(bounded["payload"]["profile"]["columns"][0]["samples"]) <= 10
    assert bounded["spec_so_far"]["comparison"]["base"]["months"] == ["2026-01", "2026-02", "2026-03"]
    assert "preset" in bounded["payload"]


def test_descriptions_cover_every_default_block_and_audit_origins():
    spec = default_spec()
    cards = describe_spec(spec, [{"path": "/drivers/top_n", "actor": "agent"}])
    assert {"value_rules", "comparison", "drivers", "materiality", "drill", "commentary", "controls"} <= {card["block"] for card in cards}
    assert all(card["sentence"].endswith(".") for card in cards)
    assert next(card for card in cards if card["path"] == "/drivers")["actor"] == "agent"


def test_instruction_http_auto_applies_validated_change_then_undoes():
    """Approved journey behaviour: a valid change applies with a summary, Undo restores it."""
    import time
    from app import create_app
    client = create_app({"TESTING": True, "SECRET_KEY": "instruction-test"}).test_client()
    client.get("/")
    initial = client.get("/state").get_json()
    headers = {"X-CSRF-Token": initial["csrf_token"]}
    queued = client.post("/instruction", json={"instruction": "Set materiality to 250k"}, headers=headers)
    assert queued.status_code == 202
    for _ in range(100):
        job = client.get("/jobs/" + queued.get_json()["job_id"]).get_json()
        if job["status"] == "done":
            break
        assert job["status"] != "error", job.get("error")
        time.sleep(.02)
    assert job["result"]["applied"]
    assert job["result"]["undo_available"]
    assert job["result"]["changes"] and job["result"]["summary"]
    state = client.get("/state").get_json()
    assert state["spec"]["drivers"]["materiality"]["abs"] == 250000
    assert state["spec_revision"] == initial["spec_revision"] + 1
    undone = client.post("/spec/undo", json={}, headers=headers).get_json()
    assert undone["csrf_token"] == initial["csrf_token"]
    assert undone["spec"]["drivers"]["materiality"]["abs"] == 300000


def test_all_step_builders_send_metadata_without_raw_row_arrays():
    import pandas as pd
    spec = default_spec()
    spec["roles"].update(value="Amount", period="Period", dimensions=["Region"], driver_text=["Text"])
    df = pd.DataFrame({"Amount": list(range(40)), "Period": ["APR-26"] * 20 + ["MAY-26"] * 20, "Region": ["EMEA"] * 40, "Text": [f"Term {n}" for n in range(40)]})
    def inspect(value):
        if isinstance(value, dict):
            assert not {"rows", "records", "raw_rows", "transactions"} & set(value)
            for key, item in value.items():
                if key == "samples":
                    assert len(item) <= 10
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
    for step in ("detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules", "apply_instruction", "explain_spec", "answer_question", "write_commentary"):
        inspect(bound_envelope(build_envelope(step, spec, df, evidence={"drivers": []})))


def test_describe_domain_settings_and_sections_offline():
    from engine.presets import get_preset, apply_defaults
    rm = describe_spec(apply_defaults(default_spec(), get_preset("rm_flux")))
    assert {"scope", "derive", "joins", "classification", "measures", "views", "flags", "gates"} <= {card["block"] for card in rm}
    flag = next(card for card in rm if card["block"] == "flags")
    assert "Material movement > $5k when abs(M1_curr - M1_base) > 5000" in flag["sentence"]
    benefits = describe_spec(apply_defaults(default_spec(), get_preset("benefits_flux")))
    assert any(card["block"] == "decompose" for card in benefits)
