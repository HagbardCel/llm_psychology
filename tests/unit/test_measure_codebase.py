import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_codebase.py"
_SPEC = importlib.util.spec_from_file_location("measure_codebase", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
measure = _MODULE.measure


def test_measure_codebase_separates_source_and_tests():
    metrics = measure(Path(__file__).resolve().parents[2])

    assert metrics["production_python_files"] > 0
    assert metrics["test_python_files"] > 0
    assert metrics["production_python_physical_loc"] >= metrics["production_python_code_loc"]
