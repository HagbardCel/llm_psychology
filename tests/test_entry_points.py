import os
import subprocess
import sys


def test_server_entry_point_importable():
    """
    Smoke test to verify that src/server.py can be imported.
    This catches missing dependencies or syntax errors in the entry point script.
    """
    # We run this as a subprocess to avoid polluting the current process
    # and to ensure it works as a standalone script.
    # We use -c "import src.server" to just test the import.

    # Add project root to python path
    env = os.environ.copy()
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_path = os.path.join(project_root, "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env.get("PYTHONPATH"), project_root, src_path]))

    result = subprocess.run(
        [sys.executable, "-c", "import psychoanalyst_app.server"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Failed to import src/server.py: {result.stderr}"


def test_main_entry_point_importable():
    """
    Smoke test to verify that src/main.py can be imported.
    """
    env = os.environ.copy()
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_path = os.path.join(project_root, "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env.get("PYTHONPATH"), project_root, src_path]))

    result = subprocess.run(
        [sys.executable, "-c", "import psychoanalyst_app.main"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Failed to import src/main.py: {result.stderr}"
