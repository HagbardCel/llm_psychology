"""Minimal HTTP/WebSocket client for legacy public API characterization.

Setup helpers (`persist_intake_messages`, `drive_to_ready`) always register a
fresh user. Callers must not register before invoking them.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import trio
from trio_websocket import open_websocket_url

DETERMINISTIC_REPLIES = [
    "I struggle with anxiety about work.",
    "This has been going on for three months.",
    (
        "I have not had thoughts of harming myself or anyone else. "
        "The chest tightness is not medically urgent."
    ),
    "I tried breathing exercises when Monday deadlines make my chest tight.",
    "I want to sleep better and feel less anxious about Monday deadlines.",
    "I freeze when my manager pressures me about Monday deadlines and my chest tightens.",
    "I have been sleeping badly and keep waking up at night.",
    (
        "This week the Monday deadline made my chest tighten and I worried "
        "that I was failing."
    ),
]

DEFAULT_WS_TIMEOUT = 120.0
DEFAULT_INTAKE_TIMEOUT = 480.0


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _diagnostic_context(
    server: LegacyServer,
    *,
    last_status: dict[str, Any] | None = None,
    last_action: dict[str, Any] | None = None,
) -> str:
    parts = [f"server_stderr={server.stderr}"]
    if last_status is not None:
        parts.append(f"workflow_status={last_status}")
    if last_action is not None:
        parts.append(f"workflow_next={last_action}")
    return "; ".join(parts)


@dataclass
class LegacyServer:
    base_url: str
    database: Path
    process: subprocess.Popen
    port: int
    stdout: Path
    stderr: Path

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return httpx.request(method, self.base_url + path, timeout=30, **kwargs)

    def rows(self, table: str) -> list[dict]:
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(f"select * from {table}")]

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def restart(self) -> None:
        self.stop()
        environment = os.environ | {
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(self.port),
            "E2E_DB_PATH": str(self.database),
            "PYTHONUNBUFFERED": "1",
        }
        with self.stdout.open("a") as output, self.stderr.open("a") as errors:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "psychoanalyst_app.deterministic_server"],
                env=environment,
                stdout=output,
                stderr=errors,
            )
        wait_until_healthy(self)


def wait_until_healthy(server: LegacyServer) -> None:
    for _ in range(200):
        if server.process.poll() is not None:
            pytest.fail(server.stderr.read_text())
        try:
            if server.request("GET", "/health").status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    server.stop()
    pytest.fail(server.stderr.read_text())


def start_legacy_server(tmp_path: Path) -> LegacyServer:
    port = _port()
    database, stderr = tmp_path / "legacy.db", tmp_path / "server.stderr"
    environment = os.environ | {
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": str(port),
        "E2E_DB_PATH": str(database),
        "PYTHONUNBUFFERED": "1",
    }
    with (tmp_path / "server.stdout").open("w") as output, stderr.open("w") as errors:
        process = subprocess.Popen(
            [sys.executable, "-m", "psychoanalyst_app.deterministic_server"],
            env=environment,
            stdout=output,
            stderr=errors,
        )
    server = LegacyServer(
        f"http://127.0.0.1:{port}",
        database,
        process,
        port,
        tmp_path / "server.stdout",
        stderr,
    )
    wait_until_healthy(server)
    return server


@dataclass
class LegacyApiClient:
    server: LegacyServer
    user_id: str = "characterization-user"
    session_id: str | None = None
    _replies: list[str] = field(default_factory=lambda: list(DETERMINISTIC_REPLIES))

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return self.server.request(method, path, **kwargs)

    def register(self, *, name: str = "Alex", language: str = "English") -> dict:
        response = self.request(
            "POST",
            "/api/user/register",
            json={
                "user_id": self.user_id,
                "name": name,
                "primary_language": language,
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        self.session_id = payload["session"]["session_id"]
        return payload

    def login(self) -> dict:
        response = self.request(
            "POST",
            "/api/user/login",
            json={"user_id": self.user_id},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        self.session_id = payload["session"]["session_id"]
        return payload

    def user_status(self) -> dict:
        response = self.request(
            "GET",
            "/api/user/status",
            params={"user_id": self.user_id},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def workflow_next(self) -> dict:
        assert self.session_id
        response = self.request(
            "GET",
            "/api/workflow/next",
            params={"user_id": self.user_id, "session_id": self.session_id},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def complete_profile(self, **fields: Any) -> dict:
        assert self.session_id
        payload = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "name": fields.get("name", "Alex"),
            "primary_language": fields.get("primary_language", "English"),
        }
        response = self.request("POST", "/api/workflow/complete_profile", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    def select_style(self, style_id: str = "cbt") -> dict:
        assert self.session_id
        response = self.request(
            "POST",
            "/api/workflow/select_therapy_style",
            json={
                "user_id": self.user_id,
                "session_id": self.session_id,
                "selected_therapy_style": style_id,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def start_therapy(self) -> dict:
        assert self.session_id
        response = self.request(
            "POST",
            "/api/workflow/start_therapy",
            json={"user_id": self.user_id, "session_id": self.session_id},
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        self.session_id = payload["session"]["session_id"]
        return payload

    def end_session(self, session_id: str | None = None) -> dict:
        session_id = session_id or self.session_id
        assert session_id
        response = self.request(
            "POST",
            f"/api/sessions/{session_id}/end",
            json={"user_id": self.user_id, "session_id": session_id},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def wait_for_workflow_state(self, target: str, *, timeout: float = 180) -> dict:
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.user_status()
            if last.get("workflow_state") == target:
                return last
            time.sleep(1)
        raise AssertionError(
            f"timed out waiting for workflow_state={target!r}, "
            f"{_diagnostic_context(self.server, last_status=last)}"
        )

    def wait_for_job(self, job_id: str, *, timeout: float = 180) -> dict:
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            response = self.request(
                "GET",
                f"/api/jobs/{job_id}",
                params={"user_id": self.user_id},
            )
            assert response.status_code == 200, response.text
            last = response.json()
            if last.get("status") == "complete":
                return last
            if last.get("status") == "failed":
                raise AssertionError(f"job failed: {last}")
            time.sleep(2)
        raise AssertionError(
            f"timed out waiting for job {job_id!r}, last={last}, "
            f"{_diagnostic_context(self.server)}"
        )

    def websocket_url(self) -> str:
        return (
            self.server.base_url.replace("http", "ws", 1)
            + f"/ws?user_id={self.user_id}"
        )

    async def _receive_json_message(self, websocket, *, timeout: float) -> dict:
        with trio.move_on_after(timeout) as cancel_scope:
            raw = await websocket.get_message()
        if cancel_scope.cancelled_caught:
            raise trio.TooSlowError
        return json.loads(raw)

    async def wait_for_session_started(
        self, websocket, *, timeout: float = DEFAULT_WS_TIMEOUT
    ) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                event = await self._receive_json_message(
                    websocket, timeout=min(remaining, 5.0)
                )
            except trio.TooSlowError:
                continue
            if event.get("type") == "session_started":
                return event
        pytest.fail(
            "legacy websocket did not start a session; "
            f"{_diagnostic_context(self.server, last_status=self.user_status())}"
        )

    async def send_chat(self, websocket, message: str) -> None:
        await websocket.send_message(
            json.dumps({"type": "chat_message", "data": {"message": message}})
        )

    async def collect_chat_response(
        self, websocket, *, timeout: float = DEFAULT_WS_TIMEOUT
    ) -> str:
        deadline = time.time() + timeout
        chunks: list[str] = []
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                event = await self._receive_json_message(
                    websocket, timeout=min(remaining, 5.0)
                )
            except trio.TooSlowError:
                continue
            if event.get("type") != "chat_response_chunk":
                continue
            chunks.append(event["data"]["chunk"])
            if event["data"]["is_complete"]:
                return "".join(chunks)
        pytest.fail(
            "legacy websocket did not complete chat streaming; "
            f"{_diagnostic_context(self.server, last_status=self.user_status())}"
        )

    async def wait_for_initial_greeting(
        self, websocket, *, timeout: float = DEFAULT_WS_TIMEOUT
    ) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            try:
                event = await self._receive_json_message(
                    websocket, timeout=min(remaining, 2.0)
                )
            except trio.TooSlowError:
                continue
            if (
                event.get("type") == "chat_response_chunk"
                and event["data"].get("is_complete")
            ):
                await trio.sleep(0.5)
                return
        pytest.fail(
            "legacy websocket did not finish initial greeting; "
            f"{_diagnostic_context(self.server, last_status=self.user_status())}"
        )

    async def drive_intake_chat(
        self,
        websocket,
        *,
        max_turns: int = 16,
        timeout: float = DEFAULT_INTAKE_TIMEOUT,
    ) -> None:
        await self.wait_for_initial_greeting(websocket, timeout=timeout)
        deadline = time.time() + timeout
        sent = 0
        last_action: dict[str, Any] = {}
        while sent < max_turns and time.time() < deadline:
            status = self.user_status()
            state = status.get("workflow_state")
            if state not in {"intake_in_progress", "new", "profile_only"}:
                return
            last_action = self.workflow_next()
            required = last_action.get("required_action")
            if required == "complete_profile":
                self.complete_profile()
                continue
            if required == "wait":
                await trio.sleep(min(2.0, max(0.1, deadline - time.time())))
                continue
            reply = self._replies[min(sent, len(self._replies) - 1)]
            await self.send_chat(websocket, reply)
            await self.collect_chat_response(
                websocket, timeout=max(0.1, deadline - time.time())
            )
            await trio.sleep(1)
            sent += 1
        status = self.user_status()
        if status.get("workflow_state") == "intake_in_progress":
            raise AssertionError(
                f"intake did not complete after {max_turns} turns: {status}; "
                f"{_diagnostic_context(self.server, last_status=status, last_action=last_action)}"
            )

    async def wait_for_assessment_complete(
        self, websocket, *, timeout: float = DEFAULT_INTAKE_TIMEOUT
    ) -> dict:
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.user_status()
            if last.get("workflow_state") == "assessment_complete":
                return last
            remaining = max(0.1, deadline - time.time())
            with trio.move_on_after(min(remaining, 2.0)):
                try:
                    await websocket.get_message()
                except trio.TooSlowError:
                    pass
            await trio.sleep(1)
        raise AssertionError(
            f"timed out waiting for assessment completion, last={last}; "
            f"{_diagnostic_context(self.server, last_status=last)}"
        )

    async def drive_to_ready(self, *, timeout: float = DEFAULT_INTAKE_TIMEOUT) -> None:
        payload = self.register()
        action = payload.get("workflow_next_action", {})
        if action.get("required_action") == "complete_profile":
            self.complete_profile()

        async with open_websocket_url(
            self.websocket_url(),
            extra_headers=[("Origin", "http://localhost")],
        ) as websocket:
            await self.wait_for_session_started(websocket, timeout=timeout)
            await self.drive_intake_chat(websocket, timeout=timeout)
            await self.wait_for_assessment_complete(websocket, timeout=timeout)

        self.select_style("cbt")
        self.wait_for_workflow_state("initial_plan_complete", timeout=timeout)

    async def chat_turn(
        self, message: str, *, register_first: bool = True
    ) -> str:
        """Submit one intake or therapy chat turn and return the streamed assistant text."""
        if register_first:
            self.register()
        async with open_websocket_url(
            self.websocket_url(),
            extra_headers=[("Origin", "http://localhost")],
        ) as websocket:
            await self.wait_for_session_started(websocket)
            await self.wait_for_initial_greeting(websocket)
            await self.send_chat(websocket, message)
            return await self.collect_chat_response(websocket)

    async def persist_intake_messages(self) -> None:
        payload = self.register()
        action = payload.get("workflow_next_action", {})
        if action.get("required_action") == "complete_profile":
            self.complete_profile()
        async with open_websocket_url(
            self.websocket_url(),
            extra_headers=[("Origin", "http://localhost")],
        ) as websocket:
            await self.wait_for_session_started(websocket)
            await self.wait_for_initial_greeting(websocket)
            await self.send_chat(websocket, self._replies[0])
            await self.collect_chat_response(websocket)
            await trio.sleep(1)
