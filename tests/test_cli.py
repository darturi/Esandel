import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import httpx

from esandel.cli import main


class CliTests(unittest.TestCase):
    query = "What is 2 + 2?"

    def run_cli(self, *args: str, check: bool = True):
        return subprocess.run(
            [sys.executable, "-m", "esandel.cli", *args],
            capture_output=True,
            text=True,
            check=check,
        )

    def test_selects_all_three_stub_paths(self):
        for decision in ("accept", "tweak", "regenerate"):
            with self.subTest(decision=decision):
                process = self.run_cli("--stub-decision", decision, "--json", self.query)
                result = json.loads(process.stdout)
                self.assertEqual(result["query"], self.query)
                self.assertEqual(result["verdict"]["decision"], decision)

                if decision == "accept":
                    self.assertEqual(result["answer"], result["draft"])
                elif decision == "tweak":
                    self.assertTrue(result["answer"].startswith(result["draft"]))
                    self.assertIn(result["verdict"]["guidance"], result["answer"])
                else:
                    self.assertEqual(
                        result["answer"], f"Stub answer written from scratch for {self.query!r}."
                    )

    def test_prints_only_the_answer_by_default(self):
        process = self.run_cli(self.query)
        self.assertEqual(process.stdout, f"Stub draft for {self.query!r}.\n")

    def test_rejects_a_whitespace_only_query(self):
        process = self.run_cli("  ", check=False)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("query must contain non-whitespace text", process.stderr)


