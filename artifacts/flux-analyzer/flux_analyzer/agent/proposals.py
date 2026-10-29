"""Pure, validated proposal/patch conversion shared by live and mock calls."""
import copy
from engine.spec import validate_spec
from engine.patches import apply_patch
from engine.presets import get_preset, apply_defaults

FIELDS = {
    "detect_flux": ("flux_name",),
    "map_columns": ("roles",),
    "define_comparison": ("comparison", "period_format", "partial_periods"),
    "derive_columns": ("scope", "derive", "joins", "value_rules"),
    "define_rules": ("measures", "views", "sections", "decompose", "flags", "gates", "drivers", "drill", "commentary", "controls", "value_rules", "joins", "classification"),
}


def merge_dict(base, update):
    if isinstance(base, dict) and isinstance(update, dict):
        result = copy.deepcopy(base)
        for key, value in update.items():
            result[key] = merge_dict(result.get(key), value)
        return result
    return copy.deepcopy(update)


def proposal_to_spec(spec: dict, step: str, proposal: dict, partial: bool = False) -> dict:
    output = validate_spec(spec)
    if step == "classify_terms":
        source = proposal.get("source_col") or next(iter(output["roles"].get("driver_text", [])), None)
        rules = proposal.get("rules") or [{"keyword": item["keyword_rule"] or item["term"], "category": item["category"], "match": "contains", "reviewed": False} for item in proposal.get("mappings", [])]
        if not rules:
            return output
        if not source:
            raise ValueError("Map a driver text column before classification.")
        config = output.get("classification") or {"source_cols": [source], "target_col": proposal.get("target_col", "Category"), "fallback": "UNMATCHED", "case_sensitive": False}
        existing = config.get("rules", [])
        reviewed = {(item["keyword"], item["match"]) for item in existing if item.get("reviewed")}
        proposed_keys = {(item["keyword"], item["match"]) for item in rules}
        config["rules"] = [item for item in existing if item.get("reviewed") or (item["keyword"], item["match"]) not in proposed_keys]
        config["rules"].extend(dict(item, reviewed=False) for item in rules if (item["keyword"], item["match"]) not in reviewed)
        output["classification"] = config
    elif step in FIELDS:
        if step == "detect_flux" and proposal.get("preset_id"):
            preset = get_preset(proposal["preset_id"])
            if preset["id"] != output["preset"]["id"]:
                output = apply_defaults(output, preset)
        for key in FIELDS[step]:
            if key in proposal:
                output[key] = merge_dict(output.get(key), proposal[key]) if partial or key in ("roles", "drivers", "commentary") else copy.deepcopy(proposal[key])
    else:
        raise ValueError("Unknown configuration step.")
    return validate_spec(output)


def candidate_for_response(spec: dict, response: dict) -> dict | None:
    if response["status"] == "cannot_do" or response["step"] in ("write_commentary", "answer_question", "explain_spec", "describe_setup"):
        return None
    if response["step"] == "extract_commentary_style":
        example = response.get("proposal", {}).get("example_style")
        if not example:
            return None
        from .contracts import sanitize_style_profile
        output = validate_spec(spec)
        commentary = output.setdefault("commentary", {})
        profile = sanitize_style_profile(commentary.get("style_profile") or {})
        profile["example_style"] = copy.deepcopy(example)
        commentary["style_profile"] = profile
        return validate_spec(output)
    if response["step"] in ("apply_instruction", "plan_from_description"):
        patch = response.get("patch", response.get("proposal", {}).get("patch", []))
        if not patch:
            return None
        return apply_patch(spec, patch, "agent", response.get("summary") or response.get("rationale") or "Applied described change")
    return proposal_to_spec(spec, response["step"], response["proposal"], response["status"] == "needs_input")
