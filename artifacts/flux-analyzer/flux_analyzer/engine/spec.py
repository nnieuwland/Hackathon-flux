"""FluxSpec schema, safe persistence and recursive token resolution."""
import copy
import ast
import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator

FILTER = {"type": "object", "required": ["col", "op"], "properties": {"col": {"type": "string"}, "op": {"enum": ["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "startswith", "contains", "regex", "isnull", "notnull"]}, "val": {}}, "additionalProperties": False}
STRINGS = {"type": "array", "items": {"type": "string"}}
SLICE = {"type": "object", "properties": {"months": {"type": "array", "items": {"type": "string", "pattern": r"^\d{4}-(0[1-9]|1[0-2])$"}}, "period": {"type": "string"}, "scenario": {"oneOf": [{"type": ["string", "null"]}, STRINGS]}, "filters": {"type": "array", "items": FILTER}}, "additionalProperties": False}
VALUE_RULES = {
    "type": "object",
    "properties": {
        "source": {"enum": ["column", "debit_minus_credit"]},
        "column": {"type": ["string", "null"]},
        "debit": {"type": ["string", "null"]},
        "credit": {"type": ["string", "null"]},
        "null_as_zero": {"type": "boolean"},
        "flip_sign_when": {"type": "array", "items": FILTER},
    }, "additionalProperties": False,
}
MATERIALITY = {
    "type": "object", "required": ["mode"],
    "properties": {
        "mode": {"enum": ["abs", "pct_of_total", "max_of", "min_of"]},
        "abs": {"type": "number", "minimum": 0},
        "pct": {"type": "number", "minimum": 0, "maximum": 1},
        "basis": {"enum": ["abs_total_movement", "abs_total_base", "abs_total_current", "total_delta", "total_base", "total_current"]},
        "thresholds": {"type": "array", "minItems": 2, "items": {"type": "object", "required": ["type", "value"], "properties": {"type": {"enum": ["abs", "pct_of_total"]}, "value": {"type": "number", "minimum": 0}, "basis": {"enum": ["total_delta", "total_base", "total_current"]}}, "additionalProperties": False}},
    }, "additionalProperties": False,
}
CLASSIFICATION = {
    "type": "object",
    "properties": {
        "source_cols": STRINGS, "target_col": {"type": "string"},
        "case_sensitive": {"type": "boolean"}, "first_match": {"type": "boolean"},
        "fallback": {"type": "string"},
        "rules": {"type": "array", "items": {"type": "object", "required": ["keyword", "category", "match"], "properties": {"keyword": {"type": "string", "minLength": 1, "maxLength": 160}, "category": {"type": "string", "minLength": 1, "maxLength": 120}, "match": {"enum": ["contains", "eq", "startswith", "regex"]}, "reviewed": {"type": "boolean"}}, "additionalProperties": False}},
        "review_flags": STRINGS,
    }, "additionalProperties": False,
}
JOIN = {
    "type": "object", "required": ["source", "on"],
    "properties": {
        "source": {"type": "string"}, "on": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["left", "right"], "properties": {"left": {"type": "string"}, "right": {"type": "string"}}, "additionalProperties": False}},
        "how": {"const": "left"}, "prefix": {"type": "string"},
        "optional": {"type": "boolean"},
        "key_normalise": {"type": "array", "items": {"enum": ["trim", "upper", "lstrip_zeros"]}},
        "dedupe_right": {"enum": ["first", "error"]}, "unmatched": {"enum": ["allow", "warn", "stop"]},
        "columns": STRINGS,
    }, "additionalProperties": False,
}
STYLE_PROFILE = {
    "type": "object", "required": ["audience", "length", "structure", "tone", "instructions", "example_style", "include"],
    "properties": {
        "audience": {"enum": ["executive", "controller", "detailed", "custom"]},
        "length": {"enum": ["short", "medium", "per_driver"]},
        "structure": {"type": "object", "required": ["type", "split_by"], "properties": {"type": {"enum": ["overall", "split"]}, "split_by": {"type": ["string", "null"], "maxLength": 200}}, "additionalProperties": False},
        "tone": {"enum": ["neutral", "risk_focused", "fav_unfav"]},
        "instructions": {"type": "string", "maxLength": 3000},
        "example_style": {"type": "object", "required": ["summary_of_style", "sample_phrases"], "properties": {"summary_of_style": {"type": "string", "maxLength": 600}, "sample_phrases": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 120}}}, "additionalProperties": False},
        "include": {"type": "array", "uniqueItems": True, "items": {"enum": ["timing", "one_offs", "to_verify"]}},
        # What the commentary is for, and facts the reader already knows. Stated by a person or a
        # preset, never checked against the data, and always attributed when the commentary uses them.
        "objective": {"type": "string", "maxLength": 300},
        "business_context": {"type": "string", "maxLength": 2000},
    }, "additionalProperties": False,
}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "required": ["spec_version", "flux_name", "sources", "roles", "comparison"],
    "properties": {
        "spec_version": {"const": "2.0"}, "run_stamp": {"type": "object"}, "preset": {"type": "object"}, "flux_name": {"type": "string", "minLength": 1, "maxLength": 120},
        "sources": {"type": "object"},
        "roles": {"type": "object", "properties": {**{k: {"type": ["string", "null"]} for k in ("value", "period", "scenario", "debit", "credit")}, **{k: STRINGS for k in ("keys", "dimensions", "driver_text")}}, "additionalProperties": False},
        "scope": {"type": "array", "items": FILTER},
        "derive": {"type": "array", "items": {"type": "object", "required": ["name", "type"], "properties": {"name": {"type": "string"}, "type": {"enum": ["rules", "regex_extract", "map", "ratio", "concat", "bucket_numeric"]}}, "additionalProperties": True}},
        "periods": {"type": "object", "properties": {"format_in": {"type": "string"}, "calendar": {"oneOf": [{"type": "string", "const": "calendar"}, {"type": "object", "required": ["start_month"], "properties": {"start_month": {"type": "integer", "minimum": 1, "maximum": 12}}, "additionalProperties": False}]}}, "additionalProperties": False},
        "comparison": {"type": "object", "required": ["type", "base", "current"], "properties": {"type": {"type": "string"}, "base": SLICE, "current": SLICE}, "additionalProperties": False},
        "measures": {"type": "object", "additionalProperties": {"type": "object", "required": ["agg", "col"], "properties": {"agg": {"enum": ["sum", "count", "mean", "min", "max", "nunique"]}, "col": {"type": "string"}, "slice": {"enum": ["none", "base", "current"]}, "filter": {"type": "array", "items": FILTER}}, "additionalProperties": False}},
        "views": {"type": "array", "items": {"type": "object", "required": ["name", "keys", "measures"], "properties": {"name": {"type": "string"}, "keys": STRINGS, "measures": STRINGS, "compare": {"type": "boolean"}, "joins": {"type": "array", "items": {"type": "object"}}}, "additionalProperties": False}},
        "sections": {"type": ["object", "null"]}, "decompose": {"type": ["object", "null"]},
        "value_rules": VALUE_RULES, "classification": {"oneOf": [CLASSIFICATION, {"type": "null"}]},
        "period_format": {"type": "string"}, "partial_periods": STRINGS, "joins": {"type": "array", "items": JOIN},
        "flags": {"type": "array", "items": {"type": "object", "required": ["view", "name", "ordered"], "properties": {"view": {"type": "string"}, "name": {"type": "string"}, "ordered": {"type": "array", "items": {"type": "object", "required": ["if", "label"], "properties": {"if": {"type": "string"}, "label": {"type": "string"}}, "additionalProperties": False}}, "default": {"type": "string"}}, "additionalProperties": False}},
        "gates": {"type": "array", "items": {"type": "object", "required": ["view", "name", "if"], "properties": {"view": {"type": "string"}, "name": {"type": "string"}, "if": {"type": "string"}}, "additionalProperties": False}},
        "drivers": {"type": "object", "properties": {"view": {"type": "string"}, "measure": {"type": "string"}, "materiality_abs": {"type": "number", "minimum": 0}, "materiality": MATERIALITY, "top_n": {"type": "integer", "minimum": 1, "maximum": 100}, "others_label": {"type": "string"}}, "additionalProperties": False},
        "drill": {"type": "object", "properties": {"group_by": {"oneOf": [{"type": "string"}, STRINGS]}, "top_n": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False},
        "commentary": {"type": "object", "properties": {"units": {"enum": ["M", "K", "B", "units", "none"]}, "decimals": {"type": "integer", "minimum": 0, "maximum": 6}, "style": {"type": "string"}, "verify_tag": {"type": "string"}, "forbidden_terms": STRINGS, "currency_symbol": {"type": "string"}, "sign_style": {"enum": ["plus_minus", "fav_unfav"]}, "favorable_when": {"enum": ["positive", "negative"]}, "dimension_label_style": {"type": "object"}, "max_line_words": {"type": "integer", "minimum": 1, "maximum": 200}, "headline_template": {"type": "string"}, "style_profile": STYLE_PROFILE}, "additionalProperties": False},
        "controls": {"type": "array", "items": {"type": "object", "required": ["id", "severity"], "properties": {"id": {"enum": ["required_columns", "periods_present", "no_duplicate_periods_across_files", "sections_reconcile", "flags_sum_to_rows", "drivers_reconcile", "debit_minus_credit_equals_value", "new_or_removed_members", "join_unmatched_keys", "join_fanout", "classification_coverage", "partial_period_used"]}, "severity": {"enum": ["stop", "warn"]}, "tolerance": {"type": "number", "minimum": 0}, "params": {"type": "object"}}, "additionalProperties": False}},
    }, "additionalProperties": False,
}

