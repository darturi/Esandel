import argparse
import json
from collections.abc import Sequence
from functools import partial
from typing import get_args

from . import stubs
from .graph import Decision, build_graph


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="esandel", description="Run the Esandel workflow with stub models."
    )
    parser.add_argument("query", help="Question to answer")
    parser.add_argument(
        "--stub-decision",
        choices=get_args(Decision),
        default="accept",
        help="Verdict returned by the stub judge (default: %(default)s)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Show the query, draft, verdict, and answer"
    )
    args = parser.parse_args(argv)
    if not args.query.strip():
        parser.error("query must contain non-whitespace text")

    graph = build_graph(
        draft_model=stubs.draft,
        judge_model=partial(stubs.judge, decision=args.stub_decision),
        tweak_model=stubs.tweak,
        regenerate_model=stubs.regenerate,
    )
    result = graph.invoke({"query": args.query})

    if args.json:
        print(json.dumps({**result, "verdict": result["verdict"].model_dump()}))
    else:
        print(result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
