"""Pure diagnostics for the intake note tracking workflow probe.

This module is intentionally side-effect free so the diagnostics logic can be
unit-tested without touching the filesystem. The probe recorder is responsible
only for calling :func:`build_intake_note_tracking_diagnostics` and writing the
returned dict to ``intake_note_tracking.json``.

Completeness is derived from the backend's own
:func:`intake_record_completion_decision` whenever the backend package is
importable (canonical source). A conservative structural fallback is used only
on a real import blocker and is surfaced as a diagnostic degradation, never a
clean pass for the main note-tracking probe.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

try:  # backend typed model; requires pydantic (probe runner image includes it)
    from psychoanalyst_app.models.intake_record import IntakeRecord

    _INTAKE_RECORD_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without pydantic
    IntakeRecord = None  # type: ignore[assignment]
    _INTAKE_RECORD_AVAILABLE = False


def _load_canonical_completion():
    """Import intake_record_completion_decision without the heavy agent package.

    ``psychoanalyst_app.agents.intake.__init__`` eagerly imports the full intake
    agent (langchain-dependent), which is unavailable in the lightweight probe
    runner image. The completeness decision itself only depends on the typed
    ``IntakeRecord`` model and the pure ``policy`` constants, so we register the
    ``agents.intake`` package as a namespace package and load
    ``record_completeness`` (and its dependency ``policy``) directly from the
    backend source tree. Returns the function or ``None`` on failure.
    """
    try:
        # Fast path: normal import works when the full backend is importable.
        from psychoanalyst_app.agents.intake.record_completeness import (
            intake_record_completion_decision as _func,
        )

        return _func
    except Exception:
        pass

    try:
        import psychoanalyst_app.agents.intake.policy  # noqa: F401
        from psychoanalyst_app.agents.intake.record_completeness import (
            intake_record_completion_decision as _func,
        )

        return _func
    except Exception:
        pass

    # Slow path: bypass the heavy package __init__ by locating the source files.
    backend_src = Path(__import__("psychoanalyst_app").__file__).resolve().parent
    intake_dir = backend_src / "agents" / "intake"
    if not (intake_dir / "record_completeness.py").exists():
        return None
    pkg_name = "psychoanalyst_app.agents.intake"
    if pkg_name not in sys.modules:
        ns = ModuleType(pkg_name)
        ns.__path__ = [str(intake_dir)]
        sys.modules[pkg_name] = ns
    try:
        policy_spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.policy", intake_dir / "policy.py"
        )
        policy_mod = importlib.util.module_from_spec(policy_spec)
        sys.modules[f"{pkg_name}.policy"] = policy_mod
        assert policy_spec.loader is not None
        policy_spec.loader.exec_module(policy_mod)

        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.record_completeness", intake_dir / "record_completeness.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.record_completeness"] = module
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.intake_record_completion_decision
    except Exception:
        return None


intake_record_completion_decision = _load_canonical_completion()
_CANONICAL_COMPLETION_AVAILABLE = intake_record_completion_decision is not None


COMPLETION_SOURCE_CANONICAL = "intake_record_completion_decision"
COMPLETION_SOURCE_STRUCTURAL_FALLBACK = "structural_fallback"

# Ordered to match record_completeness.HARD_ITEM_ORDER + SOFT_ITEM_ORDER.
ITEM_KEYS = (
    "presenting_problem",
    "duration",
    "risk_screen",
    "functional_impairment",
    "goal_preference",
    "coping_attempts",
    "sleep_impact",
)


def build_intake_note_tracking_diagnostics(
    sessions_rows: list[dict[str, Any]],
    transcript: list[dict[str, Any]],
    scenario: dict[str, Any],
    *,
    final_workflow_state: str | None = None,
) -> dict[str, Any]:
    """Build a stable intake note tracking diagnostics dict from probe rows.

    ``sessions_rows`` are the ``sessions`` table rows captured by the probe DB
    snapshot. ``transcript`` is the intake session transcript (role/content
    items) used to count patient turns for the canonical completion decision.
    ``scenario`` carries the ``intake_note_tracking`` expectations block.
    ``final_workflow_state`` is the recorder-derived final workflow state; when
    omitted it is inferred from session rows as a best-effort fallback.
    """
    expectations = scenario.get("intake_note_tracking") or {}
    failure_reasons: list[str] = []

    selected = _select_intake_session(sessions_rows, failure_reasons)
    selected_session_id = selected.get("session_id") if selected else None
    record_raw = selected.get("intake_record") if selected else None
    record_updated_at = selected.get("intake_record_updated_at") if selected else None

    session_found = selected is not None
    intake_record_persisted = record_raw not in (None, "", "null")
    patient_turn_count = _patient_turn_count(transcript)

    parsed_record: IntakeRecord | None = None
    intake_record_parseable = False
    if intake_record_persisted:
        parsed_record, intake_record_parseable = _parse_intake_record(record_raw)
        if not intake_record_parseable:
            failure_reasons.append("intake_record present but not parseable")

    completion = _derive_completion(
        parsed_record, patient_turn_count, failure_reasons
    )

    items = (
        _item_diagnostics(parsed_record) if parsed_record is not None else {}
    )

    if final_workflow_state is None:
        final_workflow_state = _infer_workflow_state(sessions_rows)
    advanced_past_intake_in_progress = bool(
        final_workflow_state and final_workflow_state != "intake_in_progress"
    )

    if expectations.get("expected") and not intake_record_persisted:
        failure_reasons.append("intake_record not persisted")
    if expectations.get("require_structured_completion") and not completion["complete"]:
        failure_reasons.append("structured completion not reached")
    if expectations.get("require_canonical_completion_source") and completion[
        "source"
    ] != COMPLETION_SOURCE_CANONICAL:
        failure_reasons.append("completion source fell back to structural helper")
    if expectations.get("require_informative_goal") and not items.get(
        "goal_preference", {}
    ).get("present"):
        failure_reasons.append("goal_preference not informatively present")

    return {
        "expected": bool(expectations.get("expected")),
        "session_found": session_found,
        "selected_session_id": selected_session_id,
        "candidate_session_count": _candidate_session_count(sessions_rows),
        "intake_record_persisted": intake_record_persisted,
        "intake_record_parseable": intake_record_parseable,
        "intake_record_updated_at": record_updated_at,
        "final_workflow_state": final_workflow_state,
        "advanced_past_intake_in_progress": advanced_past_intake_in_progress,
        "patient_turn_count": patient_turn_count,
        "completion": completion,
        "items": items,
        "failure_reasons": failure_reasons,
    }


def _select_intake_session(
    sessions_rows: list[dict[str, Any]], failure_reasons: list[str]
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in sessions_rows
        if row.get("session_type") == "intake"
        and row.get("intake_record") not in (None, "", "null")
    ]
    if not candidates:
        # Fall back to any intake session so we can still report presence/absence.
        candidates = [
            row for row in sessions_rows if row.get("session_type") == "intake"
        ]
    if not candidates:
        return None
    if len(candidates) > 1:
        failure_reasons.append(
            f"multiple candidate intake sessions with intake_record: {len(candidates)}"
        )
    # Most recent by intake_record_updated_at, then timestamp.
    return max(
        candidates,
        key=lambda row: (
            str(row.get("intake_record_updated_at") or ""),
            str(row.get("timestamp") or ""),
        ),
    )


def _candidate_session_count(sessions_rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in sessions_rows
        if row.get("session_type") == "intake"
        and row.get("intake_record") not in (None, "", "null")
    )


def _parse_intake_record(
    raw: Any,
) -> tuple[Any, bool]:
    """Parse persisted intake record JSON into a typed model (preferred) or dict.

    Returns ``(model_or_dict, parseable)``. When the backend typed model is
    importable, returns a typed ``IntakeRecord``. Otherwise returns the raw
    parsed dict as a structural fallback so item diagnostics can still run.
    """
    if isinstance(raw, (dict, list)):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None, False
    else:
        return None, False
    if not isinstance(data, dict):
        return None, False
    if _INTAKE_RECORD_AVAILABLE and IntakeRecord is not None:
        try:
            return IntakeRecord.model_validate(data), True
        except Exception:
            return None, False
    # Structural fallback: return the dict so dict-based item helpers can run.
    return data, True


def _derive_completion(
    record: Any,
    patient_turn_count: int,
    failure_reasons: list[str],
) -> dict[str, Any]:
    if record is None:
        return {
            "source": COMPLETION_SOURCE_STRUCTURAL_FALLBACK,
            "complete": False,
            "missing_hard_items": [],
            "missing_soft_items": [],
        }
    if _CANONICAL_COMPLETION_AVAILABLE and intake_record_completion_decision is not None:
        decision = intake_record_completion_decision(record, patient_turn_count)
        return {
            "source": COMPLETION_SOURCE_CANONICAL,
            "complete": bool(decision.complete),
            "missing_hard_items": list(decision.missing_hard_items),
            "missing_soft_items": list(decision.missing_soft_items),
        }
    failure_reasons.append("canonical completion helper unavailable; using structural fallback")
    return _structural_completion(record)


def _structural_completion(record: Any) -> dict[str, Any]:
    hard = [
        key
        for key in ("risk_screen", "presenting_problem", "duration", "functional_impairment", "goal_preference")
        if not _item_present(record, key)
    ]
    soft = [
        key
        for key in ("coping_attempts", "sleep_impact")
        if not _item_present(record, key)
    ]
    return {
        "source": COMPLETION_SOURCE_STRUCTURAL_FALLBACK,
        "complete": not hard and not soft,
        "missing_hard_items": hard,
        "missing_soft_items": soft,
    }


def _patient_turn_count(transcript: list[dict[str, Any]]) -> int:
    if not isinstance(transcript, list):
        return 0
    return sum(
        1
        for item in transcript
        if isinstance(item, dict) and item.get("role") == "user"
    )


def _item_diagnostics(record: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ITEM_KEYS:
        evidence = _item_evidence(record, key)
        present = _item_present(record, key)
        unknown_or_unable = _item_unknown_or_unable(record, key)
        valid_user_evidence = any(_is_valid_user_evidence(item) for item in evidence)
        result[key] = {
            "present": present,
            "unknown_or_unable_to_answer": unknown_or_unable,
            "evidence_count": len(evidence),
            "has_valid_user_sourced_evidence": valid_user_evidence,
        }
    return result


def _item_evidence(record: Any, key: str) -> list[Any]:
    if isinstance(record, dict):
        return _dict_item_evidence(record, key)
    return _typed_item_evidence(record, key)


def _typed_item_evidence(record: IntakeRecord, key: str) -> list[Any]:
    if key == "presenting_problem":
        return [record.presenting_problem.main_concern]
    if key == "duration":
        return [
            record.presenting_problem.time_course.duration_or_onset,
            record.presenting_problem.time_course.frequency,
        ]
    if key == "risk_screen":
        return [
            record.safety.self_harm,
            record.safety.harm_to_others,
            record.safety.medical_urgency,
        ]
    if key == "functional_impairment":
        return [record.presenting_problem.functional_impairment]
    if key == "goal_preference":
        return [*record.goals.therapy_goals, record.goals.preferred_start]
    if key == "coping_attempts":
        return [*record.coping.attempted_strategies, record.coping.substances_or_medication]
    if key == "sleep_impact":
        return [record.presenting_problem.sleep_impact]
    return []


def _dict_item_evidence(record: dict[str, Any], key: str) -> list[Any]:
    presenting = record.get("presenting_problem") or {}
    safety = record.get("safety") or {}
    coping = record.get("coping") or {}
    goals = record.get("goals") or {}
    time_course = presenting.get("time_course") or {}
    if key == "presenting_problem":
        return [presenting.get("main_concern")]
    if key == "duration":
        return [time_course.get("duration_or_onset"), time_course.get("frequency")]
    if key == "risk_screen":
        return [safety.get("self_harm"), safety.get("harm_to_others"), safety.get("medical_urgency")]
    if key == "functional_impairment":
        return [presenting.get("functional_impairment")]
    if key == "goal_preference":
        goals_list = goals.get("therapy_goals") or []
        return [*goals_list, goals.get("preferred_start")]
    if key == "coping_attempts":
        strategies = coping.get("attempted_strategies") or []
        return [*strategies, coping.get("substances_or_medication")]
    if key == "sleep_impact":
        return [presenting.get("sleep_impact")]
    return []


def _item_present(record: Any, key: str) -> bool:
    if isinstance(record, dict):
        return _dict_item_present(record, key)
    if key == "risk_screen":
        return record.safety.is_complete()
    if key == "duration":
        return record.presenting_problem.time_course.has_required_time_course()
    if key == "goal_preference":
        return record.goals.is_present()
    if key == "coping_attempts":
        return record.coping.is_present()
    return any(getattr(item, "is_present", lambda: False)() for item in _typed_item_evidence(record, key))


def _dict_item_present(record: dict[str, Any], key: str) -> bool:
    for evidence in _dict_item_evidence(record, key):
        if _dict_evidence_is_present(evidence):
            return True
    return False


def _dict_evidence_is_present(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    return (
        evidence.get("response_status", "informative") == "informative"
        and bool(evidence.get("value"))
        and bool(evidence.get("evidence_quote"))
        and evidence.get("source_role") == "user"
        and evidence.get("source_message_index") is not None
    )


def _dict_evidence_is_unknown_or_unable(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    return (
        evidence.get("response_status") in ("unknown", "unable_to_answer")
        and bool(evidence.get("direct_ask"))
        and bool(evidence.get("evidence_quote"))
        and evidence.get("source_role") == "user"
        and evidence.get("source_message_index") is not None
    )


def _item_unknown_or_unable(record: Any, key: str) -> bool:
    if isinstance(record, dict):
        return any(
            _dict_evidence_is_unknown_or_unable(item)
            for item in _dict_item_evidence(record, key)
        )
    return any(
        getattr(item, "is_unable_or_unknown", lambda: False)()
        for item in _typed_item_evidence(record, key)
    )


def _is_valid_user_evidence(evidence: Any) -> bool:
    if evidence is None:
        return False
    if isinstance(evidence, dict):
        return (
            evidence.get("source_role") == "user"
            and evidence.get("source_message_index") is not None
            and bool(evidence.get("evidence_quote"))
        )
    source_role = getattr(evidence, "source_role", None)
    source_index = getattr(evidence, "source_message_index", None)
    quote = getattr(evidence, "evidence_quote", None)
    return (
        source_role == "user"
        and source_index is not None
        and bool(quote)
    )


def _infer_workflow_state(sessions_rows: list[dict[str, Any]]) -> str | None:
    # Best-effort fallback when the recorder does not supply an authoritative
    # final workflow state derived from probe events.
    intake_rows = [row for row in sessions_rows if row.get("session_type") == "intake"]
    for row in reversed(intake_rows):
        if row.get("ended_at"):
            return "intake_completed"
    if intake_rows:
        return "intake_in_progress"
    return None
