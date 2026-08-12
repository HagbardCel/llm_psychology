"""Terminal adapter and CLI entry point for the Jung console client."""

from __future__ import annotations

import argparse
import asyncio
from typing import Protocol

from prompt_toolkit import PromptSession

from jung.api.contracts import (
    AppSnapshotResponse,
    ErrorEnvelope,
    StyleOptionsResponse,
)
from jung.client.api_client import ClientSettings, JungApiClient, JungClientError
from jung.client.console import (
    ConsoleApp,
    ConsoleExitRequested,
    ConsoleOperationFailed,
    ConsoleOutput,
    ErrorDisplay,
    InputProvider,
    PromptSpec,
)


class TerminalOutput(ConsoleOutput, Protocol):
    def render_client_error(self, error: JungClientError) -> None: ...


class HumanInputProvider:
    def __init__(self, session: PromptSession[str] | None = None) -> None:
        self._session = session if session is not None else PromptSession()

    async def read(self, prompt: PromptSpec) -> str:
        return await self._session.prompt_async(prompt.text)


class TerminalConsoleOutput:
    def __init__(self) -> None:
        self._assistant_stream_active = False

    def render_snapshot(self, snapshot: AppSnapshotResponse) -> None:
        commands = ", ".join(snapshot.available_commands) or "(none)"
        print(f"\n[stage={snapshot.stage} commands={commands}]")

    def render_message(self, role: str, content: str) -> None:
        label = "You" if role == "user" else "Therapist"
        print(f"\n{label}: {content}")

    def begin_assistant_message(self) -> None:
        print("\nTherapist: ", end="", flush=True)
        self._assistant_stream_active = True

    def append_assistant_token(self, text: str) -> None:
        print(text, end="", flush=True)

    def finish_assistant_stream(self) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False

    def replace_partial_assistant_message(self, content: str) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False
        print("\n[Stream corrected from durable completion]")
        print(f"Therapist: {content}")

    def render_assistant_message(self, content: str) -> None:
        print(f"\nTherapist: {content}")

    def discard_partial_assistant_message(self) -> None:
        if self._assistant_stream_active:
            print()
            self._assistant_stream_active = False

    def render_system(self, message: str) -> None:
        print(f"\n{message}")

    def render_command_rejection(self, error: ErrorEnvelope) -> None:
        print(f"\nRequest rejected ({error.code}): {error.message}")

    def render_chat_failure(self, error: ErrorEnvelope) -> None:
        print(f"\nChat failed ({error.code}): {error.message}")

    def render_operation_failure(self, error: ErrorDisplay) -> None:
        print(f"\nOperation failed ({error.code}): {error.message}")

    def render_style_options(self, options: StyleOptionsResponse) -> None:
        print("\nAvailable styles:")
        for style in options.styles:
            print(f"  {style.id}: {style.name}")
        if options.recommendations:
            print("\nRecommendations:")
            for rec in options.recommendations:
                print(f"  {rec.style_id} (score={rec.score:.2f}): {rec.rationale}")

    def render_invalid_action(self, message: str) -> None:
        print(f"\n{message}")

    def render_client_error(self, error: JungClientError) -> None:
        print(f"\nClient error: {error}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jung therapy console client")
    parser.add_argument(
        "--api-url",
        required=True,
        help="Base URL for the Jung API (e.g. http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--transport-timeout",
        type=float,
        default=None,
        help="HTTP transport timeout in seconds",
    )
    return parser


def cli() -> int:
    try:
        return asyncio.run(_async_cli())
    except KeyboardInterrupt:
        return 130


async def run_console(
    settings: ClientSettings,
    *,
    input_provider: InputProvider | None = None,
    output: TerminalOutput | None = None,
) -> int:
    console_input = input_provider or HumanInputProvider()
    console_output = output or TerminalConsoleOutput()

    try:
        async with JungApiClient(settings) as client:
            await ConsoleApp(
                client=client,
                input=console_input,
                output=console_output,
            ).run()
    except ConsoleExitRequested:
        return 0
    except ConsoleOperationFailed:
        return 1
    except JungClientError as exc:
        console_output.render_client_error(exc)
        return 3

    return 0


async def _async_cli() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings_kwargs: dict[str, object] = {"base_url": args.api_url}
    if args.transport_timeout is not None:
        settings_kwargs["transport_timeout"] = args.transport_timeout
    settings = ClientSettings(**settings_kwargs)
    return await run_console(settings)


if __name__ == "__main__":
    raise SystemExit(cli())
