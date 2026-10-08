"""No finding may disappear through truncation of serialized scanner reports."""
import json
import unittest
from src.gemini_remediate import compact_findings, remediate

class RemediationPayloadTests(unittest.TestCase):
    def test_all_findings_and_resource_evidence_survive_compaction(self):
        findings = [{'check_id': f'CKV_DEMO_{i}', 'file_path': '/main.tf',
                     'repo_file_path': '/terraform/main.tf', 'check_name': 'Test finding',
                     'resource': f'example.{i}', 'code_block': [[1, 'resource example {}']],
                     'unused_scanner_bookkeeping': 'x' * 100000} for i in range(3)]
        payload = {'checkov': [{'results': {'failed_checks': findings}}],
                   'semgrep': {'results': []}}
        compact = compact_findings(payload)
        self.assertEqual([f['check_id'] for f in compact], [f['check_id'] for f in findings])
        self.assertTrue(all(f['file'] == 'terraform/main.tf' and f['code_block'] for f in compact))
        self.assertLess(len(json.dumps(compact)), 200000)

    def test_oversize_is_rejected_before_any_model_call(self):
        with self.assertRaisesRegex(ValueError, 'No findings were sent'):
            remediate(None, 'unused-fixture', [{'code': 'x' * 200001}])
