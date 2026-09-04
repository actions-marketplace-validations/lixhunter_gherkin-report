#!/usr/bin/env python3
"""Tiny end-to-end smoke test for gherkin report generator."""

from __future__ import annotations

import tempfile
import subprocess
import sys
import json
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent


def run_action(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT_DIR / "action.sh"), *args],
        capture_output=True,
        text=True,
    )


def remove_if_present(path: Optional[Path]) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def main() -> int:
    # Create temporary terraform-like test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tftest.hcl", delete=False) as f:
        f.write("""
# Funktion: Test Smoke Test
#
# Szenario: Basic report generation works
#   Gegeben: A valid Terraform test file
#   Wenn: We extract comments and generate a report
#   Dann: The report should be generated successfully

resource "null_resource" "example" {}
""")
        terraform_test_file = Path(f.name)

    # Create temporary go test file with // comments
    with tempfile.NamedTemporaryFile(mode="w", suffix="_test.go", delete=False) as f:
        f.write("""
package smoketest

// Feature: Go Smoke Test
// Scenario: Basic go parser report generation works
//   Given: A valid Go test file
//   When: We extract comments and generate a report
//   Then: The report should be generated successfully
func TestSmoke(t *testing.T) {}
""")
        go_test_file = Path(f.name)

    # Minimal go test -json style output
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"Action":"run","Package":"smoketest","Test":"TestUnrelated"}\n')
        f.write('{"Action":"pass","Package":"smoketest","Test":"TestUnrelated"}\n')
        f.write('{"Action":"run","Package":"smoketest","Test":"TestSmoke"}\n')
        f.write('{"Action":"fail","Package":"smoketest","Test":"TestSmoke"}\n')
        go_json_file = Path(f.name)

    output_file: Optional[Path] = None
    output_json_file: Optional[Path] = None
    output_cucumber_file: Optional[Path] = None
    output_junit_file: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            output_file = Path(f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_json_file = Path(f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            output_cucumber_file = Path(f.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            output_junit_file = Path(f.name)

        # Run the action
        result = run_action(
            "--output",
            str(output_file),
            "--output-json",
            str(output_json_file),
            "--output-cucumber-json",
            str(output_cucumber_file),
            "--output-junit-xml",
            str(output_junit_file),
            str(terraform_test_file),
        )

        if result.returncode != 0:
            print(f"Error: {result.stderr}", file=sys.stderr)
            return 1

        # Verify output
        if output_file is None or not output_file.exists():
            print(f"Error: Output file not created at {output_file}", file=sys.stderr)
            return 1

        content = output_file.read_text()
        if "Gherkin Test Report" not in content:
            print("Error: HTML report does not contain expected content", file=sys.stderr)
            return 1

        if output_json_file is None or not output_json_file.exists():
            print("Error: normalized JSON report was not created", file=sys.stderr)
            return 1
        normalized_payload = json.loads(output_json_file.read_text())
        if normalized_payload.get("schema_version") != "1.0":
            print("Error: normalized JSON report schema version missing", file=sys.stderr)
            return 1

        if output_cucumber_file is None or not output_cucumber_file.exists():
            print("Error: cucumber JSON report was not created", file=sys.stderr)
            return 1
        cucumber_payload = json.loads(output_cucumber_file.read_text())
        if not isinstance(cucumber_payload, list):
            print("Error: cucumber JSON report has invalid structure", file=sys.stderr)
            return 1

        if output_junit_file is None or not output_junit_file.exists():
            print("Error: JUnit XML report was not created", file=sys.stderr)
            return 1
        junit_content = output_junit_file.read_text()
        if "<testsuites" not in junit_content:
            print("Error: JUnit XML report has invalid structure", file=sys.stderr)
            return 1

        # Run go parser flow with // comments and go JSONL.
        go_result = run_action(
            "--status-parser",
            "go",
            "--debug-scenario-mapping",
            "--status-json",
            str(go_json_file),
            "--output",
            str(output_file),
            str(go_test_file),
        )

        if go_result.returncode != 0:
            print(f"Error: {go_result.stderr}", file=sys.stderr)
            return 1

        go_content = output_file.read_text()
        if "Runner Output" not in go_content:
            print("Error: Go report does not contain runner output section", file=sys.stderr)
            return 1
        if "Go Test" not in go_content:
            print("Error: Go report does not contain parser label", file=sys.stderr)
            return 1
        if "status-fail" not in go_content:
            print("Error: Go scenario was not mapped to failed status", file=sys.stderr)
            return 1
        if "Mapped Test: TestSmoke" not in go_content:
            print("Error: Debug mapping chip missing in Go report", file=sys.stderr)
            return 1

        print(f"✓ Smoke test passed! Report generated at {output_file}")
        return 0

    finally:
        remove_if_present(terraform_test_file)
        remove_if_present(go_test_file)
        remove_if_present(go_json_file)
        remove_if_present(output_file)
        remove_if_present(output_json_file)
        remove_if_present(output_cucumber_file)
        remove_if_present(output_junit_file)


if __name__ == "__main__":
    raise SystemExit(main())