DEFAULT_CONTROLS = [
    {"id": "required_columns", "severity": "stop"},
    {"id": "periods_present", "severity": "stop"},
    {"id": "no_duplicate_periods_across_files", "severity": "stop"},
    {"id": "new_or_removed_members", "severity": "warn"},
    {"id": "drivers_reconcile", "severity": "stop"},
    {"id": "flags_sum_to_rows", "severity": "stop"},
    {"id": "sections_reconcile", "severity": "stop"},
    {"id": "join_unmatched_keys", "severity": "warn"},
    {"id": "join_fanout", "severity": "stop"},
    {"id": "classification_coverage", "severity": "warn", "params": {"minimum_percentage": 95}},
    {"id": "partial_period_used", "severity": "warn"},
]

def default_spec() -> dict:
    """Return a new unconfigured specification, not a hard-coded flux."""
    return {
        "spec_version": "2.0",
        "preset": {"id": "generic_flux", "version": "1.0.0"},
        "flux_name": "Untitled analysis",
        "sources": {},
        "roles": {"value": None, "period": None, "scenario": None, "debit": None, "credit": None, "keys": [], "dimensions": [], "driver_text": []},
        "value_rules": {"source": "column", "null_as_zero": True, "flip_sign_when": []},
        "scope": [],
        "derive": [],
        "periods": {"calendar": "calendar"},
        "period_format": "auto",
        "partial_periods": [],
        "comparison": {"type": "QoQ", "base": {"months": []}, "current": {"months": []}},
        "joins": [],
        "classification": None,
        "measures": {},
        "views": [],
        "flags": [],
        "gates": [],
        "sections": None,
        "decompose": None,
        "drivers": {"materiality": {"mode": "abs", "abs": 300000}, "top_n": 15, "others_label": "Other items"},
        "drill": {"top_n": 5},
        "commentary": {"units": "M", "decimals": 1, "verify_tag": "[TO VERIFY]", "sign_style": "plus_minus", "currency_symbol": "$", "forbidden_terms": [], "max_line_words": 35},
        "controls": copy.deepcopy(DEFAULT_CONTROLS),
    }

