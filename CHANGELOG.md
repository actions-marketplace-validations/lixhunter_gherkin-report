# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-09-04

### Added

- Initial public release of `gherkin-report`
- HTML report generation from Gherkin-style comments
- Terraform status integration from `terraform test -json`
- Go status integration from `go test -json`
- Optional output formats: normalized JSON, Cucumber JSON, JUnit XML
- Debug scenario mapping chips in HTML report

### Notes

- Designed for compatibility with both private and public CI environments.
- Allure output is intentionally not included in this release.

