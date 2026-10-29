"""Single source of truth for the `journey-1` agent contract.

The published documents in docs/agent/ describe these rules in prose; this
module enforces them. Response schemas live in schemas/responses.json and are
loaded by agent.client.
"""
import copy
import re

CONTRACT_VERSION = "journey-1"
JOURNEY_STEPS = ("data", "compare", "include", "group", "important", "explain")
STAGES = ("upload", "path", *JOURNEY_STEPS, "review", "results", "save")
MODES = ("simple", "advanced")

# Every configuration-changing call is limited to these JSON Pointer prefixes.
STEP_PATCH_PATHS = {
    "data": ("/roles", "/value_rules", "/period_format"),
    "compare": ("/comparison", "/periods", "/partial_periods", "/period_format"),
    "include": ("/scope", "/joins", "/derive", "/value_rules"),
    "group": ("/views", "/drivers/view", "/classification", "/sections", "/derive", "/measures", "/roles/dimensions"),
    "important": ("/drivers", "/flags", "/gates", "/drill"),
    "explain": ("/commentary",),
}
ALL_PATCH_PATHS = tuple(sorted({path for paths in STEP_PATCH_PATHS.values() for path in paths} | {"/flux_name", "/decompose", "/controls"}))
PROTECTED_PREFIXES = ("/sources", "/spec_version", "/run_stamp", "/preset")
MANDATORY_CONTROLS = ("required_columns", "periods_present", "drivers_reconcile")

STYLE_AUDIENCES = ("executive", "controller", "detailed", "custom")
STYLE_LENGTHS = ("short", "medium", "per_driver")
STYLE_TONES = ("neutral", "risk_focused", "fav_unfav")
STYLE_INCLUDE = ("timing", "one_offs", "to_verify")


def default_style_profile() -> dict:
    """Neutral defaults used when a user first opens the Explain step."""
    return {"audience": "controller", "length": "medium", "structure": {"type": "overall", "split_by": None}, "tone": "neutral", "instructions": "", "example_style": {"summary_of_style": "", "sample_phrases": []}, "include": ["to_verify"], "objective": "", "business_context": ""}


def allowed_paths_for(target: str | None) -> list[str]:
    """Allowed patch prefixes for a step-targeted call, or all permitted paths."""
    if target in STEP_PATCH_PATHS:
        return list(STEP_PATCH_PATHS[target])
    return list(ALL_PATCH_PATHS)


def _within(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def check_patch(patch: list, allowed: list[str] | tuple[str, ...], before: dict | None = None, after: dict | None = None) -> None:
    """Aggregate every ownership/protection error, raising one ValueError."""
    errors = []
    if not isinstance(patch, list):
        raise ValueError("proposal.patch: must be an array of operations.")
    for index, operation in enumerate(patch):
        if not isinstance(operation, dict):
            errors.append(f"proposal.patch.{index}: must be an object.")
            continue
        extra = set(operation) - {"op", "path", "value"}
        if extra:
            errors.append(f"proposal.patch.{index}: unknown keys {sorted(extra)}.")
        op, path = operation.get("op"), operation.get("path")
        if op not in ("add", "replace", "remove", "test"):
            errors.append(f"proposal.patch.{index}.op: '{op}' is not allowed.")
        if op == "remove" and "value" in operation:
            errors.append(f"proposal.patch.{index}: remove must not include a value.")
        if op in ("add", "replace", "test") and "value" not in operation:
            errors.append(f"proposal.patch.{index}: {op} requires a value.")
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"proposal.patch.{index}.path: must be a non-root JSON Pointer.")
            continue
        if any(_within(path, prefix) for prefix in PROTECTED_PREFIXES):
            errors.append(f"proposal.patch.{index}.path: {path} is protected and cannot be changed by the assistant.")
        elif not any(_within(path, prefix) for prefix in allowed):
            errors.append(f"proposal.patch.{index}.path: {path} is outside the settings this step may change.")
    if after is not None:
        present = {item.get("id") for item in after.get("controls", [])}
        had = {item.get("id") for item in (before or {}).get("controls", [])}
        removed = [control for control in MANDATORY_CONTROLS if control in had and control not in present]
        if removed:
            errors.append("proposal.patch: mandatory checks cannot be removed: " + ", ".join(removed) + ".")
    if errors:
        raise ValueError("\n".join(errors))