def migrate_spec(old: dict) -> dict:
    """Migrate legacy FluxSpec 1.0 into the generic preset-based 2.0 shape."""
    from .periods import months_for_period
    if not isinstance(old, dict):
        raise ValueError("FluxSpec must be a JSON object.")
    spec = copy.deepcopy(old)
    version = str(spec.get("spec_version", "1.0"))
    if version not in ("1.0", "2.0"):
        raise ValueError(f"Unsupported FluxSpec version '{version}'.")
    skill = spec.pop("skill", None)
    spec["preset"] = spec.get("preset") or {"id": skill or "generic_flux", "version": "1.0.0"}
    if skill and isinstance(spec["preset"], dict) and spec["preset"].get("id") == "generic_flux":
        spec["preset"]["id"] = skill
    spec["spec_version"] = "2.0"
    comparison = spec.get("comparison", {}) if isinstance(spec.get("comparison", {}), dict) else {}
    period_options = spec.get("periods", {}) if isinstance(spec.get("periods", {}), dict) else {}
    calendar = period_options.get("calendar", "calendar")
    for side in ("base", "current"):
        item = comparison.get(side, {})
        if not isinstance(item, dict):
            continue
        if item.get("period") and not item.get("months"):
            try:
                item["months"] = months_for_period(item["period"], calendar)
                item.pop("period", None)
            except (ValueError, TypeError, AttributeError):
                pass
        elif isinstance(item.get("months"), list):
            normalized = []
            for label in item["months"]:
                try:
                    normalized.extend(months_for_period(label, calendar))
                except (ValueError, TypeError, AttributeError):
                    normalized.append(label)
            item["months"] = normalized
            item.pop("period", None)
    drivers = spec.setdefault("drivers", {})
    if isinstance(drivers, dict) and "materiality_abs" in drivers:
        legacy_threshold = drivers.pop("materiality_abs")
        drivers["materiality"] = {"mode": "abs", "abs": legacy_threshold}
    commentary = spec.setdefault("commentary", {})
    if isinstance(commentary, dict):
        commentary.setdefault("sign_style", "plus_minus")
        commentary.setdefault("currency_symbol", "$")
        commentary.setdefault("max_line_words", 35)
    spec.setdefault("value_rules", {"source": "column", "null_as_zero": True, "flip_sign_when": []})
    if isinstance(spec.get("value_rules"), dict) and isinstance(spec["value_rules"].get("flip_sign_when", []), list):
        spec["value_rules"]["flip_sign_when"] = [rule.get("when", rule) if isinstance(rule, dict) else rule for rule in spec["value_rules"].get("flip_sign_when", [])]
    spec.setdefault("joins", [])
    spec.setdefault("classification", None)
    spec.setdefault("period_format", period_options.get("format_in", "auto"))
    spec.setdefault("partial_periods", [])
    spec.setdefault("controls", copy.deepcopy(DEFAULT_CONTROLS))
    spec.setdefault("joins", [])
    if isinstance(spec.get("periods"), dict):
        spec["periods"].pop("format_in", None)
    if isinstance(spec.get("classification"), dict):
        classification = spec["classification"]
        if "source_column" in classification:
            classification["source_cols"] = [classification.pop("source_column")]
        if "target_column" in classification:
            classification["target_col"] = classification.pop("target_column")
        spec["classification"].setdefault("case_sensitive", False)
        spec["classification"].setdefault("first_match", True)
        spec["classification"].setdefault("fallback", "UNMATCHED")
        spec["classification"].setdefault("review_flags", [])
        for rule in spec["classification"].get("rules", []) if isinstance(spec["classification"].get("rules", []), list) else []:
            if isinstance(rule, dict):
                rule.setdefault("reviewed", False)
    for join in spec.get("joins", []) if isinstance(spec.get("joins", []), list) else []:
        if isinstance(join, dict) and all(key in join for key in ("lookup", "left_on", "right_on")):
            join["source"] = join.pop("lookup")
            join["on"] = [{"left": join.pop("left_on"), "right": join.pop("right_on")}]
            join["key_normalise"] = join.pop("normalize_keys", ["trim"])
            join["dedupe_right"] = join.pop("dedupe", "error")
            join["columns"] = join.pop("fields", [])
    controls = spec.setdefault("controls", copy.deepcopy(DEFAULT_CONTROLS))
    if isinstance(controls, list):
        configured = {item.get("id") for item in controls if isinstance(item, dict)}
        controls.extend(copy.deepcopy(item) for item in DEFAULT_CONTROLS if item["id"] not in configured)
    return spec


