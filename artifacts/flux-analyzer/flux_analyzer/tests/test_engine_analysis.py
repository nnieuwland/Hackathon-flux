"""Generic transform, comparison, golden rule and benefits examples."""
import pandas as pd
import pytest
import json
from pathlib import Path
from engine.spec import default_spec, resolve_tokens
from engine.periods import normalize_periods, resolve_comparison
from engine.transform import derive, classify_text, apply_scope
from engine.compare import pivot_compare, apply_joins, decompose, build_sections
from engine.flags import apply_flags, apply_gates
from engine.drivers import select_drivers
from engine.controls import run_controls
from engine.pipeline import execute
from engine.money import total

def generic_spec() -> dict:
    """A generic additive comparison with no domain rules in the engine."""
    spec = default_spec()
    spec["roles"].update(value="Functional_Net", period="Period_Name", keys=["Base_PO"], dimensions=["Country"], driver_text=["Description"])
    spec["comparison"] = {"type": "QoQ", "base": {"period": "Q1 2026"}, "current": {"period": "Q2 2026"}}
    spec["measures"] = {"amount": {"agg": "sum", "col": "{roles.value}"}}
    spec["views"] = [{"name": "country", "keys": ["Country"], "measures": ["amount"], "compare": True}]
    spec["drivers"].update(view="country", measure="amount", materiality_abs=0)
    return spec

def test_golden_rule(golden: pd.DataFrame) -> None:
    spec = generic_spec()
    spec["measures"].update(
        M1_base={"agg": "sum", "col": "{roles.value}", "slice": "none", "filter": [{"col": "__month", "op": "eq", "val": "{base.first_month}"}, {"col": "Bucket", "op": "eq", "val": "Accrual - Current"}]},
        M1_curr={"agg": "sum", "col": "{roles.value}", "slice": "none", "filter": [{"col": "__month", "op": "eq", "val": "{current.first_month}"}, {"col": "Bucket", "op": "in", "val": ["Accrual - Current", "Accrual - Reversal"]}]},
    )
    spec["views"].append({"name": "po", "keys": ["Base_PO"], "measures": ["M1_base", "M1_curr"], "compare": False})
    spec["flags"] = [{"view": "po", "name": "Observation_Flag", "ordered": [{"if": "abs(M1_curr - M1_base) > 1000", "label": "Material"}], "default": "Consistent"}]
    spec["gates"] = [{"view": "po", "name": "Exception", "if": "Observation_Flag == 'Material'"}]
    run = execute(golden, spec)
    po = run["views"]["po"][0]
    assert po["M1_base"] == 1835.16
    assert po["M1_curr"] == -42.98
    assert round(po["M1_curr"] - po["M1_base"], 2) == -1878.14
    assert run["n_exceptions"] == 1
    assert total(d["delta"] for d in run["drivers"]) == run["delta"]
    assert all(c["status"] == "pass" for c in run["controls"])

def test_benefits_volume_rate(benefits: pd.DataFrame) -> None:
    frame = derive(benefits, [{"name": "Cost_per_head", "type": "ratio", "numerator": "Cost", "denominator": "Headcount"}])
    frame = normalize_periods(frame, "Period")
    output = pivot_compare(frame, ["Department"], {"amount": {"agg": "sum", "col": "Cost"}, "Headcount": {"agg": "sum", "col": "Headcount"}, "Cost_per_head": {"agg": "mean", "col": "Cost_per_head"}}, {"months": ["2026-01"], "scenario": "Forecast"}, {"months": ["2026-01"], "scenario": "Actual"}, {"scenario": "Scenario"})
    output = decompose(output, {"volume": "Headcount", "rate": "Cost_per_head", "method": "volume_at_base_rate"})
    assert output.iloc[0]["volume_impact"] == 2000
    assert output.iloc[0]["rate_impact"] == 1200
    assert output.iloc[0]["amount_delta"] == 3200

def test_transforms_flags_gates_and_joins() -> None:
    frame = pd.DataFrame({"Text": ["PO 123456_V2", "abc", "Test"], "Amount": [10, 0, 25], "HC": [2, 0, 5]})
    output = derive(frame, [
        {"name": "PO", "type": "regex_extract", "source": ["Text"], "pattern": r"(\d{6,})", "strip_suffix": r"_V\d+", "default": "UNMATCHED"},
        {"name": "Cost_per_head", "type": "ratio", "numerator": "Amount", "denominator": "HC"},
        {"name": "Group", "type": "rules", "rules": [{"when": {"col": "Amount", "op": "gt", "val": 0}, "then": "Positive"}, {"when": {"col": "Amount", "op": "gte", "val": 0}, "then": "Nonnegative"}], "default": "Other"},
        {"name": "Mapped", "type": "map", "source": "Text", "mapping": {"abc": "A"}},
        {"name": "Joined", "type": "concat", "source": ["Text", "PO"], "separator": "-"},
        {"name": "Band", "type": "bucket_numeric", "source": "Amount", "bins": [-1, 15, 100], "labels": ["Low", "High"]},
    ])
    assert output.PO.tolist() == ["123456", "UNMATCHED", "UNMATCHED"]
    assert output.Group.tolist() == ["Positive", "Nonnegative", "Positive"]
    assert output.Cost_per_head.iloc[0] == 5
    assert len(apply_scope(output, [{"col": "Group", "op": "eq", "val": "Positive"}])) == 2
    classified, unmatched = classify_text(frame, "Text", {"PO": "Purchase"}, "Category", "Amount")
    assert unmatched[0]["abs_value"] == 25
    lookup = pd.DataFrame({"PO Num": ["123456"], "Comment": ["GAO done"]})
    joined = apply_joins(output, [{"lookup": "po", "left_on": "PO", "right_on": "PO Num", "fields": {"exists": {"type": "exists"}, "gao": {"type": "exists_where", "filter": [{"col": "Comment", "op": "startswith", "val": "GAO"}]}}}], {"po": lookup})
    assert len(joined) == 3 and bool(joined.gao.iloc[0])
    flagged, counts = apply_flags(joined, {"name": "Flag", "ordered": [{"if": "Amount > 5", "label": "Material"}, {"if": "Amount > 0", "label": "Positive"}], "default": "None"})
    assert sum(counts.values()) == len(flagged)
    assert len(apply_gates(flagged, {"if": "gao and Flag == 'Material'"})) == 1
    assert total(r["total"] for r in build_sections(output, {"split_by": "Group"}, "Amount")) == 35

