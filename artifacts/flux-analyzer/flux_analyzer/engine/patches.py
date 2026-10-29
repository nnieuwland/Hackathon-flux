"""Validated JSON Patch subset and per-project spec audit utilities."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from .spec import validate_spec


def _parts(path: str) -> list[str]:
    if path == "":
        return []
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("Patch paths must be JSON Pointers beginning with '/'.")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _parent(document: Any, parts: list[str]) -> tuple[Any, str]:
    if not parts:
        raise ValueError("A patch cannot target the root except with a root replace.")
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"Patch path does not exist at '{part}'.") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValueError(f"Patch path does not exist at '{part}'.")
    return current, parts[-1]


def _get(document: Any, parts: list[str]) -> Any:
    current = document
    for part in parts:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ValueError(f"Patch path does not exist at '{part}'.") from exc
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValueError(f"Patch path does not exist at '{part}'.")
    return current


def apply_patch(
    spec: dict,
    patch: list[dict],
    actor: str,
    reason: str,
    change_log: list[dict] | None = None,
) -> dict:
    """Apply add/remove/replace/test operations and validate atomically.

    Only `add`, `remove`, `replace`, and `test` JSON Patch operations are
    supported. No mutation is returned or logged unless the complete updated
    FluxSpec passes validation.
    """
    if actor not in {"agent", "user", "preset", "undo", "redo", "system"}:
        raise ValueError("Unsupported change actor.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("A change reason of 1–1000 characters is required.")
    if not isinstance(patch, list) or not patch:
        raise ValueError("A spec patch must contain at least one operation.")

    output = copy.deepcopy(spec)
    events: list[dict] = []
    for operation in patch:
        if not isinstance(operation, dict):
            raise ValueError("Each patch operation must be an object.")
        op, path = operation.get("op"), operation.get("path")
        parts = _parts(path)
        if op not in {"add", "remove", "replace", "test"}:
            raise ValueError(f"Unsupported JSON Patch operation '{op}'.")
        if op in {"add", "replace", "test"} and "value" not in operation:
            raise ValueError(f"Patch operation '{op}' requires a value.")
        if not parts:
            if op != "replace" or not isinstance(operation["value"], dict):
                raise ValueError("Only a root replace with a FluxSpec object is allowed.")
            before = output
            output = copy.deepcopy(operation["value"])
        else:
            parent, key = _parent(output, parts)
            if isinstance(parent, list):
                if key == "-" and op == "add":
                    index = len(parent)
                else:
                    try:
                        index = int(key)
                    except ValueError as exc:
                        raise ValueError(f"Invalid array index '{key}'.") from exc
                if op == "add":
                    if index < 0 or index > len(parent):
                        raise ValueError("Array add index is out of range.")
                    parent.insert(index, copy.deepcopy(operation["value"]))
                    before = None
                else:
                    if index < 0 or index >= len(parent):
                        raise ValueError("Array patch index is out of range.")
                    before = parent[index]
                    if op == "test":
                        if before != operation["value"]:
                            raise ValueError(f"Patch test failed at '{path}'.")
                        continue
                    if op == "remove":
                        parent.pop(index)
                    else:
                        parent[index] = copy.deepcopy(operation["value"])
            elif isinstance(parent, dict):
                exists = key in parent
                before = copy.deepcopy(parent.get(key))
                if op == "test":
                    if not exists or before != operation["value"]:
                        raise ValueError(f"Patch test failed at '{path}'.")
                    continue
                if op in {"replace", "remove"} and not exists:
                    raise ValueError(f"Patch target '{path}' does not exist.")
                if op == "remove":
                    del parent[key]
                else:
                    parent[key] = copy.deepcopy(operation["value"])
            else:
                raise ValueError(f"Patch parent at '{path}' is not an object or array.")
        events.append({
            "path": path,
            "op": op,
            "from": copy.deepcopy(before),
            "to": None if op == "remove" else copy.deepcopy(operation.get("value")),
        })

    validated = validate_spec(output)
    if change_log is not None:
        timestamp = datetime.now(timezone.utc).isoformat()
        change_log.extend({
            "timestamp": timestamp,
            "actor": actor,
            "reason": reason.strip(),
            **event,
        } for event in events)
    return validated


def diff_spec(before: dict, after: dict, path: str = "") -> list[dict]:
    """Create a deterministic add/remove/replace patch between two JSON trees."""
    if isinstance(before, dict) and isinstance(after, dict):
        result: list[dict] = []
        for key in sorted(before.keys() - after.keys()):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.append({"op": "remove", "path": f"{path}/{escaped}"})
        for key in sorted(after.keys() - before.keys()):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.append({"op": "add", "path": f"{path}/{escaped}", "value": copy.deepcopy(after[key])})
        for key in sorted(before.keys() & after.keys()):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            result.extend(diff_spec(before[key], after[key], f"{path}/{escaped}"))
        return result
    if before != after:
        return [{"op": "replace", "path": path, "value": copy.deepcopy(after)}]
    return []
