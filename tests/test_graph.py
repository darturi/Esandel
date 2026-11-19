import unittest
from unittest.mock import Mock, call

from pydantic import ValidationError

from esandel.graph import build_graph


class GraphTests(unittest.TestCase):
    query = "What is 2 + 2?"
    original_draft = "  The answer is 4.\n\n"

    def setUp(self):
        self.models = Mock()
        self.models.draft.return_value = self.original_draft
        self.models.tweak.return_value = "Adding 2 and 2 gives 4."
        self.models.regenerate.return_value = "2 + 2 = 4."
        self.graph = build_graph(
            draft_model=self.models.draft,
            judge_model=self.models.judge,
            tweak_model=self.models.tweak,
            regenerate_model=self.models.regenerate,
        )
        self.initial_calls = [
            call.draft(self.query),
            call.judge(self.query, self.original_draft),
        ]

    def test_accept_returns_the_exact_draft_without_another_model_call(self):
        self.models.judge.return_value = {
            "decision": "accept",
            "rationale": "The answer is correct.",
        }

        result = self.graph.invoke({"query": self.query})

        self.assertEqual(result["answer"], self.original_draft)
        self.assertEqual(result["verdict"].decision, "accept")
        self.assertEqual(self.models.mock_calls, self.initial_calls)

    def test_tweak_receives_the_original_query_draft_and_guidance(self):
        guidance = "Show the addition."
        self.models.judge.return_value = {
            "decision": "tweak",
            "rationale": "The answer could be clearer.",
            "guidance": guidance,
        }

        result = self.graph.invoke({"query": self.query})

        self.assertEqual(result["answer"], self.models.tweak.return_value)
        self.assertEqual(result["draft"], self.original_draft)
        self.assertEqual(result["verdict"].guidance, guidance)
        self.assertEqual(
            self.models.mock_calls,
            [*self.initial_calls, call.tweak(self.query, self.original_draft, guidance)],
        )

    def test_regenerate_receives_only_the_original_query(self):
        self.models.judge.return_value = {
            "decision": "regenerate",
            "rationale": "The draft should be replaced.",
        }

        result = self.graph.invoke({"query": self.query})

        self.assertEqual(result["answer"], self.models.regenerate.return_value)
        self.assertEqual(result["draft"], self.original_draft)
        self.assertEqual(result["verdict"].decision, "regenerate")
        self.assertEqual(
            self.models.mock_calls,
            [*self.initial_calls, call.regenerate(self.query)],
        )

    def test_invalid_verdict_stops_the_run(self):
        for verdict in (
            {"decision": "unknown", "rationale": "Unknown decision."},
            {"decision": "tweak", "rationale": "Needs work.", "guidance": "  "},
        ):
            with self.subTest(verdict=verdict):
                self.models.reset_mock()
                self.models.judge.return_value = verdict

                with self.assertRaises(ValidationError):
                    self.graph.invoke({"query": self.query})

                self.assertEqual(self.models.mock_calls, self.initial_calls)
