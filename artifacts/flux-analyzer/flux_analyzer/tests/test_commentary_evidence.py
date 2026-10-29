"""Commentary evidence: history, category mix, coverage, stated context and claim checks."""
import copy
import json
from io import BytesIO
import time

import pandas as pd

from agent.client import bound_envelope
from agent.steps import build_envelope
from agent.writing_context import attach, business_context, writing_guidance
from engine.narrative_check import check_narrative
from engine.pipeline import execute
from engine.spec import default_spec

MONTHS = ["JAN-26", "FEB-26", "MAR-26", "APR-26", "MAY-26", "JUN-26"]
HISTORY = {
    "Steady": [100, 100, 100, 100, 100, 160],      # flat, then one jump
    "Rising": [100, 110, 120, 130, 140, 160],      # keeps rising
    "Bounce": [100, 100, 100, 100, 200, 100],      # undoes last month's jump
}


def frame() -> pd.DataFrame:
    rows, number = [], 0
    for region, amounts in HISTORY.items():
        for month, amount in zip(MONTHS, amounts):
            # Rising has a single description, so an AI draft can call it supported.
            for text, share in ((("Maintenance contract", 1),) if region == "Rising" else (("Maintenance contract", .75), ("Office supplies", .25))):
                number += 1
                rows.append({"Period": month, "Amount": amount * share, "Region": region, "Text": text, "Invoice": f"INV-SECRET-{number:05d}"})
    return pd.DataFrame(rows)


def spec(**comparison) -> dict:
    output = default_spec()
    output["roles"].update(value="Amount", period="Period", dimensions=["Region"], driver_text=["Text"])
    output["comparison"] = comparison or {"type": "MoM", "base": {"months": ["2026-05"]}, "current": {"months": ["2026-06"]}}
    output["measures"] = {"amount": {"agg": "sum", "col": "{roles.value}"}}
    output["views"] = [{"name": "regions", "keys": ["Region"], "measures": ["amount"], "compare": True}]
    output["drivers"] = {"view": "regions", "measure": "amount", "materiality": {"mode": "abs", "abs": 0}, "top_n": 15, "others_label": "Other items"}
    output["classification"] = {"target_col": "Category", "source_cols": ["Text"], "fallback": "Unclassified", "rules": [
        {"keyword": "maintenance", "category": "Maintenance", "match": "contains", "reviewed": True},
        {"keyword": "office", "category": "Office", "match": "contains", "reviewed": False}]}
    output["commentary"]["units"] = "units"
    output["commentary"]["decimals"] = 0
    return output


def by_label(result: dict) -> dict:
    return {driver["label"]: driver for driver in result["evidence"]["drivers"]}


def test_history_tells_one_period_change_from_continuing_pattern() -> None:
    drivers = by_label(execute(frame(), spec()))
    assert drivers["Steady"]["trend"]["pattern"] == "one_period"
    assert drivers["Rising"]["trend"]["pattern"] == "continuing"
    assert drivers["Bounce"]["trend"]["pattern"] == "reversal"
    steady = drivers["Steady"]["trend"]
    assert steady["comparability"] == "comparable" and len(steady["points"]) == 6
    assert [point["period"] for point in steady["points"]] == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert steady["points"][-1]["amount_fmt"] == drivers["Steady"]["current_fmt"] == "$160"
    assert steady["points"][-2]["amount_fmt"] == drivers["Steady"]["base_fmt"] == "$100"


def test_history_is_context_only_when_periods_are_not_consecutive() -> None:
    year_apart = spec(type="custom", base={"months": ["2026-01"]}, current={"months": ["2026-06"]})
    trend = by_label(execute(frame(), year_apart))["Steady"]["trend"]
    assert trend["comparability"] == "limited" and trend["pattern"] == "not_assessed"
    quarters = spec(type="QoQ", base={"months": ["2026-01", "2026-02", "2026-03"]}, current={"months": ["2026-04", "2026-05", "2026-06"]})
    trend = by_label(execute(frame(), quarters))["Rising"]["trend"]
    # Only two quarters exist: the history is shown but too short to call a pattern.
    assert trend["pattern"] == "insufficient_history" and trend["points"][0]["period"] == "2026-01 to 2026-03"


