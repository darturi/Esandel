import json
from collections.abc import Callable, Iterable
from typing import Literal

import httpx

from .sse import sse_data

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "Qwen/Qwen3.8-27B"
DEFAULT_MAX_TOKENS = 16_384
DraftDelta = Callable[[Literal["reasoning", "draft"], str], None]


class DraftError(RuntimeError):
    """The draft endpoint failed to return a complete answer."""


class DraftTokenLimitError(DraftError):
    """The draft used its full output budget."""


def chat_draft(
    query: str,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    api_key: str | None = None,
    on_delta: DraftDelta | None = None,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{base_url.rstrip('/')}/chat/completions"
    request = {
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "max_tokens": max_tokens,
    }
    timeout = httpx.Timeout(900.0, connect=10.0)
    try:
        if on_delta is not None:
            with httpx.stream(
                "POST", url, headers=headers, json={**request, "stream": True}, timeout=timeout
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-type", "").startswith("application/json"):
                    response.read()
                    return _completed_draft(response, on_delta)
                return _streamed_draft(response.iter_lines(), on_delta)

        response = httpx.post(url, headers=headers, json=request, timeout=timeout)
        response.raise_for_status()
        return _completed_draft(response)
    except httpx.HTTPStatusError as error:
        raise DraftError(f"The endpoint returned HTTP {error.response.status_code}.") from error
    except httpx.TimeoutException as error:
        raise DraftError("The endpoint timed out.") from error
    except (httpx.RequestError, httpx.InvalidURL) as error:
        raise DraftError(
            "Could not reach the endpoint. Check its URL and your connection."
        ) from error


def _completed_draft(response: httpx.Response, on_delta: DraftDelta | None = None) -> str:
    try:
        choice = response.json()["choices"][0]
        finish_reason = choice.get("finish_reason")
        message = choice["message"]
        content = message["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise DraftError("The endpoint returned an invalid chat completion.") from error

    answer = _checked_content(content, finish_reason)
    if on_delta is not None:
        _emit_delta(message, on_delta)
    return answer


def _streamed_draft(lines: Iterable[str], on_delta: DraftDelta) -> str:
    answer: list[str] = []
    finish_reason = None
    try:
        for data in sse_data(lines):
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise DraftError("The endpoint reported a streaming error.")
            choices = chunk["choices"]
            if not choices:
                continue
            choice = choices[0]
            content = _emit_delta(choice["delta"], on_delta)
            answer.append(content)
            finish_reason = choice.get("finish_reason") or finish_reason
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise DraftError("The endpoint returned an invalid draft stream.") from error

    if finish_reason not in ("stop", "length"):
        raise DraftError("The endpoint did not complete the draft.")
    return _checked_content("".join(answer), finish_reason)


def _emit_delta(message: dict[str, object], on_delta: DraftDelta) -> str:
    for field in ("reasoning", "reasoning_content"):
        reasoning = message.get(field)
        if isinstance(reasoning, str) and reasoning:
            on_delta("reasoning", reasoning)
            break
    content = message.get("content")
    if isinstance(content, str) and content:
        on_delta("draft", content)
        return content
    return ""


def _checked_content(content: object, finish_reason: object) -> str:
    if finish_reason == "length":
        raise DraftTokenLimitError("The draft hit the output token limit. Increase --draft-max-tokens.")
    if not isinstance(content, str) or not content.strip():
        raise DraftError("The endpoint returned no answer text.")
    return content
