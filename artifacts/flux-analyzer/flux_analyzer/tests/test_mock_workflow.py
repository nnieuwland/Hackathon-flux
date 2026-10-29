"""Optional end-to-end mock workflow. Run explicitly after the first build."""
import json
import re
import time
from app import create_app

def test_mock_workflow() -> None:
    """Use real synthetic files, user approvals, controls, a run and Excel."""
    app = create_app({"TESTING": True, "SECRET_KEY": "synthetic-test-only"})
    client = app.test_client()
    client.get("/")
    state = client.get("/state").get_json()
    headers = {"X-CSRF-Token": state["csrf_token"]}
    def post(path: str, data: dict | None = None) -> dict:
        response = client.post(path, json=data or {}, headers=headers)
        assert response.status_code in (200, 202), response.get_data(as_text=True)
        return response.get_json()
    def wait(job_id: str) -> dict:
        for _ in range(300):
            job = client.get(f"/jobs/{job_id}").get_json()
            if job["status"] == "done":
                return job["result"]
            assert job["status"] != "error", job.get("error")
            time.sleep(.05)
        raise AssertionError("Mock job timed out")
    state = post("/sources/demo")
    for source in state["sources"]:
        post(f"/sources/{source['id']}/define", source["definition"])
    for step in ("map_columns", "define_comparison", "define_rules"):
        response = wait(post(f"/config/{step}/suggest")["job_id"])
        state = post(f"/config/{step}/accept", {"proposal": response["proposal"]})
    controls = post("/review/controls")["controls"]
    assert not any(c["status"] == "stop" for c in controls)
    result = wait(post("/run")["job_id"])
    run = client.get(f"/results/{result['run_id']}?format=json").get_json()
    assert run["n_drivers"] > 0
    export = client.get(f"/download/{run['id']}/excel")
    assert export.status_code == 200 and export.data.startswith(b"PK")
