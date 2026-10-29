"""Browser-isolated local project state and asynchronous jobs."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import threading
import uuid
from flask import session
from config import WORKSPACE, AGENT_MOCK
from engine.spec import default_spec, validate_spec
from engine.patches import apply_patch, diff_spec
from engine.money import clean
from engine.ingest import load_source, union_sources
from engine.profile import profile
from engine.periods import available_months
from engine.presets import list_presets
import pandas as pd

LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="flux")
JOBS: dict[str, dict] = {}

def now() -> str:
    """Return a stable UTC audit timestamp."""
    return datetime.now(timezone.utc).isoformat()

def write_json(path: Path, value: dict) -> None:
    """Atomic JSON replacement protects against interrupted runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)

def project_id() -> str:
    """Assign an opaque project ID to this browser's signed session."""
    if not session.get("project_id"):
        session["project_id"] = uuid.uuid4().hex
    return session["project_id"]

def csrf_token() -> str:
    """Generate a session-specific CSRF token."""
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

def project_path(pid: str) -> Path:
    """Locate an internally generated project ID, never a user path."""
    return WORKSPACE / "projects" / pid / "state.json"

def get_project(pid: str | None = None) -> dict:
    """Read state or initialize an empty local project."""
    pid = pid or project_id()
    path = project_path(pid)
    with LOCK:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            state.setdefault("change_log", [])
            state.setdefault("undo_stack", [])
            state.setdefault("redo_stack", [])
            old_spec = state.get("spec", default_spec())
            migrated = validate_spec(old_spec)
            if migrated != old_spec:
                apply_spec_change(state, migrated, "system", "Migrate saved FluxSpec to version 2.0")
                write_json(path, state)
            state.setdefault("spec", migrated)
            state.setdefault("runs", [])
            state.setdefault("sources", [])
            state.setdefault("sample_data", False)
            state.setdefault("controls", [])
            return state
        state = {"project_id": pid, "step": "sources", "sources": [], "sample_data": False, "spec": default_spec(), "runs": [], "latest_proposal": None, "controls": [], "result": None, "change_log": [], "undo_stack": [], "redo_stack": [], "created": now()}
        write_json(path, state)
        return state

def save_project(state: dict) -> None:
    """Persist a complete browser project."""
    with LOCK:
        write_json(project_path(state["project_id"]), state)


def apply_spec_change(state: dict, candidate: dict, actor: str, reason: str) -> dict:
    """The only project-state entry point for persisted FluxSpec changes."""
    current = state["spec"]
    patch = diff_spec(current, candidate)
    if not patch:
        return current
    before = copy.deepcopy(current)
    state.setdefault("change_log", [])
    state.setdefault("undo_stack", [])
    state.setdefault("redo_stack", [])
    updated = apply_patch(current, patch, actor, reason, state["change_log"])
    state["undo_stack"].append({"before": before, "after": copy.deepcopy(updated), "actor": actor, "reason": reason})
    state["undo_stack"] = state["undo_stack"][-100:]
    state["redo_stack"] = []
    state["spec"] = updated
    state["controls"] = []
    state["spec_revision"] = int(state.get("spec_revision", 0)) + 1
    clear_plan_flags(state, [item["path"] for item in patch])
    return updated


def clear_plan_flags(state: dict, paths: list[str]) -> None:
    """A user or AI change to a step resolves that step's outstanding plan question."""
    from agent.contracts import STEP_PATCH_PATHS
    plan = state.get("plan_state") or {}
    for step, prefixes in STEP_PATCH_PATHS.items():
        if any(path == prefix or path.startswith(prefix + "/") or prefix.startswith(path + "/") or path == "" for path in paths for prefix in prefixes):
            plan.get("steps", {}).pop(step, None)


