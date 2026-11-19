import json
import subprocess
import sys
import unittest


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
