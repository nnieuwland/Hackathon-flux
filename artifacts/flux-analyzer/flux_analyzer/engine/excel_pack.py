"""Formula-backed Excel review pack.

Primary sheets (in order): Summary, Needs Explanation, Commentary, Drill-down,
Data checks, Data, Settings. Amounts on the primary sheets are SUMPRODUCT
formulas over the Data sheet, using the named ranges BaseMonths,
CurrentMonths and Threshold, with the engine's values cached so the file reads
correctly before Excel recalculates. When a setup cannot be expressed as exact
formulas the pack says so and writes the engine's values instead.

Supporting-detail and audit-trail sheets follow, grouped by tab colour and
listed with links on the Summary sheet. Uploaded or edited text is always
written as text, and text that starts like a formula is prefixed with an
apostrophe on every sheet.
"""
from decimal import Decimal
from pathlib import Path

import pandas as pd
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

from .excel_appendix import appendix_plan, write_table
from .excel_style import (GROUP_COLOURS, MAX_EXPORT_ROWS, MAX_FORMULA_LINES, PRIMARY, PRIMARY_GROUPS, STATUS_TEXT, TOLERANCE,  # noqa: F401  (re-exported)
                          Pack, excel_safe, landscape, ref)
from .excel_summary import write_summary
from .money import decimal, money


# ---------------------------------------------------------------- export data

def build_export_data(frame: pd.DataFrame, resolved: dict, comparison: dict, result: dict) -> dict:
    """Group prepared rows by key + month (+ version) and prove they reproduce the engine."""
    settings, measures = resolved.get("drivers", {}), resolved.get("measures", {})
    view_name = settings.get("view", resolved["views"][0]["name"])
    measure_name = settings.get("measure", next(iter(measures)))
    view = next(item for item in resolved["views"] if item["name"] == view_name)
    measure = measures[measure_name]
    base, current = comparison["base"], comparison["current"]
    info = {"view": view_name, "measure": measure_name, "keys": [str(key) for key in view["keys"]], "base_months": list(base.get("months", [])), "current_months": list(current.get("months", [])),
            "base_version": None, "current_version": None, "columns": [], "rows": []}

    def fallback(reason: str) -> dict:
        return {**info, "mode": "engine", "reason": reason}

    if measure.get("agg") != "sum":
        return fallback("The amount is not a simple sum.")
    if measure.get("filter") or measure.get("slice") == "none":
        return fallback("The amount has its own filter.")
    if base.get("filters") or current.get("filters"):
        return fallback("One side of the comparison has extra filters.")
    if not info["base_months"] or not info["current_months"]:
        return fallback("One of the periods has no months.")
    if view.get("joins"):
        return fallback("The movement lines use matched lookup fields.")
    if not view.get("compare", True):
        return fallback("The movement view is not a comparison.")
    scenario_col = None
    for side, key in ((base, "base_version"), (current, "current_version")):
        value = side.get("scenario")
        if isinstance(value, list):
            if len(value) != 1:
                return fallback("A version filter uses several values.")
            value = value[0]
        if value is not None:
            if any(char in str(value) for char in "*?~"):
                return fallback("A version filter contains wildcard characters.")
            scenario_col = resolved.get("roles", {}).get("scenario") or side.get("scenario_col")
            if not scenario_col or scenario_col not in frame:
                return fallback("The version column could not be found.")
            info[key] = str(value)
    col, keys = measure["col"], info["keys"]
    if col not in frame or "__month" not in frame or any(key not in frame for key in keys):
        return fallback("A column needed for the formulas is missing.")
    group_cols = {}
    for key in keys:
        group_cols[key] = frame[key].map(lambda value: str(value) if pd.notna(value) else "(empty)")
    group_cols["__month"] = frame["__month"].astype(str)
    if scenario_col:
        group_cols["__version"] = frame[scenario_col].astype(str)
    for name, series in group_cols.items():
        values = set(series.unique())
        label = "Month" if name == "__month" else "Version" if name == "__version" else name
        if len({value.casefold() for value in values}) != len(values):
            return fallback(f"'{label}' has values that differ only in capital letters, which Excel treats as the same.")
        # The workbook writes keys through the text guard; two values that become the same cell text
        # (for example "=North" and "'=North") would be added together by the formulas.
        if len({str(excel_safe(value)).casefold() for value in values}) != len(values):
            label_text = f"'{label}' has values that look the same once protected against formulas"
            return fallback(f"{label_text}, so their lines cannot be told apart by formulas.")
    table = pd.DataFrame(group_cols)
    table["__amount"] = frame[col].map(lambda value: decimal(value) if pd.notna(value) else Decimal(0))
    grouped = table.groupby(list(group_cols), sort=True, dropna=False)["__amount"].apply(lambda values: sum(values, Decimal(0)))
    if len(grouped) > MAX_EXPORT_ROWS:
        return fallback(f"The data has more than {MAX_EXPORT_ROWS:,} grouped lines.")
    rows = [[*(index if isinstance(index, tuple) else (index,)), money(value)] for index, value in grouped.items()]

    # Self-check: the workbook's exact-match sums must equal every engine line.
    month_at, version_at = len(keys), len(keys) + 1 if scenario_col else None
    sums = {}
    for row in rows:
        key = tuple(row[:len(keys)])
        for side, months, version in (("base", info["base_months"], info["base_version"]), ("current", info["current_months"], info["current_version"])):
            if row[month_at] in months and (version is None or row[version_at] == version):
                sums[(key, side)] = sums.get((key, side), Decimal(0)) + decimal(row[-1])
    for line in result.get("views", {}).get(view_name, []):
        key = tuple(str(line.get(name)) for name in keys)
        for side in ("base", "current"):
            if abs(float(sums.get((key, side), Decimal(0))) - float(line.get(f"{measure_name}_{side}") or 0)) > TOLERANCE:
                return fallback("The workbook check did not match the engine, so engine values are used.")
    return {**info, "mode": "formula", "reason": "", "columns": [*keys, "Month", *(["Version"] if scenario_col else []), "Amount"], "rows": rows}


