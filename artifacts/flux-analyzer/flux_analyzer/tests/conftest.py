"""Small synthetic fixtures; all data is deliberately artificial."""
import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

@pytest.fixture
def golden() -> pd.DataFrame:
    """R&M Golden Rule values from the requested worked example."""
    return pd.read_csv(Path(__file__).parent / "fixtures/golden.csv")

@pytest.fixture
def benefits() -> pd.DataFrame:
    """Forecast/actual headcount and cost for a volume/rate reconciliation."""
    return pd.read_csv(Path(__file__).parent / "fixtures/benefits.csv")
