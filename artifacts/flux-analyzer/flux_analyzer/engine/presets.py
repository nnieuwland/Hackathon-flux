"""Versioned, data-only FluxSpec presets with a safe generic fallback."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import WORKSPACE
from .spec import default_spec, validate_spec

ROOT = Path(__file__).resolve().parents[1] / "presets"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")
STEP_BLOCKS = {
    "detect_flux": ("roles", "comparison", "value_rules"),
    "map_columns": ("roles",),
    "define_comparison": ("periods", "period_format", "comparison", "partial_periods"),
    "derive_columns": ("scope", "derive", "classification"),
    "classify_terms": ("classification", "derive"),
    "define_rules": ("value_rules", "joins", "measures", "views", "sections", "decompose", "flags", "gates", "drivers", "drill", "commentary", "controls"),
    "write_commentary": ("commentary", "drivers", "views"),
}


def _read_dir(directory: Path) -> dict:
    path = directory / "preset.json"
    if not path.is_file():
        raise ValueError(f"Preset manifest is missing in {directory.name}.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not ID_PATTERN.fullmatch(str(manifest.get("id", ""))):
        raise ValueError(f"Invalid preset identifier in {path.name}.")
    if directory.parent == ROOT:
        expected_id = directory.name
    elif directory.parent.parent == WORKSPACE / "presets":
        expected_id = directory.parent.name
    else:
        raise ValueError("Preset directory is outside the built-in and workspace preset roots.")
    if manifest["id"] != expected_id:
        raise ValueError("Preset directory does not match its identifier.")
    if not all(isinstance(manifest.get(key), str) and manifest[key].strip() for key in ("name", "version")):
        raise ValueError(f"Preset '{manifest['id']}' needs a name and version.")
    guidance = directory.joinpath("guidance.md")
    manifest["guidance"] = guidance.read_text(encoding="utf-8").strip() if guidance.exists() else ""
    if len(manifest["guidance"].split()) > 800:
        raise ValueError(f"Preset '{manifest['id']}' guidance exceeds 800 words.")
    manifest["categories"] = json.loads((directory / "categories.json").read_text(encoding="utf-8")) if (directory / "categories.json").exists() else []
    if not isinstance(manifest.get("defaults", {}), dict):
        raise ValueError(f"Preset '{manifest['id']}' defaults must be an object.")
    return manifest


def _manifest_dirs() -> list[Path]:
    dirs = list(ROOT.glob("*/"))
    stored_root = WORKSPACE / "presets"
    if stored_root.exists():
        dirs.extend(p.parent for p in stored_root.glob("*/*/preset.json"))
    return dirs


def load_presets() -> dict[str, dict]:
    """Load built-in and workspace presets; newest version wins by ID."""
    manifests: dict[str, list[dict]] = {}
    for directory in _manifest_dirs():
        manifest = _read_dir(directory)
        manifests.setdefault(manifest["id"], []).append(manifest)
    presets: dict[str, dict] = {}
    for preset_id, versions in manifests.items():
        versions.sort(key=lambda item: _version_tuple(item["version"]))
        latest = versions[-1]
        latest["versions"] = [
            {"version": item["version"], "owner": item.get("owner", ""), "updated_at": item.get("updated_at", "")}
            for item in versions
        ]
        presets[preset_id] = latest
    if "generic_flux" not in presets:
        raise ValueError("The required generic_flux preset is missing.")
    return presets


def _version_tuple(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version)
    return tuple(map(int, numbers)) if numbers else (0,)


def get_preset(preset_id: str | None, version: str | None = None) -> dict:
    presets = load_presets()
    if not preset_id:
        return presets["generic_flux"]
    if preset_id not in presets:
        raise ValueError(f"Unknown preset '{preset_id}'.")
    if version and presets[preset_id]["version"] != version:
        for directory in _manifest_dirs():
            manifest = _read_dir(directory)
            if manifest["id"] == preset_id and manifest["version"] == version:
                return manifest
        raise ValueError(f"Preset '{preset_id}' version '{version}' is unavailable. Import it or select an available version.")
    return presets[preset_id]


def list_presets() -> list[dict]:
    return [
        {key: preset.get(key) for key in ("id", "name", "version", "owner", "updated_at", "versions", "description", "detect_hints")}
        for preset in sorted(load_presets().values(), key=lambda item: item["name"].lower())
    ]


def apply_defaults(spec: dict, preset: dict) -> dict:
    """Overlay a preset's declarative defaults and validate the full spec."""
    candidate = copy.deepcopy(spec)
    defaults = preset.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("Preset defaults must be an object.")
    for block, value in defaults.items():
        candidate[block] = copy.deepcopy(value)
    candidate["preset"] = {"id": preset["id"], "version": preset["version"]}
    if not candidate.get("flux_name") or candidate["flux_name"] == "Untitled analysis":
        candidate["flux_name"] = preset["name"]
    return validate_spec(candidate)