def test_categories_coverage_and_data_quality_are_scoped_and_counted() -> None:
    result = execute(frame(), spec())
    steady = by_label(result)["Steady"]
    categories = {item["category"]: item for item in steady["categories"]["items"]}
    assert categories["Maintenance"]["approval"] == "approved" and categories["Maintenance"]["delta_fmt"] == "+$45"
    assert categories["Office"]["approval"] == "not_approved" and categories["Office"]["lines"] == 2
    coverage = steady["coverage"]
    assert coverage["source_lines"] == 4 and coverage["shown_description_count"] == 2 and not coverage["truncated"]
    quality = {item["id"]: item for item in result["evidence"]["data_quality"]}
    assert quality["classification:unreviewed"]["scope"] == "categories"
    assert "12 of 30 lines" in quality["classification:unreviewed"]["message"]
    assert any("individual transactions are not supplied" in note for note in result["evidence"]["coverage_notes"])
    refs = set(result["evidence"]["allowed_evidence_refs"])
    assert {"trend:d1", "category:d1:1", "coverage:d1", "classification:unreviewed", "total:movement"} <= refs


def test_commentary_request_holds_no_source_rows_and_stays_bounded() -> None:
    data = frame()
    result = execute(data, spec())
    envelope = build_envelope("write_commentary", result["spec"], evidence=attach(copy.deepcopy(result["evidence"]), result["spec"]))
    encoded = json.dumps(bound_envelope(envelope))
    assert "INV-SECRET" not in encoded  # row identifiers never leave the engine
    assert "rows" not in envelope["payload"]["evidence_pack"]
    for driver in envelope["payload"]["evidence_pack"]["drivers"]:
        assert len(driver["top_texts"]) <= 5 and all(len(item["text"]) <= 160 for item in driver["top_texts"])
    # A wide report (many movements, long descriptions) still fits the request cap without truncation.
    wide = pd.concat([data.assign(Region=data["Region"] + str(index)) for index in range(6)], ignore_index=True)
    wide = pd.concat([wide.assign(Text=wide["Text"] + f" variant {variant} " + "x" * 200, Amount=wide["Amount"] / 4) for variant in range(4)], ignore_index=True)
    big = execute(wide, spec())
    request = bound_envelope(build_envelope("write_commentary", big["spec"], evidence=attach(copy.deepcopy(big["evidence"]), big["spec"])))
    assert len(json.dumps(request, ensure_ascii=False).encode()) <= 50 * 1024
    kept = request["payload"]["evidence_pack"]["drivers"]
    # Every movement survives, and history is shortened before any description is dropped.
    assert len(kept) == 16 and all(len(driver["top_texts"]) == min(5, driver["coverage"]["shown_description_count"]) >= 4 for driver in kept[:-1])
    assert all(driver["trend"]["pattern"] in ("one_period", "continuing", "reversal") for driver in kept[:-1])


def evidence_for(context: str = "") -> dict:
    configured = spec()
    configured["commentary"]["style_profile"] = {"audience": "executive", "length": "short", "structure": {"type": "overall", "split_by": None}, "tone": "neutral",
                                                 "instructions": "", "example_style": {"summary_of_style": "", "sample_phrases": []}, "include": ["to_verify"],
                                                 "objective": "Month-end pack for the regional director", "business_context": context}
    result = execute(frame(), configured)
    return attach(result["evidence"], configured)


def line(evidence: dict, label: str, text: str, **extra) -> tuple[dict, dict]:
    """A one-movement proposal and the matching evidence slice."""
    driver = next(item for item in evidence["drivers"] if item["label"] == label)
    single = {**evidence, "drivers": [driver]}
    return {"headline": "", "lines": [{"driver_id": driver["driver_id"], "text": f"{driver['delta_fmt']} — {label}{text}", **extra}], "others_summary": ""}, single


