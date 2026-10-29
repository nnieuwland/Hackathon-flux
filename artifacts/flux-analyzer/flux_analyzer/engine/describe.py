"""Offline plain-English descriptions of every supported configuration block."""
import copy

CONTROL_DESCRIPTIONS = {
    "required_columns": "Check that every mapped and referenced column exists",
    "periods_present": "Check that both comparison slices contain every selected month",
    "no_duplicate_periods_across_files": "Check for periods overlapping across stacked files",
    "new_or_removed_members": "Report dimension members present in only one slice",
    "drivers_reconcile": "Check that drivers and other items sum to total movement",
    "flags_sum_to_rows": "Check that every row receives exactly one ordered flag",
    "sections_reconcile": "Check that section movements reconcile to total movement",
    "debit_minus_credit_equals_value": "Compare debit less credit with the configured value",
    "join_unmatched_keys": "Report unmatched lookup keys, row counts, and values",
    "join_fanout": "Stop when error-policy duplicate lookup keys would multiply source rows",
    "classification_coverage": "Check the percentage of absolute value classified rather than assigned to fallback",
    "partial_period_used": "Warn when selected months contain fewer than half the median row count",
}


def filter_sentence(rule: dict) -> str:
    words = {"eq": "equals", "ne": "does not equal", "in": "is one of", "not_in": "is not one of", "gt": "is greater than", "gte": "is at least", "lt": "is less than", "lte": "is at most", "startswith": "starts with", "contains": "contains", "regex": "matches pattern", "isnull": "is blank", "notnull": "is not blank"}
    value = rule.get("val", "")
    if isinstance(value, list):
        value = ", ".join(map(str, value))
    return f"{rule.get('col', 'Column')} {words.get(rule.get('op'), rule.get('op', 'matches'))} {value}".strip()


def materiality_sentence(value: dict) -> str:
    mode = value.get("mode", "abs")
    absolute, percent = value.get("abs", 0), value.get("pct", 0) * 100
    basis = value.get("basis", "abs_total_movement").replace("_", " ")
    if mode == "abs":
        return f"Use an absolute materiality threshold of {absolute:g}."
    if mode == "pct_of_total":
        return f"Use {percent:g}% of {basis} as the materiality threshold."
    return f"Use the {'higher' if mode == 'max_of' else 'lower'} of {absolute:g} and {percent:g}% of {basis} as materiality."


