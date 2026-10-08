"""The baseline and secure prompt must reach the adapter without rewriting."""
import json
from pathlib import Path
import unittest
import live_provider

class LivePromptContractTests(unittest.TestCase):
    def test_both_canonical_text_variants_are_preserved(self):
        for name in ('baseline_prompt.txt', 'secure_review_prompt.txt'):
            text = (Path(__file__).resolve().parents[1] / 'prompts' / name).read_text()
            self.assertEqual(live_provider._messages(text), [{'role': 'user', 'content': text}])

    def test_chat_validation_and_empty_rejection(self):
        messages = [{'role': 'system', 'content': 'contract'}, {'role': 'user', 'content': 'case'}]
        self.assertEqual(live_provider._messages(json.dumps(messages)), messages)
        for invalid in ('', '[]', '{}', '[{"role":"tool","content":"x"}]'):
            with self.assertRaises(ValueError):
                live_provider._messages(invalid)