def issues(proposal: dict, evidence: dict, **kwargs) -> list[str]:
    return check_narrative(proposal, evidence, **kwargs)["issues"]


def test_trend_wording_must_match_the_engine_pattern_and_cite_it() -> None:
    evidence = evidence_for()
    rising = next(item for item in evidence["drivers"] if item["label"] == "Rising")
    ok, single = line(evidence, "Rising", ": continues the rise of the two periods before.", evidence_refs=[f"trend:{rising['driver_id']}"])
    assert not issues(ok, single)
    uncited, single = line(evidence, "Rising", ": continues the rise of the two periods before.")
    assert any("cite the history" in issue for issue in issues(uncited, single))
    wrong, single = line(evidence, "Steady", ": part of an ongoing trend.")
    assert any("does not show a continuing pattern" in issue for issue in issues(wrong, single))
    # History amounts and periods are quotable; anything else is not.
    quoted, single = line(evidence, "Steady", ": up from $100 in 2026-05.")
    assert not issues(quoted, single)
    for invented in (": up from $95 in 2026-05.", ": up 17 lines."):
        bad, single = line(evidence, "Steady", invented)
        assert issues(bad, single), invented


def test_causes_need_the_verify_tag_or_stated_context_unless_a_person_wrote_them() -> None:
    evidence = evidence_for("A price increase took effect in June.")
    assert evidence["business_context"][0] == {**evidence["business_context"][0], "id": "context:user:1", "source": "user", "verified": False}
    cause, single = line(evidence, "Steady", " is due to a price increase.")
    assert any("needs [TO VERIFY]" in issue for issue in issues(cause, single))
    assert not issues(cause, single, author="person")
    tagged, single = line(evidence, "Steady", " may be due to a price increase. [TO VERIFY]", support="needs_verification")
    assert not issues(tagged, single)
    stated, single = line(evidence, "Steady", " is consistent with the price increase you told us about, due to take effect in June.", evidence_refs=["context:user:1"],
                          claims=[{"type": "context", "text": "You told us a price increase took effect in June.", "evidence_refs": ["context:user:1"]}])
    assert not issues(stated, single)
    # Citing context is not proof: a cause the context does not state still needs the tag.
    unrelated, single = line(evidence, "Steady", " is due to an inventory write-off.", support="supported", evidence_refs=["context:user:1"],
                             claims=[{"type": "possible_explanation", "text": "An inventory write-off.", "evidence_refs": ["context:user:1"]}])
    found = issues(unrelated, single)
    assert any("needs [TO VERIFY]" in issue for issue in found) and any("possible explanation needs" in issue for issue in found)
    padded, single = line(evidence, "Steady", ": price increase took effect in June, because of an inventory write-off.", evidence_refs=["context:user:1"])
    assert any("needs [TO VERIFY]" in issue for issue in issues(padded, single))
    padded_claim, single = line(evidence, "Steady", ": see stated context.", evidence_refs=["context:user:1"],
                                claims=[{"type": "possible_explanation", "text": "Price increase took effect in June, because of an inventory write-off.", "evidence_refs": ["context:user:1"]}])
    assert any("possible explanation needs" in issue for issue in issues(padded_claim, single))
    mislabelled, single = line(evidence, "Steady", ": see stated context.", evidence_refs=["context:user:1"],
                               claims=[{"type": "context", "text": "You told us a warehouse closed.", "evidence_refs": ["context:user:1"]}])
    assert any("context claim must cite and repeat" in issue for issue in issues(mislabelled, single))


