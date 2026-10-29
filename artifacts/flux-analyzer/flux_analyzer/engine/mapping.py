"""Conservative, deterministic column rename mapping across uploads."""
import copy
import re
from difflib import SequenceMatcher


def remap_columns(spec: dict, columns: list[str]) -> tuple[dict, dict, list[str]]:
    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())
    roles = spec.get("roles", {})
    expected = {value for value in roles.values() if isinstance(value, str) and value}
    expected.update(value for values in roles.values() if isinstance(values, list) for value in values)
    derived = {rule["name"] for rule in spec.get("derive", [])}
    if spec.get("classification"):
        derived.add(spec["classification"].get("target_col"))
    renamed, unresolved = {}, []
    for name in sorted(expected):
        if name in columns or name in derived:
            continue
        exact = [column for column in columns if normalized(column) == normalized(name)]
        if len(exact) == 1:
            renamed[name] = exact[0]
            continue
        scores = sorted(((SequenceMatcher(None, normalized(name), normalized(column)).ratio(), column) for column in columns), reverse=True)
        if scores and scores[0][0] >= .78 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= .08):
            renamed[name] = scores[0][1]
        else:
            unresolved.append(name)
    def walk(value):
        if isinstance(value, str):
            return renamed.get(value, value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value
    candidate = copy.deepcopy(spec)
    for key in ("roles", "scope", "derive", "joins", "classification", "measures", "views", "drill", "sections"):
        if key in candidate:
            candidate[key] = walk(candidate[key])
    return candidate, renamed, unresolved
