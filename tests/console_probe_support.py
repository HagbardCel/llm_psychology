"""Shared probe infrastructure for Jung console E2E and unit tests."""

from __future__ import annotations

import json
import logging
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jung.client.console import ConsoleObserver, PromptSpec


@dataclass
class ScriptedInputProvider:
    """Feeds scripted responses to the console in order."""

    responses: deque[str] = field(default_factory=deque)

    @classmethod
    def from_lines(cls, *lines: str) -> ScriptedInputProvider:
        return cls(responses=deque(lines))

    async def read(self, prompt: PromptSpec) -> str:
        if not self.responses:
            raise EOFError("scripted input exhausted")
        value = self.responses.popleft()
        return value if value.endswith("\n") else f"{value}\n"


class ProbeRecorder(ConsoleObserver):
    """Records normalized timeline events and writes probe artifacts."""

    ARTIFACT_NAMES = (
        "manifest.json",
        "timeline.jsonl",
        "transcript.md",
        "server.log",
        "summary.md",
    )
    FAILURE_ARTIFACT = "failure_summary.md"

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.started_at = datetime.now(UTC)
        self.timeline: list[dict[str, Any]] = []
        self.transcript_lines: list[str] = []
        self._log_handler: logging.Handler | None = None

    def record(self, event: str, **fields: object) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "category": event,
        }
        for key, value in fields.items():
            if value is not None:
                entry[key] = value
        self.timeline.append(entry)
        if event in {"user_message", "assistant_message"}:
            role = "user" if event == "user_message" else "assistant"
            content = str(fields.get("content", ""))
            self.transcript_lines.append(f"**{role.title()}**: {content}")

    def attach_server_logging(self, logger_name: str = "uvicorn") -> None:
        if self._log_handler is not None:
            return
        handler = _ProbeLogHandler(self)
        handler.setLevel(logging.DEBUG)
        logging.getLogger(logger_name).addHandler(handler)
        logging.getLogger("jung").addHandler(handler)
        self._log_handler = handler

    def detach_server_logging(self) -> None:
        if self._log_handler is None:
            return
        for name in ("uvicorn", "jung"):
            logging.getLogger(name).removeHandler(self._log_handler)
        self._log_handler = None

    def write_artifacts(
        self,
        scenario_dir: Path,
        *,
        failure: BaseException | None = None,
    ) -> None:
        scenario_dir.mkdir(parents=True, exist_ok=True)
        finished_at = datetime.now(UTC)
        manifest = {
            "scenario_id": self.scenario_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "success": failure is None,
            "artifacts": list(self.ARTIFACT_NAMES),
        }
        if failure is not None:
            manifest["artifacts"].append(self.FAILURE_ARTIFACT)

        (scenario_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        timeline_path = scenario_dir / "timeline.jsonl"
        with timeline_path.open("w", encoding="utf-8") as handle:
            for entry in self.timeline:
                handle.write(json.dumps(entry, default=str) + "\n")

        transcript = (
            "\n\n".join(self.transcript_lines)
            if self.transcript_lines
            else "_No transcript captured._"
        )
        (scenario_dir / "transcript.md").write_text(transcript + "\n", encoding="utf-8")

        log_lines = [
            line
            for line in self.timeline
            if line.get("category") == "server_log"
        ]
        server_log = "\n".join(
            json.dumps(line, default=str) for line in log_lines
        )
        (scenario_dir / "server.log").write_text(
            server_log + ("\n" if server_log else ""),
            encoding="utf-8",
        )

        summary = (
            f"# {self.scenario_id}\n\n"
            f"- started: {self.started_at.isoformat()}\n"
            f"- finished: {finished_at.isoformat()}\n"
            f"- events: {len(self.timeline)}\n"
            f"- outcome: {'success' if failure is None else 'failure'}\n"
        )
        (scenario_dir / "summary.md").write_text(summary, encoding="utf-8")

        if failure is not None:
            failure_summary = (
                f"# Failure: {self.scenario_id}\n\n"
                f"```\n{traceback.format_exception_only(type(failure), failure)}```\n\n"
                f"```\n{''.join(traceback.format_tb(failure.__traceback__))}```\n"
            )
            (scenario_dir / "failure_summary.md").write_text(
                failure_summary,
                encoding="utf-8",
            )


class _ProbeLogHandler(logging.Handler):
    def __init__(self, recorder: ProbeRecorder) -> None:
        super().__init__()
        self._recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        self._recorder.timeline.append(
            {
                "timestamp": datetime.fromtimestamp(
                    record.created,
                    tz=UTC,
                ).isoformat(),
                "category": "server_log",
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
        )
