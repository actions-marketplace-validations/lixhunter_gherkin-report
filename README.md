# Gherkin Report Action

Generates an HTML report from Gherkin-style comments in source/test files and optionally integrates parser-specific test status output.
Optionally also emits normalized JSON, Cucumber JSON, and JUnit XML for downstream tooling.

The repository is intentionally set up for dual use: as a GitHub Action via `action.yaml`, and as a local CLI/report tool via `action.sh`.

## Overview

This action extracts Gherkin-style comments (Feature, Scenario, Given/When/Then, etc.) from files and generates a comprehensive HTML report with optional integration of actual test execution results.

Canonical upstream repository: https://github.com/lixhunter/gherkin-report

## Features

- Extracts Gherkin-style comments from `.tftest.hcl`, `*_test.go`, and other files
- Generates a beautiful, responsive HTML report
- Integrates runner results from JSON/JSONL output via explicit parser selection (`terraform` or `go`)
- Emits optional machine-readable outputs (`report.json`, `cucumber.json`, `junit.xml`)
- Optional mapping debug mode shows per-scenario `Test*` association chips
- Dark mode support
- Links to source files in Git repositories
- Supports multilingual keywords (German and English)

## Usage

### As a GitHub Action

```yaml
- name: Generate Gherkin Report
  uses: lixhunter/gherkin-report@v1
  with:
    input-files: ./tests/*.tftest.hcl
    status-parser: terraform
    debug-scenario-mapping: "false"
    output: ./build/gherkin-report.html
    output-json: ./build/gherkin-report.json      # optional
    output-cucumber-json: ./build/cucumber.json   # optional
    output-junit-xml: ./build/junit.xml           # optional
    status-json: ./build/terraform-test.jsonl  # optional
```

### Via `mise`

This repository also exposes a local `mise` task that delegates to `action.sh`, which is the same wrapper used by the composite GitHub Action. That keeps local usage and CI usage aligned.

List the local task:

```bash
mise tasks ls
```

Generate a report from Terraform-style test files:

```bash
mise run gherkin-report -- ./tests/*.tftest.hcl
```

Generate a report with explicit output files and parser-specific status input:

```bash
mise run gherkin-report -- \
  --output ./build/gherkin-report.html \
  --output-json ./build/gherkin-report.json \
  --output-cucumber-json ./build/cucumber.json \
  --output-junit-xml ./build/junit.xml \
  --status-parser terraform \
  --status-json ./build/terraform-test.jsonl \
  ./tests/*.tftest.hcl
```

Run against Go tests instead:

```bash
mise run gherkin-report -- \
  --status-parser go \
  --status-json ./build/go-test.jsonl \
  ./tests/*_test.go
```

Requirements for local `mise` usage are the same as direct script usage: `bash` plus `python3` available on `PATH`.

### Direct Python Script Usage

Extract comments only:

```bash
python3 extract_comments.py ./tests/*.tftest.hcl ./tests/*_test.go
```

Generate report from extracted comments:

```bash
python3 extract_comments.py ./tests/*.tftest.hcl ./tests/*_test.go | \
  python3 generate_gherkin_report.py --status-parser terraform \
    --output-json ./build/gherkin-report.json \
    --output-cucumber-json ./build/cucumber.json \
    --output-junit-xml ./build/junit.xml
```

With Terraform test results:

```bash
terraform test -verbose -json -no-color > ./build/terraform-test.jsonl
GHERKIN_REPORT_STATUS_JSON_PATH=./build/terraform-test.jsonl \
  python3 extract_comments.py ./tests/*.tftest.hcl | \
  python3 generate_gherkin_report.py --status-parser terraform
```

With Go test results:

```bash
go test -json ./... > ./build/go-test.jsonl
GHERKIN_REPORT_STATUS_JSON_PATH=./build/go-test.jsonl \
  python3 extract_comments.py ./tests/*_test.go | \
  python3 generate_gherkin_report.py --status-parser go
```

