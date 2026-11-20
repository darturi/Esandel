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
from .judge import JudgeError, judge_draft
from .openai_responses import OpenAIResponseError
from .revision import regenerate_answer, tweak_draft


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
    judge_options = parser.add_mutually_exclusive_group()
    judge_options.add_argument(
        "--live-judge", action="store_true", help="Use GPT-6.2 Sol to judge and revise the draft"
    )
    judge_options.add_argument(
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

    judge_model = partial(stubs.judge, decision=args.stub_decision)
    tweak_model: Callable[[str, str, str], str] = stubs.tweak
    regenerate_model: Callable[[str], str] = stubs.regenerate
    if args.live_judge:
        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not openai_api_key:
            parser.error("set OPENAI_API_KEY to use the live judge")
        judge_model = partial(judge_draft, api_key=openai_api_key)
        tweak_model = partial(tweak_draft, api_key=openai_api_key)
        regenerate_model = partial(regenerate_answer, api_key=openai_api_key)

    graph = build_graph(
        draft_model=draft_model,
        judge_model=judge_model,
        tweak_model=tweak_model,
        regenerate_model=regenerate_model,
    )
    try:
        result = graph.invoke({"query": args.query})
    except DraftError as error:
        parser.exit(1, f"esandel: draft failed. {error}\n")
    except JudgeError as error:
        parser.exit(1, f"esandel: judge failed. {error}\n")
    except OpenAIResponseError as error:
        parser.exit(1, f"esandel: revision failed. {error}\n")

    if args.json:
        print(json.dumps({**result, "verdict": result["verdict"].model_dump()}))
    else:
        print(result["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
