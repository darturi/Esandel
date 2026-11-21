import json
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from .sse import sse_data

MODEL = "gpt-6.2-sol"
RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIResponseError(RuntimeError):
    """OpenAI failed to return a complete text response."""


def response_text(
    input_text: str,
    *,
    api_key: str,
    instructions: str | None = None,
    text_format: dict[str, object] | None = None,
    max_output_tokens: int = 16_384,
    on_delta: Callable[[str], None] | None = None,
) -> str:
    request: dict[str, object] = {
        "model": MODEL,
        "input": input_text,
        "reasoning": {"effort": "medium"},
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    if instructions is not None:
        request["instructions"] = instructions
    if text_format is not None:
        request["text"] = {"format": text_format}

    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = httpx.Timeout(300.0, connect=10.0)
    try:
        if on_delta is not None:
            request["stream"] = True
            with httpx.stream(
                "POST", RESPONSES_URL, headers=headers, json=request, timeout=timeout
            ) as response:
                response.raise_for_status()
                return _streamed_text(response.iter_lines(), on_delta)

        response = httpx.post(RESPONSES_URL, headers=headers, json=request, timeout=timeout)
        response.raise_for_status()
        return _completed_text(response.json())
    except httpx.HTTPStatusError as error:
        raise OpenAIResponseError(f"OpenAI returned HTTP {error.response.status_code}.") from error
    except httpx.TimeoutException as error:
        raise OpenAIResponseError("OpenAI timed out.") from error
    except httpx.RequestError as error:
        raise OpenAIResponseError("Could not reach OpenAI. Check your connection.") from error
    except (ValueError, KeyError, TypeError) as error:
        raise OpenAIResponseError("OpenAI returned an invalid response.") from error


def _streamed_text(lines: Iterable[str], on_delta: Callable[[str], None]) -> str:
    for data in sse_data(lines):
        if data == "[DONE]":
            break
        event = json.loads(data)
        match event["type"]:
            case "response.output_text.delta":
                delta = event["delta"]
                if not isinstance(delta, str):
                    raise TypeError("Expected a text delta.")
                if delta:
                    on_delta(delta)
            case "response.completed":
                return _completed_text(event["response"])
            case "response.incomplete" | "response.failed" | "error":
                break
    raise OpenAIResponseError("OpenAI did not complete the response.")


def _completed_text(result: dict[str, Any]) -> str:
    if result["status"] != "completed":
        raise OpenAIResponseError("OpenAI did not complete the response.")

    text: list[str] = []
    for item in result["output"]:
        if item["type"] != "message":
            continue
        for part in item["content"]:
            if part["type"] == "refusal":
                raise OpenAIResponseError("OpenAI declined the request.")
            if part["type"] == "output_text":
                text.append(part["text"])
    answer = "".join(text)
    if not answer.strip():
        raise OpenAIResponseError("OpenAI returned no response text.")
    return answer
