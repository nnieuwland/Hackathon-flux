"""Local canned-response templates adapted only to bounded metadata."""
import copy
import json
from pathlib import Path
import re

TEMPLATES = json.loads((Path(__file__).parent / "mock_responses/templates.json").read_text())

def mock_response(envelope: dict) -> dict:
    """Return a schema-valid, explicitly mock proposal; no financial maths."""
    step, payload, spec = envelope["step"], envelope["payload"], envelope.get("spec_so_far", {})
    proposal = copy.deepcopy(TEMPLATES.get(step, {}))
    if step == "detect_flux":
        selected = payload.get("preset", {})
        proposal["preset_id"] = selected.get("id", "generic_flux")
        if spec.get("flux_name") and spec["flux_name"] != "Untitled analysis":
            proposal["flux_name"] = spec["flux_name"]
    elif step == "map_columns":
        columns = payload.get("profile", {}).get("columns", [])
        def pick(pattern: str) -> str | None:
            return next((c["name"] for c in columns if re.search(pattern, c["name"], re.I)), None)
        roles = {"value": pick(r"functional.?net|amount|^cost$|net.?value|expense"), "period": pick(r"period|month|date"), "scenario": pick(r"scenario|actual.?forecast|version"), "keys": [], "dimensions": [], "driver_text": [], "debit": pick(r"debit|accounted.?dr"), "credit": pick(r"credit|accounted.?cr")}
        roles["dimensions"] = [c["name"] for c in columns if re.search(r"country|account$|region|department|cost.?cent", c["name"], re.I)][:4]
        key = pick(r"^po.?number$|^base.?po$|vendor")
        if key:
            roles["keys"] = [key]
        text = pick(r"description|memo|narrative|text")
        if text:
            roles["driver_text"] = [text]
        if not roles["value"]:
            roles["value"] = next((c["name"] for c in columns if c["dtype_guess"] == "number"), None)
        proposal = {"roles": roles, "unmapped": [c["name"] for c in columns if c["name"] not in str(roles)]}
    elif step == "define_comparison":
        periods = sorted(payload.get("available_months", []))
        scenarios = [p["value"] for p in payload.get("scenario_values", [])]
        if len(periods) >= 6:
            base, current = periods[-6:-3], periods[-3:]
            kind = "QoQ"
        else:
            base, current = periods[-2:-1], periods[-1:]
            kind = "MoM"
        b, c = {"months": base}, {"months": current}
        if len(scenarios) >= 2 and len(periods) <= 1:
            b = {"months": periods, "scenario": next((s for s in scenarios if "forecast" in s.lower()), scenarios[0])}
            c = {"months": periods, "scenario": next((s for s in scenarios if "actual" in s.lower()), scenarios[-1])}
            kind = "Actual vs Forecast"
        proposal = {"comparison": {"type": kind, "base": b, "current": c}, "period_format": "auto", "partial_periods": []}
    elif step == "classify_terms":
        proposal["source_col"] = next(iter(spec.get("roles", {}).get("driver_text", [])), "")
        categories = payload.get("preset", {}).get("categories", [])
        if isinstance(categories, dict):
            proposal["rules"] = [{"keyword": keyword, "category": category, "match": "contains"} for keyword, category in categories.items()]
    elif step == "define_rules":
        keys = spec.get("roles", {}).get("dimensions", [])[:2] or spec.get("roles", {}).get("keys", [])[:1]
        proposal["views"] = [{"name": "by_dimension", "keys": keys, "measures": ["amount"], "compare": True}]
        proposal["drivers"]["materiality"] = copy.deepcopy(spec.get("drivers", {}).get("materiality", {"mode": "abs", "abs": 300000}))
        if spec.get("measures") and spec.get("views"):
            for key in proposal:
                if key in spec:
                    proposal[key] = copy.deepcopy(spec[key])
    elif step == "apply_instruction":
        from .mock_instructions import instruction_patch
        try:
            patch, summary = instruction_patch(spec, envelope.get("user_message") or payload.get("instruction", ""), payload.get("allowed_columns", []), payload.get("available_months", []))
            proposal = {"patch": patch}
        except ValueError as exc:
            summary = str(exc)[:1000]
            return {"contract_version": envelope.get("contract_version", "journey-1"), "request_id": envelope["request_id"], "step": step, "status": "cannot_do", "proposal": {}, "confidence": "low", "rationale": summary[:600], "questions": [], "warnings": TEMPLATES["warnings"], "summary": summary, "changes": []}
        return {"contract_version": envelope.get("contract_version", "journey-1"), "request_id": envelope["request_id"], "step": step, "status": "ok", "proposal": proposal, "confidence": "medium", "rationale": "Offline assistant: applied the instruction using the supported phrase list.", "questions": [], "warnings": TEMPLATES["warnings"], "summary": summary, "changes": []}
    elif step == "plan_from_description":
        return mock_plan(envelope)
    elif step == "extract_commentary_style":
        return mock_style(envelope)
    elif step == "describe_setup":
        sentences = [item["sentence"] for item in payload.get("rule_descriptions", []) if item["id"] in ("/comparison", "/drivers", "/roles")]
        name = payload.get("existing_name") or spec.get("flux_name") or "Flux setup"
        proposal = {"suggested_name": name[:120], "description": (" ".join(sentences) or "Reusable flux setup.")[:1000]}
    elif step == "explain_spec":
        proposal = {"sentences": ["This is the current validated FluxSpec. Mock mode does not generate custom explanations."]}
    elif step == "answer_question":
        from engine.describe import describe_spec
        cards = describe_spec(spec)
        terms = set(re.findall(r"[a-z]{4,}", envelope.get("user_message", "").lower()))
        relevant = [card["sentence"] for card in cards if any(term in card["sentence"].lower() or term in card["block"] for term in terms)]
        proposal = {"answer": "Offline explanation from the current configuration: " + " ".join(relevant[:4] or ["Review the rule descriptions and checked driver evidence. Business causes still require analyst verification."])}
    elif step == "write_commentary":
        evidence = payload["evidence_pack"]
        tag = evidence.get("commentary_rules", {}).get("verify_tag", "[TO VERIFY]")
        limit = evidence.get("commentary_rules", {}).get("max_line_words") or 35
        history_phrases = {"one_period": "Earlier periods were broadly stable.", "continuing": "It continues the direction of the two periods before."}
        lines = []
        for d in evidence["drivers"]:
            texts = d.get("top_texts", [])
            refs = list(d.get("evidence_refs", []))
            if d["driver_id"] != "others" and texts and texts[0]["delta_fmt"] == d["delta_fmt"]:
                # One consolidated description carries the whole movement: an observation, not a cause.
                refs.append(texts[0]["evidence_ref"])
                text = f"{d['delta_fmt']} — {d['label']}: the movement sits in '{texts[0]['text'][:60]}'."
                claims = [{"type": "observation", "text": f"The whole movement sits in one description, '{texts[0]['text'][:60]}'.", "evidence_refs": [texts[0]["evidence_ref"]]}]
                line = {"driver_id": d["driver_id"], "support": "supported"}
            else:
                text = f"{d['delta_fmt']} — {d['label']}. {tag} Confirm the underlying business cause."
                claims = []
                line = {"driver_id": d["driver_id"], "support": "needs_verification", "confirm_prompt": "Confirm the business reason for this movement with its owner."}
            history = d.get("trend") or {}
            phrase = history_phrases.get(history.get("pattern"))
            if phrase and d["driver_id"] != "others" and len(f"{text} {phrase}".split()) <= limit:
                # The history is Python's verdict; the draft only repeats it and cites it.
                text = f"{text} {phrase}"
                refs.append(history["evidence_ref"])
                claims.append({"type": "observation", "text": history.get("note", phrase)[:300], "evidence_refs": [history["evidence_ref"]]})
            lines.append({**line, "text": text, "evidence_refs": refs, **({"claims": claims} if claims else {})})
        proposal = {"headline": evidence.get("headline_hint") or "Variance analysis — evidence-based summary", "lines": lines, "others_summary": ""}
    return {"contract_version": envelope.get("contract_version", "journey-1"), "request_id": envelope["request_id"], "step": step, "status": "ok", "proposal": proposal, "confidence": "medium", "rationale": TEMPLATES["rationale"], "questions": [], "warnings": TEMPLATES["warnings"]}


