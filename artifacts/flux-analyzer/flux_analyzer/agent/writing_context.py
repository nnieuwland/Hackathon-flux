"""Who the commentary is for and what people already know, with where each preference came from.

Stored with the run's evidence so a draft, its checks and later reviews all see the same context.
"""
import copy
from engine.evidence import refresh_allowed
from engine.presets import get_preset
from .contracts import default_style_profile

GUIDANCE_FIELDS = ("audience", "length", "tone", "structure", "objective", "instructions", "include", "example_style")
MAX_CONTEXT_ITEMS = 8


def _preset_profile(spec: dict) -> tuple[dict, str]:
    chosen = spec.get("preset") or {}
    try:
        preset = get_preset(chosen.get("id"), chosen.get("version"))
    except ValueError:
        return {}, ""
    profile = ((preset.get("defaults") or {}).get("commentary") or {}).get("style_profile") or {}
    return profile, preset.get("name", "")


def _source(key: str, value: object, profile: dict | None, preset_profile: dict, default: dict) -> str:
    if profile is None or key not in profile:
        return "default"
    if key in preset_profile and preset_profile[key] == value:
        return "preset"
    return "default" if value == default.get(key) else "user"


def writing_guidance(spec: dict) -> dict:
    """Audience, tone, length, objective and instructions, each tagged user / preset / default."""
    profile = (spec.get("commentary") or {}).get("style_profile")
    default = default_style_profile()
    preset_profile, preset_name = _preset_profile(spec)
    output = {}
    for key in GUIDANCE_FIELDS:
        value = copy.deepcopy((profile or {}).get(key, default.get(key)))
        output[key] = {"value": value, "source": _source(key, value, profile, preset_profile, default)}
    output["preset_name"] = preset_name
    return output


def business_context(spec: dict) -> list[dict]:
    """Facts a person or preset stated, one per line; never verified against the data."""
    profile = (spec.get("commentary") or {}).get("style_profile") or {}
    text = str(profile.get("business_context") or "")
    preset_profile, preset_name = _preset_profile(spec)
    source = "preset" if text and preset_profile.get("business_context") == text else "user"
    who = f"the '{preset_name}' preset" if source == "preset" else "the user"
    items = []
    for line in [line.strip(" -•\t") for line in text.splitlines()]:
        if line and len(items) < MAX_CONTEXT_ITEMS:
            ref = f"context:{source}:{len(items) + 1}"
            items.append({"id": ref, "evidence_ref": ref, "text": line[:300], "source": source, "verified": False,
                          "note": f"Stated by {who}; not checked against the data. Attribute it when used."})
    return items


def attach(evidence: dict, spec: dict) -> dict:
    """Add writing guidance and stated business context to a run's evidence pack."""
    evidence["writing_guidance"] = writing_guidance(spec)
    evidence["business_context"] = business_context(spec)
    return refresh_allowed(evidence)
