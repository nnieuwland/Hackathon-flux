"""Supporting-detail and audit-trail sheets: finance-friendly headers, typed columns, safe text."""
import json
from decimal import Decimal
from pathlib import Path

from .excel_style import PRIMARY, Pack, sheet_name

HEADER_NAMES = {
    "driver_id": "Movement ID", "label": "Movement", "base": "Base", "current": "Current", "delta": "Change", "delta_pct": "Change %", "n_lines": "Lines",
    "text": "Description", "timestamp": "When (UTC)", "created": "Created (UTC)", "actor": "Changed by", "reason": "Reason", "path": "Setting", "op": "Change type",
    "from": "Before", "to": "After", "id": "Check", "status": "Result", "message": "Message", "details": "Details", "lookup": "Lookup", "key": "Unmatched key",
    "unmatched_rows": "Unmatched lines", "unmatched_value": "Unmatched amount", "fanout": "Duplicate matches", "duplicate_keys": "Duplicate keys",
    "flags": "Flags", "evidence_refs": "Evidence references", "top_texts": "Top descriptions", "by": "By", "action": "Action",
    "entry": "Entry", "part": "Part", "response": "Log entry (JSON)", "item": "Item", "value": "Value", "json": "FluxSpec (JSON)",
}
MONEY_KEYS = {"base", "current", "delta", "amount", "unmatched_value", "threshold"}
DATE_KEYS = {"timestamp", "created", "confirmed_at", "updated_at", "at"}


def humanize(key: object, measure: str) -> str:
    text = str(key)
    if text in HEADER_NAMES:
        return HEADER_NAMES[text]
    for suffix, label in (("_delta_pct", "Change %"), ("_base", "Base"), ("_current", "Current"), ("_delta", "Change")):
        if text.endswith(suffix):
            prefix = text[: -len(suffix)]
            return label if prefix == measure else f"{prefix.replace('_', ' ').capitalize()} – {label.lower()}"
    text = text.replace("_", " ")
    return text[:1].upper() + text[1:]


def column_kind(key: object, values: list) -> str:
    text = str(key).lower()
    present = [value for value in values if value is not None]
    numeric = bool(present) and all(isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) for value in present)
    if text.endswith("_pct") and numeric:
        return "pct100"
    if (text in MONEY_KEYS or text.endswith(("_base", "_current", "_delta", "_value", "_amount"))) and numeric:
        return "money"
    if (text.startswith("n_") or text in {"entry", "part", "unmatched_rows", "count", "lines", "rows", "fanout"} or text.endswith("_rows")) and numeric:
        return "int"
    if text in DATE_KEYS or text.endswith("_at"):
        return "date"
    return "number" if numeric else "text"


def write_table(pack: Pack, worksheet, rows: list[dict], measure: str, empty: str) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    if not rows:
        worksheet.set_column(0, 0, 80)
        worksheet.write_string(0, 0, "Status", pack.header)
        worksheet.write_string(1, 0, empty, pack.muted)
        return
    kinds = {key: column_kind(key, [row.get(key) for row in rows]) for key in keys}
    widths = []
    for key in keys:
        kind = kinds[key]
        if kind in ("money", "number"):
            widths.append(16)
        elif kind in ("pct", "pct100", "int"):
            widths.append(12)
        elif kind == "date":
            widths.append(17)
        else:
            longest = max([len(humanize(key, measure))] + [len(str(row.get(key, ""))) for row in rows[:200]])
            widths.append(min(70, max(14, longest + 2)))
    pack.headers(worksheet, 0, [humanize(key, measure) for key in keys], widths)
    for index, row in enumerate(rows, start=1):
        for col, key in enumerate(keys):
            pack.value(worksheet, index, col, row.get(key), kinds[key])
    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(rows), len(keys) - 1)


