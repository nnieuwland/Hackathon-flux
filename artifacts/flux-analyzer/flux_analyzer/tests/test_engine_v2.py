"""Canonical v2 contract, deterministic calculations, and safety controls."""
import copy
import pandas as pd
import pytest
from engine.spec import default_spec, validate_spec
from engine.pipeline import execute, preflight
from engine.drivers import materiality_threshold
from engine.v2rules import apply_classification
from engine.joins import apply_source_joins
from engine.evidence import format_delta
from engine.narrative_check import check_narrative


def spec():
    value = default_spec()
    value["roles"].update(value="Amount", period="Period", dimensions=["Region"], driver_text=["Text"])
    value["comparison"] = {"type": "MoM", "base": {"months": ["2026-04"]}, "current": {"months": ["2026-05"]}}
    value["measures"] = {"amount": {"agg": "sum", "col": "{roles.value}"}}
    value["views"] = [{"name": "regions", "keys": ["Region"], "measures": ["amount"], "compare": True}]
    value["drivers"].update(view="regions", measure="amount", materiality={"mode": "abs", "abs": 0})
    return value


def frame():
    return pd.DataFrame({"Period": ["APR-26", "MAY-26"], "Amount": [100, 150], "Region": ["EMEA", "EMEA"], "Text": ["Cooling plant", "cooling repair"], "PO": [" 001 ", "999"]})


def test_value_netting_nulls_and_direct_filter_sign_flip():
    df, settings = frame(), spec()
    df["Debit"], df["Credit"] = [100, 200], [None, 50]
    settings["roles"].update(debit="Debit", credit="Credit")
    settings["value_rules"] = {"source": "debit_minus_credit", "flip_sign_when": [{"col": "Period", "op": "eq", "val": "MAY-26"}]}
    result = execute(df, settings)
    assert (result["base"], result["current"], result["delta"]) == (100, -150, -250)
    assert df["Amount"].tolist() == [100, 150]


def test_canonical_composite_join_normalization_unmatched_and_fanout():
    df = frame()
    lookup = pd.DataFrame({"PO Number": ["1", "01"], "Status": ["Open", "Duplicate"]})
    join = {"source": "open", "on": [{"left": "PO", "right": "PO Number"}], "how": "left", "key_normalise": ["trim", "upper", "lstrip_zeros"], "columns": ["Status"], "prefix": "po_", "dedupe_right": "first"}
    joined, audit = apply_source_joins(df, [join], {"open": lookup})
    assert len(joined) == len(df) and joined.iloc[0]["po_Status"] == "Open"
    assert audit[0]["unmatched_rows"] == 1 and not audit[0]["fanout"]
    settings = spec()
    settings["joins"] = [dict(join, dedupe_right="error")]
    controls = preflight(df, settings, {"open": lookup})
    assert next(item for item in controls if item["id"] == "join_fanout")["status"] == "stop"
    with pytest.raises(ValueError, match="blocked"):
        execute(df, settings, {"open": lookup})


def test_classification_first_match_review_and_value_coverage():
    settings = spec()
    settings["classification"] = {"source_cols": ["{roles.driver_text}"], "target_col": "Category", "rules": [
        {"keyword": "cooling", "category": "Cooling", "match": "contains", "reviewed": True},
        {"keyword": "repair", "category": "Repairs", "match": "contains", "reviewed": False},
    ], "fallback": "Other", "case_sensitive": False}
    df = frame()
    df.loc[1, "Text"] = "Unknown"
    result = execute(df, settings)
    assert result["classification"]["row_coverage"] == 50
    assert result["classification"]["value_coverage"] == 40
    assert result["classification_review"][0]["reviewed"] in (True, False)
    assert next(item for item in result["controls"] if item["id"] == "classification_coverage")["status"] == "warn"
    overlapping = apply_classification(frame(), settings["classification"], settings["roles"])
    assert overlapping["Category"].tolist() == ["Cooling", "Cooling"]


@pytest.mark.parametrize("mode,expected", [("abs", 30), ("pct_of_total", 10), ("max_of", 30), ("min_of", 10)])
def test_materiality_fractional_modes(mode, expected):
    assert materiality_threshold({"mode": mode, "abs": 30, "pct": .1, "basis": "abs_total_movement"}, 100, 200) == expected


def test_partial_period_and_deterministic_run():
    df = pd.concat([frame().iloc[[0]]] * 5 + [frame().iloc[[1]]], ignore_index=True)
    result = execute(df, spec())
    assert result["partial_months_used"] == ["2026-05"]
    assert next(item for item in result["controls"] if item["id"] == "partial_period_used")["status"] == "warn"
    assert execute(df, spec()) == result
    assert result["materiality_threshold"] == 0


def test_commentary_currency_words_and_amount_first():
    assert format_delta(-1500, {"units": "K", "decimals": 1, "currency_symbol": "€"}) == "-€1.5K"
    assert format_delta(-1500, {"units": "K", "sign_style": "fav_unfav", "favorable_when": "negative"}) == "$1.5K favorable"
    evidence = {"drivers": [{"driver_id": "d1", "delta_fmt": "+$1.0K", "top_texts": []}], "commentary_rules": {"max_line_words": 4}}
    assert check_narrative({"lines": [{"driver_id": "d1", "text": "+$1.0K costs increased."}]}, evidence)["ok"]
    assert not check_narrative({"lines": [{"driver_id": "d1", "text": "Costs +$1.0K."}]}, evidence)["ok"]
    assert not check_narrative({"lines": [{"driver_id": "d1", "text": "+$1.0K costs increased without any supporting evidence."}]}, evidence)["ok"]

def test_column_rename_mapping_keeps_uncertain_roles_visible():
    from engine.mapping import remap_columns
    settings = spec()
    candidate, renamed, missing = remap_columns(settings, ["period", "Amount", "Region", "Text"])
    assert renamed == {"Period": "period"} and not missing
    assert candidate["roles"]["period"] == "period"
    assert settings["roles"]["period"] == "Period"


def test_subcent_inputs_round_only_at_financial_output_boundary():
    settings = spec()
    df = pd.DataFrame({"Period": ["APR-26", "APR-26", "MAY-26"], "Amount": [.0049, .0049, 0], "Region": ["EMEA"] * 3, "Text": ["Repair"] * 3})
    result = execute(df, settings)
    assert result["base"] == .01 and result["delta"] == -.01
