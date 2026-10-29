"""Small explicit offline instruction grammar; unsupported requests fail clearly.

The grammar understands one or more short clauses ("compare Q2 vs Q1, group by
country, top 10 movements, threshold 250k, executive audience") so the offline
mode can exercise the conversational journey without a live AI service.
"""
import copy
import re
from datetime import date

MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
MONTHS = {name.lower(): index for index, name in enumerate(MONTH_NAMES, 1)}
MONTHS.update({name[:3]: value for name, value in list(MONTHS.items())})
SUPPORTED = "Offline mode understands requests such as 'Only EMEA', 'Set the threshold to 250k', 'Compare May vs April', 'Compare Q2 vs Q1', 'Group by country', 'Show the top 10 movements', 'Executive audience', 'Short commentary' and 'Risk-focused tone'. Use the controls on this page for anything else."


def _amount(number: str, unit: str | None) -> float:
    return float(number.replace(",", "")) * {"k": 1000, "m": 1000000}.get((unit or "").lower(), 1)


def _quarter(year: int, quarter: int) -> list[str]:
    return [f"{year:04d}-{month:02d}" for month in range(quarter * 3 - 2, quarter * 3 + 1)]


def _column(spec: dict, columns: list[str], name: str) -> str | None:
    wanted = re.sub(r"[^a-z0-9]", "", name.lower())
    pool = list(dict.fromkeys([*columns, *spec.get("roles", {}).get("dimensions", [])]))
    exact = [column for column in pool if re.sub(r"[^a-z0-9]", "", column.lower()) == wanted]
    if exact:
        return exact[0]
    partial = [column for column in pool if wanted and wanted in re.sub(r"[^a-z0-9]", "", column.lower())]
    return partial[0] if len(partial) == 1 else None


# Words that may surround a recognised phrase without changing its meaning. Any
# other leftover word means part of the clause was not understood, so the whole
# clause is refused instead of being applied partially.
FILLER = frozenset("""compare comparing comparison please set show use make the a an with vs versus against to and
me just for of is at our my explain explaining movements movement drivers items lines important it
previous prior preceding one""".split())


def _whole(clean: str, match: re.Match | None) -> re.Match | None:
    """Return the match only when nothing meaningful is left over in the clause."""
    if not match:
        return None
    leftover = clean[:match.start()] + " " + clean[match.end():]
    words = re.findall(r"[a-z0-9]+", leftover.lower())
    return match if all(word in FILLER for word in words) else None


def split_clauses(text: str, split_and: bool = False) -> list[str]:
    """Split a request into clauses, turning a trailing 'by X' into its own grouping clause."""
    parts = [part for part in re.split(r"\s*(?:[;\n]|,\s*(?:and\s+)?|\.\s+|\band then\b|\band\s+(?=(?:exclude|excluding|include|only|show|set|threshold|materiality|top|explain|use|keep|remove|without|write|make|compare)\b))\s*", text.strip(), flags=re.I) if part and part.strip()]
    clauses = []
    for part in parts:
        part = part.strip().rstrip(".!")
        tail = None
        if not re.match(r"(?:group(?:ed)?|split|break(?:\s+it)?\s+down)\s+by\b", part, re.I):
            found = re.search(r"\s+(?:grouped\s+|split\s+|broken\s+down\s+)?by\s+(.+)$", part, re.I)
            if found and part[:found.start()].strip():
                part, tail = part[:found.start()].strip(), "group by " + found[1].strip()
        grouping = re.match(r"(?:group(?:ed)?|split|break(?:\s+it)?\s+down)\s+by\b", part, re.I)
        pieces = [piece for piece in re.split(r"\s+\band\b\s+", part) if piece.strip()] if split_and and not grouping else [part]
        clauses.extend(piece.strip() for piece in pieces)
        if tail:
            clauses.append(tail)
    return clauses


def _style(spec: dict) -> dict:
    from .contracts import sanitize_style_profile
    return sanitize_style_profile(spec.get("commentary", {}).get("style_profile") or {})


