import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_batches_simple import create_batch_config


class BatchRunnerTests(unittest.TestCase):
    def test_offline_configs_return_a_promptfoo_javascript_score(self):
        for config_name in ("promptfooconfig_offline.yaml", "promptfooconfig_custom.yaml"):
            config = yaml.safe_load((ROOT / config_name).read_text(encoding="utf-8"))
            assertions = config["defaultTest"]["assert"]
            javascript = next(item for item in assertions if item.get("type") == "javascript")
            self.assertIn("return actual === expected ? 1 : 0", javascript["value"])
            self.assertNotIn("(() =>", javascript["value"])

    def test_temp_config_resolves_python_provider_against_source_config(self):
        source_config = ROOT / "promptfooconfig_offline.yaml"
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "batch.yaml"
            batch_file.write_text("- vars: {label: 'no', code: 'print(1)'}\n", encoding="utf-8")
            with patch.dict(os.environ, {"LLM_OFFLINE": "1"}):
                generated = create_batch_config(source_config, batch_file, 1, tmpdir)

            config = yaml.safe_load(generated.read_text(encoding="utf-8"))

        provider_id = config["providers"][0]["id"]
        provider_path = Path(provider_id.removeprefix("python:"))
        self.assertTrue(provider_path.is_absolute())
        self.assertEqual(provider_path, ROOT / "custom_provider.py")
        self.assertTrue(config["prompts"][0].startswith(f"file://{ROOT}/prompts/"))

    def test_offline_guard_rejects_live_provider_configs(self):
        source_config = ROOT / "promptfooconfig_gemini_free_tier.yaml"
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_file = Path(tmpdir) / "batch.yaml"
            batch_file.write_text("- vars: {label: 'no', code: 'print(1)'}\n", encoding="utf-8")
            with patch.dict(os.environ, {"LLM_OFFLINE": "1"}):
                with self.assertRaisesRegex(ValueError, "LLM_OFFLINE=1"):
                    create_batch_config(source_config, batch_file, 1, tmpdir)


if __name__ == "__main__":
    unittest.main()