class Formulas:
    """Exact-match SUMPRODUCT formulas over the Data sheet."""

    def __init__(self, export: dict):
        self.keys = export["keys"]
        last = len(export["rows"]) + 1
        def rng(index):
            letter = xl_col_to_name(index)
            return f"Data!${letter}$2:${letter}${last}"
        self.key_ranges = [rng(index) for index in range(len(self.keys))]
        self.month = rng(len(self.keys))
        self.version = rng(len(self.keys) + 1) if "Version" in export["columns"] else None
        self.amount = rng(len(export["columns"]) - 1)
        self.versions = {"Base": export.get("base_version"), "Current": export.get("current_version")}

    def side(self, side: str) -> list[str]:
        conditions = [f"ISNUMBER(MATCH({self.month},{side}Months,0))"]
        if self.versions[side] is not None:
            conditions.append(f"({self.version}={side}Version)")
        return conditions

    def total(self, side: str, key_cells: list[str] | None = None) -> str:
        conditions = [f"({rng}={cell})" for rng, cell in zip(self.key_ranges, key_cells or [])] + self.side(side)
        return "=SUMPRODUCT(" + "*".join(f"({item})" if not item.startswith("(") else item for item in conditions) + f"*{self.amount})"


# ---------------------------------------------------------------- the pack