def agent_payload(preset: dict, step: str) -> dict:
    """Return only the chosen preset's guidance and step-relevant defaults."""
    relevant = {key: copy.deepcopy(preset.get("defaults", {})[key]) for key in STEP_BLOCKS.get(step, ()) if key in preset.get("defaults", {})}
    payload = {
        "id": preset["id"],
        "name": preset["name"],
        "version": preset["version"],
        "guidance": preset.get("guidance", ""),
        "defaults": relevant,
    }
    if step == "classify_terms":
        payload["categories"] = copy.deepcopy(preset.get("categories", []))
    return payload


def save_preset(preset_id: str, name: str, owner: str, description: str, guidance: str, spec: dict, categories: list | None = None, import_manifest: dict | None = None) -> dict:
    """Save a user preset as a new immutable version under workspace/presets."""
    preset_id = preset_id.strip().lower()
    if not ID_PATTERN.fullmatch(preset_id):
        raise ValueError("Preset ID must use 2–48 lowercase letters, digits, underscores, or hyphens.")
    if preset_id == "generic_flux" and (ROOT / preset_id).exists():
        raise ValueError("The built-in generic_flux preset cannot be replaced.")
    if not name.strip() or len(name) > 120 or len(guidance.split()) > 800:
        raise ValueError("Enter a preset name of 1–120 characters and guidance of at most 800 words.")
    validate_spec(spec)
    defaults = {key: copy.deepcopy(value) for key, value in spec.items() if key not in ("spec_version", "preset", "flux_name", "sources", "skill", "run_stamp")}
    existing = [manifest for manifest in load_presets().values() if manifest["id"] == preset_id]
    if existing:
        version_parts = list(_version_tuple(max((p["version"] for p in existing), key=_version_tuple)))
        while len(version_parts) < 3:
            version_parts.append(0)
        version_parts[-1] += 1
        version = ".".join(map(str, version_parts))
    else:
        version = "1.0.0"
    directory = WORKSPACE / "presets" / preset_id / version
    if directory.exists():
        raise ValueError(f"Preset version {preset_id}@{version} already exists.")
    directory.mkdir(parents=True, exist_ok=False)
    timestamp = datetime.now(timezone.utc).isoformat()
    manifest = {
        "id": preset_id, "name": name.strip(), "version": version,
        "owner": owner.strip()[:120], "description": description.strip()[:500],
        "updated_at": timestamp, "defaults": defaults,
    }
    (directory / "preset.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "guidance.md").write_text(guidance.strip() + "\n", encoding="utf-8")
    if categories:
        (directory / "categories.json").write_text(json.dumps(categories, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_presets()[preset_id]


def export_preset(preset: dict) -> dict:
    return {
        "id": preset["id"], "name": preset["name"], "version": preset["version"],
        "owner": preset.get("owner", ""), "description": preset.get("description", ""),
        "updated_at": preset.get("updated_at", ""), "versions": preset.get("versions", []),
        "guidance": preset.get("guidance", ""), "defaults": preset.get("defaults", {}),
        "categories": preset.get("categories", []),
    }