def test_claims_separate_observations_from_possible_explanations() -> None:
    evidence = evidence_for()
    steady = next(item for item in evidence["drivers"] if item["label"] == "Steady")
    observation = {"type": "observation", "text": "Most of it sits in Maintenance.", "evidence_refs": [steady["categories"]["items"][0]["evidence_ref"]]}
    good, single = line(evidence, "Steady", ": mostly Maintenance. Possibly a contract change. [TO VERIFY]", support="needs_verification",
                        evidence_refs=[f"driver:{steady['driver_id']}"], claims=[observation, {"type": "possible_explanation", "text": "Possibly a contract change.", "evidence_refs": []}],
                        confirm_prompt="Ask the budget owner whether the contract changed.")
    assert not issues(good, single)
    cases = {
        "every observation must cite": {**observation, "evidence_refs": []},
        "label it a possible explanation": {**observation, "text": "It rose because of a new contract."},
        "possible explanation needs": {"type": "possible_explanation", "text": "Possibly a contract change.", "evidence_refs": []},
    }
    for expected, claim in cases.items():
        bad, single = line(evidence, "Steady", ": mostly Maintenance.", claims=[claim])
        assert any(expected in issue for issue in issues(bad, single)), expected
    other = next(item for item in evidence["drivers"] if item["label"] == "Rising")
    crossed, single = line(evidence, "Steady", ": mostly Maintenance.", evidence_refs=[f"trend:{other['driver_id']}"])
    assert any("another movement" in issue for issue in issues(crossed, single))
    unsupported, single = line(evidence, "Steady", ": mostly Maintenance.", support="supported")
    assert any("must list the evidence" in issue for issue in issues(unsupported, single))


def test_writing_guidance_records_where_each_preference_came_from(tmp_path, monkeypatch) -> None:
    configured = spec()
    assert writing_guidance(configured)["audience"] == {"value": "controller", "source": "default"}
    configured["commentary"]["style_profile"] = {"audience": "executive", "objective": "Board pack"}
    guidance = writing_guidance(configured)
    assert guidance["audience"] == {"value": "executive", "source": "user"} and guidance["objective"]["source"] == "user"
    assert guidance["tone"]["source"] == "default"
    import engine.presets as presets
    monkeypatch.setattr(presets, "WORKSPACE", tmp_path)
    configured["commentary"]["style_profile"] = {**configured["commentary"]["style_profile"], "business_context": "Plant B closed in May.\n- Prices rose in June."}
    full = copy.deepcopy(configured)
    full["commentary"]["style_profile"] = {**{"length": "medium", "structure": {"type": "overall", "split_by": None}, "tone": "neutral", "instructions": "",
                                             "example_style": {"summary_of_style": "", "sample_phrases": []}, "include": ["to_verify"]}, **configured["commentary"]["style_profile"]}
    saved = presets.save_preset("board_pack", "Board pack", "Finance", "", "Explain for the board.", full)
    full["preset"] = {"id": "board_pack", "version": saved["version"]}
    context = business_context(full)
    assert [item["text"] for item in context] == ["Plant B closed in May.", "Prices rose in June."]
    assert all(item["source"] == "preset" and item["id"].startswith("context:preset:") and "Board pack" in item["note"] for item in context)
    assert writing_guidance(full)["audience"]["source"] == "preset"


