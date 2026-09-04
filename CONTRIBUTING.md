# Contributing

Thanks for your interest in contributing.

## Development setup

```bash
git clone https://github.com/lixhunter/gherkin-report.git
cd gherkin-report
python3 -m unittest -v test_status_lookup.py
python3 smoke_test_report_generator.py
```

## Pull requests

- Open an issue first for larger changes.
- Keep PRs small and focused.
- Add or update tests when behavior changes.
- Keep output compatibility in mind for `cucumber.json` and `junit.xml`.

## Commit style

Use clear, imperative commit messages, for example:

- `add junit exporter for scenario status`
- `fix go status lookup for named tests`

## Code quality

```bash
python3 -m mypy --config-file mypy.ini
python3 -m unittest -v test_status_lookup.py
python3 smoke_test_report_generator.py
```

## Reporting bugs

Please include:

- sample input files with Gherkin comments
- parser used (`terraform` or `go`)
- status JSON/JSONL snippet (sanitized)
- expected vs actual output

