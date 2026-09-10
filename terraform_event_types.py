#!/usr/bin/env python3
"""Typed models for Terraform test JSONL events."""

from __future__ import annotations

from typing import Any, TypedDict

JsonObject = dict[str, Any]
JsonList = list[Any]
StatusLookup = dict[str, list[str]]


class TerraformTestSummaryPayload(TypedDict, total=False):
    status: str
    passed: int
    failed: int
    errored: int
    skipped: int


class TerraformTestRunPayload(TypedDict, total=False):
    path: str
    run: str
    progress: str
    status: str


class TerraformTestFilePayload(TypedDict, total=False):
    path: str
    progress: str
    status: str


class DiagnosticRangeStart(TypedDict, total=False):
    line: int


class DiagnosticRange(TypedDict, total=False):
    filename: str
    start: DiagnosticRangeStart


class DiagnosticSnippet(TypedDict, total=False):
    context: str
    code: str


class DiagnosticPayload(TypedDict, total=False):
    summary: str
    detail: str
    address: str
    range: DiagnosticRange
    snippet: DiagnosticSnippet


class TerraformResourceChangeMeta(TypedDict, total=False):
    actions: list[str]
    after: JsonObject
    after_unknown: JsonObject
    after_sensitive: JsonObject


class TerraformResourceChange(TypedDict, total=False):
    address: str
    mode: str
    type: str
    name: str
    change: TerraformResourceChangeMeta


class TerraformOutputChange(TypedDict, total=False):
    after: Any
    after_unknown: Any
    after_sensitive: Any


class TerraformTestPlanPayload(TypedDict, total=False):
    resource_changes: list[TerraformResourceChange]
    output_changes: dict[str, TerraformOutputChange]


class TerraformEvent(TypedDict, total=False):
    type: str
    diagnostic: DiagnosticPayload
    test_file: TerraformTestFilePayload
    test_run: TerraformTestRunPayload
    test_plan: TerraformTestPlanPayload
    test_summary: TerraformTestSummaryPayload