def restore_spec_history(state: dict, direction: str) -> dict:
    """Undo or redo one validated configuration change."""
    if direction not in ("undo", "redo"):
        raise ValueError("Choose undo or redo.")
    source_name = "undo_stack" if direction == "undo" else "redo_stack"
    target_name = "redo_stack" if direction == "undo" else "undo_stack"
    stack = state.setdefault(source_name, [])
    if not stack:
        raise ValueError(f"Nothing to {direction}.")
    record = stack.pop()
    target = record["before"] if direction == "undo" else record["after"]
    patch = [{"op": "replace", "path": "", "value": target}]
    updated = apply_patch(state["spec"], patch, direction, f"{direction.title()}: {record['reason']}", state.setdefault("change_log", []))
    state.setdefault(target_name, []).append(record)
    state["spec"] = updated
    state["controls"] = []
    state["spec_revision"] = int(state.get("spec_revision", 0)) + 1
    return updated

def source_path(pid: str, source: dict) -> Path:
    """Get server-assigned upload path, not an arbitrary client filename."""
    return WORKSPACE / "uploads" / pid / source["stored"]

def load_defined(pid: str, source: dict) -> pd.DataFrame:
    """Load selected sheets with matching schemas and optional sheet tags."""
    definition = source["definition"]
    selected_sheets = definition.get("combine_sheets") or [definition.get("sheet")]
    frames = [load_source(source_path(pid, source), sheet, int(definition["header_row"]), definition["start_col"], definition.get("end_col"), WORKSPACE / "cache") for sheet in selected_sheets]
    return union_sources(frames, tag_column=definition.get("tag_column"), tags=[str(s) for s in selected_sheets]) if len(frames) > 1 or definition.get("tag_column") else frames[0]

def datasets(state: dict) -> tuple[pd.DataFrame, dict]:
    """Build primary/forecast stack and independent named lookup datasets."""
    primary, tags, lookups = [], [], {}
    for source in state["sources"]:
        if not source.get("defined"):
            continue
        frame = load_defined(state["project_id"], source)
        role = source["definition"]["role"]
        if role == "lookup":
            lookups.setdefault(source["definition"].get("name") or source["name"], []).append(frame)
        else:
            if role == "forecast" and state["spec"]["roles"].get("scenario"):
                scenario = state["spec"]["roles"]["scenario"]
                if scenario not in frame:
                    frame[scenario] = "Forecast"
            primary.append(frame)
            tags.append(source["name"])
    if not primary:
        raise ValueError("Upload and define at least one primary data source first.")
    combined = union_sources(primary)
    combined["__source"] = [tag for tag, frame in zip(tags, primary) for _ in range(len(frame))]
    return combined, {name: union_sources(frames) for name, frames in lookups.items()}

def source_bindings(state: dict) -> dict:
    """Build the portable source file selection for the current upload state."""
    primary, lookups = [], {}
    for source in state["sources"]:
        if not source.get("defined"):
            continue
        definition = source["definition"]
        entries = [{"file": source["name"], "sheet": sheet, "header_row": definition["header_row"], "start_col": definition["start_col"], "end_col": definition.get("end_col")} for sheet in definition.get("combine_sheets") or [definition.get("sheet")]]
        if definition["role"] == "lookup":
            lookups.setdefault(definition.get("name") or source["name"], {"files": []})["files"].extend(entries)
        else:
            primary.extend(entries)
    return {"primary": {"files": primary, "union": {"mode": "stack", "tag_column": None}}, "lookups": lookups}

def bind_sources(state: dict) -> None:
    """Keep portable FluxSpec file selections in sync with active sources."""
    candidate = copy.deepcopy(state["spec"])
    candidate["sources"] = source_bindings(state)
    apply_spec_change(state, candidate, "user", "Updated uploaded source definitions")

def auto_map_sources(state: dict) -> None:
    """Apply unambiguous exact/similar header renames and retain ambiguities."""
    from engine.mapping import remap_columns
    if not any(source.get("defined") and source.get("role") != "lookup" for source in state["sources"]):
        return
    frame, _ = datasets(state)
    candidate, renames, unresolved = remap_columns(state["spec"], list(frame.columns))
    state["mapping_warnings"] = unresolved
    if renames:
        apply_spec_change(state, candidate, "system", "Mapped renamed columns: " + "; ".join(f"{old} → {new}" for old, new in renames.items()))

