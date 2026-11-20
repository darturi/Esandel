import httpx

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "Qwen/Qwen3.8-27B"
DEFAULT_MAX_TOKENS = 16_384


class DraftError(RuntimeError):
    """The draft endpoint failed to return a complete answer."""


def chat_draft(
    query: str,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    api_key: str | None = None,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "max_tokens": max_tokens,
            },
            timeout=httpx.Timeout(900.0, connect=10.0),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise DraftError(f"The endpoint returned HTTP {error.response.status_code}.") from error
    except httpx.TimeoutException as error:
        raise DraftError("The endpoint timed out.") from error
    except (httpx.RequestError, httpx.InvalidURL) as error:
        raise DraftError(
            "Could not reach the endpoint. Check its URL and your connection."
        ) from error

    try:
        choice = response.json()["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise DraftError("The endpoint returned an invalid chat completion.") from error

    if finish_reason == "length":
        raise DraftError("The draft hit the output token limit. Increase --draft-max-tokens.")
    if not isinstance(content, str) or not content.strip():
        raise DraftError("The endpoint returned no answer text.")
    return content
