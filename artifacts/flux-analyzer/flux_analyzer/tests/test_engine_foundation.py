"""Ingestion, profiles, period normalization, expression security and spec tests."""
from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from engine.ingest import list_sheets, preview, load_source, detect_header_row, union_sources
from engine.profile import profile, distinct_values, value_counts_combo
from engine.periods import parse_period, resolve_comparison, months_for_period
from engine.expr import evaluate, filter_mask
from engine.spec import default_spec, validate_spec, migrate_spec, resolve_tokens, save_spec, load_spec, validate_spec_against_data
from engine.patches import apply_patch, diff_spec
from engine.money import total

def test_csv_selection_and_cache(tmp_path: Path) -> None:
    path = tmp_path / "book.csv"
    path.write_text("Report,,\nIgnore, Amount ,Amount\nx,1.10,2.20\n")
    assert list_sheets(path) == ["(csv)"]
    grid = preview(path)
    assert grid[0][0] == "Report"
    assert detect_header_row(grid) == 2
    frame = load_source(path, None, 2, "B", cache_dir=tmp_path / "cache")
    assert list(frame) == ["Amount", "Amount_2"]
    assert total(frame.Amount) == 1.1
    pd.testing.assert_frame_equal(frame, load_source(path, None, 2, "B", cache_dir=tmp_path / "cache"))

def test_xlsx_exact_sheet_names(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    pd.DataFrame({"Amount": [1, 2]}).to_excel(path, sheet_name="Open PO Report ", index=False)
    assert list_sheets(path) == ["Open PO Report "]
    assert len(load_source(path, "Open PO Report ", 1, "A")) == 2

def test_union_and_profiles(golden: pd.DataFrame) -> None:
    combined = union_sources([golden, golden], tag_column="Source", tags=["Q1", "Q2"])
    assert len(combined) == len(golden) * 2
    with pytest.raises(ValueError, match="different columns"):
        union_sources([golden, golden.drop(columns="Country")])
    desc = profile(combined)
    assert all(len(c["samples"]) <= 5 and all(len(v) <= 60 for v in c["samples"]) for c in desc["columns"])
    assert distinct_values(golden, "Country", value_col="Functional_Net")[0]["count"] == len(golden)
    assert value_counts_combo(golden, ["Country", "Bucket"])

@pytest.mark.parametrize("value,expected", [("JAN-26", "2026-01"), ("Jan-2026", "2026-01"), ("2026-01", "2026-01"), ("01/2026", "2026-01"), ("Q1 2026", "2026-01"), ("FY26 Q1", "2026-01"), (date(2026, 1, 3), "2026-01")])
def test_period_formats(value: object, expected: str) -> None:
    assert parse_period(value) == expected

def test_fiscal_and_missing_months() -> None:
    assert months_for_period("FY26 Q4", {"start_month": 4}) == ["2027-01", "2027-02", "2027-03"]
    c = resolve_comparison({"base": {"period": "Q1 2026"}, "current": {"period": "Q2 2026"}}, ["2026-01", "2026-02", "2026-03", "2026-04"])
    assert c["current"]["first_month"] == "2026-04"
    assert len(c["partial_periods"]) == 2

def test_safe_expressions(golden: pd.DataFrame) -> None:
    assert evaluate("abs(Functional_Net) > 1800 and Bucket in ['Accrual - Current']", golden).sum() == 2
    assert filter_mask(golden, [{"col": "Country", "op": "startswith", "val": "Nether"}]).all()
    assert evaluate("not isnull(Functional_Net)", golden).all()
    assert evaluate("A + B == 0.3", pd.DataFrame({"A": [0.1], "B": [0.2]})).all()
    for expression in ["__import__('os').system('ls')", "Functional_Net.__class__", "Functional_Net[0]", "[x for x in Functional_Net]", "(lambda: 1)()", "2 ** 99999"]:
        with pytest.raises(ValueError):
            evaluate(expression, golden)

def test_spec_validation_tokens_and_storage(tmp_path: Path) -> None:
    spec = default_spec()
    validate_spec(spec)
    spec["roles"]["value"] = "Amount"
    spec["measures"] = {"amount": {"agg": "sum", "col": "{roles.value}"}}
    resolved = resolve_tokens(spec, {"base": {"months": ["2026-01"]}, "current": {}})
    assert resolved["measures"]["amount"]["col"] == "Amount"
    assert validate_spec_against_data(spec, []) == ["Amount"]
    path = save_spec(spec, tmp_path, "../../my flux")
    assert path.parent == tmp_path
    assert load_spec(path)["roles"]["value"] == "Amount"
    spec["scope"] = [{"col": "Amount", "op": "execute", "val": "bad"}]
    with pytest.raises(ValueError):
        validate_spec(spec)

def test_migrate_v1_month_labels_and_materiality() -> None:
    legacy = default_spec()
    legacy["spec_version"] = "1.0"
    legacy["skill"] = "rm_flux"
    legacy["periods"]["format_in"] = "MON-YY"
    legacy["comparison"]["base"] = {"months": ["JAN-26", "FEB-26"]}
    legacy["comparison"]["current"] = {"period": "Q1 2026"}
    legacy["drivers"]["materiality_abs"] = 42
    migrated = migrate_spec(legacy)
    assert migrated["spec_version"] == "2.0"
    assert migrated["preset"]["id"] == "rm_flux"
    assert migrated["comparison"]["base"]["months"] == ["2026-01", "2026-02"]
    assert migrated["comparison"]["current"]["months"] == ["2026-01", "2026-02", "2026-03"]
    assert migrated["drivers"]["materiality"] == {"mode": "abs", "abs": 42}
    assert "materiality_abs" not in migrated["drivers"]
    assert validate_spec(legacy)["spec_version"] == "2.0"
    assert legacy["comparison"]["base"]["months"][0] == "JAN-26"

def test_spec_reports_all_validation_errors() -> None:
    spec = default_spec()
    spec["flux_name"] = ""
    spec["unknown_setting"] = True
    spec["scope"] = [{"col": "Amount", "op": "invalid", "val": 1}]
    with pytest.raises(ValueError) as error:
        validate_spec(spec)
    message = str(error.value)
    assert "flux_name" in message and "unknown_setting" in message and "scope.0.op" in message

def test_json_patch_validation_audit_and_round_trip() -> None:
    original = default_spec()
    audit: list[dict] = []
    update = {"op": "replace", "path": "/flux_name", "value": "Reviewed flux"}
    modified = apply_patch(original, [update], "user", "Renamed in the editor", audit)
    assert modified["flux_name"] == "Reviewed flux"
    assert audit[0]["actor"] == "user" and audit[0]["path"] == "/flux_name"
    patch = diff_spec(modified, original)
    restored = apply_patch(modified, patch, "undo", "Undo: Renamed in the editor")
    assert restored == original
    with pytest.raises(ValueError):
        apply_patch(original, [{"op": "replace", "path": "/flux_name", "value": ""}], "agent", "Invalid suggestion", audit)
    assert len(audit) == 1

def test_json_patch_array_and_test_operations() -> None:
    spec = default_spec()
    updated = apply_patch(spec, [
        {"op": "test", "path": "/roles/keys", "value": []},
        {"op": "add", "path": "/roles/keys/-", "value": "Cost Center"}
    ], "user", "Add a grouping key")
    assert updated["roles"]["keys"] == ["Cost Center"]

def test_exact_cent_math() -> None:
    assert total(["0.10"] * 10000) == 1000.0
    assert total(["1835.16", "-1813.59", "1804.68", "-1847.66"]) == -21.41
