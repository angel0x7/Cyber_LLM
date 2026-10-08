import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_provider import call_api


class DatasetContractTests(unittest.TestCase):
    def test_thirty_embedded_cases_cover_each_snippet_and_provider_contract(self):
        dataset_path = ROOT / "_generated" / "tests_flat.yaml"
        cases = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
        snippet_files = {
            path.relative_to(ROOT / "snippets").as_posix()
            for language in ("python", "javascript", "java")
            for path in (ROOT / "snippets" / language).iterdir()
            if path.is_file()
        }

        self.assertEqual(len(cases), 30)
        files = set()
        for case in cases:
            variables = case["vars"]
            self.assertTrue(variables["code"].strip())
            self.assertIn(variables["label"], {"yes", "no"})
            files.add(variables["file"])
            # The local provider accepts every seeded case without loading the
            # dataset itself or making a provider/network call.
            self.assertIn("output", call_api("", {}, {"vars": variables}))

        self.assertEqual(files, snippet_files)


if __name__ == "__main__":
    unittest.main()