def _envelope(envelope: dict, status: str, proposal: dict, summary: str, questions: list | None = None, warnings: list | None = None) -> dict:
    return {"contract_version": envelope.get("contract_version", "journey-1"), "request_id": envelope["request_id"], "step": envelope["step"], "status": status, "proposal": proposal, "confidence": "medium" if status == "ok" else "low", "rationale": "Offline assistant: deterministic setup from your description and the uploaded column names.", "questions": questions or [], "warnings": [*TEMPLATES["warnings"], *(warnings or [])][:10], "summary": summary[:1000], "changes": []}


def _clause_step(clause: str) -> str:
    """Which journey step an unparsed clause was most likely about."""
    text = clause.lower()
    if re.search(r"\b(?:by|group|grouped|split|break|per)\b", text):
        return "group"
    if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\bq[1-4]\b|\b(?:quarter|month|year|ytd|vs|versus|compare|against|budget|forecast|prior)\b", text):
        return "compare"
    if re.search(r"\b(?:only|exclude|excluding|include|including|without|except|filter)\b", text):
        return "include"
    if re.search(r"\b(?:threshold|materiality|material|top|over|above|largest|biggest)\b|\d", text):
        return "important"
    if re.search(r"\b(?:audience|tone|style|commentary|summary|executive|short|risk|write|explanations?)\b", text):
        return "explain"
    return "data"


