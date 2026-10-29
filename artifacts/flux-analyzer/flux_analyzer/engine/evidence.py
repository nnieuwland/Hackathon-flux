"""Bounded, aggregated commentary evidence, formatted exclusively by Python.

The pack never contains source rows. Each piece of evidence carries a reference so a commentary
line can say which checked fact it relies on, and every number the commentary may quote is
pre-formatted here and listed in allowed_numeric_tokens.
"""
from decimal import Decimal, ROUND_HALF_UP
import re
from .money import decimal, total
from . import evidence_context as ctx

NUMERIC_TOKEN = r"(?<!\w)[+-]?\d+(?:[.,]\d+)*[MKB]?"
COUNT_KEYS = {"lines", "source_lines", "shown_description_count", "unmatched_lookup_lines", "unclassified_lines"}
# Content that is not checked evidence: preferences, user-stated context and validation settings.
NOT_CITABLE = {"business_context", "writing_guidance", "commentary_rules", "allowed_evidence_refs", "allowed_numeric_tokens", "evidence_ref", "evidence_refs", "id", "driver_id", "comparability", "pattern", "approval", "severity"}
MAX_TEXTS = 5


def _scale(settings: dict) -> tuple[Decimal, int, str, str]:
    units = settings.get("units", "M")
    scale = Decimal(1000000000 if units == "B" else 1000000 if units == "M" else 1000 if units == "K" else 1)
    return scale, settings.get("decimals", 1), units, settings.get("currency_symbol", "$")


def format_delta(value: object, settings: dict) -> str:
    """Format an evidence amount without producing misleading zero millions."""
    val = decimal(value)
    scale, places, units, symbol = _scale(settings)
    rounded = (abs(val) / scale).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign_style = settings.get("sign_style", "plus_minus")
    if rounded == 0 and val != 0:
        amount = f"{symbol}{abs(val):,.2f}"
        return f"{'+' if val > 0 else '-'}{amount}" if sign_style == "plus_minus" else f"{amount} {'favorable' if ((val > 0) == (settings.get('favorable_when', 'positive') == 'positive')) else 'unfavorable'}"
    if val == 0:
        return f"{symbol}{rounded:,.{places}f}"
    amount = f"{symbol}{rounded:,.{places}f}{units if units in ('M', 'K', 'B') else ''}"
    if sign_style == "fav_unfav":
        favorable = (val > 0) == (settings.get("favorable_when", "positive") == "positive")
        return f"{amount} {'favorable' if favorable else 'unfavorable'}"
    return f"{'+' if val > 0 else '-'}{amount}"


def format_level(value: object, settings: dict) -> str:
    """Format a period amount (a level, not a movement): no plus sign or favourable wording."""
    val = decimal(value)
    scale, places, units, symbol = _scale(settings)
    rounded = (abs(val) / scale).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if rounded == 0 and val != 0:
        amount = f"{symbol}{abs(val):,.2f}"
    elif val == 0:
        amount = f"{symbol}{rounded:,.{places}f}"
    else:
        amount = f"{symbol}{rounded:,.{places}f}{units if units in ('M', 'K', 'B') else ''}"
    return ("-" if val < 0 else "") + amount


