"""Explanation status for every movement in a run.

Status precedence (the model never decides any of these):
1. The engine grouped the movement into "Other items" -> below_threshold.
2. A person confirmed or saved valid text for the current evidence -> confirmed.
3. Missing, invalid, needs-confirmation-marker or unsupported text -> needs_explanation.
4. A valid, supported AI draft -> ai_review.
"""
import copy
import hashlib
import json
from datetime import datetime, timezone

from .narrative_check import check_narrative

STATUSES = ("needs_explanation", "ai_review", "confirmed", "below_threshold")


def evidence_hash(driver: dict) -> str:
    """Stable fingerprint of the evidence a confirmation was given against."""
    material = {key: driver.get(key) for key in ("driver_id", "label", "base", "current", "delta", "delta_fmt")}
    material["top_texts"] = [[item.get("text"), item.get("delta_fmt")] for item in driver.get("top_texts", [])]
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()[:24]


def check_line(run: dict, driver_id: str, text: str, support: str | None = None, author: str = "person", line: dict | None = None) -> dict:
    """Validate one explanation against the same evidence rules as the full commentary.

    Pass the stored ``line`` for an AI draft so its evidence references and claims are checked too.
    """
    evidence = copy.deepcopy(run["evidence"])
    evidence["drivers"] = [driver for driver in evidence["drivers"] if driver["driver_id"] == driver_id]
    if not evidence["drivers"]:
        raise ValueError("This movement is not part of the report.")
    line = {**{key: value for key, value in (line or {}).items() if key in ("evidence_refs", "claims", "confirm_prompt")}, "driver_id": driver_id, "text": text}
    if support:
        line["support"] = support
    checked = check_narrative({"headline": evidence.get("headline_hint") or "", "lines": [line], "others_summary": ""}, evidence, author=author)
    return {"ok": checked["ok"], "issues": checked["issues"]}


def explanation_items(run: dict) -> list[dict]:
    """One record per movement, in engine order, with a deterministic status."""
    commentary = run.get("commentary") or {}
    lines = {line.get("driver_id"): line for line in commentary.get("lines", [])}
    reviews = run.get("reviews", {})
    tag = run.get("evidence", {}).get("commentary_rules", {}).get("verify_tag", "[TO VERIFY]")
    origin_default = "ai" if commentary.get("source") == "agent" else "user" if commentary.get("source") == "analyst_edited" else "system"
    pending = {item["driver_id"]: item for item in commentary.get("pending_replacements", [])}
    items = []
    for driver in run.get("evidence", {}).get("drivers", []):
        driver_id = driver["driver_id"]
        line = lines.get(driver_id, {})
        review = reviews.get(driver_id)
        fingerprint = evidence_hash(driver)
        if review and review.get("evidence_hash") != fingerprint:
            review = None
        text = review["text"] if review else line.get("text", "")
        origin = review.get("origin", "user") if review else origin_default
        issues = []
        if driver_id == "others":
            status = "below_threshold"
        elif review and review.get("confirmed_at"):
            status = "confirmed"
        else:
            checked = (check_line(run, driver_id, text) if review else check_line(run, driver_id, text, line.get("support"), "person" if origin == "user" else "agent", line)) if text else {"ok": False, "issues": ["No explanation yet."]}
            issues = checked["issues"]
            unsupported = (not review and line.get("support") == "needs_verification") or origin == "system"
            status = "needs_explanation" if (not text or not checked["ok"] or tag in text or unsupported) else "ai_review"
        items.append({
            "driver_id": driver_id, "label": driver.get("label"), "dimensions": driver.get("dimensions", {}),
            "base": driver.get("base"), "current": driver.get("current"), "delta": driver.get("delta"), "delta_fmt": driver.get("delta_fmt"),
            "status": status, "text": text, "origin": origin, "issues": issues,
            "evidence": driver.get("top_texts", []), "evidence_refs": line.get("evidence_refs", driver.get("evidence_refs", [])),
            "confirmed_by": review.get("confirmed_by") if review else None, "confirmed_at": review.get("confirmed_at") if review else None,
            "pending_replacement": pending.get(driver_id, {}).get("text"),
            "history": (driver.get("trend") or {}).get("note") if driver_id != "others" else None,
            "limits": (driver.get("coverage") or {}).get("note"),
            "confirm_prompt": None if review else line.get("confirm_prompt"),
        })
    return items


def counts(items: list[dict]) -> dict:
    return {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}


def record_review(run: dict, driver_id: str, text: str, actor: str, confirm: bool) -> dict:
    """Save a person's text and/or confirmation; confirmation needs valid text with no marker."""
    driver = next((item for item in run["evidence"]["drivers"] if item["driver_id"] == driver_id), None)
    if driver is None:
        raise ValueError("This movement is not part of the report.")
    if driver_id == "others":
        raise ValueError("Movements below the threshold do not need confirming.")
    actor = actor.strip()[:80]
    if confirm and not actor:
        raise ValueError("Enter your name before confirming an explanation.")
    text = text.strip()
    if not text or len(text) > 2000:
        raise ValueError("Write an explanation of 1–2,000 characters.")
    tag = run["evidence"].get("commentary_rules", {}).get("verify_tag", "[TO VERIFY]")
    checked = check_line(run, driver_id, text)
    if confirm and (not checked["ok"] or tag in text):
        problems = checked["issues"] + ([f"Remove {tag} once the cause is confirmed."] if tag in text else [])
        raise ValueError("This explanation cannot be confirmed yet: " + " ".join(problems))
    timestamp = datetime.now(timezone.utc).isoformat()
    previous = run.setdefault("reviews", {}).get(driver_id)
    record = {"run_id": run.get("id"), "driver_id": driver_id, "evidence_hash": evidence_hash(driver), "text": text, "origin": "user",
              "evidence_refs": driver.get("evidence_refs", []), "confirmed_by": actor if confirm else None, "confirmed_at": timestamp if confirm else None,
              "updated_by": actor or "Unnamed reviewer", "updated_at": timestamp}
    run["reviews"][driver_id] = record
    run.setdefault("review_log", []).append({"timestamp": timestamp, "driver_id": driver_id, "action": "confirm" if confirm else "save", "by": record["updated_by"], "from": (previous or {}).get("text"), "to": text})
    commentary = run.setdefault("commentary", {})
    lines = commentary.setdefault("lines", [])
    existing = next((line for line in lines if line.get("driver_id") == driver_id), None)
    if existing is None:
        lines.append({"driver_id": driver_id, "text": text})
    elif existing.get("text") != text:
        existing.clear()
        existing.update(driver_id=driver_id, text=text)
    commentary["pending_replacements"] = [item for item in commentary.get("pending_replacements", []) if item["driver_id"] != driver_id]
    order = [item["driver_id"] for item in run["evidence"]["drivers"]]
    lines.sort(key=lambda line: order.index(line["driver_id"]) if line["driver_id"] in order else len(order))
    commentary["text"] = "\n\n".join(filter(None, [commentary.get("headline", ""), *[line["text"] for line in lines], commentary.get("others_summary", "")]))
    return record


def protected_ids(run: dict) -> set[str]:
    """Movements with a person's current text; AI drafts must not overwrite these."""
    fingerprints = {driver["driver_id"]: evidence_hash(driver) for driver in run.get("evidence", {}).get("drivers", [])}
    return {driver_id for driver_id, review in run.get("reviews", {}).items() if review.get("evidence_hash") == fingerprints.get(driver_id)}
