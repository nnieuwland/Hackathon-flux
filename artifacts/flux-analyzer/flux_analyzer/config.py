"""Environment-only configuration; credentials never leave the server."""
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
WORKSPACE = Path(os.getenv("FLUX_WORKSPACE", str(ROOT / "workspace"))).resolve()
AGENT_MODE = os.getenv("AGENT_MODE", "mock" if os.getenv("AGENT_MOCK", "true").lower() == "true" else "live").lower()
if AGENT_MODE not in ("mock", "live"):
    raise ValueError("AGENT_MODE must be mock or live.")
AGENT_MOCK = AGENT_MODE == "mock"
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT_SECONDS", "180"))
MAX_AGENT_PAYLOAD_KB = min(50, int(os.getenv("MAX_AGENT_PAYLOAD_KB", "50")))

def prepare_workspace() -> None:
    """Create local, private data directories."""
    for name in ("uploads", "cache", "specs/maps", "runs", "projects"):
        (WORKSPACE / name).mkdir(parents=True, exist_ok=True)
    # Examples are declarative JSON, not Python domain-specific logic.
    for example in (ROOT / "examples").glob("*.json"):
        destination = WORKSPACE / "specs" / example.name
        if not destination.exists():
            shutil.copyfile(example, destination)
