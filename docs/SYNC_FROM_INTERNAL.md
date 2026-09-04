# Sync from internal copy

This project is published on GitHub, while a private operational copy may exist in another repository.

## Recommended flow

1. Develop and validate in internal environment.
2. Copy `gherkin-report` sources into this repository.
3. Run tests locally.
4. Commit and push to GitHub.
5. Create a release tag.

## Manual sync commands (example)

```bash
rsync -av --exclude '__pycache__' \
  /path/to/internal/gherkin-report/ \
  /path/to/this/repo/

cd /path/to/this/repo
python3 -m unittest -v test_status_lookup.py
python3 smoke_test_report_generator.py
python3 -m mypy --config-file mypy.ini
```

## Notes

- Keep this repository as public release source.
- Keep private CI-specific integration details out of this public repo.

