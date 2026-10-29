"""Equinix AI Engine invoke/poll client with strict JSON and size bounds."""
import copy
import json
import os
from pathlib import Path
import re
import time
import uuid
import requests
from jsonschema import Draft202012Validator, ValidationError
from config import AGENT_MOCK, AGENT_TIMEOUT_SECONDS, MAX_AGENT_PAYLOAD_KB

SCHEMAS = json.loads((Path(__file__).parent / "schemas/responses.json").read_text())

class AgentError(Exception):
    """Friendly, credential-free integration failure."""

def validate_response(response: dict, step: str, request_id: str | None = None) -> dict:
    """Check the response envelope, step-specific schema and FluxSpec fragments."""
    errors = list(Draft202012Validator(SCHEMAS["envelope"]).iter_errors(response))
    if errors:
        raise ValueError("\n".join(f"{'.'.join(map(str, error.absolute_path)) or 'response'}: {error.message}" for error in errors))
    if response["step"] != step:
        raise ValueError("The agent replied for a different step.")
    if request_id and response["request_id"] != request_id:
        raise ValueError("The agent response has a different request ID.")
    if response["status"] in ("ok", "needs_input"):
        if step == "apply_instruction" and "patch" in response:
            response["proposal"]["patch"] = response["patch"]
        # Fix a known agent typo before strict schema validation.
        if step == "write_commentary" and isinstance(response.get("proposal"), dict):
            for line in response["proposal"].get("lines") or []:
                if isinstance(line, dict) and "confirm_prompts" in line:
                    value = line.pop("confirm_prompts")
                    line.setdefault("confirm_prompt", value)
        schema = copy.deepcopy(SCHEMAS[step])
        if response["status"] == "needs_input":
            schema.pop("required", None)
        errors = list(Draft202012Validator(schema).iter_errors(response["proposal"]))
        if errors:
            raise ValueError("\n".join(f"proposal.{'.'.join(map(str, error.absolute_path))}: {error.message}" for error in errors))
        if response["status"] == "needs_input":
            return response
        if step == "detect_flux" and response["proposal"].get("preset_id"):
            from engine.presets import get_preset
            get_preset(response["proposal"]["preset_id"])
        from engine.spec import default_spec, validate_spec
        spec = default_spec()
        proposal = response["proposal"]
        allowed = set(spec)
        for key, value in proposal.items():
            if key in allowed:
                spec[key] = value
        validate_spec(spec)
    return response

def repair_errors(exc: Exception) -> list[dict]:
    """Aggregate validation failures into contract-shaped repair errors."""
    errors = []
    for line in str(exc).splitlines() or ["response: invalid"]:
        path, _, message = line.partition(": ")
        if not message:
            path, message = "response", line
        errors.append({"path": path.strip() or "response", "code": type(exc).__name__, "message": message.strip()[:500]})
    return errors[:30]


def enforce_contract(envelope: dict, response: dict) -> None:
    """Request-dependent checks: patch ownership, plan readiness and style safety."""
    from .contracts import check_patch, validate_step_states, example_leaks, allowed_paths_for
    step, payload = envelope["step"], envelope.get("payload", {})
    if response["status"] == "cannot_do":
        return
    proposal = response.get("proposal", {})
    if step in ("apply_instruction", "plan_from_description") and "patch" in proposal:
        allowed = payload.get("allowed_patch_paths") or allowed_paths_for(None)
        check_patch(proposal["patch"], allowed)
    if step == "plan_from_description":
        if response["status"] == "needs_input" and not response.get("questions"):
            raise ValueError("questions: needs_input requires at least one question.")
        validate_step_states(proposal.get("step_states", []), response.get("questions", []), response["status"])
    if step == "extract_commentary_style" and proposal.get("example_style"):
        issues = example_leaks(proposal["example_style"], payload.get("example_text", ""))
        if issues:
            raise ValueError("\n".join("proposal.example_style: " + issue for issue in issues))
    if step == "describe_setup":
        text = proposal.get("suggested_name", "") + " " + proposal.get("description", "")
        if "/" in text and ("/home" in text or "\\" in text or "workspace/" in text):
            raise ValueError("proposal.description: must not mention file-system paths.")


def parse_agent_json(content: object, step: str, request_id: str | None = None) -> dict:
    """Strip optional fences, parse JSON only and validate before use."""
    if isinstance(content, dict):
        result = content
    else:
        text = str(content).strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
    return validate_response(result, step, request_id)

def bound_envelope(envelope: dict) -> dict:
    """Reduce metadata arrays, never exceeding the 50KB encoded envelope cap."""
    data = copy.deepcopy(envelope)
    cap = MAX_AGENT_PAYLOAD_KB * 1024
    def size() -> int:
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    def trim(value: object, limit: int) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, list) and key in ("samples", "terms", "period_values", "scenario_values", "value_counts", "top_texts"):
                    del child[limit:]
                trim(child, limit)
        elif isinstance(value, list):
            for child in value:
                trim(child, limit)
    trim(data["payload"], 10)
    pack = data["payload"].get("evidence_pack") or {}
    if size() > cap and pack.get("drivers"):
        # Shorten context before descriptions: keep the latest history points and largest categories.
        # The trend pattern was decided by Python on the full history, so it stays valid.
        data["payload"]["truncated"] = True
        for driver in pack["drivers"]:
            if isinstance(driver.get("trend"), dict):
                driver["trend"]["points"] = driver["trend"].get("points", [])[-3:]
            if isinstance(driver.get("categories"), dict):
                driver["categories"]["items"] = driver["categories"].get("items", [])[:2]
    for limit in (10, 5, 2, 0):
        if size() <= cap:
            return data
        data["payload"]["truncated"] = True
        trim(data["payload"], limit)
    if size() > cap:
        raise AgentError("This configuration exceeds the 50 KB agent limit. Reduce configuration complexity or configure it manually.")
    return data

