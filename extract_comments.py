#!/usr/bin/env python3
"""Extract Gherkin-style comments from test and source files."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

FEATURE_RE = re.compile(r"^(Funktion|Funktionalitaet|Funktionalitt|Feature|Business Need|Ability):\s*(.*)$")
SCENARIO_RE = re.compile(r"^(Szenario|Scenario|Example|Szenariogrundriss|Szenarien|Scenario Outline|Scenario Template):\s*(.*)$")
GO_TEST_FUNC_RE = re.compile(r"^\s*func\s+(Test[\w_]+)\s*\(")
COMMENT_RE = re.compile(r"^\s*(?:#|//)\s?(.*)$")


def git_output(cwd: Path, *args: str) -> str:
    try:
        return subprocess.check_output(args, cwd=str(cwd), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def detect_remote_owner_and_base_url(cwd: Path) -> tuple[str, str]:
    remote_url = git_output(cwd, "git", "remote", "get-url", "origin")
    if not remote_url:
        return "", ""

    # SSH form: git@github.com:owner/repo.git
    ssh_match = re.match(r"^git@([^:]+):([^/]+)/(.+?)(?:\.git)?$", remote_url)
    if ssh_match:
        host = ssh_match.group(1)
        owner = ssh_match.group(2)
        return owner, f"https://{host}"

    # HTTPS form: https://github.com/owner/repo(.git)
    https_match = re.match(r"^https?://([^/]+)/([^/]+)/(.+?)(?:\.git)?$", remote_url)
    if https_match:
        host = https_match.group(1)
        owner = https_match.group(2)
        return owner, f"https://{host}"

    return "", ""


def find_next_go_test_name(source_lines: list[str], start_index: int) -> str:
    for candidate in source_lines[start_index:]:
        func_match = GO_TEST_FUNC_RE.match(candidate)
        if func_match:
            return func_match.group(1)
    return ""


def extract_comments(input_file: Path) -> str:
    resolved_path = input_file.resolve()
    repo_root = git_output(resolved_path.parent, "git", "rev-parse", "--show-toplevel")
    branch = os.environ.get("GHERKIN_REPORT_GIT_BRANCH") or git_output(resolved_path.parent, "git", "branch", "--show-current") or "main"

    if repo_root:
        repo_root_path = Path(repo_root)
        repo_name = repo_root_path.name
    else:
        repo_root_path = None
        repo_name = resolved_path.parent.name

    inferred_owner, inferred_base_url = detect_remote_owner_and_base_url(resolved_path.parent)
    org = os.environ.get("GHERKIN_REPORT_GIT_ORG") or inferred_owner or "unknown-owner"
    base_url = (os.environ.get("GHERKIN_REPORT_WEB_BASE_URL") or inferred_base_url or "https://github.com").rstrip("/")

    if repo_root_path:
        try:
            relative_path = resolved_path.relative_to(repo_root_path).as_posix()
        except ValueError:
            relative_path = resolved_path.name
    else:
        relative_path = resolved_path.name

    source_lines = resolved_path.read_text(encoding="utf-8").splitlines()

    comment_lines: list[tuple[int, str]] = []
    for line_number, line in enumerate(source_lines, start=1):
        # Support single-line comments used by HCL/shell (#) and Go/C-like sources (//).
        m = COMMENT_RE.match(line)
        if m:
            comment_lines.append((line_number, m.group(1)))

    first_line = comment_lines[0][0] if comment_lines else 1
    last_line = comment_lines[-1][0] if comment_lines else first_line
    web_url = f"{base_url}/{org}/{repo_name}/src/branch/{branch}/{relative_path}"

    out: list[str] = [
        f"Datei-Web-URL: {web_url}#L{first_line}-L{last_line}",
        f"Datei: {input_file}",
        f"Datei-Zeilen: {first_line}-{last_line}",
    ]

    intro_card_line_emitted = False
    previous_comment_line: Optional[int] = None

    for line_number, comment in comment_lines:
        if previous_comment_line is not None and line_number > previous_comment_line + 1:
            out.append("")
        if not intro_card_line_emitted and FEATURE_RE.match(comment):
            out.append(f"Karten-Zeile: {line_number}")
            intro_card_line_emitted = True
        if SCENARIO_RE.match(comment):
            out.append(f"Karten-Zeile: {line_number}")
            out.append(f"Szenario-Zeile: {line_number}")
            # For Go tests we can map a scenario to the next Test* function.
            next_test_name = find_next_go_test_name(source_lines, line_number)
            if next_test_name:
                out.append(f"Szenario-Test: {next_test_name}")
        out.append(comment)
        previous_comment_line = line_number

    out.append("")
    return "\n".join(out)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Gherkin comments from files.")
    parser.add_argument("input_files", nargs="+", help="Input file path(s)")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    chunks: list[str] = []
    for raw_path in args.input_files:
        path = Path(raw_path)
        if not path.exists():
            print(f"Input file not found: {raw_path}", file=sys.stderr)
            return 1

        chunks.append(extract_comments(path))

    sys.stdout.write("".join(chunks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