def semantic_errors(spec: dict) -> list[str]:
    messages = []
    style = (spec.get("commentary") or {}).get("style_profile") if isinstance(spec.get("commentary"), dict) else None
    if isinstance(style, dict) and isinstance(style.get("structure"), dict):
        structure = style["structure"]
        if structure.get("type") == "split" and not structure.get("split_by"):
            messages.append("Commentary style: choose a grouping field when splitting commentary.")
        if structure.get("type") == "overall" and structure.get("split_by") is not None:
            messages.append("Commentary style: an overall structure cannot have a split field.")
    views = spec.get("views", [])
    view_names = {view.get("name") for view in views if isinstance(view, dict)} if isinstance(views, list) else set()
    for block in ("flags", "gates"):
        rules = spec.get(block, [])
        for index, rule in enumerate(rules if isinstance(rules, list) else []):
            if not isinstance(rule, dict):
                continue
            for key in ("view", "name", "ordered", "default") if block == "flags" else ("view", "name", "if"):
                if key not in rule:
                    messages.append(f"Configuration {block}.{index}.{key}: required.")
            if rule.get("view") not in view_names:
                messages.append(f"Configuration {block}.{index}.view: choose an existing view.")
            conditions = rule.get("ordered", []) if block == "flags" else [rule]
            for position, condition in enumerate(conditions if isinstance(conditions, list) else []):
                if not isinstance(condition, dict):
                    continue
                expression = condition.get("if")
                try:
                    if not isinstance(expression, str) or not expression.strip() or len(expression) > 4000:
                        raise ValueError("provide a non-empty expression of at most 4000 characters")
                    if len(list(ast.walk(ast.parse(expression, mode="eval")))) > 500:
                        raise ValueError("expression exceeds 500 syntax nodes")
                except (ValueError, SyntaxError) as error:
                    messages.append(f"Configuration {block}.{index}.condition.{position}: {error}.")
    derives = spec.get("derive", [])
    for index, rule in enumerate(derives if isinstance(derives, list) else []):
        if not isinstance(rule, dict):
            continue
        path, kind = f"derive.{index}", rule.get("type")
        required = {"rules": ["rules"], "regex_extract": ["source", "pattern"], "map": ["source"], "ratio": ["numerator", "denominator"], "concat": ["source"], "bucket_numeric": ["source", "bins"]}.get(kind, [])
        for key in required:
            if key not in rule:
                messages.append(f"Configuration {path}.{key}: required for {kind}.")
        if kind == "regex_extract":
            for key in ("pattern", "strip_suffix"):
                value = rule.get(key)
                if value is None:
                    continue
                try:
                    if not isinstance(value, str) or len(value) > 500:
                        raise ValueError("must be a string of at most 500 characters")
                    compiled = re.compile(value)
                    if key == "pattern" and not compiled.groups:
                        raise ValueError("extraction requires at least one capture group")
                except (re.error, ValueError) as error:
                    messages.append(f"Configuration {path}.{key}: {error}.")
        if kind == "bucket_numeric" and isinstance(rule.get("bins"), list):
            bins = rule["bins"]
            if len(bins) < 2 or any(not isinstance(value, (float, int)) for value in bins) or any(a >= b for a, b in zip(bins, bins[1:])):
                messages.append(f"Configuration {path}.bins: provide at least two increasing numeric boundaries.")
            if "labels" in rule and (not isinstance(rule["labels"], list) or len(rule["labels"]) != len(bins) - 1):
                messages.append(f"Configuration {path}.labels: provide one label per interval.")
    return messages

