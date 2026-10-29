"""Stable configuration and input-file fingerprints for local audit packs."""
import copy
import hashlib
import json
from pathlib import Path


def spec_hash(spec: dict) -> str:
    content = copy.deepcopy(spec)
    content.pop("run_stamp", None)
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def stamp_run(run_id: str, created: str, spec: dict, sources: list[dict], uploads: Path) -> dict:
    files = []
    for source in sources:
        if not source.get("defined"):
            continue
        digest = hashlib.sha256()
        with (uploads / source["stored"]).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({"name": source["name"], "sha256": digest.hexdigest(), "role": source.get("role"), "definition": copy.deepcopy(source["definition"])})
    return {"run_id": run_id, "created": created, "engine_version": "2.0", "spec_sha256": spec_hash(spec), "preset": copy.deepcopy(spec.get("preset")), "input_files": files}
