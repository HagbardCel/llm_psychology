"""Console output routing and logging helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(log_path: str) -> logging.Logger:
    """Configure file-only logging and return the root logger."""
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)
    return root_logger


@dataclass
class ConsoleOutput:
    """Route user-facing output to stdout and all output to logs."""

    logger: logging.Logger

    def system(self, message: str) -> None:
        """Log system messages without printing to stdout."""
        self.logger.info("SYSTEM: %s", message)

    def prompt(
        self, message: str, *, end: str = "\n", flush: bool = True
    ) -> None:
        """Print user prompts and log them."""
        print(message, end=end, flush=flush)
        self.logger.info("PROMPT: %s", message)

    def user_text(
        self,
        message: str,
        *,
        end: str = "\n",
        flush: bool = True,
        log: bool = True,
    ) -> None:
        """Print user-visible text and optionally log it."""
        print(message, end=end, flush=flush)
        if log:
            self.logger.info("USER_VIEW: %s", message)

    def error(self, message: str) -> None:
        """Print user-visible errors and log them."""
        print(message, flush=True)
        self.logger.error("USER_ERROR: %s", message)

    def log_chat(self, role: str, text: str) -> None:
        """Log chat messages without ANSI formatting."""
        self.logger.info("CHAT_%s: %s", role.upper(), text)

    def log_input(self, text: str) -> None:
        """Log user input for debugging."""
        self.logger.info("USER_INPUT: %s", text)
