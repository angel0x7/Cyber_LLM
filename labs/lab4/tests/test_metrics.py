import csv
import json
import tempfile
import unittest
from pathlib import Path

from src import metrics


class MetricsTests(unittest.TestCase):
    def test_failed_cases_remain_in_total_denominator(self):
        statuses = [
            "locally_blocked",
            "model_refusal",
            "model_safe_decision",
            "model_unsafe_decision",
            "schema_error",
            "transport_error",
            "invalid_json",
        ]
        items = [{"status": status} for status in statuses]

        stats = metrics.compute_stats(items)

        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["rate_denominator"], 7)
        for status in statuses:
            self.assertEqual(stats[status], 1)
            self.assertAlmostEqual(stats[f"{status}_rate"], 1 / 7)
        self.assertNotIn("unsafe_pass", stats)
        self.assertNotIn("unsafe_pass_rate", stats)

    def test_empty_run_has_zero_rates(self):
        stats = metrics.compute_stats([])
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["rate_denominator"], 0)
        self.assertTrue(all(stats[f"{status}_rate"] == 0 for status in metrics.OUTCOMES))

    def test_legacy_rows_are_classified_without_unsafe_pass_claim(self):
        data = [
            {"blocked": True},
            {"blocked": False, "decision": {"is_safe": "no"}},
            {"blocked": False, "decision": {"is_safe": "yes"}},
            {"blocked": False, "error": "timeout"},
            {"blocked": False, "schema_ok": False, "schema_err": "invalid JSON: syntax"},
            {"blocked": False, "schema_ok": False, "schema_err": "schema error: is_safe"},
        ]

        stats = metrics.compute_stats(data)

        self.assertEqual(stats["total"], 6)
        self.assertEqual(stats["locally_blocked"], 1)
        self.assertEqual(stats["model_unsafe_decision"], 1)
        self.assertEqual(stats["model_safe_decision"], 1)
        self.assertEqual(stats["transport_error"], 1)
        self.assertEqual(stats["invalid_json"], 1)
        self.assertEqual(stats["schema_error"], 1)

    def test_main_writes_all_outcomes_and_keeps_failures_in_denominator(self):
        unguarded = [
            {"status": "model_safe_decision"},
            {"status": "transport_error"},
            {"status": "invalid_json"},
        ]
        guarded = [
            {"status": "locally_blocked"},
            {"status": "model_refusal"},
            {"status": "schema_error"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            ug_path = Path(tmp) / "ug.json"
            gd_path = Path(tmp) / "gd.json"
            csv_path = Path(tmp) / "nested" / "metrics.csv"
            ug_path.write_text(json.dumps(unguarded))
            gd_path.write_text(json.dumps(guarded))

            metrics.main(str(ug_path), str(gd_path), str(csv_path))

            with csv_path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rate_denominator"], "3")
        self.assertEqual(rows[0]["transport_error"], "1")
        self.assertEqual(rows[0]["invalid_json"], "1")
        self.assertEqual(rows[1]["locally_blocked"], "1")
        self.assertEqual(rows[1]["model_refusal"], "1")
        self.assertEqual(rows[1]["schema_error"], "1")
        self.assertNotIn("unsafe_pass", rows[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
