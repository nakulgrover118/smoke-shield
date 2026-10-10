import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "layers" / "common" / "python"))
sys.path.insert(0, str(ROOT / "functions" / "advisory"))
sys.path.insert(0, str(ROOT / "scripts"))


def load_handler_module(name):
    """Each function dir has its own app.py, so load them by path under distinct names."""
    spec = importlib.util.spec_from_file_location(f"{name}_app", ROOT / "functions" / name / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sample_fires_csv():
    return (ROOT / "samples" / "fires_sample.csv").read_text()