def clause_patch(spec: dict, text: str, columns: list[str], months: list[str]) -> tuple[list[dict], str] | None:
    """Return a patch for one clause, or None when the clause is not understood."""
    clean = text.strip().rstrip(".!")
    threshold = _whole(clean, re.search(r"(?:(?:materiality|threshold)(?:\s+(?:to|at|of|is))?\s*=?|(?:over|above|of at least|at least|greater than|more than)|>=?)\s*[$€£]?\s*([\d,.]*\d)\s*([km])?\b", clean, re.I))
    if threshold:
        amount = _amount(threshold[1], threshold[2])
        return [{"op": "add", "path": "/drivers/materiality", "value": {"mode": "abs", "abs": amount}}], f"Movements of at least {amount:,.0f} are treated as important."
    top = _whole(clean, re.search(r"\btop\s+(\d+)\b|\bshow(?:\s+the)?\s+(\d+)\s+(?:largest\s+|biggest\s+)?(?:drivers|movements|items|lines)\b", clean, re.I))
    if top:
        count = int(top[1] or top[2])
        if 1 <= count <= 50:
            return [{"op": "add", "path": "/drivers/top_n", "value": count}], f"Show up to {count} important movements."
        top = None
    only = re.fullmatch(r"(?:only|keep only|include only)\s+(.+)", clean, re.I)
    if only:
        dimensions = spec.get("roles", {}).get("dimensions", [])
        column = next((item for item in dimensions if re.search(r"region|geography|market", item, re.I)), None)
        column = column or (dimensions[0] if len(dimensions) == 1 else None)
        if not column:
            raise ValueError("Choose the grouping fields first so the offline assistant knows which field to filter.")
        value = only[1].strip()
        scope = [rule for rule in spec.get("scope", []) if rule["col"] != column]
        scope.append({"col": column, "op": "eq", "val": value})
        return [{"op": "replace", "path": "/scope", "value": scope}], f"Only include rows where {column} is {value}."
    group = re.fullmatch(r"(?:group(?:ed)?|split|break(?:\s+it)?\s+down)\s+by\s+(.+)", clean, re.I)
    if group:
        names = [part for part in re.split(r"\s*(?:,|\band\b|\bthen\b)\s*", group[1]) if part]
        keys = [_column(spec, columns, name) for name in names]
        if not names or None in keys:
            raise ValueError(f"I could not find a column called '{group[1]}'. Pick the grouping fields on the Group step.")
        views = copy.deepcopy(spec.get("views", []))
        name = spec.get("drivers", {}).get("view") or "by_dimension"
        view = next((item for item in views if item.get("name") == name), None)
        if view is None:
            view = {"name": name, "keys": keys, "measures": ["amount"], "compare": True}
            views.append(view)
        view["keys"] = keys
        patch = [{"op": "replace" if "views" in spec else "add", "path": "/views", "value": views}]
        dimensions = list(dict.fromkeys([*keys, *spec.get("roles", {}).get("dimensions", [])]))
        if dimensions != spec.get("roles", {}).get("dimensions", []):
            patch.append({"op": "replace", "path": "/roles/dimensions", "value": dimensions})
        if spec.get("drivers", {}).get("view") != name:
            patch.append({"op": "add", "path": "/drivers/view", "value": name})
        return patch, "Group movements by " + ", ".join(keys) + "."
    quarter = _whole(clean, re.search(r"\bQ([1-4])(?:\s+(\d{4}))?\s+(?:vs\.?|versus|against|with|to)\s+Q([1-4])(?:\s+(\d{4}))?", clean, re.I))
    if quarter:
        latest = int((months[-1] if months else str(date.today().year))[:4])
        current = _quarter(int(quarter[2] or quarter[4] or latest), int(quarter[1]))
        base = _quarter(int(quarter[4] or quarter[2] or latest), int(quarter[3]))
        return [{"op": "replace", "path": "/comparison", "value": {"type": "QoQ", "base": {"months": base}, "current": {"months": current}}}], f"Compare {current[0]} to {current[-1]} with {base[0]} to {base[-1]}."
    latest_quarter = r"(?:the\s+)?(?:latest|last|most\s+recent)\s+quarter(?:\s+(?:with|vs\.?|versus|against|to)\s+(?:the\s+)?(?:previous|prior|preceding)\s+(?:quarter|one))?|quarter\s+on\s+quarter|\bqoq\b"
    if _whole(clean, re.search(latest_quarter, clean, re.I)) and len(months) >= 6:
        return [{"op": "replace", "path": "/comparison", "value": {"type": "QoQ", "base": {"months": months[-6:-3]}, "current": {"months": months[-3:]}}}], f"Compare the latest three months ({months[-3]} to {months[-1]}) with the three before."
    latest_month = r"(?:the\s+)?(?:latest|last|most\s+recent)\s+month(?:\s+(?:with|vs\.?|versus|against|to)\s+(?:the\s+)?(?:previous|prior|preceding)\s+(?:month|one))?|month\s+on\s+month|\bmom\b"
    if _whole(clean, re.search(latest_month, clean, re.I)) and len(months) >= 2:
        return [{"op": "replace", "path": "/comparison", "value": {"type": "MoM", "base": {"months": months[-2:-1]}, "current": {"months": months[-1:]}}}], f"Compare {months[-1]} with {months[-2]}."
    comparison = None
    for found in re.finditer(r"\b([a-z]+)(?:\s+(\d{4}))?\s+(?:vs\.?|versus|against|with|to)\s+([a-z]+)(?:\s+(\d{4}))?", clean, re.I):
        if found[1].lower() in MONTHS and found[3].lower() in MONTHS:
            comparison = _whole(clean, found)
            break
    if comparison:
        existing = spec.get("comparison", {}).get("current", {}).get("months", []) or months
        year = int(comparison[2] or comparison[4] or (existing[-1][:4] if existing else date.today().year))
        current = f"{year:04d}-{MONTHS[comparison[1].lower()]:02d}"
        base = f"{int(comparison[4] or year):04d}-{MONTHS[comparison[3].lower()]:02d}"
        return [{"op": "replace", "path": "/comparison", "value": {"type": "MoM", "base": {"months": [base]}, "current": {"months": [current]}}}], f"Compare {current} against {base}."
    style, changed, words = _style(spec), [], clean.lower()
    for key, pattern, value, label in (
        ("audience", r"\bexecutive|leadership|board\b", "executive", "executive audience"),
        ("audience", r"\bcontroller|finance team\b", "controller", "controller audience"),
        ("audience", r"\bdetailed|analyst\b", "detailed", "detailed audience"),
        ("length", r"\bshort|brief|concise\b", "short", "short commentary"),
        ("length", r"\bmedium\b", "medium", "medium-length commentary"),
        ("length", r"\bper (?:driver|movement)|one line (?:per|for each)\b", "per_driver", "one line per movement"),
        ("tone", r"\brisk", "risk_focused", "risk-focused tone"),
        ("tone", r"\bfavou?rable|unfavou?rable\b", "fav_unfav", "favourable/unfavourable tone"),
        ("tone", r"\bneutral\b", "neutral", "neutral tone"),
    ):
        if re.search(pattern, words) and re.search(r"audience|commentary|tone|style|summary|write|bullets|explanations|" + pattern, words):
            if style[key] != value and not any(item[0] == key for item in changed):
                style[key] = value
                changed.append((key, label))
    if changed:
        leftover = words
        for pattern in (r"\bexecutive|leadership|board\b", r"\bcontroller|finance team\b", r"\bdetailed|analyst\b", r"\bshort|brief|concise\b", r"\bmedium(?:-length)?\b",
                        r"\bper (?:driver|movement)|one line (?:per|for each)(?: driver| movement)?\b", r"\brisk(?:-focused| focused)?\b", r"\bfavou?rable|unfavou?rable|adverse\b", r"\bneutral\b",
                        r"\b(?:audience|commentary|tone|style|summary|summaries|write|written|bullets|explanations|level|length|language|focused|use|a|an|the|and|with|please|for|of|or|readers?)\b"):
            leftover = re.sub(pattern, " ", leftover)
        if re.search(r"[a-z0-9]", leftover):
            return None
        commentary = copy.deepcopy(spec.get("commentary", {}))
        commentary["style_profile"] = style
        return [{"op": "replace" if "commentary" in spec else "add", "path": "/commentary", "value": commentary}], "Use " + " and ".join(label for _, label in changed) + "."
    return None


