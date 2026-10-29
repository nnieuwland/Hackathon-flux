"""Reject commentary that changes evidence, order or numbers, or states causes the evidence cannot support."""
import re

NUMERIC = r"(?<!\w)[+-]?\d+(?:[.,]\d+)*[MKB]?"
# References that belong to one movement carry its driver id in the second position.
DRIVER_REF_KINDS = {"driver", "text", "trend", "decomp", "category", "coverage", "flag"}
# Report-wide references any line may cite.
SHARED_REF_KINDS = {"total", "control", "lookup", "classification", "partial", "section", "context"}
CLAIM_TYPES = ("observation", "possible_explanation", "context")

# Wording a model may only use when Python's history for that movement shows the pattern.
TREND_WORDS = {
    "continuing": re.compile(r"\b(?:continu(?:es|ing|ed)|ongoing|trend(?:s|ing)?|consecutive|sustained|persist(?:s|ent|ing)?|run[- ]rate)\b", re.I),
    "one_period": re.compile(r"\b(?:one[- ]period|single[- ]period|isolated|spike)\b", re.I),
    "reversal": re.compile(r"\brevers(?:al|als|es|ed|ing)\b", re.I),
}
# A business cause, timing or one-off judgement: never proven by descriptions or categories alone.
HYPOTHESIS_WORDS = re.compile(r"\b(?:due to|because|caused by|as a result of|owing to|attributable to|resulted from|result of|one[- ]off|one[- ]time|non[- ]?recurring|timing|phasing)\b", re.I)


# Words that attribute or hedge rather than carry content, ignored when matching stated context.
FILLER = {"that", "this", "these", "those", "with", "from", "were", "have", "been", "which", "their", "there", "about", "into", "than",
          "then", "they", "your", "told", "said", "stated", "according", "note", "notes", "possibly", "maybe", "might", "likely", "could",
          "would", "should", "caused", "result", "resulted", "owing", "attributable", "consistent", "line", "matches", "mentioned", "context", "user", "preset", "movement", "also", "what", "when"}


def _content(text: str) -> set[str]:
    words = re.findall(r"[a-z][a-z'-]{3,}", text.lower())
    return {word[:5] for word in words if word not in FILLER and not HYPOTHESIS_WORDS.fullmatch(word)}


def _repeats_context(text: str, cited: list[str]) -> bool:
    """True when nearly every content word of a sentence comes from the stated context it cites.

    Citing context is not proof: "due to an inventory write-off" citing a note about a new
    contract is still an unverified cause.
    """
    words = _content(text)
    return bool(words) and any(len(words & _content(context)) * 3 >= len(words) * 2 for context in cited)


def _cause_statements(text: str) -> list[str]:
    """Each sentence stating a cause, plus the clause that follows each cause word (the stated reason)."""
    output = []
    for sentence in re.split(r"(?<=[.;!?])\s+|\s+—\s+", text):
        for match in HYPOTHESIS_WORDS.finditer(sentence):
            output.append(sentence)
            reason = re.split(r"[,.;:!?()]", sentence[match.end():], maxsplit=1)[0]
            if _content(reason):
                output.append(reason)
    return output


def _only_context(text: str, cited: list[str]) -> bool:
    """The whole text, and every reason it gives, comes from the cited stated context."""
    return all(_repeats_context(part, cited) for part in [text, *_cause_statements(text)])


def _amount_tokens(value: object) -> set[str]:
    """Every pre-formatted amount inside one piece of evidence."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("_fmt") and isinstance(child, str):
                found.add(child)
            else:
                found |= _amount_tokens(child)
    elif isinstance(value, list):
        for child in value:
            found |= _amount_tokens(child)
    return found


def _evidence_strings(driver: dict) -> list[str]:
    """Source wording quoted in the evidence (labels, descriptions, categories, flags)."""
    strings = [str(driver.get("label", ""))]
    strings += [str(item.get("text", "")) for item in driver.get("top_texts", [])]
    strings += [str(item.get("category", "")) for item in (driver.get("categories") or {}).get("items", [])]
    strings += [f"{flag.get('rule', '')}" for flag in driver.get("flags", [])] + [f"{flag.get('label', '')}" for flag in driver.get("flags", [])]
    return sorted({item for item in strings if item.strip()}, key=len, reverse=True)


def _own_words(text: str, driver: dict) -> str:
    """The writer's own words: quoted source wording is evidence, not a claim, so it is removed."""
    for quoted in _evidence_strings(driver):
        text = re.sub(re.escape(quoted), " ", text, flags=re.I)
    return text


