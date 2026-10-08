import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts import run_checkov, run_semgrep
from src import gemini_remediate

class LocalScannerTests(unittest.TestCase):
    def test_local_only_command_targets(self):
        c=run_checkov.build_cmd();s=run_semgrep.build_cmd()
        self.assertEqual(c.count('-d'),3)
        for name in ['terraform','k8s','docker']:
            self.assertTrue(any(str(x).endswith('/'+name) for x in c))
            self.assertTrue(any(str(x).endswith('/'+name) for x in s))
        self.assertIn('--skip-download',c)
        self.assertNotIn('p/kubernetes',s)
        self.assertIn('--metrics=off',s)

    def test_broken_scanner_report_is_not_success(self):
        for module in [run_checkov,run_semgrep]:
            with tempfile.TemporaryDirectory() as tmp:
                runner=lambda *a,**k: SimpleNamespace(returncode=2,stdout='{}',stderr='synthetic failure')
                with self.assertRaises(RuntimeError):module.run(runner=runner,report_dir=Path(tmp))
                runner=lambda *a,**k: SimpleNamespace(returncode=0,stdout='',stderr='')
                with self.assertRaises(ValueError):module.run(runner=runner,report_dir=Path(tmp))

    def test_remediation_is_separate_and_offline_blocked(self):
        with patch.dict(os.environ,{'LLM_OFFLINE':'1'}), patch('src.gemini_remediate.load_dotenv') as env:
            with self.assertRaises(RuntimeError):gemini_remediate.main('missing','missing')
        env.assert_not_called()

    def test_multiple_checkov_directory_documents_are_normalized(self):
        text='{"check_type":"terraform"}\n[{"check_type":"terraform"},{"check_type":"kubernetes"}]'
        self.assertEqual([x['check_type'] for x in run_checkov.decode_reports(text)],['terraform','kubernetes'])
