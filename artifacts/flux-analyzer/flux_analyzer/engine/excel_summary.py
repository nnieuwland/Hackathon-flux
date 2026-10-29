"""The Summary sheet: the overview a reviewer reads first."""
from xlsxwriter.utility import xl_col_to_name

from .excel_style import PRIMARY, PRIMARY_DESCRIPTIONS, PRIMARY_GROUPS, STATUS_TEXT, SUMMARY_DRIVERS, Pack, landscape, months_text, parse_time, ref


def write_summary(pack: Pack, run: dict, export: dict, formula_mode: bool, formulas, items: dict, drivers: list, threshold: float,
                  plan: list[dict], cols: dict, driver_rows: dict) -> None:
    """The overview a reviewer reads first: comparison, totals, status, key drivers and a guide to the tabs."""
    sheet = pack.sheets["Summary"]
    book = pack.book
    sheet.hide_gridlines(2)
    sheet.set_column(0, 0, 34)
    sheet.set_column(1, 4, 17)
    sheet.set_column(5, 5, 26)
    sheet.set_column(6, 6, 70)
    landscape(sheet, repeat_header=False)
    stamp = run.get("run_stamp", {})
    sheet.set_row(0, 30)
    pack.text_cell(sheet, 0, 0, run.get("name") or "Flux review", pack.title)
    created = parse_time(stamp.get("created") or run.get("created"))
    prepared = f" · Prepared {created:%d %b %Y %H:%M} UTC" if created else ""
    sheet.write_string(1, 0, f"{months_text(export.get('current_months') or [])} compared with {months_text(export.get('base_months') or [])}{prepared}", pack.subtitle)

    # Headline totals. TotalBase / TotalCurrent anchor every other check in the workbook.
    for col, label in enumerate(("Base total", "Current total", "Movement", "Movement %", "Threshold")):
        sheet.write_string(3, col, label, pack.kpi_label)
    if formula_mode:
        sheet.write_formula(4, 0, formulas.total("Base"), pack.kpi, float(run.get("base") or 0))
        sheet.write_formula(4, 1, formulas.total("Current"), pack.kpi, float(run.get("current") or 0))
    else:
        sheet.write_number(4, 0, float(run.get("base") or 0), pack.kpi)
        sheet.write_number(4, 1, float(run.get("current") or 0), pack.kpi)
    base, delta = float(run.get("base") or 0), float(run.get("delta") or 0)
    sheet.write_formula(4, 2, "=B5-A5", pack.kpi, delta)
    sheet.write_formula(4, 3, '=IF(A5=0,"",C5/ABS(A5))', pack.kpi_pct, delta / abs(base) if base else "")
    sheet.write_formula(4, 4, "=Threshold", pack.kpi, threshold)
    sheet.set_row(4, 22)
    book.define_name("TotalBase", "=Summary!$A$5")
    book.define_name("TotalCurrent", "=Summary!$B$5")

    # Explanation status.
    status_letter = xl_col_to_name(cols["status"])
    status_range = f"Commentary!${status_letter}$2:${status_letter}${max(2, len(drivers) + 1)}"
    counts = {status: sum(1 for item in items.values() if item.get("status") == status) for status in STATUS_TEXT}
    sheet.merge_range(6, 0, 6, 6, "", pack.section)
    sheet.write_string(6, 0, "Explanation status", pack.section)
    for col, status in enumerate(("needs_explanation", "ai_review", "confirmed", "below_threshold")):
        sheet.write_string(7, col, STATUS_TEXT[status], pack.kpi_label)
        sheet.write_formula(8, col, f'=COUNTIF({status_range},"{STATUS_TEXT[status]}")', pack.kpi_count, counts[status])
    sheet.set_row(7, 28)
    if not items:
        sheet.write_string(9, 0, "Explanation status is not available for this report.", pack.muted)
    elif counts["needs_explanation"] or counts["ai_review"]:
        waiting = counts["needs_explanation"] + counts["ai_review"]
        pack.link_to(sheet, 9, 0, "Needs Explanation", f"{waiting} movement{'s' if waiting != 1 else ''} still need{'s' if waiting == 1 else ''} a person to write or check the explanation — open Needs Explanation")
    else:
        sheet.write_string(9, 0, "Every reported movement is confirmed by a person or below the threshold.", pack.ok)

    # Headline.
    row = 11
    commentary = run.get("commentary", {})
    sheet.merge_range(row, 0, row, 6, "", pack.section)
    sheet.write_string(row, 0, "Headline", pack.section)
    headline = str(commentary.get("headline") or "") or (str(commentary.get("text") or "").splitlines() or [""])[0]
    sheet.merge_range(row + 1, 0, row + 1, 6, "", pack.text)
    pack.text_cell(sheet, row + 1, 0, headline or "No headline was written for this report.", pack.text if headline else pack.muted)
    sheet.set_row(row + 1, 15 * max(1, min(6, len(headline) // 150 + 1)))

    # Key drivers, linked to the Commentary sheet so the numbers stay traceable.
    row += 3
    sheet.merge_range(row, 0, row, 6, "", pack.section)
    sheet.write_string(row, 0, "Key drivers", pack.section)
    row += 1
    for col, label in enumerate(("Movement", "Base", "Current", "Change", "Change %", "Status", "Explanation")):
        sheet.write_string(row, col, label, pack.header)
    lines = {line.get("driver_id"): line for line in commentary.get("lines", [])}
    shown = drivers[:SUMMARY_DRIVERS]
    if not shown:
        row += 1
        sheet.write_string(row, 0, "No movements were reported.", pack.muted)
    for driver in shown:
        row += 1
        source = driver_rows[driver.get("driver_id")]
        item = items.get(driver.get("driver_id"), {})
        pack.text_cell(sheet, row, 0, driver.get("label", ""))
        base_value, delta_value = float(driver.get("base") or 0), float(driver.get("delta") or 0)
        for col, key, cached in ((1, "base", base_value), (2, "current", float(driver.get("current") or 0)), (3, "change", delta_value)):
            sheet.write_formula(row, col, "=" + ref("Commentary", source, cols[key]), pack.money, cached)
        sheet.write_formula(row, 4, f'=IF(B{row + 1}=0,"",D{row + 1}/ABS(B{row + 1}))', pack.pct, delta_value / abs(base_value) if base_value else "")
        status = item.get("status")
        sheet.write_string(row, 5, STATUS_TEXT.get(status, "—"), pack.warn if status == "needs_explanation" else pack.ok if status == "confirmed" else pack.text)
        text = item.get("text") or lines.get(driver.get("driver_id"), {}).get("text", "")
        pack.text_cell(sheet, row, 6, text)
    if len(drivers) > len(shown):
        row += 1
        pack.link_to(sheet, row, 0, "Commentary", f"{len(drivers) - len(shown)} more movements on the Commentary sheet")

    # Contents: every tab, grouped, with a link.
    row += 2
    sheet.merge_range(row, 0, row, 6, "", pack.section)
    sheet.write_string(row, 0, "What is in this workbook", pack.section)
    contents = [{"name": name, "group": PRIMARY_GROUPS[name], "description": PRIMARY_DESCRIPTIONS[name]} for name in PRIMARY] + plan
    group = None
    for entry in contents:
        if entry["group"] != group:
            group = entry["group"]
            row += 2 if group != PRIMARY_GROUPS["Summary"] else 1
            sheet.write_string(row, 0, group, pack.label)
        row += 1
        pack.link_to(sheet, row, 0, entry["name"])
        sheet.merge_range(row, 1, row, 6, "", pack.text)
        sheet.write_string(row, 1, entry["description"], pack.text)

    # How to trust the numbers.
    row += 2
    sheet.merge_range(row, 0, row, 6, "", pack.section)
    sheet.write_string(row, 0, "About these numbers", pack.section)
    notes = [("How amounts are calculated", "Formulas over the Data sheet, checked against the engine before saving." if formula_mode else "Engine-calculated values. " + (export.get("reason") or "")),
             ("Checked commentary", "Explanations marked Confirmed were checked by a person. Explanations marked 'Explained by AI — please review' are drafts."),
             ("Currency", f"Amounts are in {pack.symbol}." if pack.symbol else "Amounts are shown in the source currency."),
             ("Run ID", stamp.get("run_id") or run.get("id") or ""), ("Setup fingerprint (SHA-256)", stamp.get("spec_sha256") or "")]
    for label, value in notes:
        if not value:
            continue
        row += 1
        sheet.write_string(row, 0, label, pack.label)
        sheet.merge_range(row, 1, row, 6, "", pack.text)
        pack.text_cell(sheet, row, 1, value)
    sheet.activate()
