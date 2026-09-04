#!/usr/bin/env python3
"""Generate an HTML report for Gherkin-style comments.

Reads comment extraction input from stdin and writes an HTML report to
`build/gherkin-report.html` by default.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from event_types import JsonList, JsonObject, OutputChange, ResourceChange, StatusLookup, TerraformEvent

BASE_DIR = Path(__file__).resolve().parent

SCENARIO_STATUSES = {"pass", "fail", "error", "skip"}

KEYWORD_RE = re.compile(r"^(Funktion|Hintergrund|Szenario|Szenariogrundriss|Regel|Beispiele|Gegeben|Wenn|Dann|Und|Aber):(.*)$")
COMMAND_RE = re.compile(r"^(terraform|tofu|bash|sh|zsh|python3?|make|helm|kubectl|git)(\s.*)?$")

MATCH_GHERKIN_RE = re.compile(
    r"^[\s-]*(Funktion|Funktionalitaet|Funktionalitt|Feature|Business Need|Ability|"
    r"Grundlage|Hintergrund|Voraussetzungen|Vorbedingungen|Background|"
    r"Szenario|Scenario|Example|Szenariogrundriss|Szenarien|Scenario Outline|Scenario Template|"
    r"Regel|Rule|Beispiele|Examples|Scenarios|"
    r"Angenommen|Gegeben sei|Gegeben seien|Gegeben|Given|"
    r"Wenn|When|Dann|Then|Und|And|Aber|But):\s*(.+)$"
)

FEATURE_RE = re.compile(r"^[\s-]*(Funktion|Funktionalitaet|Funktionalitt|Feature|Business Need|Ability):\s*(.+)$")
BACKGROUND_RE = re.compile(r"^[\s-]*(Grundlage|Hintergrund|Voraussetzungen|Vorbedingungen|Background):\s*(.+)$")
SCENARIO_RE = re.compile(r"^[\s-]*(Szenario|Scenario|Example):\s*(.+)$")
SCENARIO_OUTLINE_RE = re.compile(r"^[\s-]*(Szenariogrundriss|Szenarien|Scenario Outline|Scenario Template):\s*(.+)$")
RULE_RE = re.compile(r"^[\s-]*(Regel|Rule):\s*(.+)$")
EXAMPLES_RE = re.compile(r"^[\s-]*(Beispiele|Examples|Scenarios):\s*(.+)$")
GIVEN_RE = re.compile(r"^[\s-]*(Angenommen|Gegeben sei|Gegeben seien|Gegeben|Given):\s*(.+)$")
WHEN_RE = re.compile(r"^[\s-]*(Wenn|When):\s*(.+)$")
THEN_RE = re.compile(r"^[\s-]*(Dann|Then):\s*(.+)$")
AND_RE = re.compile(r"^[\s-]*(Und|And):\s*(.+)$")
BUT_RE = re.compile(r"^[\s-]*(Aber|But):\s*(.+)$")

SIMPLE_STEP_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (BACKGROUND_RE, "Hintergrund"),
    (RULE_RE, "Regel"),
    (EXAMPLES_RE, "Beispiele"),
    (GIVEN_RE, "Gegeben"),
    (WHEN_RE, "Wenn"),
    (THEN_RE, "Dann"),
    (AND_RE, "Und"),
    (BUT_RE, "Aber"),
)


@dataclass
class StepLine:
    level: int
    text: str
    is_step: bool


@dataclass
class CaseEntry:
    title: str
    status: str = "doku"
    source_line: str = ""
    scenario_test_name: str = ""
    scenario_status_source: str = ""
    lines: list[StepLine] = field(default_factory=list)


@dataclass
class FileGroup:
    input_path: str
    url: str
    label: str
    cases: list[CaseEntry] = field(default_factory=list)


@dataclass
class RunnerSummary:
    status: str = "nicht-verfuegbar"
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0


@dataclass
class ParseState:
    files: list[FileGroup] = field(default_factory=list)
    pending_file_url: str = ""
    current_file: FileGroup | None = None
    current_case: CaseEntry | None = None
    current_file_scenario_index: int = 0
    global_scenario_index: int = 0
    pending_case_line: str = ""
    pending_scenario_line: str = ""
    pending_scenario_test_name: str = ""
    pending_intro_title: str = ""
    in_gherkin_block: bool = False


def as_object(value: Optional[Any]) -> JsonObject:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def as_list(value: Optional[Any]) -> JsonList:
    if isinstance(value, list):
        return list(value)
    return []


def as_event(value: JsonObject) -> TerraformEvent:
    return cast(TerraformEvent, value)


def as_resource_change(value: JsonObject) -> ResourceChange:
    return cast(ResourceChange, value)


def as_output_change(value: JsonObject) -> OutputChange:
    return cast(OutputChange, value)


def as_str(value: Optional[Any], default: str = "") -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return default


def escape_html(text: str) -> str:
    return html.escape(text, quote=True)


def normalize_status(status: str) -> str:
    return status if status in SCENARIO_STATUSES else "unknown"


def parser_display_name(status_parser: str) -> str:
    if status_parser == "go":
        return "Go Test"
    return "Terraform Test"


def status_chip_markup(status: str) -> str:
    label = "DOKU" if status == "doku" else status.upper()
    return f'<span class="chip status-chip status-{escape_html(status)}">{escape_html(label)}</span>'


def file_issue_chip_markup(label: str, count: int, status: str) -> str:
    if count <= 0:
        return ""
    return f'<span class="chip status-chip status-{escape_html(status)}">{escape_html(label)}: {count}</span>'


def normalize_test_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def resolve_status_values_for_file_with_key(status_lookup: StatusLookup, file_path: str) -> tuple[list[str], str]:
    normalized = normalize_test_path(file_path)

    exact = status_lookup.get(normalized)
    if exact is not None:
        return exact, normalized

    best_key = ""
    for key in status_lookup:
        normalized_key = normalize_test_path(key)
        if normalized.endswith("/" + normalized_key) or normalized_key.endswith("/" + normalized):
            if len(normalized_key) > len(best_key):
                best_key = normalized_key

    if best_key:
        return status_lookup.get(best_key, []), best_key

    return [], ""



def strip_line_anchor(url: str) -> str:
    return url.split("#", 1)[0]


def is_gherkin_step_line(text: str) -> bool:
    return KEYWORD_RE.match(text) is not None


def format_step_markup(text: str) -> str:
    keyword_match = KEYWORD_RE.match(text)
    if keyword_match:
        keyword = escape_html(keyword_match.group(1))
        body = escape_html(keyword_match.group(2).strip())
        return f'<span class="teal-text text-darken-2"><strong>{keyword}:</strong></span> <span>{body}</span>'
    if COMMAND_RE.match(text):
        return f"<code>{escape_html(text)}</code>"
    return escape_html(text)


def wrap_with_indent(level: int, content: str) -> str:
    margin = level * 16
    return f'<div style="margin-left:{margin}px">{content}</div>'


def parse_prefixed_value(raw_line: str, prefix: str) -> Optional[str]:
    if not raw_line.startswith(prefix):
        return None
    value = raw_line[len(prefix) :].strip()
    return value if value else None


def parse_prefixed_line_number(raw_line: str, prefix: str) -> Optional[str]:
    value = parse_prefixed_value(raw_line, prefix)
    return value if value and value.isdigit() else None


def load_json_objects(json_path: Path) -> list[JsonObject]:
    items: list[JsonObject] = []
    if not json_path.exists():
        return items
    for raw in json_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(as_object(value))
    return items


def load_events(json_path: Path) -> list[TerraformEvent]:
    return [as_event(item) for item in load_json_objects(json_path)]


def load_terraform_test_summary(events: list[TerraformEvent]) -> RunnerSummary:
    summary = RunnerSummary()
    for ev in events:
        if as_str(ev.get("type")) == "test_summary":
            payload = as_object(ev.get("test_summary"))
            summary.status = normalize_status(as_str(payload.get("status"), "unknown"))
            summary.passed = int(as_str(payload.get("passed"), "0") or 0)
            summary.failed = int(as_str(payload.get("failed"), "0") or 0)
            summary.errored = int(as_str(payload.get("errored"), "0") or 0)
            summary.skipped = int(as_str(payload.get("skipped"), "0") or 0)
    return summary


def build_status_lookup(events: list[TerraformEvent]) -> StatusLookup:
    statuses: StatusLookup = {}
    for ev in events:
        if as_str(ev.get("type")) != "test_run":
            continue
        test_run = as_object(ev.get("test_run"))
        if as_str(test_run.get("progress")) != "complete":
            continue
        path = normalize_test_path(as_str(test_run.get("path")))
        status = normalize_status(as_str(test_run.get("status"), "unknown"))
        statuses.setdefault(path, []).append(status)
    return statuses


def load_go_events(json_path: Path) -> list[JsonObject]:
    return load_json_objects(json_path)


def load_go_test_summary(events: list[JsonObject]) -> RunnerSummary:
    summary = RunnerSummary()
    for ev in events:
        action = as_str(ev.get("Action"))
        if as_str(ev.get("Test")):
            if action == "pass":
                summary.passed += 1
            elif action == "fail":
                summary.failed += 1
            elif action == "skip":
                summary.skipped += 1
        elif action == "fail":
            summary.errored += 1

    if summary.failed > 0:
        summary.status = "fail"
    elif summary.errored > 0:
        summary.status = "error"
    elif summary.passed > 0 or summary.skipped > 0:
        summary.status = "pass"
    else:
        summary.status = "nicht-verfuegbar"
    return summary


def build_go_status_lookup(events: list[JsonObject]) -> StatusLookup:
    global_statuses: list[str] = []
    by_test_name: dict[str, list[str]] = {}
    for ev in events:
        action = as_str(ev.get("Action"))
        if action not in {"pass", "fail", "skip"}:
            continue
        test_name = as_str(ev.get("Test"))
        if not test_name:
            continue
        normalized = normalize_status(action)
        global_statuses.append(normalized)
        by_test_name.setdefault(test_name, []).append(normalized)

    lookup: StatusLookup = {}
    if global_statuses:
        lookup["__global__"] = global_statuses
    for test_name, statuses in by_test_name.items():
        lookup[f"__test__:{test_name}"] = statuses
    return lookup


def next_scenario_status_for_file(
    status_lookup: StatusLookup,
    file_path: str,
    scenario_index: int,
    global_scenario_index: Optional[int] = None,
    scenario_test_name: str = "",
) -> str:
    status, _ = resolve_scenario_status_with_source(
        status_lookup,
        file_path,
        scenario_index,
        global_scenario_index=global_scenario_index,
        scenario_test_name=scenario_test_name,
    )
    return status


def resolve_scenario_status_with_source(
    status_lookup: StatusLookup,
    file_path: str,
    scenario_index: int,
    global_scenario_index: Optional[int] = None,
    scenario_test_name: str = "",
) -> tuple[str, str]:
    if scenario_test_name:
        test_values = status_lookup.get(f"__test__:{scenario_test_name}", [])
        if len(test_values) == 1:
            return test_values[0], f"name:{scenario_test_name}"
        named_idx = (global_scenario_index if global_scenario_index is not None else scenario_index) - 1
        if 0 <= named_idx < len(test_values):
            return test_values[named_idx], f"name:{scenario_test_name}[{named_idx + 1}]"

    values, matched_key = resolve_status_values_for_file_with_key(status_lookup, file_path)
    idx = scenario_index - 1
    if 0 <= idx < len(values):
        source_key = matched_key or normalize_test_path(file_path)
        return values[idx], f"file:{source_key}[{scenario_index}]"

    global_values = status_lookup.get("__global__", [])
    fallback_index = (global_scenario_index if global_scenario_index is not None else scenario_index) - 1
    if 0 <= fallback_index < len(global_values):
        return global_values[fallback_index], f"global[{fallback_index + 1}]"
    return "unknown", "unmapped"


def action_label(actions: list[str]) -> str:
    acts = set(actions or [])
    if acts == {"create"}:
        return "created"
    if acts == {"delete"}:
        return "destroyed"
    if acts == {"update"}:
        return "updated in-place"
    if acts == {"create", "delete"}:
        return "replaced"
    return "changed"


def scalar(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def has_meaningful(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, dict):
        return any(has_meaningful(v) for v in value.values())
    if isinstance(value, list):
        return any(has_meaningful(v) for v in value)
    return False


def format_value(value: Any, indent: int) -> list[str]:
    if isinstance(value, dict):
        if not value:
            return ["{}"]
        lines = ["{"]
        for key in sorted(value):
            rendered = format_value(value[key], indent + 4)
            if len(rendered) == 1:
                lines.append(" " * (indent + 2) + f'+ "{key}" = {rendered[0]}')
            else:
                lines.append(" " * (indent + 2) + f'+ "{key}" = {rendered[0]}')
                lines.extend(" " * (indent + 2) + s for s in rendered[1:-1])
                lines.append(" " * (indent + 2) + rendered[-1])
        lines.append(" " * indent + "}")
        return lines
    if isinstance(value, list):
        if not value:
            return ["[]"]
        lines = ["["]
        for item in value:
            rendered = format_value(item, indent + 4)
            if len(rendered) == 1:
                lines.append(" " * (indent + 2) + f"+ {rendered[0]},")
            else:
                lines.append(" " * (indent + 2) + f"+ {rendered[0]}")
                lines.extend(" " * (indent + 2) + s for s in rendered[1:-1])
                lines.append(" " * (indent + 2) + rendered[-1] + ",")
        lines.append(" " * indent + "]")
        return lines
    return [scalar(value)]


def format_attr_line(key: str, value_lines: list[str]) -> list[str]:
    if len(value_lines) == 1:
        return [f"      + {key} = {value_lines[0]}"]
    return [f"      + {key} = {value_lines[0]}", *value_lines[1:]]


def render_resource_change(rc: ResourceChange) -> list[str]:
    out: list[str] = []
    change = as_object(rc.get("change"))
    after = as_object(change.get("after"))
    after_unknown = as_object(change.get("after_unknown"))
    after_sensitive = as_object(change.get("after_sensitive"))

    key_candidates = set(after.keys()) | set(after_unknown.keys()) | set(after_sensitive.keys())
    keys = [k for k in key_candidates if not k.endswith("_wo_version")]

    action_values = [as_str(v) for v in as_list(change.get("actions")) if as_str(v)]
    out.append(f'  # {as_str(rc.get("address"), "resource")} will be {action_label(action_values)}')
    mode = as_str(rc.get("mode"), "managed")
    kind = "data" if mode == "data" else "resource"
    out.append(f'  + {kind} "{as_str(rc.get("type"), "unknown")}" "{as_str(rc.get("name"), "unknown")}" {{')

    for key in sorted(keys):
        direct_value = after.get(key)
        marker_sensitive = after_sensitive.get(key)
        marker_unknown = after_unknown.get(key)
        is_sensitive = marker_sensitive is True
        is_unknown = marker_unknown is True

        if key.endswith("_wo") and direct_value is None and not is_sensitive and not is_unknown:
            out.append(f"      + {key} = (write-only attribute)")
            continue

        if marker_unknown is True and isinstance(marker_sensitive, (dict, list)) and key not in after:
            out.append(f"      + {key} (known after apply)")
            continue

        if is_sensitive:
            out.append(f"      + {key} = (sensitive value)")
            continue

        if direct_value is None and is_unknown:
            out.append(f"      + {key} = (known after apply)")
            continue

        if direct_value is None:
            continue

        out.extend(format_attr_line(key, format_value(direct_value, 6)))

    out.append("    }")
    out.append("")
    return out


def count_actions(resource_changes: list[ResourceChange]) -> tuple[int, int, int]:
    add = update_count = destroy = 0
    for rc in resource_changes:
        change_obj = as_object(rc.get("change"))
        acts = {as_str(v) for v in as_list(change_obj.get("actions")) if as_str(v)}
        if "create" in acts:
            add += 1
        if "update" in acts:
            update_count += 1
        if "delete" in acts:
            destroy += 1
    return add, update_count, destroy


def render_output_change(name: str, change: OutputChange) -> list[str]:
    after = change.get("after")
    after_unknown = change.get("after_unknown")
    after_sensitive = change.get("after_sensitive")

    if after_sensitive is True:
        return [f"  + {name} = (sensitive value)"]

    if isinstance(after_unknown, dict) and after == {} and after_unknown:
        lines = [f"  + {name} = {{"]
        for key in sorted(after_unknown):
            lines.append(f"      + {key} = (known after apply)")
        lines.append("    }")
        return lines

    if after is None and has_meaningful(after_unknown):
        return [f"  + {name} = (known after apply)"]

    rendered = format_value(after, 4)
    if len(rendered) == 1:
        return [f"  + {name} = {rendered[0]}"]
    return [f"  + {name} = {rendered[0]}", *rendered[1:]]


def progress_label(progress: str, status: str) -> str:
    if progress == "starting":
        return "in progress"
    if progress == "teardown":
        return "tearing down"
    if progress == "complete":
        return status or "complete"
    return progress or status or "unknown"


def reconstruct_terraform_output(events: list[TerraformEvent]) -> str:
    out: list[str] = ["$ terraform test -verbose -no-color", ""]

    for ev in events:
        et = as_str(ev.get("type"))

        if et == "diagnostic":
            diag = as_object(ev.get("diagnostic"))
            summary = as_str(diag.get("summary"), "Diagnostic")
            out.append(f"Warning: {summary}")
            out.append("")

            address = as_str(diag.get("address"))
            if address:
                out.append(f"  with {address},")

            r = as_object(diag.get("range"))
            filename = as_str(r.get("filename"))
            line = as_str(as_object(r.get("start")).get("line"), "0")
            snippet = as_object(diag.get("snippet"))
            context = as_str(snippet.get("context"), "resource")
            code = as_str(snippet.get("code"), "")
            if filename:
                out.append(f"  on {filename} line {line or 0}, in {context}:")
                out.append(f"  {line or 0}: {code}")
                out.append("")

            detail = as_str(diag.get("detail"), "")
            if detail:
                out.extend(detail.splitlines())
                out.append("")
            continue

        if et == "test_file":
            tf = as_object(ev.get("test_file"))
            path = as_str(tf.get("path"), "tests")
            out.append(f"{path}... {progress_label(as_str(tf.get('progress')), as_str(tf.get('status')))}")
            continue

        if et == "test_run":
            tr = as_object(ev.get("test_run"))
            run_name = as_str(tr.get("run"), "run")
            out.append(f'  run "{run_name}"... {progress_label(as_str(tr.get("progress")), as_str(tr.get("status")))}')
            continue

        if et == "test_plan":
            plan = as_object(ev.get("test_plan"))
            resource_changes = [as_resource_change(as_object(v)) for v in as_list(plan.get("resource_changes")) if isinstance(v, dict)]
            out.append("")
            out.append("Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the following")
            out.append("symbols:")

            action_symbols: list[str] = []
            if any("create" in {as_str(v) for v in as_list(as_object(rc.get("change")).get("actions")) if as_str(v)} for rc in resource_changes):
                action_symbols.append("  + create")
            if any("update" in {as_str(v) for v in as_list(as_object(rc.get("change")).get("actions")) if as_str(v)} for rc in resource_changes):
                action_symbols.append("  ~ update in-place")
            if any("delete" in {as_str(v) for v in as_list(as_object(rc.get("change")).get("actions")) if as_str(v)} for rc in resource_changes):
                action_symbols.append("  - destroy")
            if any({as_str(v) for v in as_list(as_object(rc.get("change")).get("actions")) if as_str(v)} == {"create", "delete"} for rc in resource_changes):
                action_symbols.append("  +/- replace")
            if not action_symbols:
                action_symbols.append("  (no changes)")
            out.extend(action_symbols)
            out.append("")

            out.append("Terraform will perform the following actions:")
            out.append("")
            for rc in resource_changes:
                out.extend(render_resource_change(rc))

            add, chg, dst = count_actions(resource_changes)
            out.append(f"Plan: {add} to add, {chg} to change, {dst} to destroy.")
            out.append("")

            output_changes = as_object(plan.get("output_changes"))
            if output_changes:
                out.append("Changes to Outputs:")
                for name in sorted(output_changes):
                    payload = as_output_change(as_object(output_changes[name]))
                    out.extend(render_output_change(name, payload))
                out.append("")
            continue

        if et in {"version", "test_abstract"}:
            continue

        msg = as_str(ev.get("@message"))
        if msg:
            out.append(msg)
            out.append("")

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def reconstruct_go_output(events: list[JsonObject]) -> str:
    out: list[str] = ["$ go test -json ./...", ""]

    for ev in events:
        action = as_str(ev.get("Action"))
        package = as_str(ev.get("Package"), "")
        test_name = as_str(ev.get("Test"), "")
        output = as_str(ev.get("Output"), "").rstrip("\n")

        if output:
            out.append(output)
            continue

        if action in {"run", "pause", "cont", "pass", "fail", "skip"}:
            subject = test_name or package or "go test"
            if action == "run":
                out.append(f"=== RUN   {subject}")
            elif action == "pass":
                out.append(f"--- PASS: {subject}")
            elif action == "fail":
                out.append(f"--- FAIL: {subject}")
            elif action == "skip":
                out.append(f"--- SKIP: {subject}")
            elif action == "pause":
                out.append(f"=== PAUSE {subject}")
            elif action == "cont":
                out.append(f"=== CONT  {subject}")
            continue

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def start_file_group(state: ParseState, file_path: str, file_url: str) -> None:
    state.current_file = FileGroup(
        input_path=normalize_test_path(file_path),
        url=file_url,
        label=file_path,
    )
    state.files.append(state.current_file)
    state.current_case = None
    state.pending_intro_title = ""
    state.current_file_scenario_index = 0


def ensure_file_group(state: ParseState) -> None:
    if state.current_file is None:
        start_file_group(state, "Eingang ohne Dateikopf", "")


def start_case(
    state: ParseState,
    title: str,
    status: str = "doku",
    scenario_test_name: str = "",
    scenario_status_source: str = "",
) -> None:
    ensure_file_group(state)
    assert state.current_file is not None
    case = CaseEntry(
        title=title,
        status=status,
        source_line=state.pending_case_line,
        scenario_test_name=scenario_test_name,
        scenario_status_source=scenario_status_source,
    )
    state.current_file.cases.append(case)
    state.current_case = case
    state.pending_case_line = ""
    state.pending_scenario_line = ""
    state.pending_scenario_test_name = ""
    state.pending_intro_title = ""


def ensure_case(state: ParseState) -> None:
    if state.current_case is None:
        start_case(state, state.pending_intro_title or "Einleitung", "doku")


def begin_scenario_case(
    state: ParseState,
    status_lookup: StatusLookup,
    title: str,
    canonical_keyword: str,
    leading_spaces: str,
) -> None:
    ensure_file_group(state)
    state.current_file_scenario_index += 1
    state.global_scenario_index += 1
    status, status_source = resolve_scenario_status_with_source(
        status_lookup,
        state.current_file.input_path if state.current_file else "",
        state.current_file_scenario_index,
        state.global_scenario_index,
        scenario_test_name=state.pending_scenario_test_name,
    )
    start_case(state, title, status, state.pending_scenario_test_name, status_source)
    append_case_line(state, f"{leading_spaces}{canonical_keyword}: {title}")


def append_case_line(state: ParseState, raw_line: str) -> None:
    text = raw_line.rstrip("\n")
    if not text.strip():
        return

    ensure_case(state)
    assert state.current_case is not None

    leading_spaces_match = re.match(r"^ *", text)
    leading_spaces = leading_spaces_match.group(0) if leading_spaces_match else ""
    stripped = text[len(leading_spaces) :]
    level = len(leading_spaces) // 2

    state.current_case.lines.append(StepLine(level=level, text=stripped, is_step=is_gherkin_step_line(stripped)))


def parse_comment_stream(lines: list[str], status_lookup: StatusLookup) -> list[FileGroup]:
    state = ParseState()

    for raw_line in lines:
        raw_line = raw_line.rstrip("\n")

        web_url = parse_prefixed_value(raw_line, "Datei-Web-URL:")
        if web_url:
            state.pending_file_url = web_url
            continue

        legacy_url = parse_prefixed_value(raw_line, "Datei-URL:")
        if legacy_url:
            state.pending_file_url = legacy_url
            continue

        file_name = parse_prefixed_value(raw_line, "Datei:")
        if file_name:
            start_file_group(state, file_name, state.pending_file_url)
            state.pending_file_url = ""
            state.in_gherkin_block = False
            continue

        card_line = parse_prefixed_line_number(raw_line, "Karten-Zeile:")
        if card_line:
            state.pending_case_line = card_line
            continue

        scenario_line = parse_prefixed_line_number(raw_line, "Szenario-Zeile:")
        if scenario_line:
            state.pending_scenario_line = scenario_line
            state.pending_case_line = scenario_line
            continue

        scenario_test_name = parse_prefixed_value(raw_line, "Szenario-Test:")
        if scenario_test_name:
            state.pending_scenario_test_name = scenario_test_name
            continue

        if not raw_line.strip():
            state.in_gherkin_block = False
            continue

        if MATCH_GHERKIN_RE.match(raw_line):
            state.in_gherkin_block = True
        elif not state.in_gherkin_block:
            continue

        leading_spaces_match = re.match(r"^ *", raw_line)
        leading_spaces = leading_spaces_match.group(0) if leading_spaces_match else ""
        trimmed_line = raw_line[len(leading_spaces) :]

        m = FEATURE_RE.match(raw_line)
        if m:
            if state.current_case is None:
                state.pending_intro_title = m.group(2)
            append_case_line(state, f"{leading_spaces}Funktion: {m.group(2)}")
            continue

        m = SCENARIO_RE.match(raw_line)
        if m:
            begin_scenario_case(state, status_lookup, m.group(2), "Szenario", leading_spaces)
            continue

        m = SCENARIO_OUTLINE_RE.match(raw_line)
        if m:
            begin_scenario_case(state, status_lookup, m.group(2), "Szenariogrundriss", leading_spaces)
            continue

        matched_simple_step = False
        for pattern, canonical_keyword in SIMPLE_STEP_RULES:
            m = pattern.match(raw_line)
            if m:
                append_case_line(state, f"{leading_spaces}{canonical_keyword}: {m.group(2)}")
                matched_simple_step = True
                break
        if matched_simple_step:
            continue

        append_case_line(state, f"{leading_spaces}{trimmed_line}")

    return state.files


def render_case(case: CaseEntry, file_url: str, debug_scenario_mapping: bool = False) -> str:
    source_html = ""
    if case.source_line and file_url:
        source_url = f"{strip_line_anchor(file_url)}#L{case.source_line}"
        source_html = (
            '<div class="right-align" style="display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap;">'
            f'<span class="chip">Zeile {escape_html(case.source_line)}</span>'
            f'<a class="btn-small waves-effect waves-light teal" href="{escape_html(source_url)}" target="_blank" rel="noopener noreferrer">'
            '<i class="material-icons left">open_in_new</i>Zur Quelle</a></div>'
        )

    lines_html: list[str] = []
    current_step_open = False

    for line in case.lines:
        markup = format_step_markup(line.text)
        wrapped = wrap_with_indent(line.level, f"<p>{markup}</p>")

        if line.is_step:
            if current_step_open:
                lines_html.append("                    </div></li>")
            lines_html.append(f"                    <li class=\"collection-item\"><div>{wrapped}")
            current_step_open = True
        elif current_step_open:
            lines_html.append(wrapped)
        else:
            lines_html.append(f"                    <li class=\"collection-item\"><div>{wrapped}</div></li>")

    if current_step_open:
        lines_html.append("                    </div></li>")

    if not lines_html:
        lines_html.append('                    <li class="collection-item"><div><p>Keine Inhalte.</p></div></li>')

    debug_mapping_html = ""
    if debug_scenario_mapping:
        debug_chips: list[str] = []
        if case.scenario_test_name:
            debug_chips.append(f'<span class="chip debug-mapping-chip">Mapped Test: {escape_html(case.scenario_test_name)}</span>')
        show_status_source = bool(case.scenario_status_source)
        if case.scenario_test_name and case.scenario_status_source.startswith("name:"):
            # Name-based source duplicates the dedicated test-name chip.
            show_status_source = False
        if show_status_source:
            debug_chips.append(f'<span class="chip debug-mapping-source-chip">Status Source: {escape_html(case.scenario_status_source)}</span>')
        if debug_chips:
            debug_mapping_html = (
                '<div class="right-align" style="margin-top:6px;display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap;">'
                + "".join(debug_chips)
                + "</div>"
            )

    return "\n".join(
        [
            '        <div class="card hoverable z-depth-1">',
            '            <div class="card-content">',
            '                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">'
            f'<span class="card-title">{escape_html(case.title)}</span>{status_chip_markup(case.status)}</div>',
            f"                {source_html}" if source_html else "",
            f"                {debug_mapping_html}" if debug_mapping_html else "",
            '                <ul class="collection z-depth-0">',
            *lines_html,
            '                </ul>',
            '            </div>',
            '        </div>',
        ]
    )


def render_file_group(group: FileGroup, debug_scenario_mapping: bool = False) -> tuple[str, int, int, int, int]:
    failed = sum(1 for c in group.cases if c.status == "fail")
    errored = sum(1 for c in group.cases if c.status == "error")
    skipped = sum(1 for c in group.cases if c.status == "skip")

    body = "\n".join(render_case(case, group.url, debug_scenario_mapping=debug_scenario_mapping) for case in group.cases)
    if not body:
        body = '        <div class="card-panel amber lighten-5">Keine kommentarbasierten Gherkin-Schnipsel gefunden.</div>'

    chips = "".join(
        [
            file_issue_chip_markup("FAIL", failed, "fail"),
            file_issue_chip_markup("ERROR", errored, "error"),
            file_issue_chip_markup("SKIP", skipped, "skip"),
        ]
    )

    header_chips = f'<span class="file-issue-chips">{chips}</span>' if chips else ""

    section = "\n".join(
        [
            "        <li>",
            '            <div class="collapsible-header">',
            '                <i class="material-icons teal-text text-darken-2">description</i>',
            f'                <span class="truncate">{escape_html(group.label)}</span>',
            f"                {header_chips}" if header_chips else "",
            f'                <span class="new badge teal lighten-1" data-badge-caption="Szenarien">{len(group.cases)}</span>',
            "            </div>",
            '            <div class="collapsible-body white">',
            '                <div class="section">',
            body,
            "                </div>",
            "            </div>",
            "        </li>",
        ]
    )
    return section, len(group.cases), failed, errored, skipped


def build_runner_output_markup(output_text: str, json_path_exists: bool, status_parser: str, event_count: int) -> str:
    if not json_path_exists:
        return '                        <div class="card-panel amber lighten-5">Keine Status-/Output-Datei gefunden.</div>'

    output_text = output_text.strip()
    if not output_text:
        return '                        <div class="card-panel amber lighten-5">Status-/Output-Datei ist leer oder unlesbar.</div>'

    output_summary = f"{parser_display_name(status_parser)} Output (rekonstruiert, {event_count} Events)"
    output_html = escape_html(output_text)
    return "\n".join(
        [
            '                        <details class="runner-output-entry">',
            f"                            <summary>{escape_html(output_summary)}</summary>",
            f'                            <pre><code class="language-shell">{output_html}</code></pre>',
            "                        </details>",
        ]
    )


def render_html_report(
    files: list[FileGroup],
    summary: RunnerSummary,
    runner_output_html: str,
    status_parser: str,
    debug_scenario_mapping: bool = False,
) -> str:
    total_file_count = len(files)
    total_scenario_count = sum(len(group.cases) for group in files)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    report_entries: list[str] = []
    for group in files:
        section, _, _, _, _ = render_file_group(group, debug_scenario_mapping=debug_scenario_mapping)
        report_entries.append(section)

    report_data = "\n".join(report_entries)

    return f"""<!DOCTYPE html>
