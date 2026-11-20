import argparse
import json
import os
from collections.abc import Callable, Sequence
from functools import partial
from typing import get_args

from . import stubs
from .draft import (
    DEEPINFRA_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DraftError,
    chat_draft,
)
from .graph import Decision, build_graph


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="esandel", description="Run the Esandel draft and review workflow."
    )
    parser.add_argument("query", help="Question to answer")
    parser.add_argument(
        "--live-draft",
        action="store_true",
        help="Use the configured draft endpoint (default endpoint: Qwen3.8-27B on DeepInfra)",
    )
    parser.add_argument(
        "--draft-max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help="Output token limit for a live draft (default: %(default)s)",
    )
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

    draft_model: Callable[[str], str] = stubs.draft
    if args.live_draft:
        if args.draft_max_tokens < 1:
            parser.error("--draft-max-tokens must be positive")
        base_url = os.environ.get("ESANDEL_DRAFT_BASE_URL", DEEPINFRA_BASE_URL).strip().rstrip("/")
        model = os.environ.get("ESANDEL_DRAFT_MODEL", DEFAULT_MODEL).strip()
        if not base_url or not model:
            parser.error("the draft base URL and model must be nonempty")
        uses_deepinfra = base_url == DEEPINFRA_BASE_URL
        key_var = "DEEPINFRA_API_KEY" if uses_deepinfra else "ESANDEL_DRAFT_API_KEY"
        api_key = os.environ.get(key_var, "").strip()
        if uses_deepinfra and not api_key:
            parser.error("set DEEPINFRA_API_KEY to use the DeepInfra draft endpoint")
        draft_model = partial(
            chat_draft,
            base_url=base_url,
            model=model,
            max_tokens=args.draft_max_tokens,
            api_key=api_key,
        )

    graph = build_graph(
        draft_model=draft_model,
        judge_model=partial(stubs.judge, decision=args.stub_decision),
        tweak_model=stubs.tweak,
        regenerate_model=stubs.regenerate,
    )
    try:
        result = graph.invoke({"query": args.query})
    except DraftError as error:
        parser.exit(1, f"esandel: draft failed. {error}\n")

    if args.json:
        print(json.dumps({**result, "verdict": result["verdict"].model_dump()}))
    else:
        print(result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