def validate_spec(spec: dict) -> dict:
    """Migrate then validate a spec, reporting all schema errors at once."""
    migrated = migrate_spec(spec)
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(migrated), key=lambda e: (tuple(map(str, e.absolute_path)), e.validator or ""))
    messages = semantic_errors(migrated)
    for error in errors:
        path = ".".join(map(str, error.absolute_path)) or "root"
        messages.append(f"Configuration {path}: {error.message}")
    if messages:
        raise ValueError("Configuration has validation errors:\n- " + "\n- ".join(messages))
    return migrated

def resolve_tokens(spec: dict, comparison: dict) -> dict:
    """Resolve exact tokens preserving lists, numbers and nulls."""
    context = {**spec, **comparison}
    token_pattern = r"\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}"
    def lookup(token: str) -> object:
        value = context
        for part in token.split("."):
            if not isinstance(value, dict) or part not in value:
                raise ValueError(f"Unknown configuration token '{{{token}}}'.")
            value = value[part]
        return copy.deepcopy(value)
    def walk(value: object) -> object:
        if isinstance(value, dict):
            return {key: walk(val) for key, val in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            match = re.fullmatch(token_pattern, value)
            if match:
                return lookup(match[1])
            return re.sub(token_pattern, lambda m: str(lookup(m[1])), value)
        return value
    return walk(spec)

def validate_spec_against_data(spec: dict, columns: list[str]) -> list[str]:
    """Find source-column dependencies, excluding defined derived columns."""
    derived = {d["name"] for d in spec.get("derive", [])}
    wanted = set()
    for key, value in spec["roles"].items():
        wanted.update(value if isinstance(value, list) else [value] if value else [])
    for condition in spec.get("scope", []):
        wanted.add(condition["col"])
    for item in spec.get("derive", []):
        source = item.get("source", [])
        wanted.update(source if isinstance(source, list) else [source])
        wanted.update(item[k] for k in ("numerator", "denominator") if k in item)
    return sorted(wanted - set(columns) - derived)

def save_spec(spec: dict, directory: Path, name: str) -> Path:
    """Save a validated JSON spec under a safe, non-traversing filename."""
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "flux"
    path = directory / f"{filename}.json"
    payload = copy.deepcopy(spec)
    payload["flux_name"] = name
    payload = validate_spec(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path

def load_spec(path: Path) -> dict:
    """Load JSON only, never deserialize user-controlled pickle files."""
    return validate_spec(json.loads(path.read_text(encoding="utf-8")))