def test_explain_step_context_reaches_the_run_and_ai_drafts_stay_reviewable(tmp_path, monkeypatch) -> None:
    import web.routes_setups as setups
    from app import create_app
    from config import WORKSPACE
    monkeypatch.setattr(setups, "WORKSPACE", tmp_path)
    client = create_app({"TESTING": True, "SECRET_KEY": "evidence-test"}).test_client()
    client.get("/")
    headers = {"X-CSRF-Token": client.get("/state").get_json()["csrf_token"]}

    def post(path, data=None):
        reply = client.post(path, json=data or {}, headers=headers)
        assert reply.status_code in (200, 202), reply.get_data(as_text=True)
        return reply.get_json()

    def wait(job):
        for _ in range(300):
            status = client.get("/jobs/" + job["job_id"]).get_json()
            if status["status"] == "done":
                return status["result"]
            assert status["status"] != "error", status.get("error")
            time.sleep(.02)
        raise AssertionError("job timed out")

    upload = frame().drop(columns=["Invoice"]).to_csv(index=False).encode()
    source = client.post("/sources/upload", data={"files": (BytesIO(upload), "costs.csv")}, content_type="multipart/form-data", headers=headers).get_json()["sources"][0]
    post("/sources/" + source["id"] + "/define", {"name": "costs", "role": "primary", "header_row": 1, "start_col": "A"})
    configured = spec()
    post("/spec/patch", {"patch": [{"op": "add", "path": "/" + key, "value": configured[key]} for key in ("roles", "comparison", "measures", "views", "drivers", "classification", "commentary")], "reason": "Evidence test"})
    post("/journey/simple/explain", {"audience": "executive", "objective": "Month-end pack for the regional director", "business_context": "A price increase took effect in June."})
    run_id = wait(post("/run"))["run_id"]
    stored = json.loads((WORKSPACE / "runs" / run_id / "result.json").read_text())
    evidence = stored["evidence"]
    assert evidence["writing_guidance"]["objective"] == {"value": "Month-end pack for the regional director", "source": "user"}
    assert evidence["business_context"][0]["text"] == "A price increase took effect in June." and "context:user:1" in evidence["allowed_evidence_refs"]
    draft = wait(post(f"/results/{run_id}/narrative"))
    assert draft["applied"], draft["validation"]
    lines = {line["driver_id"]: line for line in draft["proposal"]["lines"]}
    rising = next(item for item in evidence["drivers"] if item["label"] == "Rising")
    assert f"trend:{rising['driver_id']}" in lines[rising["driver_id"]]["evidence_refs"]
    items = {item["label"]: item for item in client.get(f"/results/{run_id}?format=json").get_json()["explanations"]}
    assert items["Rising"]["status"] == "ai_review" and "same direction" in items["Rising"]["history"]
    assert items["Steady"]["history"].startswith("The earlier periods were broadly stable")


def test_volume_rate_effects_only_explain_the_measure_they_were_built_for() -> None:
    rows = []
    for region, (heads, cost) in {"North": ((10, 12), (1000, 1500)), "South": ((8, 8), (800, 700))}.items():
        for month, h, c in zip(("JAN-26", "FEB-26"), heads, cost):
            rows.append({"Period": month, "Region": region, "Cost": c, "Headcount": h})
    configured = default_spec()
    configured["roles"].update(value="Cost", period="Period", dimensions=["Region"])
    configured["derive"] = [{"name": "Cost_per_head", "type": "ratio", "numerator": "Cost", "denominator": "Headcount"}]
    configured["comparison"] = {"type": "MoM", "base": {"months": ["2026-01"]}, "current": {"months": ["2026-02"]}}
    configured["measures"] = {"amount": {"agg": "sum", "col": "Cost"}, "Headcount": {"agg": "sum", "col": "Headcount"}, "Cost_per_head": {"agg": "mean", "col": "Cost_per_head"}}
    configured["views"] = [{"name": "regions", "keys": ["Region"], "measures": ["amount", "Headcount", "Cost_per_head"], "compare": True}]
    configured["decompose"] = {"view": "regions", "measure": "amount", "volume": "Headcount", "rate": "Cost_per_head", "method": "volume_at_base_rate"}
    configured["drivers"] = {"view": "regions", "measure": "amount", "materiality": {"mode": "abs", "abs": 0}, "top_n": 5, "others_label": "Other items"}
    configured["commentary"].update(units="units", decimals=0)
    north = by_label(execute(pd.DataFrame(rows), configured))["North"]
    assert [item["delta_fmt"] for item in north["decomposition"]["components"]] == ["+$200", "+$300"] and north["delta_fmt"] == "+$500"
    # Movements of headcount must not be "explained" by the cost decomposition.
    configured["drivers"]["measure"] = "Headcount"
    north = by_label(execute(pd.DataFrame(rows), configured))["North"]
    assert "decomposition" not in north