def build_evidence_pack(spec: dict, drivers: list[dict], drills: dict, sections: list[dict], context: dict | None = None) -> dict:
    """Provide bounded consolidated evidence, never raw transaction rows.

    ``context`` (from the pipeline) adds history, category mix, volume/rate effects and coverage;
    without it the pack holds only the movement, its amounts and the drill-down descriptions.
    """
    rules = spec.get("commentary", {})
    fmt, level = (lambda value: format_delta(value, rules)), (lambda value: format_level(value, rules))
    context = context or {}
    items = []
    for driver in drivers:
        driver_id = driver["driver_id"]
        texts = drills.get(driver_id, [])
        item = {k: driver[k] for k in ("driver_id", "label", "dimensions", "base", "current", "delta")} | {
            "delta_fmt": fmt(driver["delta"]), "base_fmt": level(driver["base"]), "current_fmt": level(driver["current"]),
            "top_texts": [{"text": str(t["text"])[:160], "delta_fmt": fmt(t["delta"]), "evidence_ref": f"text:{driver_id}:{index}"} for index, t in enumerate(texts[:MAX_TEXTS], 1)],
            "n_lines": sum(t.get("n_lines", 0) for t in texts),
            "flags_summary": {f"{flag['rule']}: {flag['label']}": flag["count"] for flag in driver.get("flag_counts", [])},
        }
        if driver.get("flag_counts"):
            item["flags"] = [{"rule": str(flag["rule"])[:60], "label": str(flag["label"])[:80], "lines": int(flag["count"]), "evidence_ref": f"flag:{driver_id}:{index}"} for index, flag in enumerate(driver["flag_counts"][:MAX_TEXTS], 1)]
        if "threshold" in context:
            # The policy and threshold are stated once for the report (materiality_policy).
            item["is_material"] = driver_id != "others"
        if context.get("rows_for"):
            rows = context["rows_for"](driver)
            args = (context["comparison"], context["roles"], context["value_col"])
            item["trend"] = ctx.trend(rows, driver, *args, context["available"], context["partial"], level)
            item["decomposition"] = ctx.decomposition(context.get("compared"), context.get("keys", []), driver, fmt, context.get("measure"), context.get("decompose"))
            item["categories"] = ctx.categories(rows, driver, *args, context.get("classification"), fmt)
            item["coverage"] = ctx.coverage(rows, driver, texts, *args[:2], context["partial"], context.get("classification"))
            item = {key: value for key, value in item.items() if value is not None}
        item["evidence_refs"] = [f"driver:{driver_id}"]
        items.append(item)
    hint = None
    totals = {name: total(driver.get(name, 0) for driver in drivers) for name in ("base", "current", "delta")}
    if rules.get("headline_template"):
        template_values = {"flux_name": spec["flux_name"], "total_delta": fmt(totals["delta"]), "total_base": fmt(totals["base"]), "total_current": fmt(totals["current"])}
        template_values.update(label=spec["flux_name"], delta_fmt=template_values["total_delta"], top_driver=drivers[0]["label"] if drivers else "no drivers")
        try:
            hint = rules["headline_template"].format_map(template_values)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid commentary headline template: {exc}") from exc
    pack = {"flux_name": spec["flux_name"], "drivers": items,
            "sections": [{**section, "delta_fmt": fmt(section.get("delta", 0)), "evidence_ref": f"section:{index}"} for index, section in enumerate(sections, 1)],
            "commentary_rules": rules, "headline_hint": hint,
            "totals": {"base_fmt": level(totals["base"]), "current_fmt": level(totals["current"]), "delta_fmt": fmt(totals["delta"]), "evidence_ref": "total:movement"}}
    if context.get("comparison"):
        comparison = context["comparison"]
        pack["comparison"] = {side: {"months": list(comparison[side].get("months", [])), "version": comparison[side].get("scenario")} for side in ("base", "current")}
        pack["description_columns"] = [str(column) for column in context.get("description_columns", [])]
        if "threshold" in context:
            pack["materiality_policy"] = f"Movements of at least {level(context['threshold'])} are listed individually, up to {context.get('top_n', 15)}; the rest are combined in '{context.get('others_label', 'Other items')}'. The engine decides this, not the commentary."
    return refresh_allowed(pack)


def finalize_evidence(pack: dict, controls: list[dict], join_audit: list[dict], classification: dict, partial: list[str], description_columns: list[str]) -> dict:
    """Add report-wide data-quality findings and coverage limits once all controls have run."""
    pack["data_quality"] = ctx.data_quality(controls, join_audit, classification, partial)
    notes = ["Commentary sees grouped descriptions and totals only; individual transactions are not supplied."]
    if description_columns:
        notes.append("Descriptions come from the column(s) " + ", ".join(f"'{c}'" for c in description_columns) + f"; at most {MAX_TEXTS} per movement are shown and smaller ones are combined.")
    else:
        notes.append("No description column is mapped, so movements cannot be explained from transaction descriptions.")
    if partial:
        notes.append("Incomplete periods in the comparison: " + ", ".join(partial) + ".")
    if any(item.get("trend") is None for item in pack["drivers"]):
        notes.append("Where a movement has no history, no earlier periods of the same length were available; say nothing about trends for it.")
    pack["coverage_notes"] = notes
    return refresh_allowed(pack)


def _walk(value: object, key: str = ""):
    if key in NOT_CITABLE:
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, key)
    elif isinstance(value, str):
        yield value
    elif isinstance(value, int) and not isinstance(value, bool) and key in COUNT_KEYS:
        yield str(value)


def _refs(value: object, key: str = ""):
    if key == "commentary_rules":
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == "evidence_ref" and isinstance(child, str):
                yield child
            elif child_key == "evidence_refs" and isinstance(child, list):
                yield from (ref for ref in child if isinstance(ref, str))
            elif child_key != "allowed_evidence_refs":
                yield from _refs(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child, key)


def refresh_allowed(pack: dict) -> dict:
    """Recompute the references and number tokens a commentary may use from the pack itself."""
    pack["allowed_evidence_refs"] = list(dict.fromkeys(_refs(pack)))
    pack["allowed_numeric_tokens"] = sorted(set(re.findall(NUMERIC_TOKEN, " ".join(_walk(pack)))))[:600]
    return pack