def test_drivers_remainder_and_zero_base() -> None:
    frame = pd.DataFrame({"Country": ["A", "B", "C"], "amount_base": [0, 10, 20], "amount_current": [100, 12, 17], "amount_delta": [100, 2, -3]})
    drivers = select_drivers(frame, "amount", 50, 1)
    assert [d["label"] for d in drivers] == ["A", "Other items"]
    assert total(d["delta"] for d in drivers) == 99
    result = pivot_compare(pd.DataFrame({"V": [0, 10], "__month": ["2026-01", "2026-02"]}), [], {"a": {"agg": "sum", "col": "V"}}, {"months": ["2026-01"]}, {"months": ["2026-02"]})
    assert result.iloc[0]["a_delta_pct"] is None

def test_controls_stop_and_sections(golden: pd.DataFrame) -> None:
    spec = generic_spec()
    spec["sections"] = {"split_by": "Bucket", "must_reconcile_to": "amount", "order": ["Operational"]}
    run = execute(golden, spec)
    assert total(s["delta"] for s in run["sections"]) == run["delta"]
    spec["comparison"]["current"] = {"period": "Q3 2026"}
    with pytest.raises(ValueError, match="blocked"):
        execute(golden, spec)

def test_shipped_declarative_examples(golden: pd.DataFrame, benefits: pd.DataFrame) -> None:
    """Shipped JSON examples, not Python branches, encode domain rules."""
    examples = Path(__file__).resolve().parents[1] / "examples"
    rm_spec = json.loads((examples / "rm_qoq.json").read_text())
    frame = golden.rename(columns={"Description": "FAH_Line_Description", "Bucket": "FAH_Event_Type", "Base_PO": "Po_Number"}).copy()
    frame["Po_Number"] = frame["Po_Number"].astype(str)
    frame["Account"] = "54100"
    frame["Accounted_Dr"] = frame["Functional_Net"].clip(lower=0)
    frame["Accounted_Cr"] = -frame["Functional_Net"].clip(upper=0)
    lookup = pd.DataFrame({"PO Num": ["800001"], "GAO Comment": ["GAO booked"]})
    result = execute(frame, rm_spec, {"open_po": lookup})
    assert result["views"]["po"][0]["M1_base"] == 1835.16
    assert result["views"]["po"][0]["M1_curr"] == -42.98
    assert bool(result["views"]["po"][0]["gao_booked"])
    benefits_spec = json.loads((examples / "benefits.json").read_text())
    output = execute(benefits, benefits_spec)
    assert output["views"]["department"][0]["volume_impact"] == 2000
    assert output["views"]["department"][0]["rate_impact"] == 1200
    assert output["delta"] == 3200

def test_quarter_label_sources_are_not_partial() -> None:
    """Quarterly extracts cover a quarter even when no monthly rows exist."""
    frame = pd.DataFrame({"Period_Name": ["Q1 2026", "Q2 2026"], "Functional_Net": [100, 250], "Country": ["NL", "NL"], "Description": ["Costs", "Costs"], "Base_PO": ["1", "1"]})
    result = execute(frame, generic_spec())
    assert result["delta"] == 150

def test_debit_credit_and_new_members_controls(golden: pd.DataFrame) -> None:
    """Optional controls show warnings without hiding discrepancies."""
    from engine.controls import debit_minus_credit_equals_value, new_or_removed_members
    from engine.pipeline import prepare
    spec = generic_spec()
    frame = golden.copy()
    frame["Debit"], frame["Credit"] = frame["Functional_Net"].clip(lower=0), -frame["Functional_Net"].clip(upper=0)
    prepared, resolved, comparison = prepare(frame, spec)
    context = {"df": prepared, "spec": resolved, "comparison": comparison}
    cfg = {"severity": "warn", "params": {"debit": "Debit", "credit": "Credit"}}
    assert debit_minus_credit_equals_value(context, cfg)["status"] == "pass"
    prepared.loc[0, "Debit"] += 5
    assert debit_minus_credit_equals_value(context, cfg)["status"] == "warn"
    assert new_or_removed_members(context, {"severity": "warn"})["status"] == "pass"
