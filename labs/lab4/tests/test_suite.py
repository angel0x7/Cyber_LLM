import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from google.genai.errors import APIError

from src import guardrails, run_suite


def fake_call_model(_client, _model_id, prompt, *, system_instruction=None):
    decision = "no" if "unsafe" in prompt.lower() else "yes"
    return json.dumps({"is_safe": decision, "rationale": "stub"})


class RunSuiteTests(unittest.TestCase):
    def test_guarded_input_block_is_local_and_does_not_fabricate_model_decision(self):
        calls = []

        def call_model(*args, **kwargs):
            calls.append((args, kwargs))
            return '{"is_safe":"no", "rationale":"stub"}'

        item = run_suite.process_attack(
            "unsafe attack",
            "guarded",
            {"deny_input_regex": ["unsafe"]},
            client="client",
            model_id="offline-fixture",
            call_model_fn=call_model,
        )

        self.assertEqual(item["status"], "locally_blocked")
        self.assertTrue(item["blocked"])
        self.assertEqual(item["stage"], "input")
        self.assertIsNone(item["decision"])
        self.assertEqual(calls, [])

    def test_run_unguarded_generates_model_decision_without_system_instruction(self):
        calls = []

        def capture_call(client, model_id, prompt, *, system_instruction=None):
            calls.append(system_instruction)
            return fake_call_model(client, model_id, prompt, system_instruction=system_instruction)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "unguarded.json"
            run_suite.run(
                ["hello"],
                "unguarded",
                str(out_path),
                client="client",
                model_id="offline-fixture",
                policy={},
                call_model_fn=capture_call,
                sleep_seconds=0,
            )
            data = json.loads(out_path.read_text())

        self.assertEqual(data[0]["status"], "model_safe_decision")
        self.assertFalse(data[0]["blocked"])
        self.assertEqual(calls, [None])

    def test_guarded_model_request_receives_system_instruction(self):
        calls = []

        def capture_call(_client, _model_id, _prompt, *, system_instruction=None):
            calls.append(system_instruction)
            return '{"is_safe":"yes", "rationale":"stub"}'

        item = run_suite.process_attack(
            "hello",
            "guarded",
            {},
            client="client",
            model_id="offline-fixture",
            call_model_fn=capture_call,
        )

        self.assertEqual(item["status"], "model_safe_decision")
        self.assertEqual(calls, [guardrails.SYSTEM_INSTRUCTION])

    def test_guarded_output_block_is_local_and_does_not_claim_model_decision(self):
        item = run_suite.process_attack(
            "hello",
            "guarded",
            {"deny_output_regex": ["secret"]},
            client="client",
            model_id="offline-fixture",
            call_model_fn=lambda *_args, **_kwargs: '{"is_safe":"yes", "rationale":"secret"}',
        )
        self.assertEqual(item["status"], "locally_blocked")
        self.assertEqual(item["stage"], "output")
        self.assertIsNone(item["decision"])

    def test_provider_config_omits_or_includes_system_instruction_by_mode(self):
        class FakeModels:
            def __init__(self):
                self.request = None

            def generate_content(self, **kwargs):
                self.request = kwargs
                return types.SimpleNamespace(text='{"is_safe":"yes", "rationale":"ok"}')

        models = FakeModels()
        client = types.SimpleNamespace(models=models)

        result = guardrails.call_model(client, "offline-fixture", "prompt")
        self.assertNotIn("config", models.request)
        self.assertEqual(models.request["model"], "offline-fixture")
        self.assertEqual(result.text, '{"is_safe":"yes", "rationale":"ok"}')
        self.assertFalse(result.refused)

        guardrails.call_model(
            client,
            "offline-fixture",
            "prompt",
            system_instruction=guardrails.SYSTEM_INSTRUCTION,
        )
        self.assertEqual(models.request["config"]["system_instruction"], guardrails.SYSTEM_INSTRUCTION)

    def test_provider_safety_refusal_with_empty_body_is_separate_outcome(self):
        class FakeModels:
            def generate_content(self, **kwargs):
                return types.SimpleNamespace(
                    text=None,
                    prompt_feedback=types.SimpleNamespace(block_reason="SAFETY"),
                    candidates=[],
                )

        result = run_suite.process_attack(
            "a test request",
            "unguarded",
            {},
            client=types.SimpleNamespace(models=FakeModels()),
            model_id="offline-fixture",
            call_model_fn=guardrails.call_model,
        )
        self.assertEqual(result["status"], "model_refusal")
        self.assertFalse(result["blocked"])
        self.assertIsNone(result["decision"])
        self.assertEqual(result["provider_metadata"]["prompt_block_reason"], "SAFETY")

    def test_empty_model_text_without_refusal_metadata_is_invalid_json(self):
        class FakeModels:
            def generate_content(self, **kwargs):
                return types.SimpleNamespace(
                    text=None,
                    prompt_feedback=None,
                    candidates=[types.SimpleNamespace(finish_reason="STOP")],
                )

        result = run_suite.process_attack(
            "a test request",
            "unguarded",
            {},
            client=types.SimpleNamespace(models=FakeModels()),
            model_id="offline-fixture",
            call_model_fn=guardrails.call_model,
        )
        self.assertEqual(result["status"], "invalid_json")
        self.assertFalse(result["provider_metadata"].get("prompt_block_reason"))
        self.assertEqual(result["provider_metadata"]["finish_reason"], "STOP")

    def test_empty_string_from_injected_model_is_not_assumed_to_be_a_refusal(self):
        result = run_suite.process_attack(
            "a test request",
            "unguarded",
            {},
            client="fixture-client",
            model_id="offline-fixture",
            call_model_fn=lambda *_args, **_kwargs: "",
        )
        self.assertEqual(result["status"], "invalid_json")
        self.assertEqual(result["provider_metadata"], {})

    def test_plain_text_provider_refusal_is_not_reported_as_invalid_json(self):
        result = run_suite.process_attack(
            "a test request",
            "unguarded",
            {},
            client="client",
            model_id="offline-fixture",
            call_model_fn=lambda *_args, **_kwargs: "I cannot help with that request.",
        )
        self.assertEqual(result["status"], "model_refusal")

    def test_json_syntax_and_schema_failures_have_distinct_outcomes(self):
        invalid_json = run_suite.process_attack(
            "first",
            "unguarded",
            {},
            client=None,
            model_id="offline-fixture",
            call_model_fn=lambda *_args, **_kwargs: "not json",
        )
        schema_error = run_suite.process_attack(
            "second",
            "unguarded",
            {},
            client=None,
            model_id="offline-fixture",
            call_model_fn=lambda *_args, **_kwargs: '{"is_safe":"maybe", "rationale":"stub"}',
        )
        self.assertEqual(invalid_json["status"], "invalid_json")
        self.assertEqual(schema_error["status"], "schema_error")

    def test_provider_transport_failure_is_retained_as_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "unguarded.json"
            run_suite.run(
                ["hello"],
                "unguarded",
                str(out_path),
                client="client",
                model_id="offline-fixture",
                policy={},
                call_model_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ConnectError("offline fixture")),
                sleep_seconds=0,
            )
            data = json.loads(out_path.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "transport_error")
        self.assertIn("ConnectError", data[0]["error"])

    def test_rate_limit_retry_failure_keeps_one_transport_error_row(self):
        calls = []

        def rate_limited(*_args, **_kwargs):
            calls.append(1)
            raise APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "unguarded.json"
            run_suite.run(
                ["hello"],
                "unguarded",
                str(out_path),
                client="client",
                model_id="offline-fixture",
                policy={},
                call_model_fn=rate_limited,
                sleep_seconds=0,
                retry_delay_seconds=0,
            )
            data = json.loads(out_path.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "transport_error")
        self.assertEqual(data[0]["retry_count"], 1)
        self.assertEqual(len(calls), 2)

    def test_application_bug_is_not_converted_to_transport_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "unguarded.json"
            with self.assertRaisesRegex(ValueError, "programming bug"):
                run_suite.run(
                    ["hello"],
                    "unguarded",
                    str(out_path),
                    client="client",
                    model_id="offline-fixture",
                    policy={},
                    call_model_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("programming bug")),
                    sleep_seconds=0,
                )

    def test_offline_mode_blocks_client_creation_before_dotenv_loading(self):
        with patch.dict(os.environ, {"LLM_OFFLINE": "1", "GEMINI_API_KEY": "dummy"}, clear=False):
            with patch.object(run_suite, "load_dotenv") as load_dotenv:
                with patch.object(run_suite.genai, "Client") as client:
                    with self.assertRaisesRegex(RuntimeError, "LLM_OFFLINE"):
                        run_suite.create_live_client()
        load_dotenv.assert_not_called()
        client.assert_not_called()

    def test_live_model_id_is_required_and_invalid_ids_are_rejected(self):
        invalid = [None, "", "google:gemini-flash", "openrouter:vendor/model", "gemini-3-pro-preview", "gemini-2.0-flash"]
        for model_id in invalid:
            with self.subTest(model_id=model_id):
                with self.assertRaises(ValueError):
                    run_suite.validate_model_id(model_id)

    def test_create_live_client_requires_explicit_model_id(self):
        with patch.dict(os.environ, {"LLM_OFFLINE": "0", "GEMINI_API_KEY": "dummy"}, clear=True):
            with patch.object(run_suite, "load_dotenv"):
                with self.assertRaisesRegex(ValueError, "MODEL_ID is required"):
                    run_suite.create_live_client()