def validate_step_states(step_states: list, questions: list, status: str) -> None:
    """Exactly one state per journey step, in order, with consistent question IDs."""
    errors = []
    steps = [item.get("step") for item in step_states]
    if steps != list(JOURNEY_STEPS):
        errors.append("proposal.step_states: must contain exactly data, compare, include, group, important, explain in order.")
    question_ids = {question["id"] for question in questions}
    referenced = set()
    for index, item in enumerate(step_states):
        ids = item.get("question_ids", [])
        referenced.update(ids)
        unknown = set(ids) - question_ids
        if unknown:
            errors.append(f"proposal.step_states.{index}.question_ids: unknown question IDs {sorted(unknown)}.")
        if item.get("status") == "confident" and ids:
            errors.append(f"proposal.step_states.{index}: a confident step cannot have unresolved questions.")
    if status == "ok" and any(item.get("status") == "needs_input" for item in step_states):
        errors.append("status: use needs_input when any step needs input.")
    if errors:
        raise ValueError("\n".join(errors))


_MONTHS = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"


# Words a style description may share with the pasted example. Anything else the
# example and the style output have in common is treated as copied content.
STYLE_VOCABULARY = frozenset("""
a an the and or but nor of to in on at by for from with into onto over under than then that this these those
it its is are was were be been being as so if when where which while who whom whose what each every both
either neither not no only also more most less least very much many some any such same other another own
one two first second last next per via up down out off about after before above below between through
they them their there here we our you your he she his her will would should could can may might must shall
use uses used using lead leads leading start starts starting end ends ending open opens opening close closes
amount amounts movement movements line lines item items driver drivers variance variances total totals
favourable favorable unfavourable unfavorable adverse positive negative increase increases increased
decrease decreases decreased higher lower up down growth decline change changes changed
short shorter brief concise fuller full longer long detailed summary summaries paragraph paragraphs
sentence sentences bullet bullets bulleted list lists heading headings headline headlines label labels labelled labeled
tone neutral formal informal plain direct risk risks risky exposure focus focused calls call
timing phasing accrual accruals reversal reversals oneoff one-off oneoffs recurring nonrecurring non-recurring
effect effects impact impacts explanation explanations explain explains explained commentary comment comments
cause causes caused reason reasons driven drive drives relates related relating relate evidence supported support
verify verified verification confirm confirmed confirmation unverified unconfirmed marks mark marked flag flags flagged
offset offsets partly partially largest smallest biggest main key primary secondary first separately separate separates
group grouped groups split splits section sections period periods month months quarter quarters year years prior previous
budget forecast actual actuals plan versus compared against compare comparison write writes written style styled
number numbers figure figures value values percent percentage rounded round units currency
""".split())


def _style_words(text: str) -> list[str]:
    # Placeholders such as [supported evidence] are generic by construction.
    return re.findall(r"[a-z][a-z\-]*", re.sub(r"\[[^\]]*\]", " ", text).lower())


def example_leaks(example_style: dict, example_text: str) -> list[str]:
    """Reject style output that copies numbers, periods, names, wording or claims from the example.

    Only a fixed style vocabulary may be shared with the example. Any other word
    that appears in both - sentence-initial names included - or any copied run of
    four words counts as content from the example, so the output is refused.
    """
    produced = " ".join([example_style.get("summary_of_style", ""), *example_style.get("sample_phrases", [])])
    issues = []
    if re.search(r"\d", re.sub(r"\[[^\]]*\]", " ", produced)):
        issues.append("Style summaries and phrases must not contain numbers, amounts or dates from the example.")
    if re.search(rf"\b({_MONTHS})\b|\bQ[1-4]\b|\bFY\d*", re.sub(r"\[[^\]]*\]", " ", produced), re.I):
        issues.append("Style summaries and phrases must not mention periods from the example.")
    example_words = _style_words(example_text)
    produced_words = _style_words(produced)
    shared = sorted({word for word in produced_words if word in set(example_words) and word not in STYLE_VOCABULARY})
    if shared:
        issues.append("Style summaries and phrases must not reuse names or wording from the example: " + ", ".join(shared[:5]) + ".")
    grams = {tuple(example_words[i:i + 4]) for i in range(len(example_words) - 3)}
    copied = [" ".join(produced_words[i:i + 4]) for i in range(len(produced_words) - 3) if tuple(produced_words[i:i + 4]) in grams]
    if copied:
        issues.append("Style summaries and phrases must not copy phrases from the example: '" + copied[0] + "'.")
    return issues


def sanitize_style_profile(profile: dict | None) -> dict | None:
    """Return a profile copy with defaults; spec schema validates strict types."""
    if profile is None:
        return None
    output = default_style_profile()
    output.update(copy.deepcopy(profile))
    if output["structure"].get("type") == "overall":
        output["structure"]["split_by"] = None
    output["include"] = [item for item in dict.fromkeys(output.get("include", [])) if item in STYLE_INCLUDE]
    return output
