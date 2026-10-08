import json
import tempfile
import unittest
from pathlib import Path

from scripts import run_checkov, run_semgrep


class _FakeResult:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _runner_factory(expected_binary):
    calls = {}

    def _runner(cmd, capture_output, text, check):
        calls["cmd"] = cmd
        assert cmd[0] == expected_binary, f"expected {expected_binary}, got {cmd}"
        return _FakeResult("{}", returncode=0)

    _runner.calls = calls
    return _runner


class ScriptTests(unittest.TestCase):
    def test_run_checkov_writes_expected_file(self):
        fake_runner = _runner_factory("checkov")
        with tempfile.TemporaryDirectory() as tmp:
            out = run_checkov.run(after=False, runner=fake_runner, report_dir=Path(tmp))
            self.assertTrue(out.exists())
            self.assertEqual(json.loads(out.read_text()), {})
            self.assertEqual(fake_runner.calls["cmd"][0], "checkov")

    def test_run_semgrep_writes_after_file(self):
        fake_runner = _runner_factory("semgrep")
        with tempfile.TemporaryDirectory() as tmp:
            out = run_semgrep.run(after=True, runner=fake_runner, report_dir=Path(tmp))
            self.assertTrue(out.name.endswith("semgrep_after.json"))
            self.assertEqual(json.loads(out.read_text()), {})
            self.assertTrue(out.exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