def _ref_problem(ref: str, driver_id: str, allowed: set[str]) -> str | None:
    if ref not in allowed:
        return "unknown"
    parts = ref.split(":")
    if parts[0] in DRIVER_REF_KINDS and len(parts) > 1 and parts[1] != driver_id:
        return "other"
    return None


def check_narrative(response: dict, evidence: dict, author: str = "agent", people: set[str] | frozenset = frozenset()) -> dict:
    """Verify driver order/coverage, exact amount tokens, numbers, references and claim wording.

    ``author`` is "agent" for model drafts and "person" for text a reviewer wrote; ``people`` lists
    movements whose current line a person wrote. People are the source of business causes, so cause
    and trend wording is only restricted for agent text.
    """
    proposal = response.get("proposal", response)
    lines = proposal.get("lines", [])
    drivers = evidence.get("drivers", [])
    rules = evidence.get("commentary_rules", {})
    verify_tag = rules.get("verify_tag", "[TO VERIFY]")
    allowed_refs = set(evidence.get("allowed_evidence_refs") or [])
    contexts = {item.get("evidence_ref") or item.get("id"): str(item.get("text", "")) for item in evidence.get("business_context") or []}
    shared_amounts = _amount_tokens(evidence.get("totals", {}))
    symbol = re.escape(rules.get("currency_symbol", "$"))
    amount_pattern = rf"[+-]?(?:{symbol}|[$€£¥])\d+(?:[.,]\d+)*[MKB]?(?: favorable| unfavorable| adverse)?"
    issues = []
    if [line.get("driver_id") for line in lines] != [d["driver_id"] for d in drivers]:
        issues.append("Drivers are missing, duplicated, or reordered.")
    for line, driver in zip(lines, drivers):
        driver_id = driver["driver_id"]
        text = line.get("text", "")
        claims = line.get("claims") or []
        refs = list(line.get("evidence_refs", []))
        by_agent = author == "agent" and driver_id not in people
        if driver["delta_fmt"] not in text:
            issues.append(f"{driver_id}: amount/sign must be exactly {driver['delta_fmt']}.")
        if not text.startswith(driver["delta_fmt"]):
            issues.append(f"{driver_id}: the line must start with the exact amount {driver['delta_fmt']}.")
        problems = {ref: _ref_problem(ref, driver_id, allowed_refs) for ref in refs + [r for claim in claims for r in claim.get("evidence_refs", [])]}
        unknown = [ref for ref, problem in problems.items() if problem == "unknown"]
        other = [ref for ref, problem in problems.items() if problem == "other"]
        if unknown:
            issues.append(f"{driver_id}: unknown evidence references {', '.join(unknown[:3])}.")
        if other:
            issues.append(f"{driver_id}: cites evidence that belongs to another movement ({', '.join(other[:3])}).")
        if line.get("support") == "needs_verification" and verify_tag not in text:
            issues.append(f"{driver_id}: a line that needs verification must include {verify_tag}.")
        if line.get("support") == "supported" and not refs:
            issues.append(f"{driver_id}: a supported line must list the evidence it relies on.")
        word_limit = rules.get("max_line_words")
        if word_limit and len(text.split()) > word_limit:
            issues.append(f"{driver_id}: line exceeds the {word_limit}-word limit.")
        allowed_amounts = _amount_tokens(driver) | shared_amounts
        for written in [text, line.get("confirm_prompt", ""), *(claim.get("text", "") for claim in claims)]:
            if any(amount not in allowed_amounts for amount in re.findall(amount_pattern, written)):
                issues.append(f"{driver_id}: an unsupported amount or sign appears.")
                break
        cited_contexts = [contexts[ref] for ref in refs if ref in contexts]
        for claim in claims:
            kind, claim_refs = claim.get("type"), claim.get("evidence_refs", [])
            if kind not in CLAIM_TYPES:
                issues.append(f"{driver_id}: claim type must be one of {', '.join(CLAIM_TYPES)}.")
            elif kind == "observation" and not [ref for ref in claim_refs if not ref.startswith("context:")]:
                issues.append(f"{driver_id}: every observation must cite checked evidence.")
            elif kind == "context" and not _only_context(claim.get("text", ""), [contexts[ref] for ref in claim_refs if ref in contexts]):
                issues.append(f"{driver_id}: a context claim must cite and repeat the business context it relies on.")
            elif kind == "possible_explanation" and not (line.get("support") == "needs_verification" and verify_tag in text) and not _only_context(claim.get("text", ""), [contexts[ref] for ref in claim_refs if ref in contexts]):
                issues.append(f"{driver_id}: a possible explanation needs {verify_tag} and support 'needs_verification', unless it only repeats the stated business context it cites.")
            if kind == "observation" and by_agent and HYPOTHESIS_WORDS.search(_own_words(claim.get("text", ""), driver)):
                issues.append(f"{driver_id}: an observation states a cause; label it a possible explanation.")
            cited_contexts += [contexts[ref] for ref in claim_refs if ref in contexts]
        if by_agent:
            own = _own_words(text, driver)
            if verify_tag not in text and any(not _repeats_context(sentence, cited_contexts) for sentence in _cause_statements(own.replace(driver["delta_fmt"], " "))):
                issues.append(f"{driver_id}: a cause, timing or one-off claim needs {verify_tag} unless it only repeats stated business context it cites.")
            history = driver.get("trend") or {}
            for pattern, words in TREND_WORDS.items():
                if words.search(own):
                    if history.get("pattern") != pattern:
                        issues.append(f"{driver_id}: the history does not show a {pattern.replace('_', '-')} pattern; remove that wording.")
                    elif not any(ref.startswith(f"trend:{driver_id}") for ref in refs + [r for claim in claims for r in claim.get("evidence_refs", [])]):
                        issues.append(f"{driver_id}: cite the history (trend:{driver_id}) when describing the pattern.")
    text = " ".join(str(proposal.get(k, "")) for k in ("headline", "others_summary")) + " " + " ".join(
        " ".join([line.get("text", ""), line.get("confirm_prompt", ""), *(claim.get("text", "") for claim in line.get("claims") or [])]) for line in lines)
    headline_hint = evidence.get("headline_hint")
    if headline_hint and proposal.get("headline") != headline_hint:
        issues.append("Use the configured headline template exactly.")
    numbers = set(re.findall(NUMERIC, text))
    permitted_text = " ".join(str(driver.get("delta_fmt", "")) + " " + str(driver.get("label", "")) + " " + " ".join(item["delta_fmt"] for item in driver.get("top_texts", [])) for driver in drivers)
    permitted_text += " " + (evidence.get("headline_hint") or "")
    allowed = set(re.findall(NUMERIC, permitted_text)) | set(evidence.get("allowed_numeric_tokens") or [])
    if numbers - allowed:
        issues.append("Unsupported numbers: " + ", ".join(sorted(numbers - allowed)))
    for term in rules.get("forbidden_terms", []):
        if str(term).lower() in text.lower():
            issues.append(f"Forbidden term appears: {term}.")
    global_issues = [issue for issue in issues if not any(issue.startswith(driver["driver_id"] + ":") for driver in drivers)]
    line_results = []
    for driver in drivers:
        local = [issue for issue in issues if issue.startswith(driver["driver_id"] + ":")] + global_issues
        line_results.append({"driver_id": driver["driver_id"], "ok": not local, "issues": local})
    return {"ok": not issues, "issues": issues, "line_results": line_results}
