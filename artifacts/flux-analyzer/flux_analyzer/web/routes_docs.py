"""Bundled, offline help; an explicit allowlist prevents filesystem traversal."""
from pathlib import Path
import html
import re
from flask import Blueprint, jsonify, render_template, request
from markupsafe import Markup
from config import ROOT

bp = Blueprint("docs", __name__)
DOCUMENTS = {
    "getting_started": "Getting started",
    **{f"steps/{key}": title for key, title in (
        ("sources", "Sources and presets"), ("columns", "Column mappings"),
        ("comparison", "Comparison periods"), ("scope", "Scope, signs and joins"),
        ("classification", "Classification review"), ("rules", "Analysis rules"),
        ("review", "Controls and review"), ("results", "Results and commentary"))},
    "glossary": "Glossary", "presets": "Managing presets", "controls": "Control catalogue",
    "ai_and_data": "AI, privacy and local setup", "known_gaps": "Known limits",
    "reference": "Complete engine and agent reference",
    "agent_system_prompt": "Live agent instructions",
    "agent/agent_instructions": "Agent instructions (journey-1)",
    "agent/contract": "Agent contract (journey-1)",
    "ux-redesign-plan": "Guided journey design",
}


def document(doc_id):
    if doc_id not in DOCUMENTS:
        raise ValueError("Help page not found.")
    return {"title": DOCUMENTS[doc_id], "markdown": (ROOT / "docs" / (doc_id + ".md")).read_text(encoding="utf-8")}


def safe_markdown(text):
    def inline(value):
        value = html.escape(value)
        value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"\[([^\]]+)\]\((/docs\?doc=[a-z_/-]+|https://[^ )]+)\)", r'<a href="\2">\1</a>', value)
    output, code = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            output.append("</code></pre>" if code else "<pre><code>")
            code = not code
        elif code:
            output.append(html.escape(line) + "\n")
        elif re.match(r"^#{1,4} ", line):
            level = len(line.split(" ", 1)[0])
            output.append(f"<h{level}>{inline(line[level + 1:])}</h{level}>")
        elif line.startswith("- "):
            output.append("<p class='bullet'>• " + inline(line[2:]) + "</p>")
        elif line.strip():
            output.append("<p>" + inline(line) + "</p>")
    if code:
        output.append("</code></pre>")
    return Markup("\n".join(output))


@bp.get("/help/<path:doc_id>")
def help_page(doc_id):
    return jsonify(document(doc_id))


@bp.get("/docs")
def docs():
    selected = request.args.get("doc", "getting_started")
    page = document(selected)
    return render_template("docs.html", documents=DOCUMENTS, selected=selected, title=page["title"], content=safe_markdown(page["markdown"]))
