import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.metrics import main as run_metrics


class MetricsScriptTests(unittest.TestCase):
    def run_export(self, data, dataset=None):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        source = Path(tempdir.name) / "results.json"
        details = Path(tempdir.name) / "metrics.csv"
        summary = Path(tempdir.name) / "summary.csv"
        dataset_path = None
        if dataset is not None:
            dataset_path = Path(tempdir.name) / "expected.yaml"
            dataset_path.write_text(yaml.safe_dump(dataset), encoding="utf-8")
        source.write_text(json.dumps(data), encoding="utf-8")
        run_metrics(str(source), str(details), str(summary), str(dataset_path) if dataset_path else None)
        with details.open(newline="", encoding="utf-8") as handle:
            detail_rows = list(csv.DictReader(handle))
        with summary.open(newline="", encoding="utf-8") as handle:
            summary_rows = list(csv.DictReader(handle))
        return detail_rows, summary_rows

    def test_legacy_promptfoo_results_keep_per_prompt_counts(self):
        sample = Path(__file__).parent / "data" / "sample_results.json"
        with tempfile.TemporaryDirectory() as tmpdir:
            details = Path(tmpdir) / "metrics.csv"
            summary = Path(tmpdir) / "summary.csv"
            run_metrics(str(sample), str(details), str(summary))
            with details.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            with summary.open(newline="", encoding="utf-8") as handle:
                grouped = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["test_id"], "test-0")
        self.assertEqual(rows[0]["outcome"], "TP")
        self.assertEqual({row["prompt_idx"] for row in grouped}, {"0", "1"})
        by_prompt = {row["prompt_idx"]: row for row in grouped}
        self.assertEqual(
            [by_prompt["0"][key] for key in ("tp", "fp", "tn", "fn", "precision", "recall", "f1")],
            ["1", "0", "1", "0", "", "", ""],
        )
        self.assertEqual(by_prompt["0"]["scoring_status"], "incomplete")
        self.assertEqual(by_prompt["0"]["missing_tests"], "30")
        self.assertEqual(
            [by_prompt["1"][key] for key in ("tp", "fp", "tn", "fn")],
            ["0", "1", "1", "1"],
        )

    def test_provider_model_prompt_test_and_failure_dimensions_are_preserved(self):
        data = {
            "results": {
                "results": [
                    {
                        "provider": {"id": "google:gemini-example", "label": "live-google"},
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 2,
                        "vars": {"file": "python/01_insecure_sql.py", "label": "yes"},
                        "response": {"output": '{"is_vuln":"yes"}'},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 3,
                        "vars": {"file": "python/02_safe_param.py", "label": "no"},
                        "response": {"output": '{"is_vuln":"yes"}'},
                    },
                    {
                        "providerId": "python:/opt/course/labs/lab2/custom_provider.py",
                        "providerLabel": "synthetic-fixture-v1",
                        "promptId": "baseline",
                        "promptIdx": 0,
                        "testIdx": 4,
                        "vars": {"file": "python/03_os_cmd.py", "label": "yes"},
                        "response": {"output": "I cannot help with that request."},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 5,
                        "vars": {"file": "python/04_os_cmd_safe.py", "label": "no"},
                        "response": {"output": "not valid JSON"},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 6,
                        "vars": {"file": "python/05_deser.py", "label": "yes"},
                        "response": {"error": "HTTP 429 Too Many Requests"},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 7,
                        "vars": {"file": "python/06_hash.py", "label": "yes"},
                        "response": {"output": '{"is_vuln":"maybe"}'},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 8,
                        "vars": {"file": "python/07_eval.py", "label": "yes"},
                        "response": {"output": '{"refusal":true}'},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 9,
                        "vars": {"file": "python/08_eval_guard.py", "label": "yes"},
                        "response": {"output": '{"status":"refused","message":"policy"}'},
                    },
                    {
                        "providerId": "google:gemini-example",
                        "providerLabel": "live-google",
                        "modelId": "gemini-example",
                        "promptId": "secure-review",
                        "promptIdx": 1,
                        "testIdx": 10,
                        "vars": {"file": "python/09_xss_flask.py", "label": "yes"},
                        "response": {"output": '{"is_vuln":"yes"}'},
                        "error": "Custom function assertion failed",
                    },
                ]
            }
        }

        details, summaries = self.run_export(data)

        self.assertEqual(len(details), 9)
        self.assertEqual(details[0]["provider_id"], "google:gemini-example")
        self.assertEqual(details[0]["model_id"], "gemini-example")
        self.assertEqual(details[0]["prompt_id"], "secure-review")
        self.assertEqual(details[0]["test_id"], "python/01_insecure_sql.py")
        self.assertEqual(details[0]["outcome"], "TP")
        self.assertEqual(details[1]["outcome"], "FP")
        self.assertEqual(details[2]["outcome"], "REFUSAL")
        self.assertEqual(details[2]["model_id"], "synthetic-fixture-v1")
        self.assertEqual(details[3]["outcome"], "PARSE_ERROR")
        self.assertEqual(details[4]["outcome"], "TRANSPORT_ERROR")
        self.assertEqual(details[5]["outcome"], "CLASSIFICATION_ERROR")
        self.assertEqual(details[6]["outcome"], "REFUSAL")
        self.assertEqual(details[7]["outcome"], "REFUSAL")
        self.assertEqual(details[8]["outcome"], "EVALUATION_ERROR")
        self.assertEqual(details[8]["error_type"], "evaluation_error")

        live_summary = next(row for row in summaries if row["provider_id"] == "google:gemini-example")
        self.assertEqual(live_summary["model_id"], "gemini-example")
        self.assertEqual(live_summary["prompt_id"], "secure-review")
        self.assertEqual(
            [live_summary[key] for key in ("total_tests", "tp", "fp", "fn", "refusals", "parse_errors", "transport_errors", "classification_errors", "evaluation_errors", "missing_tests", "scoring_status", "f1")],
            ["8", "1", "1", "0", "2", "1", "1", "1", "1", "22", "incomplete", ""],
        )

    def test_f1_requires_complete_unique_dataset_coverage_and_classifications(self):
        dataset = [
            {"vars": {"file": "a.py", "label": "yes", "code": "vulnerable"}},
            {"vars": {"file": "b.py", "label": "no", "code": "safe"}},
        ]

        complete, summaries = self.run_export(
            {
                "results": [
                    {"providerId": "google:test", "promptId": "p0", "promptIdx": 0, "vars": {"file": "a.py", "label": "yes"}, "response": {"output": '{"is_vuln":"yes"}'}},
                    {"providerId": "google:test", "promptId": "p0", "promptIdx": 0, "vars": {"file": "b.py", "label": "no"}, "response": {"output": '{"is_vuln":"no"}'}},
                ]
            },
            dataset,
        )
        self.assertEqual(summaries[0]["run_coverage"], "complete")
        self.assertEqual(summaries[0]["scoring_status"], "complete")
        self.assertEqual(summaries[0]["classification_coverage"], "1.000")
        self.assertEqual(summaries[0]["f1"], "1.000")

        duplicate, summaries = self.run_export(
            {
                "results": [
                    {"providerId": "google:test", "promptId": "p0", "promptIdx": 0, "vars": {"file": "a.py", "label": "yes"}, "response": {"output": '{"is_vuln":"yes"}'}},
                    {"providerId": "google:test", "promptId": "p0", "promptIdx": 0, "vars": {"file": "a.py", "label": "yes"}, "response": {"output": '{"is_vuln":"yes"}'}},
                    {"providerId": "google:test", "promptId": "p0", "promptIdx": 0, "vars": {"file": "extra.py", "label": "no"}, "response": {"output": '{"is_vuln":"no"}'}},
                ]
            },
            dataset,
        )
        self.assertEqual(summaries[0]["run_coverage"], "incomplete")
        self.assertEqual(summaries[0]["missing_tests"], "1")
        self.assertEqual(summaries[0]["duplicate_results"], "1")
        self.assertEqual(summaries[0]["unexpected_tests"], "1")
        self.assertEqual(summaries[0]["f1"], "")


if __name__ == "__main__":
    unittest.main()
