import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_provider import call_api


class SyntheticProviderTests(unittest.TestCase):
    def test_provider_returns_fixture_json_without_prompt_or_network_assumptions(self):
        result = call_api(
            "any prompt text",
            {},
            {"vars": {"label": "yes", "cwe_hint": "CWE-89"}},
        )

        self.assertEqual(set(result), {"output"})
        self.assertEqual(json.loads(result["output"])["is_vuln"], "yes")
        self.assertEqual(json.loads(result["output"])["cwe"], "CWE-89")

    def test_safe_fixture_has_no_cwe(self):
        result = call_api("", {}, {"vars": {"label": "no", "cwe_hint": "CWE-89"}})
        parsed = json.loads(result["output"])
        self.assertEqual(parsed["is_vuln"], "no")
        self.assertIsNone(parsed["cwe"])

    def test_missing_label_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "vars.label"):
            call_api("", {}, {"vars": {}})


if __name__ == "__main__":
    unittest.main()