With mapping debug chips enabled:

```bash
python3 extract_comments.py ./tests/*_test.go | \
  python3 generate_gherkin_report.py --status-parser go --debug-scenario-mapping
```

Note: For Go, scenario status mapping prefers the next `Test*` function after a `Szenario:` comment (for example `// Szenario: ...` followed by `func TestXxx(...)`).
With `--debug-scenario-mapping`, the report also shows the status source per scenario (for example `name:TestXxx`, `file:tests/... [2]`, or `global[3]`).

## Input Files

Input files should contain Gherkin-style comments. Single-line comments with `#` and `//` are supported.

HCL example (`#`):

```hcl
# Funktion: Provision AWS Networking
# 
# Szenario: Create VPC with default configuration
#   Gegeben: A valid AWS provider configuration
#   Wenn: We apply the terraform configuration
#   Dann: The VPC should be created successfully

resource "aws_vpc" "main" {
  # ...
}
```

Go example (`//`):

```go
package api_test

import "testing"

// Feature: API health checks
// Scenario: Health endpoint responds with 200
//   Given: The HTTP server is running
//   When: A GET request is sent to /healthz
//   Then: The response code should be 200
func TestHealthz(t *testing.T) {}
```

## Supported Keywords

### German
- **Funktion/Funktionalitaet/Funktionalitt** - Feature
- **Szenario** - Scenario
- **Szenariogrundriss** - Scenario Outline
- **Regel** - Rule
- **Hintergrund/Grundlage** - Background
- **Gegeben** - Given
- **Wenn** - When
- **Dann** - Then
- **Und** - And
- **Aber** - But
- **Beispiele** - Examples

### English
- **Feature/Business Need/Ability** - Feature
- **Scenario/Example** - Scenario
- **Scenario Outline/Scenario Template** - Scenario Outline
- **Rule** - Rule
- **Background** - Background
- **Given** - Given
- **When** - When
- **Then** - Then
- **And** - And
- **But** - But
- **Examples/Scenarios** - Examples

## Environment Variables

- `GHERKIN_REPORT_GIT_ORG` - Git organization/owner (default: `unknown-owner`)
- `GHERKIN_REPORT_GIT_BRANCH` - Git branch name (auto-detected if not set)
- `GHERKIN_REPORT_WEB_BASE_URL` - Web base URL for Git repository (default: `https://github.com`)
- `GHERKIN_REPORT_STATUS_JSON_PATH` - Path to parser-specific status JSON/JSONL file
- `GHERKIN_REPORT_TERRAFORM_JSON_PATH` - Backward-compatible alias

## Output

The action generates an HTML report at the specified output path with:

- Summary cards (file count, scenario count, generation timestamp)
- Test status summary (passed, failed, errored, skipped)
- Runner output (if JSON/JSONL provided)
- Collapsible file groups with scenarios
- Source code links
- Dark mode toggle
- Expand/collapse all functionality

Optional additional output files:

- Normalized report JSON (internal schema)
- Cucumber JSON (for BDD-compatible tooling)
- JUnit XML (for CI test reporting)

Note: Some Cucumber HTML tools read every `*.json` file in `jsonDir`. Use a dedicated folder for `cucumber.json` (for example `build/cucumber-json/cucumber.json`) so non-Cucumber JSON files are not picked up accidentally.

## Dependencies

- Python 3.7+
- Standard library only (no external dependencies)

## Type Checking

For development with strict type checking:

```bash
pip install -r requirements.txt  # mypy
python3 -m mypy --config-file mypy.ini
```

## Tests

Run the regression tests (status mapping and parser behavior):

```bash
python3 -m unittest -v test_status_lookup.py
```

## Related

- `extract_comments.py` - Extracts Gherkin comments and file metadata
- `generate_gherkin_report.py` - Generates HTML report from extracted comments
- `terraform_event_types.py` - TypedDict definitions for Terraform JSONL events

## License

This project is licensed under the MIT License. See `LICENSE` for details.