def mock_plan(envelope: dict) -> dict:
    """Combine the offline column, period and rule suggestions with parsed clauses."""
    from engine.patches import diff_spec
    from .proposals import proposal_to_spec
    from .mock_instructions import plan_from_text
    payload, spec = envelope["payload"], envelope.get("spec_so_far", {})
    working = copy.deepcopy(spec)
    months = payload.get("available_months", [])
    def nested(step: str, extra: dict) -> dict:
        return mock_response({**envelope, "step": step, "payload": {**payload, **extra}})["proposal"]
    if not working.get("roles", {}).get("value") or not working.get("roles", {}).get("period"):
        working = proposal_to_spec(working, "map_columns", nested("map_columns", {"profile": payload.get("column_profile", {})}))
    if not working.get("comparison", {}).get("current", {}).get("months") and months:
        working = proposal_to_spec(working, "define_comparison", nested("define_comparison", {"scenario_values": payload.get("scenario_values", [])}))
    if not working.get("measures") or not working.get("views"):
        working = proposal_to_spec(working, "define_rules", nested("define_rules", {}))
    patch_text, summaries, skipped = plan_from_text(working, payload.get("description", ""), payload.get("allowed_columns", []), months)
    if patch_text:
        from engine.patches import apply_patch
        working = apply_patch(working, patch_text, "agent", "Offline plan")
    patch = diff_spec(spec, working)
    roles, comparison = working.get("roles", {}), working.get("comparison", {})
    questions = []
    states = []
    data_ok = bool(roles.get("value") and roles.get("period"))
    compare_ok = bool(comparison.get("current", {}).get("months") and (comparison.get("base", {}).get("months") or comparison.get("base", {}).get("scenario")))
    if not compare_ok and len(months) >= 2:
        options = [f"Compare {months[-1]} with {months[-2]}."]
        if len(months) >= 6:
            options.insert(0, "Compare the latest quarter with the previous quarter.")
        questions.append({"id": "periods", "text": "Which periods should we compare?", "options": options[:3]})
    keys = next((view.get("keys", []) for view in working.get("views", []) if view.get("name") == working.get("drivers", {}).get("view")), [])
    # Text the grammar could not use must never leave a default in place silently:
    # the step it was about is marked as needing input, with the words quoted back.
    unparsed: dict[str, list[str]] = {}
    for clause in skipped:
        unparsed.setdefault(_clause_step(clause), []).append(clause)
    dimensions = [item for item in roles.get("dimensions", []) if item][:3]
    options_for = {"compare": (["Compare the latest quarter with the previous quarter."] if len(months) >= 6 else []) + ([f"Compare {months[-1]} with {months[-2]}."] if len(months) >= 2 else []),
                   "group": [f"Group by {item}" for item in dimensions], "important": ["Set the threshold to 100k.", "Show the top 10 movements."],
                   "explain": ["Executive audience, short commentary.", "Neutral tone."], "include": [], "data": []}
    for step in [item for item in ("data", "compare", "include", "group", "important", "explain") if item in unparsed]:
        if len(questions) >= 3:
            break
        if step == "compare":
            questions = [item for item in questions if item["id"] != "periods"]
        quoted = "', '".join(unparsed[step])[:150]
        questions.append({"id": f"unparsed_{step}", "text": f"I could not use '{quoted}'. What should this step use?"[:240], "options": options_for[step][:3]})
    asked = {item["id"] for item in questions}
    for step, ok, summary in (
        ("data", data_ok, f"Amounts from {roles.get('value')}, months from {roles.get('period')}." if data_ok else "Choose the amount and month columns."),
        ("compare", compare_ok, "Compare " + ", ".join(comparison.get("current", {}).get("months", [])) + " with " + ", ".join(comparison.get("base", {}).get("months", [])) + "." if compare_ok else "Choose the periods to compare."),
        ("include", True, f"{len(working.get('scope', []))} filters applied." if working.get("scope") else "Include all rows."),
        ("group", bool(keys), "Group by " + ", ".join(keys) + "." if keys else "Choose how to group movements."),
        ("important", True, f"Show up to {working.get('drivers', {}).get('top_n', 15)} important movements."),
        ("explain", True, "Neutral, controller-level commentary unless you change it."),
    ):
        if f"unparsed_{step}" in asked:
            states.append({"step": step, "status": "needs_input", "summary": summary[:600], "reason": "Part of your description about this step was not understood: '" + "', '".join(unparsed[step])[:200] + "'. Please check it here.", "question_ids": [f"unparsed_{step}"]})
            continue
        if step in unparsed:
            ok = False
        ids = ["periods"] if step == "compare" and "periods" in asked else []
        states.append({"step": step, "status": "confident" if ok else "needs_input", "summary": summary[:600], "reason": "Matched from your description and column names." if ok else "This could not be decided from the description.", "question_ids": ids})
    status = "needs_input" if questions or any(item["status"] == "needs_input" for item in states) else "ok"
    if status == "needs_input" and not questions:
        questions.append({"id": "setup", "text": "Some steps still need your input. Open the first one marked 'Needs input' to finish them.", "options": ["Show me the first step that needs input."]})
        for item in states:
            if item["status"] == "needs_input":
                item["question_ids"] = ["setup"]
                break
    summary = "Set up " + str(len(patch)) + " settings from your description." + (" " + " ".join(summaries) if summaries else "")
    warnings = [f"I could not use: '{item}'. Set this on the matching step." for item in skipped[:5]]
    return _envelope(envelope, status, {"patch": patch, "step_states": states}, summary, questions, warnings)


