import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from functools import partial
from time import monotonic
from typing import Literal, NamedTuple, get_args
from urllib.parse import urlsplit

from langgraph.config import get_stream_writer

from . import stubs
from .draft import (
    DEEPINFRA_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DraftError,
    DraftTokenLimitError,
    chat_draft,
)
from .graph import Decision, build_graph
from .judge import JudgeError, judge_draft
from .openai_responses import OpenAIResponseError
from .revision import regenerate_answer, tweak_draft

DEEPINFRA_DRAFT_MODELS = {
    DEFAULT_MODEL: "Qwen3.8-27B",
    "google/gemma-3-4b-it": "Gemma 3 4B (smaller model)",
}


class DraftSettings(NamedTuple):
    base_url: str
    model: str
    api_key: str

    @property
    def issue(self) -> str | None:
        if not self.base_url or not self.model:
            return "draft_settings_missing"
        try:
            url = urlsplit(self.base_url)
            if url.scheme not in ("http", "https") or not url.hostname:
                return "draft_url_invalid"
        except ValueError:
            return "draft_url_invalid"
        if self.base_url == DEEPINFRA_BASE_URL and not self.api_key:
            return "draft_key_missing"
        return None


def draft_settings() -> DraftSettings:
    base_url = os.environ.get("ESANDEL_DRAFT_BASE_URL", DEEPINFRA_BASE_URL).strip().rstrip("/")
    model = os.environ.get("ESANDEL_DRAFT_MODEL", DEFAULT_MODEL).strip()
    key_var = "DEEPINFRA_API_KEY" if base_url == DEEPINFRA_BASE_URL else "ESANDEL_DRAFT_API_KEY"
    return DraftSettings(base_url, model, os.environ.get(key_var, "").strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="esandel", description="Run the Esandel draft and review workflow."
    )
    parser.add_argument("query", nargs="?", help="Question to answer (or read stdin with --events)")
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
    output_options = parser.add_mutually_exclusive_group()
    output_options.add_argument(
        "--json", action="store_true", help="Show the query, draft, verdict, and answer"
    )
    output_options.add_argument(
        "--events", action="store_true", help="Stream workflow events as newline-delimited JSON"
    )
    output_options.add_argument(
        "--check-config", action="store_true", help="Report local provider setup as JSON"
    )
    args = parser.parse_args(argv)
    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() if args.check_config or args.live_judge else ""
    if args.check_config:
        settings = draft_settings()
        choices = dict(DEEPINFRA_DRAFT_MODELS) if settings.base_url == DEEPINFRA_BASE_URL else {}
        if choices and settings.model:
            choices.setdefault(settings.model, settings.model)
        print(json.dumps({
            "draftIssue": settings.issue,
            "draftModel": settings.model,
            "draftModelChoices": [
                {"id": model, "label": label} for model, label in choices.items()
            ],
            "judgeIssue": None if openai_api_key else "judge_key_missing",
            "defaultDraftMaxTokens": DEFAULT_MAX_TOKENS,
        }))
        return 0
    if args.query is None:
        if not args.events:
            parser.error("the following arguments are required: query")
        args.query = sys.stdin.read()
    if not args.query.strip():
        parser.error("query must contain non-whitespace text")

    def draft_delta(kind: Literal["reasoning", "draft"], text: str) -> None:
        get_stream_writer()({"type": f"{kind}_delta", "text": text})

    draft_model: Callable[[str], str] = stubs.draft
    model = "Stub draft"
    if args.live_draft:
        if args.draft_max_tokens < 1:
            parser.error("--draft-max-tokens must be positive")
        settings = draft_settings()
        issues = {
            "draft_settings_missing": "the draft base URL and model must be nonempty",
            "draft_url_invalid": "the draft base URL must be a valid HTTP or HTTPS URL",
            "draft_key_missing": "set DEEPINFRA_API_KEY to use the DeepInfra draft endpoint",
        }
        if issue := settings.issue:
            parser.error(issues[issue])
        model = settings.model
        draft_model = partial(
            chat_draft,
            base_url=settings.base_url,
            model=model,
            max_tokens=args.draft_max_tokens,
            api_key=settings.api_key,
            on_delta=draft_delta if args.events else None,
        )

    judge_model = partial(stubs.judge, decision=args.stub_decision)
    tweak_model: Callable[[str, str, str], str] = stubs.tweak
    regenerate_model: Callable[[str], str] = stubs.regenerate
    if args.live_judge:
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
    started = monotonic()

    def emit(event: dict[str, object]) -> None:
        elapsed_ms = round((monotonic() - started) * 1000)
        print(json.dumps({**event, "elapsed_ms": elapsed_ms}), flush=True)

    try:
        if args.events:
            emit({"type": "draft_started", "model": model})
            for mode, update in graph.stream({"query": args.query}, stream_mode=["custom", "updates"]):
                if mode == "custom":
                    emit(update)
                    continue
                for node, output in update.items():
                    if node == "draft":
                        emit({"type": "draft_completed", "draft": output["draft"]})
                    elif node == "judge":
                        emit({"type": "verdict", **output["verdict"].model_dump()})
                    else:
                        emit({"type": "final_answer", "answer": output["answer"], "decision": node})
            return 0
        result = graph.invoke({"query": args.query})
    except DraftError as error:
        if args.events and isinstance(error, DraftTokenLimitError):
            emit({"type": "draft_limit"})
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
