#!/usr/bin/env python3
"""Reformat common long-line patterns to satisfy E501 (88 columns)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_LEN = 88
ROOT = Path(__file__).resolve().parent.parent


def _split_field_args(args: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote: str | None = None
    i = 0
    while i < len(args):
        ch = args[i]
        if in_quote:
            current.append(ch)
            if ch == in_quote and (i == 0 or args[i - 1] != "\\"):
                in_quote = None
        elif ch in "\"'":
            in_quote = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


def reformat_field_line(line: str) -> list[str] | None:
    match = re.match(r"^(\s*)(\w+):\s*(.+?)\s*=\s*Field\((.*)\)\s*$", line)
    if not match:
        return None
    indent, name, typ, args = match.groups()
    inner = indent + "    "
    arg_parts = _split_field_args(args)
    if len(line) <= MAX_LEN and all(len(inner + p + ",") <= MAX_LEN for p in arg_parts):
        return None
    out = [f"{indent}{name}: {typ} = Field("]
    for part in arg_parts:
        out.append(f"{inner}{part},")
    out.append(f"{indent})")
    return out


def reformat_string_concat(line: str) -> list[str] | None:
    """Break long assignments with a single string literal using parens."""
    match = re.match(r'^(\s*)(\w+)\s*=\s*("""[\s\S]*"""|"[^"]*")\s*$', line)
    if not match or len(line) <= MAX_LEN:
        return None
    indent, name, literal = match.groups()
    if literal.startswith('"""'):
        return None
    text = literal[1:-1]
    inner = indent + "    "
    chunks: list[str] = []
    words = text.split()
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(inner) + len(f'"{candidate}"') > MAX_LEN and current:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    if len(chunks) <= 1:
        return None
    out = [f"{indent}{name} = ("]
    for chunk in chunks:
        out.append(f'{inner}"{chunk}"')
    out.append(f"{indent})")
    return out


def reformat_def_line(line: str) -> list[str] | None:
    match = re.match(r"^(\s*)(async )?def ([\w_]+)\((.*)\)(.*)$", line)
    if not match:
        return None
    indent, async_kw, name, params, suffix = match.groups()
    inner = indent + "    "
    if len(line) <= MAX_LEN:
        return None
    param_parts = _split_field_args(params)
    out = [f"{indent}{async_kw or ''}def {name}("]
    for part in param_parts:
        out.append(f"{inner}{part},")
    out.append(f"{indent}){suffix}")
    if all(len(row) <= MAX_LEN for row in out):
        return out
    return None


def reformat_call_line(line: str) -> list[str] | None:
    """Break long calls/returns at the opening parenthesis."""
    match = re.match(r"^(\s*)(.*?)(\([^)]*)\)\s*(.*)$", line)
    if not match:
        return None
    indent, prefix, inner_args, suffix = match.groups()
    if len(line) <= MAX_LEN or len(prefix) > 60:
        return None
    args = inner_args[1:]  # drop leading (
    parts = _split_field_args(args)
    if len(parts) <= 1:
        return None
    out = [f"{indent}{prefix}("]
    arg_indent = indent + "    "
    for part in parts:
        out.append(f"{arg_indent}{part},")
    closing = f"{indent}){suffix}"
    out.append(closing)
    if all(len(row) <= MAX_LEN for row in out):
        return out
    return None


def reformat_docstring_line(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (
        stripped.startswith('"""') and stripped.endswith('"""') and len(stripped) > 6
    ):
        return None
    indent = line[: len(line) - len(line.lstrip())]
    text = stripped[3:-3]
    if len(line) <= MAX_LEN:
        return None
    inner = indent + "    "
    return [f'{indent}"""', f"{inner}{text}", f'{indent}"""']


def break_long_line(line: str) -> list[str]:
    if len(line) <= MAX_LEN:
        return [line]
    for formatter in (
        reformat_field_line,
        reformat_def_line,
        reformat_call_line,
        reformat_string_concat,
        reformat_docstring_line,
    ):
        result = formatter(line)
        if result and all(len(row) <= MAX_LEN for row in result):
            return result
    match = re.match(r"^(\s*)(.+)$", line)
    if not match:
        return [line]
    indent, body = match.groups()
    if 'description="' in body and "Field(" in body:
        field_fix = reformat_field_line(line)
        if field_fix:
            return field_fix
    # Break long f-strings and string literals with implicit concatenation.
    if 'f"' in body or (body.count('"') >= 2 and "=" in body):
        inner = indent + "    "
        m = re.match(r"^(\s*\S+\s*=\s*)?f?(.*)$", body)
        if m:
            prefix = m.group(1) or ""
            rest = m.group(2).strip()
            if rest.startswith('"') and rest.endswith('"'):
                text = rest[1:-1]
                words = text.split()
                chunks: list[str] = []
                current = ""
                for word in words:
                    candidate = f"{current} {word}".strip()
                    if len(inner) + len(f'f"{candidate}"') > MAX_LEN and current:
                        chunks.append(current)
                        current = word
                    else:
                        current = candidate
                if current:
                    chunks.append(current)
                if len(chunks) > 1:
                    out = [f"{indent}{prefix}(" if prefix else f"{indent}("]
                    for chunk in chunks:
                        out.append(f'{inner}f"{chunk}"')
                    out.append(f"{indent})")
                    if all(len(row) <= MAX_LEN for row in out):
                        return out
    return [line]


def fix_file(path: Path, rows: set[int]) -> bool:
    lines = path.read_text().splitlines()
    changed = False
    offset = 0
    for row in sorted(rows):
        idx = row - 1 + offset
        if idx < 0 or idx >= len(lines):
            continue
        new_lines = break_long_line(lines[idx])
        if new_lines != [lines[idx]]:
            lines[idx : idx + 1] = new_lines
            offset += len(new_lines) - 1
            changed = True
    if changed:
        path.write_text("\n".join(lines) + "\n")
    return changed


def collect_e501(paths: list[str]) -> dict[str, set[int]]:
    cmd = ["ruff", "check", *paths, "--select", "E501", "--output-format", "json"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        data = []
    by_file: dict[str, set[int]] = {}
    for item in data:
        filename = item["filename"]
        if filename.startswith(str(ROOT)):
            rel = str(Path(filename).relative_to(ROOT))
        else:
            rel = filename.removeprefix("/app/")
        by_file.setdefault(rel, set()).add(item["location"]["row"])
    return by_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["src", "scripts"])
    args = parser.parse_args()

    by_file = collect_e501(args.paths)
    if not by_file:
        print("No E501 violations found.")
        return 0

    changed_any = False
    for rel, rows in sorted(by_file.items()):
        path = ROOT / rel
        if not path.exists():
            continue
        if fix_file(path, rows):
            print(f"updated {rel}")
            changed_any = True

    if changed_any:
        by_file = collect_e501(args.paths)
        remaining = sum(len(v) for v in by_file.values())
        print(f"remaining E501: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
