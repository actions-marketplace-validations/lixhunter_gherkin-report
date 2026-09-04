#!/usr/bin/env bash
#MISE description="Generate Gherkin test report from comment-annotated files"
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: action.sh [OPTIONS] INPUT_FILES...

Options:
  --output PATH                     Output HTML path (default: ./build/gherkin-report.html)
  --output-json PATH                Optional normalized report JSON path
  --output-cucumber-json PATH       Optional cucumber.json output path
  --output-junit-xml PATH           Optional JUnit XML output path
  --status-parser terraform|go      Status parser to apply (default: terraform)
  --status-json PATH                Optional parser-specific JSON/JSONL status file
  --terraform-json PATH             Deprecated alias for --status-json
  --debug-scenario-mapping          Show debug mapping chips in report
  --help                            Show this help
EOF
}

die() {
  echo "Error: $*" >&2
  echo >&2
  usage >&2
  exit 1
}

require_option_value() {
  local option_name="$1"
  local option_value="${2:-}"
  [[ -n "$option_value" ]] || die "Missing value for ${option_name}"
}

# Parse arguments
# Usage: action.sh [--output OUTPUT_PATH] [--status-parser terraform|go] [--status-json JSON_PATH] [--terraform-json JSON_PATH] [--debug-scenario-mapping] INPUT_FILES...
OUTPUT_PATH="./build/gherkin-report.html"
OUTPUT_JSON_PATH=""
OUTPUT_CUCUMBER_JSON_PATH=""
OUTPUT_JUNIT_XML_PATH=""
STATUS_PARSER="terraform"
STATUS_JSON_PATH=""
TERRAFORM_JSON_PATH=""
DEBUG_SCENARIO_MAPPING="false"
INPUT_FILES=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --help)
      usage
      exit 0
      ;;
    --output)
      require_option_value "$1" "${2:-}"
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --output-json)
      require_option_value "$1" "${2:-}"
      OUTPUT_JSON_PATH="$2"
      shift 2
      ;;
    --output-cucumber-json)
      require_option_value "$1" "${2:-}"
      OUTPUT_CUCUMBER_JSON_PATH="$2"
      shift 2
      ;;
    --output-junit-xml)
      require_option_value "$1" "${2:-}"
      OUTPUT_JUNIT_XML_PATH="$2"
      shift 2
      ;;
    --terraform-json)
      # Legacy alias for status JSON input.
      require_option_value "$1" "${2:-}"
      TERRAFORM_JSON_PATH="$2"
      shift 2
      ;;
    --status-json)
      require_option_value "$1" "${2:-}"
      STATUS_JSON_PATH="$2"
      shift 2
      ;;
    --status-parser)
      require_option_value "$1" "${2:-}"
      STATUS_PARSER="$2"
      shift 2
      ;;
    --debug-scenario-mapping)
      DEBUG_SCENARIO_MAPPING="true"
      shift
      ;;
    -*)
      die "Unknown option '$1'"
      ;;
    *)
      INPUT_FILES+=("$1")
      shift
      ;;
  esac
done

# Set environment variables if provided
if [[ -z "$STATUS_JSON_PATH" && -n "$TERRAFORM_JSON_PATH" ]]; then
  STATUS_JSON_PATH="$TERRAFORM_JSON_PATH"
fi

if [[ -n "$STATUS_JSON_PATH" ]]; then
  export GHERKIN_REPORT_STATUS_JSON_PATH="$STATUS_JSON_PATH"
  # Backward compatible fallback consumed by older paths.
  export GHERKIN_REPORT_TERRAFORM_JSON_PATH="$STATUS_JSON_PATH"
fi

# Validate and expand inputs
if [[ ${#INPUT_FILES[@]} -eq 0 ]]; then
  die "No input files specified"
fi

EXPANDED_INPUT_FILES=()
for raw_input in "${INPUT_FILES[@]}"; do
  if [[ -e "$raw_input" ]]; then
    EXPANDED_INPUT_FILES+=("$raw_input")
    continue
  fi

  if [[ "$raw_input" == *"*"* || "$raw_input" == *"?"* || "$raw_input" == *"["* ]]; then
    mapfile -t matches < <(compgen -G "$raw_input" || true)
    if [[ ${#matches[@]} -eq 0 ]]; then
      echo "Warning: Pattern matched no files: $raw_input" >&2
      continue
    fi
    EXPANDED_INPUT_FILES+=("${matches[@]}")
    continue
  fi

  echo "Warning: Input file not found: $raw_input" >&2
done

if [[ ${#EXPANDED_INPUT_FILES[@]} -eq 0 ]]; then
  die "No files to process after pattern expansion"
fi

case "$STATUS_PARSER" in
  terraform|go) ;;
  *) die "Invalid --status-parser '$STATUS_PARSER' (expected: terraform|go)" ;;
esac

# Run extraction and report generation
REPORT_ARGS=(
  --output "$OUTPUT_PATH"
  --status-parser "$STATUS_PARSER"
)

if [[ -n "$OUTPUT_JSON_PATH" ]]; then
  REPORT_ARGS+=(--output-json "$OUTPUT_JSON_PATH")
fi

if [[ -n "$OUTPUT_CUCUMBER_JSON_PATH" ]]; then
  REPORT_ARGS+=(--output-cucumber-json "$OUTPUT_CUCUMBER_JSON_PATH")
fi

if [[ -n "$OUTPUT_JUNIT_XML_PATH" ]]; then
  REPORT_ARGS+=(--output-junit-xml "$OUTPUT_JUNIT_XML_PATH")
fi

if [[ "$DEBUG_SCENARIO_MAPPING" == "true" ]]; then
  REPORT_ARGS+=(--debug-scenario-mapping)
fi

if [[ -n "$STATUS_JSON_PATH" ]]; then
  REPORT_ARGS+=(--status-json "$STATUS_JSON_PATH")
fi

"${SCRIPT_DIR}/extract_comments.py" "${EXPANDED_INPUT_FILES[@]}" | \
  "${SCRIPT_DIR}/generate_gherkin_report.py" "${REPORT_ARGS[@]}"