def saved_specs() -> list[dict]:
    """List human-readable saved configurations without exposing credentials."""
    rows = []
    for path in (WORKSPACE / "specs").glob("*.json"):
        try:
            spec = json.loads(path.read_text())
            rows.append({"name": spec["flux_name"], "file": path.name, "updated": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
        except (ValueError, KeyError):
            continue
    return sorted(rows, key=lambda r: r["updated"], reverse=True)

def public_state(state: dict | None = None, token: str | None = None) -> dict:
    """Return UI state and local-only profiles, no file paths or secrets."""
    state = copy.deepcopy(state or get_project())
    state["agent_mock"] = AGENT_MOCK
    state["csrf_token"] = token or csrf_token()
    state["saved_specs"] = saved_specs()
    state["presets"] = list_presets()
    state["change_log"] = state.get("change_log", [])
    state["can_undo"] = bool(state.get("undo_stack"))
    state["can_redo"] = bool(state.get("redo_stack"))
    from engine.describe import describe_spec
    state["rule_cards"] = describe_spec(state["spec"], state.get("change_log", []))
    state["monthly_row_counts"], state["partial_periods_detected"] = {}, []
    state.pop("undo_stack", None)
    state.pop("redo_stack", None)
    state["profile"], state["periods"], state["scenarios"] = {"n_rows": 0, "columns": []}, [], []
    if any(s.get("defined") and s.get("role") != "lookup" for s in state["sources"]):
        try:
            df, _ = datasets(state)
            state["profile"] = profile(df.drop(columns=["__source"], errors="ignore"))
            period_col = state["spec"]["roles"].get("period")
            scenario_col = state["spec"]["roles"].get("scenario")
            if period_col and period_col in df:
                state["periods"] = available_months(df[period_col].dropna().unique(), state["spec"].get("periods", {}).get("calendar", "calendar"), state["spec"].get("period_format", "auto"))
                from engine.periods import parse_period
                from statistics import median
                counts = df[period_col].dropna().map(lambda value: parse_period(value, state["spec"].get("periods", {}).get("calendar", "calendar"), state["spec"].get("period_format", "auto"))).value_counts().to_dict()
                state["monthly_row_counts"] = counts
                midpoint = median(counts.values()) if counts else 0
                state["partial_periods_detected"] = sorted(month for month, count in counts.items() if count < midpoint * .5)
            if scenario_col and scenario_col in df:
                state["scenarios"] = sorted(df[scenario_col].dropna().astype(str).unique().tolist())
        except ValueError as exc:
            state["data_warning"] = str(exc)
    state["spec_revision"] = int(state.get("spec_revision", 0))
    from .journey import journey_state
    state["journey"] = journey_state(state)
    state.pop("plan_state", None)
    for source in state["sources"]:
        source.pop("stored", None)
    return clean(state)

def start_job(pid: str, message: str, operation: object) -> str:
    """Start a background operation, returning before expensive work runs."""
    job_id = uuid.uuid4().hex
    with LOCK:
        JOBS[job_id] = {"id": job_id, "project_id": pid, "status": "pending", "message": message, "result": None, "error": None}
    def worker() -> None:
        try:
            result = operation()
            with LOCK:
                JOBS[job_id].update(status="done", result=clean(result), message="Ready for your review.")
        except Exception as exc:
            # Only controlled, credential-free errors are returned to users.
            from agent.client import AgentError
            friendly = str(exc) if isinstance(exc, (ValueError, AgentError, KeyError)) else "This operation could not complete. Check your file selection and configuration, then try again."
            with LOCK:
                JOBS[job_id].update(status="error", error=friendly[:1200], message="A change is needed.")
    POOL.submit(worker)
    return job_id