class LiveDraftCliTests(unittest.TestCase):
    query = "What is 2 + 2?"

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.post = self.enterContext(patch("esandel.draft.httpx.post"))

    def reply(self, *, finish_reason: str = "stop", content: str = "  The answer is 4.\n"):
        self.post.return_value = httpx.Response(
            200,
            request=httpx.Request("POST", "http://draft.test/chat/completions"),
            json={
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"reasoning_content": "Thinking text", "content": content},
                    }
                ]
            },
        )

    def run_live_draft(self, *args: str):
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--live-draft", "--json", *args, self.query]), 0)
        return json.loads(stdout.getvalue())

    def test_deepinfra_defaults_to_qwen_and_uses_only_the_answer(self):
        os.environ["DEEPINFRA_API_KEY"] = "deepinfra-test-key"
        answer = "  The answer is 4.\n"
        self.reply(content=answer)

        result = self.run_live_draft()

        self.post.assert_called_once()
        self.assertEqual(
            self.post.call_args.args,
            ("https://api.deepinfra.com/v1/openai/chat/completions",),
        )
        request = self.post.call_args.kwargs
        self.assertEqual(request["headers"], {"Authorization": "Bearer deepinfra-test-key"})
        self.assertEqual(
            request["json"],
            {
                "model": "Qwen/Qwen3.8-27B",
                "messages": [{"role": "user", "content": self.query}],
                "max_tokens": 16_384,
            },
        )
        self.assertEqual(result["draft"], answer)
        self.assertEqual(result["answer"], answer)

    def test_custom_endpoint_uses_its_own_configuration(self):
        os.environ.update(
            {
                "DEEPINFRA_API_KEY": "deepinfra-test-key",
                "ESANDEL_DRAFT_BASE_URL": "http://127.0.0.1:8000/v1/",
                "ESANDEL_DRAFT_MODEL": "torch-qwen",
            }
        )
        self.reply()

        self.run_live_draft("--draft-max-tokens", "2048")

        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.args, ("http://127.0.0.1:8000/v1/chat/completions",))
        request = self.post.call_args.kwargs
        self.assertEqual(request["headers"], {})
        self.assertEqual(request["json"]["model"], "torch-qwen")
        self.assertEqual(request["json"]["max_tokens"], 2048)

    def test_missing_deepinfra_key_fails_before_sending_a_request(self):
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(["--live-draft", self.query])

        self.assertEqual(error.exception.code, 2)
        self.assertIn("set DEEPINFRA_API_KEY", stderr.getvalue())
        self.post.assert_not_called()

    def test_truncated_draft_fails_instead_of_printing_a_partial_answer(self):
        os.environ["DEEPINFRA_API_KEY"] = "deepinfra-test-key"
        self.reply(finish_reason="length", content="Partial answer")
        stdout, stderr = StringIO(), StringIO()
        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as error,
        ):
            main(["--live-draft", self.query])

        self.assertEqual(error.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("draft hit the output token limit", stderr.getvalue())


class LiveOpenAICliTests(unittest.TestCase):
    query = "What is 2 + 2?"
    endpoint = "https://api.openai.com/v1/responses"

    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.post = self.enterContext(patch("httpx.post"))

    def openai_reply(self, content: str) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", self.endpoint),
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning"},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": content}],
                    },
                ],
            },
        )

    def test_live_tweak_receives_the_original_query_draft_and_guidance(self):
        os.environ.update(
            {"OPENAI_API_KEY": "judge-test-key", "DEEPINFRA_API_KEY": "draft-test-key"}
        )
        draft_endpoint = "https://api.deepinfra.com/v1/openai/chat/completions"
        draft = "  It is 5.\n"
        verdict = {"decision": "tweak", "rationale": "Wrong sum.", "guidance": "Use 4."}
        revised = "It is 4."
        self.post.side_effect = [
            httpx.Response(
                200,
                request=httpx.Request("POST", draft_endpoint),
                json={"choices": [{"finish_reason": "stop", "message": {"content": draft}}]},
            ),
            self.openai_reply(json.dumps(verdict)),
            self.openai_reply(revised),
        ]
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--live-draft", "--live-judge", "--json", self.query]), 0)

        draft_call, judge_call, tweak_call = self.post.call_args_list
        self.assertEqual(draft_call.args, (draft_endpoint,))
        self.assertEqual(draft_call.kwargs["headers"], {"Authorization": "Bearer draft-test-key"})
        self.assertEqual(judge_call.args, (self.endpoint,))
        self.assertEqual(judge_call.kwargs["headers"], {"Authorization": "Bearer judge-test-key"})
        request = judge_call.kwargs["json"]
        self.assertEqual(request["model"], "gpt-6.2-sol")
        self.assertEqual(json.loads(request["input"]), {"query": self.query, "draft": draft})
        self.assertTrue(request["text"]["format"]["strict"])

        self.assertEqual(tweak_call.args, (self.endpoint,))
        self.assertEqual(tweak_call.kwargs["headers"], judge_call.kwargs["headers"])
        request = tweak_call.kwargs["json"]
        self.assertEqual(request["model"], "gpt-6.2-sol")
        self.assertEqual(
            json.loads(request["input"]),
            {"query": self.query, "draft": draft, "guidance": verdict["guidance"]},
        )
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["verdict"], verdict)
        self.assertEqual(result["answer"], revised)

    def test_live_regenerate_sends_only_the_original_query(self):
        os.environ["OPENAI_API_KEY"] = "judge-test-key"
        query = "  What is 2 + 2?\n"
        verdict = {"decision": "regenerate", "rationale": "Missing answer.", "guidance": ""}
        self.post.side_effect = [self.openai_reply(json.dumps(verdict)), self.openai_reply("4")]
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--live-judge", "--json", query]), 0)

        judge_call, regenerate_call = self.post.call_args_list
        self.assertEqual(regenerate_call.args, (self.endpoint,))
        self.assertEqual(regenerate_call.kwargs["headers"], judge_call.kwargs["headers"])
        request = regenerate_call.kwargs["json"]
        self.assertEqual(request["model"], "gpt-6.2-sol")
        self.assertEqual(request["input"], query)
        self.assertNotIn("instructions", request)
        self.assertNotIn("previous_response_id", request)
        self.assertNotIn("conversation", request)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["verdict"], verdict)
        self.assertEqual(result["answer"], "4")

    def test_missing_judge_key_fails_before_drafting(self):
        os.environ["DEEPINFRA_API_KEY"] = "draft-test-key"
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
            main(["--live-draft", "--live-judge", self.query])

        self.assertEqual(error.exception.code, 2)
        self.assertIn("set OPENAI_API_KEY", stderr.getvalue())
        self.post.assert_not_called()

    def test_incomplete_openai_response_stops_the_workflow(self):
        os.environ["OPENAI_API_KEY"] = "judge-test-key"
        incomplete = httpx.Response(
            200,
            request=httpx.Request("POST", self.endpoint),
            json={"status": "incomplete", "output": []},
        )
        verdict = {"decision": "regenerate", "rationale": "Missing answer.", "guidance": ""}
        for phase, replies in (
            ("judge", [incomplete]),
            ("revision", [self.openai_reply(json.dumps(verdict)), incomplete]),
        ):
            with self.subTest(phase=phase):
                self.post.side_effect = replies
                stdout, stderr = StringIO(), StringIO()
                with (
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as error,
                ):
                    main(["--live-judge", self.query])

                self.assertEqual(error.exception.code, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn(f"{phase} failed. OpenAI did not complete", stderr.getvalue())
