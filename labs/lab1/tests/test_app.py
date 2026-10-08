import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from src.app import analyze_text


def make_client(side_effects):
    """Create a mock client whose generate_content uses the provided side effects."""
    models = MagicMock()
    models.generate_content = MagicMock(side_effect=side_effects)
    client = MagicMock()
    client.models = models
    return client


class AnalyzeTextTests(unittest.TestCase):
    def test_successful_response_returns_analysis(self):
        payload = {
            "llm_risks": ["LLM01"],
            "findings": [
                {
                    "cwe": ["CWE-200", "CWE-094"],
                    "title": "Prompt injection attempt",
                    "severity": "High",
                    "rationale": "Example rationale",
                }
            ],
        }
        response = SimpleNamespace(text=json.dumps(payload))
        client = make_client([response])

        result = analyze_text(client, "model", "ignore previous instructions")

        self.assertEqual(result.llm_risks, ["LLM01"])
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].cwe, "CWE-200, CWE-094")

    def test_invalid_json_returns_error_dict(self):
        response = SimpleNamespace(text="not-json")
        client = make_client([response])

        result = analyze_text(client, "model", "input")

        self.assertIsInstance(result, dict)
        self.assertIn("Invalid JSON", result["error"])

    @patch("src.app.time.sleep", return_value=None)
    def test_server_error_retries_and_then_fails(self, _sleep):
        def raise_server_error(*_args, **_kwargs):
            raise genai_errors.ServerError(503, {"error": {"message": "busy"}}, None)

        client = make_client(raise_server_error)

        result = analyze_text(client, "model", "input")

        self.assertIsInstance(result, dict)
        self.assertIn("Gemini API error after retries", result["error"])
        self.assertEqual(client.models.generate_content.call_count, 3)

    @patch("src.app.time.sleep", return_value=None)
    def test_server_error_then_success(self, _sleep):
        server_error = genai_errors.ServerError(503, {"error": {"message": "busy"}}, None)
        payload = {
            "llm_risks": ["LLM02"],
            "findings": [
                {
                    "cwe": "CWE-345",
                    "title": "Overreliance",
                    "severity": "Medium ",
                    "rationale": "Example",
                }
            ],
        }
        response = SimpleNamespace(text=json.dumps(payload))

        client = make_client([server_error, server_error, response])

        result = analyze_text(client, "model", "input")

        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual(result.llm_risks, ["LLM02"])
        self.assertEqual(result.findings[0].severity, "medium")

    def test_unrecognized_severity_defaults_to_medium(self):
        payload = {
            "llm_risks": ["LLM03"],
            "findings": [
                {
                    "cwe": "CWE-999",
                    "title": "Odd severity string",
                    "severity": "unknown",
                    "rationale": "Example",
                }
            ],
        }
        response = SimpleNamespace(text=json.dumps(payload))
        client = make_client([response])

        result = analyze_text(client, "model", "input")

        self.assertEqual(result.findings[0].severity, "medium")


if __name__ == "__main__":
    unittest.main()