def mock_style(envelope: dict) -> dict:
    """Describe structure only: bullets, sentence length, tone markers. Never content."""
    text = envelope["payload"].get("example_text", "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullets = sum(1 for line in lines if re.match(r"^[-•*]|^\d+[.)]", line))
    sentences = [part for part in re.split(r"[.!?]+\s", text) if part.strip()]
    average = sum(len(part.split()) for part in sentences) / max(len(sentences), 1)
    traits = ["Bulleted, one movement per line" if bullets >= max(2, len(lines) // 2) else "Short paragraphs"]
    traits.append("short sentences" if average <= 14 else "fuller sentences")
    if re.search(r"\b(?:risk|exposure|concern)\b", text, re.I):
        traits.append("calls out risks")
    if re.search(r"\b(?:favou?rable|adverse|unfavou?rable)\b", text, re.I):
        traits.append("labels movements favourable or adverse")
    if re.search(r"\b(?:timing|phasing|accrual)\b", text, re.I):
        traits.append("separates timing effects")
    phrases = ["The movement relates to [supported evidence].", "[Amount] — [movement]: [explanation]."]
    if re.search(r"\b(?:offset|partly offset|partially offset)\b", text, re.I):
        phrases.append("Partly offset by [related movement].")
    proposal = {"example_style": {"summary_of_style": (", ".join(traits) + ".")[:600], "sample_phrases": phrases[:5]}}
    return _envelope(envelope, "ok", proposal, "Captured the writing style (not the content) of your example.")
