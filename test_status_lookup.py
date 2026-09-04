#!/usr/bin/env python3
"""Regression tests for Terraform JSONL scenario status path matching."""

from __future__ import annotations

import unittest

import generate_gherkin_report as report


class StatusLookupPathResolutionTests(unittest.TestCase):
    def test_matches_short_jsonl_path_against_full_comment_path(self) -> None:
        lookup = {
            "tests/config-plan-mocked.tftest.hcl": ["pass"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "terraform/cnap/dev/tests/config-plan-mocked.tftest.hcl",
            1,
        )

        self.assertEqual(status, "pass")

    def test_matches_full_jsonl_path_against_short_comment_path(self) -> None:
        lookup = {
            "terraform/cnap/dev/tests/config-plan-mocked.tftest.hcl": ["pass"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "tests/config-plan-mocked.tftest.hcl",
            1,
        )

        self.assertEqual(status, "pass")

    def test_prefers_most_specific_suffix_match(self) -> None:
        lookup = {
            "tests/config-plan-mocked.tftest.hcl": ["fail"],
            "cnap/dev/tests/config-plan-mocked.tftest.hcl": ["pass"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "terraform/cnap/dev/tests/config-plan-mocked.tftest.hcl",
            1,
        )

        self.assertEqual(status, "pass")

    def test_normalizes_windows_separators(self) -> None:
        lookup = {
            "tests/config-plan-mocked.tftest.hcl": ["pass"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "terraform\\cnap\\dev\\tests\\config-plan-mocked.tftest.hcl",
            1,
        )

        self.assertEqual(status, "pass")

    def test_returns_unknown_for_missing_index(self) -> None:
        lookup = {
            "tests/config-plan-mocked.tftest.hcl": ["pass"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "terraform/cnap/dev/tests/config-plan-mocked.tftest.hcl",
            2,
        )

        self.assertEqual(status, "unknown")

    def test_global_fallback_when_file_statuses_are_unavailable(self) -> None:
        lookup = {
            "__global__": ["pass", "fail"],
        }

        first = report.next_scenario_status_for_file(
            lookup,
            "tests/any-file_test.go",
            1,
            1,
        )
        second = report.next_scenario_status_for_file(
            lookup,
            "tests/another-file_test.go",
            1,
            2,
        )

        self.assertEqual(first, "pass")
        self.assertEqual(second, "fail")

    def test_prefers_named_go_test_status_when_available(self) -> None:
        lookup = {
            "__global__": ["pass", "pass"],
            "__test__:Test_integration_getDGTicketNumber": ["fail"],
        }

        status = report.next_scenario_status_for_file(
            lookup,
            "tests/go/middleware/jiraClientRequest/jiraClientRequest_test.go",
            1,
            1,
            scenario_test_name="Test_integration_getDGTicketNumber",
        )

        self.assertEqual(status, "fail")

    def test_named_go_test_status_uses_global_index_for_multiple_entries(self) -> None:
        lookup = {
            "__test__:TestSameName": ["pass", "fail"],
        }

        first = report.next_scenario_status_for_file(
            lookup,
            "tests/a_test.go",
            1,
            1,
            scenario_test_name="TestSameName",
        )
        second = report.next_scenario_status_for_file(
            lookup,
            "tests/b_test.go",
            1,
            2,
            scenario_test_name="TestSameName",
        )

        self.assertEqual(first, "pass")
        self.assertEqual(second, "fail")


if __name__ == "__main__":
    unittest.main(verbosity=2)

