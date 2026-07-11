"""Hook policy tests run hooks with mocked Git and Make executables."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _mock(path: Path, name: str, body: str) -> None:
    target = path / name
    target.write_text("#!/bin/bash\nset -eu\n" + body, encoding="utf-8")
    target.chmod(0o755)


def _run_push(tmp_path: Path, remote_ref: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "make-calls"
    _mock(bin_dir, "git", 'if [ "$1" = "rev-parse" ]; then pwd; fi\n')
    _mock(bin_dir, "make", f'printf "%s\\n" "$*" >> "{calls}"\n')
    environment = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
    }
    hook = Path(__file__).resolve().parents[2] / "scripts" / "pre-push"
    result = subprocess.run(
        [str(hook)],
        cwd=tmp_path,
        env=environment,
        input=f"refs/heads/topic deadbeef {remote_ref} 0000000000000000000000000000000000000000\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return calls.read_text(encoding="utf-8")


def test_pre_push_uses_remote_phase_ref_not_checked_out_branch(tmp_path):
    calls = _run_push(tmp_path, "refs/heads/refactor/single-user-architecture")
    assert "hook-push" in calls
    assert "validate-refactor-phase-1" in calls


def test_pre_push_runs_full_gate_for_main_remote_ref(tmp_path):
    calls = _run_push(tmp_path, "refs/heads/main")
    assert "hook-push" in calls
    assert "finalization-check" in calls
