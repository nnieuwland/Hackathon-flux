"""Generic composite-key left joins; never release silently multiplied facts."""
import pandas as pd
from .money import total


def _normalize(value: object, steps: list[str]) -> str | None:
    if pd.isna(value):
        return None
    text = str(value)
    for step in steps:
        if step == "trim":
            text = text.strip()
        elif step == "upper":
            text = text.upper()
        elif step == "lstrip_zeros":
            text = text.lstrip("0") or "0"
    return text or None


def apply_source_joins(df: pd.DataFrame, joins: list[dict], lookups: dict[str, pd.DataFrame] | None) -> tuple[pd.DataFrame, list[dict]]:
    result, audit = df.copy(), []
    for index, join in enumerate(joins):
        name = join["source"]
        if name not in (lookups or {}):
            if join.get("optional"):
                for column in join.get("columns", []):
                    output = join.get("prefix", "") + column
                    if output in result:
                        raise ValueError(f"Optional join '{name}' would overwrite {output}.")
                    result[output] = None
                audit.append({"lookup": name, "missing_source": True, "unmatched_keys": [], "unmatched_rows": len(result), "unmatched_value": total(result["__flux_value"]) if "__flux_value" in result else 0, "duplicate_keys": [], "fanout": False, "severity": "warn"})
                continue
            raise ValueError(f"Lookup '{name}' is missing. Upload and define it first.")
        source = lookups[name].copy()
        left = [pair["left"] for pair in join["on"]]
        right = [pair["right"] for pair in join["on"]]
        if any(column not in result for column in left) or any(column not in source for column in right):
            raise ValueError(f"Join '{name}' references missing key columns.")
        steps = join.get("key_normalise", ["trim"])
        key = f"__join_key_{index}"
        def keys(frame: pd.DataFrame, columns: list[str]) -> list:
            values = [tuple(_normalize(value, steps) for value in row) for row in frame[columns].itertuples(index=False, name=None)]
            return [value if all(part is not None for part in value) else None for value in values]
        result[key] = keys(result, left)
        source[key] = keys(source, right)
        source = source.loc[source[key].notna()]
        duplicates = set(source.loc[source[key].duplicated(False), key])
        matched_duplicate_keys = duplicates & set(result[key].dropna())
        fanout = bool(matched_duplicate_keys) and join.get("dedupe_right", "error") == "error"
        # Controls stop error-policy fanout before any results are released.
        source = source.drop_duplicates(key, keep="first")
        fields = join.get("columns", [column for column in source if column not in right + [key]])
        if any(field not in source for field in fields):
            raise ValueError(f"Join '{name}' references missing output columns.")
        names = {field: join.get("prefix", "") + field for field in fields}
        if any(output in result for output in names.values()):
            raise ValueError(f"Join '{name}' would overwrite columns. Choose a distinct prefix.")
        unmatched = ~result[key].isin(set(source[key]))
        result[f"__join_unmatched_{index}"] = unmatched.to_numpy()
        attrs = dict(result.attrs)
        audit.append({
            "lookup": name, "unmatched_keys": sorted(str(value) for value in set(result.loc[unmatched, key])),
            "unmatched_rows": int(unmatched.sum()),
            "unmatched_value": total(result.loc[unmatched, "__flux_value"]) if "__flux_value" in result else 0,
            "duplicate_keys": sorted(str(value) for value in duplicates), "fanout": fanout,
            "deduplicated_keys": sorted(str(value) for value in duplicates) if join.get("dedupe_right") == "first" else [],
            "severity": join.get("unmatched", "warn"),
        })
        result = result.merge(source[[key, *fields]].rename(columns=names), how="left", on=key, sort=False, validate="many_to_one").drop(columns=[key])
        result.attrs.update(attrs)
    result.attrs["join_audit"] = audit
    return result, audit