def render_excel(run: dict, directory: Path | None = None) -> Path:
    from .explanations import explanation_items
    directory = directory or Path(run["directory"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "flux_pack.xlsx"
    spec = run.get("spec", {})
    pack = Pack(path, spec.get("commentary", {}).get("currency_symbol", ""))
    book = pack.book
    export = run.get("export_data") or {"mode": "engine", "reason": "This report was created before formula-backed workbooks were available.", "keys": [], "columns": [], "rows": [],
                                        "base_months": spec.get("comparison", {}).get("base", {}).get("months", []), "current_months": spec.get("comparison", {}).get("current", {}).get("months", []),
                                        "measure": spec.get("drivers", {}).get("measure", "amount"), "view": spec.get("drivers", {}).get("view")}
    formula_mode = export["mode"] == "formula" and bool(export["rows"])
    if formula_mode and any(key not in driver.get("dimensions", {}) for driver in run.get("drivers", []) if driver.get("driver_id") != "others" for key in export["keys"]):
        export = {**export, "mode": "engine", "reason": "A grouping field is not text, so its lines cannot be matched by formulas."}
        formula_mode = False
    formulas = Formulas(export) if formula_mode else None
    keys = export.get("keys", []) if formula_mode else []
    measure = export.get("measure") or "amount"
    for name in PRIMARY:
        pack.sheet(name, GROUP_COLOURS[PRIMARY_GROUPS[name]])
    summary, needs, commentary, drill, checks, data, settings = (pack.sheets[name] for name in PRIMARY)
    items = {item["driver_id"]: item for item in (explanation_items(run) if run.get("evidence") else [])}
    threshold = float(run.get("materiality_threshold") or 0)
    plan = appendix_plan(run, directory, measure)
    stamp = run.get("run_stamp", {})

    # Settings first: the named ranges every formula depends on.
    settings.set_column(0, 0, 30)
    settings.set_column(1, 1, 60)
    settings.write_string(0, 0, "Report settings", pack.title)
    row = 2
    for label, value, kind in (("Report", run.get("name", ""), "text"), ("Run ID", run.get("id", ""), "text"), ("Created (UTC)", run.get("created", ""), "date"),
                               ("Comparison", spec.get("comparison", {}).get("type", ""), "text")):
        settings.write_string(row, 0, label, pack.label)
        pack.value(settings, row, 1, value, kind)
        row += 1
    for side, months in (("Base", export.get("base_months") or [""]), ("Current", export.get("current_months") or [""])):
        settings.write_string(row, 0, f"{side} months", pack.label)
        for offset, month in enumerate(months):
            settings.write_string(row + offset, 1, str(month))
        book.define_name(f"{side}Months", f"=Settings!$B${row + 1}:$B${row + len(months)}")
        row += len(months)
    for side in ("Base", "Current"):
        version = export.get(f"{side.lower()}_version")
        settings.write_string(row, 0, f"{side} version", pack.label)
        settings.write_string(row, 1, str(excel_safe(version)) if version else "All versions")
        book.define_name(f"{side}Version", f"=Settings!$B${row + 1}")
        row += 1
    settings.write_string(row, 0, "Threshold", pack.label)
    settings.write_number(row, 1, threshold, pack.money)
    book.define_name("Threshold", f"=Settings!$B${row + 1}")
    row += 1
    drivers_settings = spec.get("drivers", {})
    for label, value, kind in (("Movements shown (top N)", drivers_settings.get("top_n", 15), "int"), ("Remaining movements label", drivers_settings.get("others_label", "Other items"), "text"),
                               ("Currency", pack.symbol or "Not set", "text"),
                               ("How amounts are calculated", "Formulas over the Data sheet" if formula_mode else "Engine-calculated values", "text"),
                               ("Why", export.get("reason") or "Every line was checked against the engine before saving.", "text"),
                               ("Setup fingerprint (SHA-256)", stamp.get("spec_sha256", ""), "text")):
        settings.write_string(row, 0, label, pack.label)
        pack.value(settings, row, 1, value, kind)
        row += 1
    settings.write_string(row + 1, 0, "Change Threshold to see which movements cross it. The list of movements was chosen when the report ran; run the report again to change months, versions or the list.", pack.muted)

    # Data: grouped rows the formulas sum. Keys go through the same text guard as every cell that matches them.
    if formula_mode:
        pack.headers(data, 0, export["columns"], [22] * (len(export["columns"]) - 1) + [16])
        for index, values in enumerate(export["rows"], start=1):
            for col, value in enumerate(values):
                if col == len(values) - 1:
                    data.write_number(index, col, float(value), pack.money)
                else:
                    pack.text_cell(data, index, col, value)
        data.freeze_panes(1, 0)
        data.autofilter(0, 0, len(export["rows"]), len(export["columns"]) - 1)
    else:
        data.set_column(0, 0, 90)
        data.write_string(0, 0, "Grouped data is not included", pack.header)
        pack.text_cell(data, 1, 0, "Amounts in this workbook are the engine's calculated values. " + (export.get("reason") or ""))

    # Commentary: one line per reported movement.
    drivers = run.get("drivers", [])
    lines = {line.get("driver_id"): line for line in run.get("commentary", {}).get("lines", [])}
    columns = ["Movement", *keys, "Base", "Current", "Change", "Change %", "Above threshold?", "Status", "Explanation", "Written by", "Confirmed by", "Confirmed (UTC)", "Evidence"]
    pack.headers(commentary, 0, columns, [34, *[18] * len(keys), 16, 16, 16, 11, 14, 24, 70, 12, 18, 17, 50])
    base_col = 1 + len(keys)
    cur_col, chg_col, pct_col, imp_col, status_col = base_col + 1, base_col + 2, base_col + 3, base_col + 4, base_col + 5
    driver_rows = {}
    first = 1
    for index, driver in enumerate(drivers, start=1):
        driver_rows[driver.get("driver_id")] = index
        item = items.get(driver.get("driver_id"), {})
        pack.text_cell(commentary, index, 0, driver.get("label", ""))
        is_other = driver.get("driver_id") == "others"
        for offset, key in enumerate(keys):
            pack.text_cell(commentary, index, 1 + offset, "" if is_other else str(driver.get("dimensions", {}).get(key, "")))
        base_value, current_value = float(driver.get("base") or 0), float(driver.get("current") or 0)
        cell = lambda col: xl_rowcol_to_cell(index, col)
        if formula_mode and not is_other:
            key_cells = [xl_rowcol_to_cell(index, 1 + offset, col_abs=True) for offset in range(len(keys))]
            commentary.write_formula(index, base_col, formulas.total("Base", key_cells), pack.money, base_value)
            commentary.write_formula(index, cur_col, formulas.total("Current", key_cells), pack.money, current_value)
        elif formula_mode and is_other:
            above = f"{xl_rowcol_to_cell(first, base_col)}:{xl_rowcol_to_cell(max(first, index - 1), base_col)}" if index > first else None
            above_cur = f"{xl_rowcol_to_cell(first, cur_col)}:{xl_rowcol_to_cell(max(first, index - 1), cur_col)}" if index > first else None
            commentary.write_formula(index, base_col, f"=TotalBase-SUM({above})" if above else "=TotalBase", pack.money, base_value)
            commentary.write_formula(index, cur_col, f"=TotalCurrent-SUM({above_cur})" if above_cur else "=TotalCurrent", pack.money, current_value)
        else:
            commentary.write_number(index, base_col, base_value, pack.money)
            commentary.write_number(index, cur_col, current_value, pack.money)
        delta = float(driver.get("delta") or 0)
        commentary.write_formula(index, chg_col, f"={cell(cur_col)}-{cell(base_col)}", pack.money, delta)
        commentary.write_formula(index, pct_col, f'=IF({cell(base_col)}=0,"",{cell(chg_col)}/ABS({cell(base_col)}))', pack.pct, delta / abs(base_value) if base_value else "")
        if is_other:
            commentary.write_string(index, imp_col, "Grouped", pack.text)
        else:
            commentary.write_formula(index, imp_col, f'=IF(ABS({cell(chg_col)})>=Threshold,"Yes","No")', pack.text, "Yes" if abs(delta) >= threshold else "No")
        status = item.get("status")
        commentary.write_string(index, status_col, STATUS_TEXT.get(status, "—"), pack.warn if status == "needs_explanation" else pack.ok if status == "confirmed" else pack.text)
        pack.text_cell(commentary, index, status_col + 1, item.get("text") or lines.get(driver.get("driver_id"), {}).get("text", ""))
        commentary.write_string(index, status_col + 2, {"ai": "AI", "user": "Person", "system": "Placeholder"}.get(item.get("origin"), ""), pack.text)
        pack.text_cell(commentary, index, status_col + 3, item.get("confirmed_by") or "")
        pack.value(commentary, index, status_col + 4, item.get("confirmed_at"), "date")
        pack.text_cell(commentary, index, status_col + 5, "; ".join(f"{text.get('text')} ({text.get('delta_fmt')})" for text in driver.get("top_texts", []) if text.get("text")))
    commentary.freeze_panes(1, 1)
    landscape(commentary)
    if drivers:
        commentary.autofilter(0, 0, len(drivers), len(columns) - 1)

    write_summary(pack, run, export, formula_mode, formulas, items, drivers, threshold, plan,
                  {"base": base_col, "current": cur_col, "change": chg_col, "pct": pct_col, "status": status_col}, driver_rows)

    # Needs Explanation: what a person still has to do.
    columns = ["Movement", "Change", "Base", "Current", "Status", "Current text", "What is needed", "Supporting descriptions"]
    pack.headers(needs, 0, columns, [34, 16, 16, 16, 24, 60, 40, 60])
    todo = [driver for driver in drivers if items.get(driver.get("driver_id"), {}).get("status") in ("needs_explanation", "ai_review")]
    todo.sort(key=lambda driver: 0 if items[driver["driver_id"]]["status"] == "needs_explanation" else 1)
    if not todo:
        needs.write_string(1, 0, "Nothing needs explaining: every reported movement is confirmed or below the threshold." if items else "Explanation status is not available for this report.", pack.muted)
    for index, driver in enumerate(todo, start=1):
        item, source_row = items[driver["driver_id"]], driver_rows[driver["driver_id"]]
        pack.text_cell(needs, index, 0, driver.get("label", ""))
        for col, source_col, cached in ((1, chg_col, driver.get("delta")), (2, base_col, driver.get("base")), (3, cur_col, driver.get("current"))):
            needs.write_formula(index, col, "=" + ref("Commentary", source_row, source_col), pack.money, float(cached or 0))
        needs.write_string(index, 4, STATUS_TEXT[item["status"]], pack.warn if item["status"] == "needs_explanation" else pack.text)
        pack.text_cell(needs, index, 5, item.get("text") or "")
        needed = "Write the business reason and confirm it." if item["status"] == "needs_explanation" else "Check the AI draft against the evidence, then confirm or edit it."
        if item.get("issues"):
            needed += " " + " ".join(item["issues"])[:500]
        pack.text_cell(needs, index, 6, needed)
        pack.text_cell(needs, index, 7, "; ".join(f"{text.get('text')} ({text.get('delta_fmt')})" for text in driver.get("top_texts", []) if text.get("text")))
    needs.freeze_panes(1, 1)
    landscape(needs)

    # Drill-down: every line of the movement view, largest first.
    view_rows = sorted(run.get("views", {}).get(export.get("view") or "", []), key=lambda item: -abs(float(item.get(f"{measure}_delta") or 0)))
    reported = {tuple(str(driver.get("dimensions", {}).get(key, "")) for key in keys): driver.get("label") for driver in drivers if driver.get("driver_id") != "others"}
    others_label = next((driver.get("label") for driver in drivers if driver.get("driver_id") == "others"), "Other items")
    drill_keys = keys or [key for key in (view_rows[0].keys() if view_rows else []) if not str(key).startswith(f"{measure}_") and isinstance(view_rows[0].get(key), str)]
    columns = [*drill_keys, "Base", "Current", "Change", "Change %", "Above threshold?", "Reported as"]
    pack.headers(drill, 0, columns, [*[20] * len(drill_keys), 16, 16, 16, 11, 14, 30])
    use_formulas = formula_mode and len(view_rows) <= MAX_FORMULA_LINES
    b, c, d = len(drill_keys), len(drill_keys) + 1, len(drill_keys) + 2
    for index, line in enumerate(view_rows, start=1):
        for col, key in enumerate(drill_keys):
            pack.text_cell(drill, index, col, str(line.get(key, "")))
        base_value, current_value = float(line.get(f"{measure}_base") or 0), float(line.get(f"{measure}_current") or 0)
        if use_formulas:
            key_cells = [xl_rowcol_to_cell(index, col, col_abs=True) for col in range(len(drill_keys))]
            drill.write_formula(index, b, formulas.total("Base", key_cells), pack.money, base_value)
            drill.write_formula(index, c, formulas.total("Current", key_cells), pack.money, current_value)
        else:
            drill.write_number(index, b, base_value, pack.money)
            drill.write_number(index, c, current_value, pack.money)
        delta = float(line.get(f"{measure}_delta") or 0)
        drill.write_formula(index, d, f"={xl_rowcol_to_cell(index, c)}-{xl_rowcol_to_cell(index, b)}", pack.money, delta)
        drill.write_formula(index, d + 1, f'=IF({xl_rowcol_to_cell(index, b)}=0,"",{xl_rowcol_to_cell(index, d)}/ABS({xl_rowcol_to_cell(index, b)}))', pack.pct, delta / abs(base_value) if base_value else "")
        drill.write_formula(index, d + 2, f'=IF(ABS({xl_rowcol_to_cell(index, d)})>=Threshold,"Yes","No")', pack.text, "Yes" if abs(delta) >= threshold else "No")
        pack.text_cell(drill, index, d + 3, reported.get(tuple(str(line.get(key, "")) for key in keys), others_label) if keys else "")
    drill.freeze_panes(1, 0)
    landscape(drill)
    if view_rows:
        drill.autofilter(0, 0, len(view_rows), len(columns) - 1)

    # Data checks: the workbook must agree with the engine.
    pack.headers(checks, 0, ["Check", "Engine value", "Workbook value", "Difference", "Result"], [46, 18, 18, 14, 10])
    commentary_change = f"SUM(Commentary!${xl_col_to_name(chg_col)}$2:${xl_col_to_name(chg_col)}${max(2, len(drivers) + 1)})"
    drill_change = f"SUM('Drill-down'!${xl_col_to_name(d)}$2:${xl_col_to_name(d)}${max(2, len(view_rows) + 1)})"
    check_rows = [("Base total", run.get("base"), "=TotalBase", run.get("base")), ("Current total", run.get("current"), "=TotalCurrent", run.get("current")),
                  ("Movement lines add up to the total movement", run.get("delta"), "=" + commentary_change, sum(float(driver.get("delta") or 0) for driver in drivers)),
                  ("Drill-down lines add up to the total movement", run.get("delta"), "=" + drill_change, sum(float(line.get(f"{measure}_delta") or 0) for line in view_rows))]
    for index, (label, engine_value, formula, cached) in enumerate(check_rows, start=1):
        engine_value, cached = float(engine_value or 0), float(cached or 0)
        checks.write_string(index, 0, label, pack.text)
        checks.write_number(index, 1, engine_value, pack.money)
        checks.write_formula(index, 2, formula, pack.money, cached)
        checks.write_formula(index, 3, f"=C{index + 1}-B{index + 1}", pack.money, cached - engine_value)
        checks.write_formula(index, 4, f'=IF(ABS(D{index + 1})<{TOLERANCE},"OK","Check")', pack.ok, "OK" if abs(cached - engine_value) < TOLERANCE else "Check")
    row = len(check_rows) + 2
    checks.write_string(row, 0, "Data controls run before the report", pack.label)
    for offset, control in enumerate(run.get("controls", []), start=1):
        pack.text_cell(checks, row + offset, 0, control.get("id", ""))
        checks.write_string(row + offset, 1, {"pass": "Passed", "warn": "Warning", "stop": "Stopped"}.get(control.get("status"), str(excel_safe(str(control.get("status", ""))))), pack.text)
        pack.text_cell(checks, row + offset, 2, control.get("message", ""))
    checks.write_string(row + len(run.get("controls", [])) + 2, 0, "Full details are on the Data controls sheet.", pack.muted)
    checks.freeze_panes(1, 0)

    for entry in plan:
        worksheet = pack.sheet(entry["name"], GROUP_COLOURS[entry["group"]])
        write_table(pack, worksheet, entry["rows"], measure, entry["empty"])
    book.close()
    return path