def instruction_patch(spec: dict, text: str, columns: list[str] | None = None, months: list[str] | None = None) -> tuple[list[dict], str]:
    """Apply every understood clause in order; fail if any clause is unknown."""
    from engine.patches import apply_patch
    clauses = split_clauses(text)
    if not clauses:
        raise ValueError(SUPPORTED)
    working, patch, summaries = copy.deepcopy(spec), [], []
    for clause in clauses:
        result = clause_patch(working, clause, columns or [], months or [])
        if result is None:
            raise ValueError(f"I could not apply '{clause.strip()[:80]}'. {SUPPORTED}")
        operations, summary = result
        working = apply_patch(working, operations, "agent", summary)
        patch.extend(operations)
        summaries.append(summary)
    return patch, " ".join(summaries)


def plan_from_text(spec: dict, text: str, columns: list[str], months: list[str]) -> tuple[list[dict], list[str], list[str]]:
    """Best-effort plan: apply understood clauses, report the rest as notes."""
    from engine.patches import apply_patch
    clauses = split_clauses(text, split_and=True)
    working, patch, summaries, skipped = copy.deepcopy(spec), [], [], []
    for clause in clauses:
        try:
            result = clause_patch(working, clause, columns, months)
        except ValueError:
            result = None
        if result is None:
            skipped.append(clause.strip()[:120])
            continue
        operations, summary = result
        try:
            working = apply_patch(working, operations, "agent", summary)
        except ValueError:
            skipped.append(clause.strip()[:120])
            continue
        patch.extend(operations)
        summaries.append(summary)
    return patch, summaries, skipped
