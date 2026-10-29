"""Evidence privacy, narrative validation, export and agent boundary tests."""
import json
from pathlib import Path
import pandas as pd
import pytest
from openpyxl import load_workbook
from engine.evidence import format_delta, build_evidence_pack
from engine.narrative_check import check_narrative
from engine.excel_pack import render_excel, PRIMARY
from engine.spec import default_spec
from agent.steps import build_envelope
from agent.client import bound_envelope, parse_agent_json, invoke_agent, AgentError

def evidence() -> dict:
    """One preformatted driver evidence entry."""
    return {"drivers": [{"driver_id": "d1", "label": "EMEA", "delta": 1200000, "delta_fmt": "+$1.2M", "top_texts": []}], "commentary_rules": {"forbidden_terms": ["SECRET_PRODUCT"]}}

def test_narrative_amounts_order_and_forbidden_terms() -> None:
    response = {"lines": [{"driver_id": "d1", "text": "+$1.2M — EMEA. [TO VERIFY] Confirm the business cause."}], "headline": "Movement", "others_summary": ""}
    assert check_narrative(response, evidence())["ok"]
    for text in ("EMEA: -$1.2M.", "EMEA: +$1.3M.", "EMEA: +$1.2M and 83 customers.", "EMEA: +$1.2M SECRET_PRODUCT.", "EMEA: +$1.2M and $0.0M."):
        bad = {**response, "lines": [{"driver_id": "d1", "text": text}]}
        assert not check_narrative(bad, evidence())["ok"]
    assert not check_narrative({**response, "lines": []}, evidence())["ok"]
    assert format_delta(12.34, {"units": "M", "decimals": 1}) == "+$12.34"
    assert format_delta(-1200000, {"units": "M", "decimals": 1}) == "-$1.2M"

def test_evidence_bounded() -> None:
    drivers = [{"driver_id": "d1", "label": "A", "dimensions": {"Country": "A"}, "base": 10, "current": 22, "delta": 12}]
    drills = {"d1": [{"text": "a" * 500, "delta": 1, "n_lines": 2}] * 12}
    output = build_evidence_pack(default_spec(), drivers, drills, [])
    assert len(output["drivers"][0]["top_texts"]) == 5
    assert len(output["drivers"][0]["top_texts"][0]["text"]) == 160

def test_exports_and_formula_injection(tmp_path: Path) -> None:
    run = {"name": "=HYPERLINK(\"evil\")", "base": 1, "current": 2, "delta": 1, "n_drivers": 1, "n_exceptions": 0, "commentary": {"text": "Checked commentary", "headline": "+cmd|' /C calc'!A0", "lines": [{"driver_id": "d1", "text": "+$1.2M — EMEA: new contract signed."}]},
           "views": {"country": [{"Country": "=1+1", "amount_delta": 1}]}, "drivers": [{"driver_id": "d1", "label": "@evil", "delta": 1, "top_texts": [{"text": "-2+3", "delta_fmt": "+$1"}]}],
           "drills": {"d1": [{"text": "=cmd()", "base": 0, "current": 1, "delta": 1, "n_lines": 1}]}, "controls": [{"id": "test", "status": "pass", "message": "=bad()"}],
           "change_log": [{"timestamp": "2026-10-28T10:00:00+00:00", "actor": "user", "reason": "@SUM(A1)", "path": "/flux_name", "op": "replace", "from": "a", "to": "=b"}], "spec": default_spec()}
    path = render_excel(run, tmp_path)
    workbook = load_workbook(path)
    assert workbook.sheetnames[:len(PRIMARY)] == PRIMARY
    assert {"Variance - country", "Movement detail", "Source lines", "Data controls", "Setup changes", "Run audit", "FluxSpec"} <= set(workbook.sheetnames)
    assert "Variance_country" not in workbook.sheetnames and "Spec" not in workbook.sheetnames
    # No cell anywhere holds a formula built from untrusted text, and the text is kept visibly prefixed.
    texts = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    if cell.data_type == "f":
                        assert not any(bad in cell.value for bad in ("HYPERLINK", "cmd", "bad()", "1+1", "@")), (sheet.title, cell.coordinate, cell.value)
                    else:
                        texts.append(cell.value)
    for injected in ('=HYPERLINK("evil")', "@evil", "=1+1", "=cmd()", "=bad()", "@SUM(A1)", "-2+3", "+cmd|' /C calc'!A0"):
        assert "'" + injected in texts or any(("'" + injected) in text for text in texts), injected
        assert injected not in texts
    # A signed amount opening a sentence stays readable, protected by Excel's hidden quote prefix.
    signed = [cell for row in workbook["Summary"].iter_rows() for cell in row if cell.value == "+$1.2M — EMEA: new contract signed."]
    assert signed and all(cell.quotePrefix for cell in signed)
    variance = workbook["Variance - country"]
    assert variance["A2"].data_type == "s" and variance["A2"].value.startswith("'=")
    assert workbook["Movement detail"].freeze_panes == "A2"
    when = workbook["Setup changes"]["A2"]
    assert when.is_date and when.number_format == "yyyy-mm-dd hh:mm"

def test_agent_payload_no_rows_and_hard_cap(golden: pd.DataFrame) -> None:
    spec = default_spec()
    spec["roles"].update(value="Functional_Net", period="Period_Name", driver_text=["Description"])
    for step in ("detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules"):
        envelope = build_envelope(step, spec, golden)
        assert "rows" not in envelope["payload"]
        assert len(json.dumps(bound_envelope(envelope)).encode()) <= 50 * 1024
    envelope = build_envelope("map_columns", spec, golden)
    envelope["payload"]["profile"]["columns"][0]["samples"] = ["é" * 1000] * 100
    assert len(json.dumps(bound_envelope(envelope), ensure_ascii=False).encode()) <= 50 * 1024
    envelope["spec_so_far"]["flux_name"] = "x" * 60000
    with pytest.raises(AgentError):
        bound_envelope(envelope)

def test_mock_schemas_and_log(golden: pd.DataFrame, tmp_path: Path) -> None:
    spec = default_spec()
    spec["roles"].update(value="Functional_Net", period="Period_Name", driver_text=["Description"], dimensions=["Country"])
    for step in ("detect_flux", "map_columns", "define_comparison", "derive_columns", "classify_terms", "define_rules"):
        response = invoke_agent(build_envelope(step, spec, golden), log_dir=tmp_path)
        assert response["status"] == "ok"
        assert parse_agent_json("```json\n" + json.dumps(response) + "\n```", step)["step"] == step
    entries = [json.loads(line) for line in (tmp_path / "agent_log.jsonl").read_text().splitlines()]
    assert len(entries) == 6
    assert all("headers" not in entry and entry["envelope_size"] <= 50 * 1024 for entry in entries)
    with pytest.raises((ValueError, Exception)):
        parse_agent_json('{"step":"bad"}', "map_columns")