<html lang=\"de\">
<head>
    <meta charset=\"UTF-8\">
    <meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <meta name=\"color-scheme\" content=\"light dark\">
    <title>Gherkin Test Report</title>
    <script>
        (function () {{
            var storageKey = 'gherkin-report-theme';
            var storedTheme = null;
            try {{
                storedTheme = window.localStorage.getItem(storageKey);
            }} catch (e) {{
                storedTheme = null;
            }}
            var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
            var useDarkMode = storedTheme ? storedTheme === 'dark' : prefersDark;
            document.documentElement.classList.toggle('dark-mode', useDarkMode);
        }})();
    </script>
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
    <link href=\"https://fonts.googleapis.com/icon?family=Material+Icons\" rel=\"stylesheet\">
    <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/css/materialize.min.css\">
    <style>
        html {{ color-scheme: light; }}
        body {{ background-color: #ffffff; color: #212121; transition: none; }}
        .dark-mode {{ color-scheme: dark; }}
        .theme-ready body {{ transition: background-color 0.2s ease, color 0.2s ease; }}
        .dark-mode body {{ background-color: #121212; color: #e0e0e0; }}
        .dark-mode .card, .dark-mode .card-panel, .dark-mode .collapsible-header, .dark-mode .collapsible-body, .dark-mode .collection-item, .dark-mode .chip {{
            background-color: #1e1e1e !important; color: #e0e0e0 !important; border-color: #424242 !important;
        }}
        .dark-mode .grey-text.text-darken-1 {{ color: #bdbdbd !important; }}
        .status-chip {{ color: #ffffff !important; font-weight: 600; }}
        .status-pass {{ background-color: #2e7d32 !important; }}
        .status-fail {{ background-color: #c62828 !important; }}
        .status-error {{ background-color: #ef6c00 !important; }}
        .status-skip {{ background-color: #546e7a !important; }}
        .status-doku {{ background-color: #1565c0 !important; }}
        .status-unknown {{ background-color: #616161 !important; }}
        .collapsible-header {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .collapsible-header .material-icons {{ margin-right: 0; }}
        .collapsible-header .truncate {{ flex: 1 1 260px; min-width: 0; }}
        .collapsible-header .new.badge {{ float: none; margin-left: auto; }}
        .file-issue-chips {{ display: inline-flex; align-items: center; gap: 6px; margin-left: 0; flex-wrap: wrap; max-width: 100%; }}
        .dark-mode .status-chip {{ border: 1px solid #616161 !important; }}
        .floating-controls {{ position: fixed; right: 24px; bottom: 24px; z-index: 1000; display: flex; flex-direction: column; gap: 12px; align-items: flex-end; }}
        .theme-switch-panel {{ background: rgba(255, 255, 255, 0.95); border-radius: 999px; padding: 6px 12px; }}
        .dark-mode .theme-switch-panel {{ background: rgba(30, 30, 30, 0.95); }}
        .runner-output-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-bottom: 8px; flex-wrap: wrap; }}
        .runner-output-entry {{ margin-bottom: 8px; border: 1px solid #e0e0e0; border-radius: 6px; padding: 6px 10px; background: #fafafa; }}
        .runner-output-entry summary {{ cursor: pointer; font-weight: 600; }}
        .runner-output-entry pre {{ margin-top: 8px; background: #263238; color: #eceff1; padding: 10px; border-radius: 4px; overflow-x: auto; white-space: pre; }}
        .runner-output-entry code {{ font-family: Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 0.9rem; }}
        .dark-mode .runner-output-entry {{ background: #1f1f1f; border-color: #555; }}
        .dark-mode .runner-output-entry pre {{ background: #111; }}
        .debug-mapping-chip {{ background-color: #5d4037 !important; color: #ffffff !important; }}
        .debug-mapping-source-chip {{ background-color: #37474f !important; color: #ffffff !important; }}
    </style>
</head>
<body>
    <main class=\"container section\">
        <section class=\"section center-align\">
            <h3>Gherkin Test Report</h3>
            <p class=\"flow-text grey-text text-darken-1\">Szenarien aus Gherkin-Kommentaren mit optionalem Testergebnis-Status, gruppiert nach Datei.</p>
        </section>
        <section class=\"section\">
            <div class=\"row\">
                <div class=\"col s12 m4\"><div class=\"card-panel z-depth-1\"><span class=\"grey-text text-darken-1\">Dateien</span><h5>{total_file_count}</h5></div></div>
                <div class=\"col s12 m4\"><div class=\"card-panel z-depth-1\"><span class=\"grey-text text-darken-1\">Szenarien</span><h5>{total_scenario_count}</h5></div></div>
                <div class=\"col s12 m4\"><div class=\"card-panel z-depth-1\"><span class=\"grey-text text-darken-1\">Erstellt (UTC)</span><h6>{escape_html(generated_at)}</h6></div></div>
            </div>
            <div class=\"row\"><div class=\"col s12\"><div class=\"card-panel z-depth-1\"><span class=\"grey-text text-darken-1\">Teststatus ({escape_html(parser_display_name(status_parser))})</span><h6>Gesamtstatus: {escape_html(summary.status)}</h6><p>Passed: {summary.passed} · Failed: {summary.failed} · Errored: {summary.errored} · Skipped: {summary.skipped}</p></div></div></div>
            <div class=\"row\"><div class=\"col s12\"><div class=\"card-panel z-depth-1\"><div style=\"display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;\"><span class=\"grey-text text-darken-1\">Runner Output</span><div class=\"runner-output-actions\"><a id=\"expand-runner-output\" class=\"btn-small waves-effect waves-light blue-grey\">Expand</a><a id=\"collapse-runner-output\" class=\"btn-small waves-effect waves-light blue-grey\">Collapse</a></div></div><div id=\"runner-output-list\">{runner_output_html}</div></div></div></div>
        </section>
        <ul class=\"collapsible popout z-depth-0\">{report_data}</ul>
    </main>
    <div class=\"floating-controls\">
        <div class=\"fixed-action-btn\" style=\"position: static; margin: 0;\"><a id=\"expand-all-btn\" class=\"btn-floating btn-large teal\" title=\"Alle aufklappen\" aria-label=\"Alle aufklappen\"><i class=\"large material-icons\">unfold_more</i></a></div>
        <div class=\"fixed-action-btn\" style=\"position: static; margin: 0;\"><a id=\"collapse-all-btn\" class=\"btn-floating btn-large teal\" title=\"Alle einklappen\" aria-label=\"Alle einklappen\"><i class=\"large material-icons\">unfold_less</i></a></div>
        <div class=\"theme-switch-panel z-depth-2\"><div class=\"switch\"><label>Hell<input id=\"dark-mode-toggle\" type=\"checkbox\"><span class=\"lever\"></span>Dunkel</label></div></div>
    </div>
    <script src=\"https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/js/materialize.min.js\"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function () {{
            var collapsibles = document.querySelectorAll('.collapsible');
            M.Collapsible.init(collapsibles, {{ accordion: false }});
            var collapsible = collapsibles.length > 0 ? M.Collapsible.getInstance(collapsibles[0]) : null;
            var expandAllBtn = document.getElementById('expand-all-btn');
            var collapseAllBtn = document.getElementById('collapse-all-btn');
            var runnerOutputList = document.getElementById('runner-output-list');
            var expandRunnerOutputBtn = document.getElementById('expand-runner-output');
            var collapseRunnerOutputBtn = document.getElementById('collapse-runner-output');

            function forEachItem(callback) {{
                if (!collapsible) return;
                var items = collapsibles[0].querySelectorAll(':scope > li');
                items.forEach(function (_, index) {{ callback(index); }});
            }}

            if (expandAllBtn) expandAllBtn.addEventListener('click', function (event) {{ event.preventDefault(); forEachItem(function (index) {{ collapsible.open(index); }}); }});
            if (collapseAllBtn) collapseAllBtn.addEventListener('click', function (event) {{ event.preventDefault(); forEachItem(function (index) {{ collapsible.close(index); }}); forEachRunnerOutputEntry(function (entry) {{ entry.open = false; }}); }});

            function forEachRunnerOutputEntry(callback) {{
                if (!runnerOutputList) return;
                var entries = runnerOutputList.querySelectorAll('details.runner-output-entry');
                entries.forEach(function (entry) {{ callback(entry); }});
            }}

            if (expandRunnerOutputBtn) expandRunnerOutputBtn.addEventListener('click', function (event) {{ event.preventDefault(); forEachRunnerOutputEntry(function (entry) {{ entry.open = true; }}); }});
            if (collapseRunnerOutputBtn) collapseRunnerOutputBtn.addEventListener('click', function (event) {{ event.preventDefault(); forEachRunnerOutputEntry(function (entry) {{ entry.open = false; }}); }});

            var toggle = document.getElementById('dark-mode-toggle');
            var storageKey = 'gherkin-report-theme';
            var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
            var storedTheme = null;
            try {{ storedTheme = window.localStorage.getItem(storageKey); }} catch (e) {{ storedTheme = null; }}

            function applyTheme(isDark) {{
                document.documentElement.classList.toggle('dark-mode', isDark);
                if (toggle) toggle.checked = isDark;
            }}

            var useDarkMode = storedTheme ? storedTheme === 'dark' : prefersDark;
            applyTheme(useDarkMode);

            if (toggle) {{
                toggle.addEventListener('change', function () {{
                    var isDark = toggle.checked;
                    applyTheme(isDark);
                    try {{ window.localStorage.setItem(storageKey, isDark ? 'dark' : 'light'); }} catch (e) {{}}
                }});
            }}

            document.documentElement.classList.add('theme-ready');
        }});
    </script>
</body>
</html>
"""


def keyword_and_text_from_line(text: str) -> tuple[str, str]:
    match = KEYWORD_RE.match(text)
    if match:
        return match.group(1), match.group(2).strip()
    return "", text.strip()


def to_cucumber_status(status: str) -> str:
    if status == "pass":
        return "passed"
    if status in {"fail", "error"}:
        return "failed"
    return "skipped"


def to_junit_kind(status: str) -> str:
    if status == "pass":
        return "pass"
    if status in {"fail", "error"}:
        return "fail"
    return "skip"


def infer_feature_name(group: FileGroup) -> str:
    for case in group.cases:
        for line in case.lines:
            keyword, body = keyword_and_text_from_line(line.text)
            if keyword == "Funktion" and body:
                return body
    return Path(group.input_path).stem


def find_scenario_line_number(case: CaseEntry) -> int:
    if case.source_line.isdigit():
        return int(case.source_line)
    return 1


def build_internal_report_payload(
    files: list[FileGroup],
    summary: RunnerSummary,
    status_parser: str,
    output_text: str,
    debug_scenario_mapping: bool,
) -> JsonObject:
    payload_files: list[JsonObject] = []
    for group in files:
        payload_cases: list[JsonObject] = []
        for case in group.cases:
            payload_steps: list[JsonObject] = []
            for line in case.lines:
                keyword, body = keyword_and_text_from_line(line.text)
                payload_steps.append(
                    {
                        "level": line.level,
                        "text": line.text,
                        "is_step": line.is_step,
                        "keyword": keyword,
                        "body": body,
                    }
                )
            payload_case: JsonObject = {
                "title": case.title,
                "status": case.status,
                "source_line": case.source_line,
                "scenario_test_name": case.scenario_test_name,
                "scenario_status_source": case.scenario_status_source,
                "steps": payload_steps,
            }
            if debug_scenario_mapping:
                payload_case["debug"] = {
                    "scenario_test_name": case.scenario_test_name,
                    "scenario_status_source": case.scenario_status_source,
                }
            payload_cases.append(payload_case)

        payload_files.append(
            {
                "input_path": group.input_path,
                "label": group.label,
                "url": group.url,
                "cases": payload_cases,
            }
        )

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status_parser": status_parser,
        "summary": {
            "status": summary.status,
            "passed": summary.passed,
            "failed": summary.failed,
            "errored": summary.errored,
            "skipped": summary.skipped,
        },
        "runner_output": output_text,
        "files": payload_files,
    }


def render_cucumber_json(files: list[FileGroup]) -> list[JsonObject]:
    feature_documents: list[JsonObject] = []
    for group in files:
        elements: list[JsonObject] = []
        for idx, case in enumerate(group.cases, start=1):
            steps: list[JsonObject] = []
            for line in case.lines:
                if not line.is_step:
                    continue
                keyword, body = keyword_and_text_from_line(line.text)
                if not keyword:
                    continue
                steps.append(
                    {
                        "keyword": f"{keyword}: ",
                        "name": body,
                        "line": find_scenario_line_number(case),
                        "result": {
                            "status": to_cucumber_status(case.status),
                            "duration": 0,
                        },
                    }
                )

            if not steps:
                steps.append(
                    {
                        "keyword": "Dann: ",
                        "name": "Dokumentationsszenario ohne ausführbare Steps",
                        "line": find_scenario_line_number(case),
                        "result": {
                            "status": to_cucumber_status(case.status),
                            "duration": 0,
                        },
                    }
                )

            elements.append(
                {
                    "id": f"{Path(group.input_path).stem};{idx}",
                    "keyword": "Scenario",
                    "name": case.title,
                    "line": find_scenario_line_number(case),
                    "type": "scenario",
                    "steps": steps,
                }
            )

        feature_documents.append(
            {
                "uri": group.input_path,
                "id": Path(group.input_path).stem,
                "keyword": "Feature",
                "name": infer_feature_name(group),
                "line": 1,
                "elements": elements,
            }
        )
    return feature_documents


def render_junit_xml(files: list[FileGroup], status_parser: str, output_text: str) -> str:
    suites_el = ET.Element("testsuites")
    total_tests = total_failures = total_errors = total_skipped = 0

    for group in files:
        suite_tests = len(group.cases)
        suite_failures = sum(1 for c in group.cases if c.status == "fail")
        suite_errors = sum(1 for c in group.cases if c.status == "error")
        suite_skipped = sum(1 for c in group.cases if c.status in {"skip", "doku", "unknown"})

        total_tests += suite_tests
        total_failures += suite_failures
        total_errors += suite_errors
        total_skipped += suite_skipped

        suite_el = ET.SubElement(
            suites_el,
            "testsuite",
            {
                "name": group.input_path,
                "tests": str(suite_tests),
                "failures": str(suite_failures),
                "errors": str(suite_errors),
                "skipped": str(suite_skipped),
                "time": "0",
            },
        )

        for case in group.cases:
            testcase_el = ET.SubElement(
                suite_el,
                "testcase",
                {
                    "classname": group.input_path,
                    "name": case.title,
                    "time": "0",
                },
            )
            junit_kind = to_junit_kind(case.status)
            if junit_kind == "fail":
                tag = "error" if case.status == "error" else "failure"
                issue = ET.SubElement(testcase_el, tag, {"message": f"Scenario status: {case.status}"})
                issue.text = f"{case.title} ({case.scenario_status_source or 'unmapped'})"
            elif junit_kind == "skip":
                skipped = ET.SubElement(testcase_el, "skipped")
                skipped.text = f"Scenario status: {case.status}"

            system_out = ET.SubElement(testcase_el, "system-out")
            rendered_lines = [line.text for line in case.lines]
            if case.scenario_test_name:
                rendered_lines.append(f"Mapped Test: {case.scenario_test_name}")
            if case.scenario_status_source:
                rendered_lines.append(f"Status Source: {case.scenario_status_source}")
            system_out.text = "\n".join(rendered_lines)

        suite_out = ET.SubElement(suite_el, "system-out")
        suite_out.text = f"Parser: {parser_display_name(status_parser)}\n\n{output_text}"

    suites_el.set("tests", str(total_tests))
    suites_el.set("failures", str(total_failures))
    suites_el.set("errors", str(total_errors))
    suites_el.set("skipped", str(total_skipped))
    suites_el.set("time", "0")
    return ET.tostring(suites_el, encoding="unicode")


def resolve_status_json_path(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        return Path(explicit)
    env_value = os.environ.get("GHERKIN_REPORT_STATUS_JSON_PATH")
    if env_value:
        return Path(env_value)
    env_value = os.environ.get("GHERKIN_REPORT_TERRAFORM_JSON_PATH")
    if env_value:
        return Path(env_value)
    default_path = BASE_DIR / "build" / "terraform-test.jsonl"
    return default_path if default_path.exists() else None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Gherkin HTML report from extracted comments.")
    parser.add_argument(
        "--output",
        default=str(BASE_DIR / "build" / "gherkin-report.html"),
        help="Output HTML file path.",
    )
    parser.add_argument(
        "--status-parser",
        choices=["terraform", "go"],
        default="terraform",
        help="Status/output parser to apply.",
    )
    parser.add_argument(
        "--status-json",
        default=None,
        help="Optional parser-specific JSON/JSONL status path.",
    )
    parser.add_argument(
        "--terraform-json",
        default=None,
        help="Deprecated alias for --status-json.",
    )
    parser.add_argument(
        "--debug-scenario-mapping",
        action="store_true",
        help="Show mapping debug chips for scenario-to-test association.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the internal normalized report JSON.",
    )
    parser.add_argument(
        "--output-cucumber-json",
        default=None,
        help="Optional path to write cucumber.json output.",
    )
    parser.add_argument(
        "--output-junit-xml",
        default=None,
        help="Optional path to write JUnit XML output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    status_json = resolve_status_json_path(args.status_json or args.terraform_json)
    terraform_events: list[TerraformEvent] = []
    go_events: list[JsonObject] = []
    summary = RunnerSummary()
    status_lookup: StatusLookup = {}
    output_text = ""
    resolved_status_json: Optional[Path] = status_json if status_json is not None and status_json.exists() else None
    has_status_json = resolved_status_json is not None

    if resolved_status_json is not None:
        if args.status_parser == "go":
            go_events = load_go_events(resolved_status_json)
            summary = load_go_test_summary(go_events)
            status_lookup = build_go_status_lookup(go_events)
            output_text = reconstruct_go_output(go_events)
        else:
            terraform_events = load_events(resolved_status_json)
            summary = load_terraform_test_summary(terraform_events)
            status_lookup = build_status_lookup(terraform_events)
            output_text = reconstruct_terraform_output(terraform_events)

    input_lines = sys.stdin.read().splitlines()
    files = parse_comment_stream(input_lines, status_lookup)
    runner_output_html = build_runner_output_markup(
        output_text,
        has_status_json,
        args.status_parser,
        len(go_events) if args.status_parser == "go" else len(terraform_events),
    )

    html_content = render_html_report(
        files,
        summary,
        runner_output_html,
        args.status_parser,
        debug_scenario_mapping=args.debug_scenario_mapping,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")

    if args.output_json:
        report_json_path = Path(args.output_json)
        report_json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = build_internal_report_payload(
            files,
            summary,
            args.status_parser,
            output_text,
            args.debug_scenario_mapping,
        )
        report_json_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    if args.output_cucumber_json:
        cucumber_path = Path(args.output_cucumber_json)
        cucumber_path.parent.mkdir(parents=True, exist_ok=True)
        cucumber_docs = render_cucumber_json(files)
        cucumber_path.write_text(json.dumps(cucumber_docs, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    if args.output_junit_xml:
        junit_path = Path(args.output_junit_xml)
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        junit_xml = render_junit_xml(files, args.status_parser, output_text)
        junit_path.write_text(junit_xml + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