def appendix_plan(run: dict, directory: Path, measure: str) -> list[dict]:
    """Supporting-detail and audit-trail sheets, in workbook order."""
    taken = set(PRIMARY)
    plan = []
    labels = {driver.get("driver_id"): driver.get("label") for driver in run.get("drivers", [])}

    def add(name, group, description, rows, empty="Nothing to show for this report."):
        plan.append({"name": sheet_name(name, taken), "group": group, "description": description, "rows": rows, "empty": empty})

    for view, rows in run.get("views", {}).items():
        title = str(view).replace("_", " ")
        add(f"Variance {title}" if title.startswith("by ") else f"Variance - {title}", "Supporting detail", f"Every line of the '{title}' comparison, as calculated by the engine.", rows)
    movements = []
    for driver in run.get("drivers", []):
        base = driver.get("base")
        delta = driver.get("delta")
        movements.append({"label": driver.get("label"), **(driver.get("dimensions") or {}), "base": base, "current": driver.get("current"), "delta": delta,
                          "delta_pct": float(delta) / abs(float(base)) * 100 if isinstance(base, (int, float)) and base and isinstance(delta, (int, float)) else None,
                          "n_lines": driver.get("n_lines"), "flags": ", ".join(str(flag) for flag in driver.get("flags") or []),
                          "top_texts": "; ".join(f"{item.get('text')} ({item.get('delta_fmt')})" for item in driver.get("top_texts") or [] if item.get("text")),
                          "evidence_refs": ", ".join(str(item) for item in driver.get("evidence_refs") or []), "driver_id": driver.get("driver_id")})
    add("Movement detail", "Supporting detail", "Each reported movement with its grouping, line count, flags and evidence references.", movements)
    source = [{"label": labels.get(key, key), **row, "driver_id": key} for key, rows in run.get("drills", {}).items() for row in rows]
    add("Source lines", "Supporting detail", "The source descriptions behind each movement, with their amounts.", source, "No source lines were collected for this report.")
    for key, title, description in (("flags", "Flags", "Lines the engine flagged for attention."), ("exceptions", "Exceptions", "Exceptions raised while building the report."), ("sections", "Sections", "Report sections and their totals.")):
        if run.get(key):
            add(title, "Supporting detail", description, run[key])
    add("Classifications", "Supporting detail", "How lines were classified, for review.", run.get("classification_review", []), "No classifications needed review.")
    unmatched = []
    for audit in run.get("join_audit", []):
        for index, key in enumerate(audit.get("unmatched_keys") or ["(no unmatched key)" if not audit.get("missing_source") else "(optional lookup not uploaded)"]):
            unmatched.append({"lookup": audit.get("lookup"), "key": key, "unmatched_rows": audit.get("unmatched_rows") if not index else None, "unmatched_value": audit.get("unmatched_value") if not index else None,
                              "fanout": audit.get("fanout"), "duplicate_keys": ", ".join(str(item) for item in audit.get("duplicate_keys") or []) if not index else None})
    add("Unmatched lookups", "Supporting detail", "Lookup values that did not match the main data.", unmatched, "No lookups were used, or every value matched.")

    status = {"pass": "Passed", "warn": "Warning", "stop": "Stopped"}
    add("Data controls", "Audit trail", "Every data control run before the report, with its details.",
        [{"id": control.get("id"), "status": status.get(control.get("status"), control.get("status")), "message": control.get("message"), "details": control.get("details")} for control in run.get("controls", [])])
    add("Setup changes", "Audit trail", "Every change made to the setup before this run, with who made it and why.", run.get("change_log", []), "No setup changes were recorded.")
    add("Explanation log", "Audit trail", "Every explanation saved or confirmed, with who did it and when.",
        [{"timestamp": entry.get("timestamp"), "label": labels.get(entry.get("driver_id"), entry.get("driver_id")), "action": {"confirm": "Confirmed", "save": "Saved"}.get(entry.get("action"), entry.get("action")),
          "by": entry.get("by"), "from": entry.get("from"), "to": entry.get("to")} for entry in run.get("review_log", [])], "No explanations have been saved or confirmed yet.")
    stamp = run.get("run_stamp", {})
    preset = stamp.get("preset") or run.get("spec", {}).get("preset") or {}
    audit = [{"item": "Run ID", "value": stamp.get("run_id", run.get("id"))}, {"item": "Created (UTC)", "value": stamp.get("created", run.get("created"))},
             {"item": "Engine version", "value": stamp.get("engine_version")}, {"item": "Preset", "value": f"{preset.get('id', '')} v{preset.get('version', '')}".strip()},
             {"item": "Setup fingerprint (SHA-256)", "value": stamp.get("spec_sha256")}]
    audit.extend({"item": f"Input file ({item.get('role', 'input')})", "value": f"{item.get('name')} — SHA-256 {item.get('sha256')}"} for item in stamp.get("input_files", []))
    add("Run audit", "Audit trail", "Run fingerprint: engine version, setup fingerprint and the fingerprint of every input file.", [row for row in audit if row["value"] not in (None, "")])
    logs = []
    entries = list(run.get("agent_logs", []))
    local_log = directory / "agent_log.jsonl"
    if local_log.exists():
        entries.extend({"transport_attempt": json.loads(line)} for line in local_log.read_text().splitlines() if line.strip())
    for index, entry in enumerate(entries):
        text = json.dumps(entry, ensure_ascii=False, default=str)
        logs.extend({"entry": index + 1, "part": part // 30000 + 1, "response": text[part:part + 30000]} for part in range(0, len(text), 30000))
    add("AI assistant log", "Audit trail", "What the AI assistant was asked and answered while building this report.", logs, "The AI assistant was not used for this report.")
    add("FluxSpec", "Audit trail", "The full setup used for this run, as JSON. The same file is available as a separate download.",
        [{"json": line} for line in json.dumps({**run.get("spec", {}), "run_stamp": stamp}, indent=2, default=str).splitlines()])
    return plan