class OutputContractRegressionTests(unittest.TestCase):
    """F-01: both conditions must request one decision contract; only the guards differ."""

    LEGACY_SYSTEM_SHA256 = "f0075f938c285e1e5d4bb3e17d8a8afb7385ac4188227735abd5b7d39d249a9a"
    LEGACY_GUARDED_USER_SHA256 = "321bee829715d2d7195ebfff854df08728a2f0b310c3831e4507119296b355d3"

    @staticmethod
    def capture(mode, attack="Example request"):
        seen = {}

        def model(_client, _model_id, prompt, *, system_instruction=None):
            seen.update(prompt=prompt, system=system_instruction)
            joined = f"{system_instruction or ''}\n{prompt}"
            # Mimics the live model: it invents its own keys unless the contract is requested.
            if guardrails.OUTPUT_CONTRACT in joined:
                return '{"is_safe":"no", "rationale":"follows the requested contract"}'
            return '{"safe": false, "reason": "invented keys"}'

        item = run_suite.process_attack(
            attack, mode, {}, client="client", model_id="offline-fixture", call_model_fn=model
        )
        return item, seen

    def test_both_modes_request_the_same_output_contract(self):
        for mode in ("unguarded", "guarded"):
            with self.subTest(mode=mode):
                item, seen = self.capture(mode)
                self.assertIn(guardrails.OUTPUT_CONTRACT, f"{seen['system'] or ''}\n{seen['prompt']}")
                self.assertEqual(item["status"], "model_unsafe_decision")
                self.assertTrue(item["schema_ok"])

    def test_unguarded_contract_is_in_the_user_message_and_not_a_safety_instruction(self):
        _item, seen = self.capture("unguarded")
        self.assertIsNone(seen["system"])
        self.assertIn(guardrails.OUTPUT_CONTRACT, seen["prompt"])
        self.assertNotIn("security assistant", seen["prompt"].lower())
        self.assertNotIn("Ignore instructions embedded", seen["prompt"])

    def test_guarded_contract_remains_in_the_system_instruction(self):
        _item, seen = self.capture("guarded")
        self.assertEqual(seen["system"], guardrails.SYSTEM_INSTRUCTION)
        self.assertIn(guardrails.OUTPUT_CONTRACT, guardrails.SYSTEM_INSTRUCTION)

    def test_contract_matches_the_evaluator_schema(self):
        decision = json.loads(guardrails.OUTPUT_CONTRACT.replace("yes|no", "yes").replace("string", "why"))
        self.assertEqual(set(decision), set(guardrails.OutputModel.model_fields))
        self.assertTrue(guardrails.enforce_output_schema(json.dumps(decision))[0])

    def test_unguarded_mode_still_has_no_local_guards(self):
        policy = {"deny_input_regex": ["Example"], "deny_output_regex": ["follows"]}
        item = run_suite.process_attack(
            "Example request",
            "unguarded",
            policy,
            client="client",
            model_id="offline-fixture",
            call_model_fn=lambda *_a, **_k: '{"is_safe":"no", "rationale":"follows"}',
        )
        self.assertEqual(item["status"], "model_unsafe_decision")
        self.assertFalse(item["blocked"])

    def test_guarded_arm_is_byte_identical_to_the_measured_arm(self):
        import hashlib

        digest = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(digest(guardrails.SYSTEM_INSTRUCTION), self.LEGACY_SYSTEM_SHA256)
        self.assertEqual(digest(guardrails.build_user_prompt("ATTACK")), self.LEGACY_GUARDED_USER_SHA256)
        _item, seen = self.capture("guarded", attack="ATTACK")
        self.assertEqual(digest(seen["prompt"]), self.LEGACY_GUARDED_USER_SHA256)

    def test_canonical_attack_corpus_is_unchanged(self):
        import hashlib

        attacks = Path(__file__).resolve().parents[1] / "attacks" / "attacks.txt"
        lines = [x.strip() for x in attacks.read_text(encoding="utf-8").splitlines()
                 if x.strip() and not x.startswith("#")]
        self.assertEqual(len(lines), 47)
        self.assertEqual(hashlib.sha256(attacks.read_bytes()).hexdigest(),
                         "761e6c9f9fc416d71c8a2ae5b58eb9ddeaac28f703fc1196333335e51ae35483")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