def describe_spec(spec: dict, change_log: list[dict] | None = None) -> list[dict]:
    cards = []
    def add(block, path, value, sentence):
        actor = "preset"
        for event in change_log or []:
            event_path = event.get("path", "")
            if not event_path or path == event_path or path.startswith(event_path + "/") or event_path.startswith(path + "/"):
                actor = event.get("actor", "user")
        cards.append({"block": block, "path": path, "value": copy.deepcopy(value), "sentence": sentence, "actor": actor})
    def escaped(value):
        return str(value).replace("~", "~0").replace("/", "~1")
    if spec.get("preset"):
        value = spec["preset"]
        add("preset", "/preset", value, f"Use preset {value.get('id')} version {value.get('version')}.")
    add("roles", "/roles", spec.get("roles", {}), f"Use {spec.get('roles', {}).get('value') or 'an unmapped column'} for value and {spec.get('roles', {}).get('period') or 'an unmapped column'} for periods; group by {', '.join(spec.get('roles', {}).get('dimensions', [])) or 'total'}.")
    value = spec.get("value_rules", {})
    add("value_rules", "/value_rules", value, f"Calculate value from {'debit less credit' if value.get('source') == 'debit_minus_credit' else 'the mapped amount column'}; {'treat nulls as zero' if value.get('null_as_zero', True) else 'reject nulls'}; apply {len(value.get('flip_sign_when', []))} conditional sign flips.")
    value = spec.get("comparison", {})
    add("comparison", "/comparison", value, f"Compare current {', '.join(value.get('current', {}).get('months', [])) or 'not set'} against base {', '.join(value.get('base', {}).get('months', [])) or 'not set'} ({value.get('type', 'custom')}).")
    for index, rule in enumerate(spec.get("scope", [])):
        add("scope", f"/scope/{index}", rule, f"Keep only rows where {filter_sentence(rule)}.")
    for index, rule in enumerate(spec.get("derive", [])):
        add("derive", f"/derive/{index}", rule, f"Create {rule.get('name')} using {rule.get('type', '').replace('_', ' ')}" + (f" from {', '.join(rule['source']) if isinstance(rule.get('source'), list) else rule.get('source')}" if rule.get("source") else "") + ".")
    for index, join in enumerate(spec.get("joins", [])):
        keys = ", ".join(f"{pair['left']} = {pair['right']}" for pair in join.get("on", []))
        add("joins", f"/joins/{index}", join, f"Left join {join.get('source')} on {keys}; prefix fields with '{join.get('prefix', '')}' and {'keep the first duplicate' if join.get('dedupe_right') == 'first' else 'stop on matching duplicate keys'}.")
    if spec.get("classification"):
        value = spec["classification"]
        add("classification", "/classification", value, f"Classify {', '.join(value.get('source_cols', []))} into {value.get('target_col')} with {len(value.get('rules', []))} ordered rules; first match wins and unmatched text becomes {value.get('fallback', 'UNMATCHED')}.")
    for name, measure in spec.get("measures", {}).items():
        add("measures", f"/measures/{escaped(name)}", measure, f"Measure {name}: {measure.get('agg')} of {measure.get('col')}, using the {measure.get('slice', 'comparison')} slice and {len(measure.get('filter', []))} filters.")
    for index, view in enumerate(spec.get("views", [])):
        add("views", f"/views/{index}", view, f"View {view.get('name')}: group {', '.join(view.get('measures', []))} by {', '.join(view.get('keys', [])) or 'total'}; {'compare base with current' if view.get('compare', True) else 'show sliced measures'}.")
    for block in ("flags", "gates"):
        for index, rule in enumerate(spec.get(block, [])):
            sentence = f"Flag {rule.get('view')} using {rule.get('name')}: " + "; ".join(f"{item['label']} when {item['if']}" for item in rule.get("ordered", [])) + f"; otherwise {rule.get('default', 'Unclassified')}." if block == "flags" else f"Include {rule.get('view')} in exception gate {rule.get('name')} when {rule.get('if')}."
            add(block, f"/{block}/{index}", rule, sentence)
    for block in ("sections", "decompose"):
        value = spec.get(block)
        if value:
            sentence = f"Split commentary by {value.get('split_by')}; reconcile to {value.get('must_reconcile_to', 'amount')}." if block == "sections" else f"Decompose {value.get('measure', 'amount')} into volume at base rate and residual rate impact using {value.get('volume')} and {value.get('rate')}."
            add(block, f"/{block}", value, sentence)
    value = spec.get("drivers", {})
    add("drivers", "/drivers", value, f"Show the top {value.get('top_n', 15)} material drivers from {value.get('view', 'the selected view')} by {value.get('measure', 'amount')}; group all remaining movement as {value.get('others_label', 'Other items')}.")
    if value.get("materiality"):
        add("materiality", "/drivers/materiality", value["materiality"], materiality_sentence(value["materiality"]))
    value = spec.get("drill", {})
    add("drill", "/drill", value, f"Show the top {value.get('top_n', 5)} consolidated transaction descriptions per driver, retaining a reconciling remainder.")
    value = spec.get("commentary", {})
    add("commentary", "/commentary", value, f"Write amount-first commentary in {value.get('units', 'M')} units with {value.get('decimals', 1)} decimals and {value.get('currency_symbol', '$')} currency; at most {value.get('max_line_words', 35)} words per driver, marking unverified causes {value.get('verify_tag', '[TO VERIFY]')}.")
    for index, control in enumerate(spec.get("controls", [])):
        add("controls", f"/controls/{index}", control, f"{CONTROL_DESCRIPTIONS.get(control['id'], control['id'])}; {'stop' if control.get('severity') == 'stop' else 'warn'} on failure (tolerance {control.get('tolerance', .01)}).")
    return cards