def _http(method: str, url: str, headers: dict, **kwargs: object) -> requests.Response:
    """Retry network and server errors twice; never retry a client error."""
    for attempt in range(3):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            if response.status_code >= 500 and attempt < 2:
                time.sleep((2, 5)[attempt])
                continue
            if response.status_code >= 400:
                raise AgentError(f"AI Engine returned HTTP {response.status_code}. Check server credentials and access, then try again.")
            return response
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == 2:
                raise AgentError("Could not reach the AI Engine. Check network access or use mock mode.") from exc
            time.sleep((2, 5)[attempt])
    raise AgentError("AI Engine request failed.")

def _live(envelope: dict, timeout_s: int) -> object:
    """Backend-only exact Equinix invoke/202 conversation polling pattern."""
    required = ("EAP_BASE_URL", "EAP_AGENT_ID", "EAP_API_KEY", "EAP_PAT")
    if any(not os.environ.get(key) for key in required):
        raise AgentError("AI Engine is not configured. Add the required EAP settings securely, or enable AGENT_MOCK=true.")
    base = os.environ["EAP_BASE_URL"].rstrip("/")
    agent = os.environ["EAP_AGENT_ID"]
    headers = {"Api-Key": os.environ["EAP_API_KEY"], "X-EAP-Authorization": f"Bearer {os.environ['EAP_PAT']}"}
    response = _http("POST", f"{base}/api/v1/agents/{agent}/invoke", headers, json={"message": json.dumps(envelope, ensure_ascii=False)}, timeout=(30, timeout_s))
    data = response.json()
    if response.status_code == 200:
        return data["response"]
    if response.status_code != 202 or not data.get("conversation_id"):
        raise AgentError("The AI Engine returned an unexpected response.")
    conversation = requests.utils.quote(str(data["conversation_id"]), safe="")
    url = f"{base}/api/v1/agents/{agent}/conversations/{conversation}/messages"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(2)
        poll = _http("GET", url, headers, timeout=30)
        messages = poll.json()
        if isinstance(messages, dict):
            messages = messages.get("messages", [])
        if len(messages) > 1:
            for message in reversed(messages[1:]):
                if message.get("role") in ("user", "human"):
                    continue
                if message.get("content"):
                    return message["content"]
    raise AgentError("The AI Engine took too long. Your data is safe; try again.")

def invoke_agent(envelope: dict, timeout_s: int = AGENT_TIMEOUT_SECONDS, log_dir: Path | None = None) -> dict:
    """Invoke, validate and allow exactly one invalid-response repair attempt."""
    original = copy.deepcopy(envelope)
    original.setdefault("request_id", str(uuid.uuid4()))
    expected_step, request_id = original["step"], original["request_id"]
    current = original
    for repair in range(2):
        bounded = bound_envelope(current)
        started, raw, status = time.monotonic(), None, "error"
        try:
            if AGENT_MOCK:
                from .mock import mock_response
                raw = mock_response(original)
            else:
                raw = _live(bounded, timeout_s)
            response = parse_agent_json(raw, expected_step, request_id)
            enforce_contract(original, response)
            from .proposals import candidate_for_response
            candidate_for_response(original.get("spec_so_far", {}), response)
            status = "ok"
            return response
        except (ValueError, KeyError, ValidationError, json.JSONDecodeError) as exc:
            if repair:
                raise AgentError("The agent did not return a valid suggestion after one repair. Please configure this step manually or try again.") from exc
            original_payload = {key: value for key, value in original.get("payload", {}).items() if key not in ("example_text", "response_schema")}
            current = {**original, "step": "repair", "payload": {"errors": repair_errors(exc), "previous_output": json.dumps(raw, ensure_ascii=False)[:10000] if expected_step != "extract_commentary_style" else "(withheld: may contain pasted example text)", "expected_step": expected_step, "expected_schema": SCHEMAS[expected_step], "original_request_id": request_id, "original_payload": original_payload, "preset": original.get("payload", {}).get("preset", {})}}
            status = "repair"
        finally:
            if log_dir:
                log_dir.mkdir(parents=True, exist_ok=True)
                entry = {"request_id": request_id, "step": bounded["step"], "envelope_size": len(json.dumps(bounded, ensure_ascii=False).encode()), "duration": round(time.monotonic() - started, 3), "status": status, "response": raw if expected_step != "extract_commentary_style" or status == "ok" else "(withheld: may contain pasted example text)"}
                with (log_dir / "agent_log.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    raise AgentError("Invalid agent response.")


def call(step: str, spec_so_far: dict, payload: dict, user_message: str = "") -> dict:
    """Public stateless API; current configuration and preset accompany each call."""
    from engine.spec import validate_spec
    from engine.presets import get_preset, agent_payload
    spec = validate_spec(spec_so_far)
    data = copy.deepcopy(payload)
    data["preset"] = agent_payload(get_preset(spec["preset"]["id"], spec["preset"]["version"]), step)
    return invoke_agent({"request_id": str(uuid.uuid4()), "step": step, "spec_so_far": spec, "payload": data, "user_message": user_message[:3000]})
