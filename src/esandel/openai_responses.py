import httpx

MODEL = "gpt-6.2-sol"


class OpenAIResponseError(RuntimeError):
    """OpenAI failed to return a complete text response."""


def response_text(
    input_text: str,
    *,
    api_key: str,
    instructions: str | None = None,
    text_format: dict[str, object] | None = None,
    max_output_tokens: int = 16_384,
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

    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=request,
            timeout=httpx.Timeout(300.0, connect=10.0),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise OpenAIResponseError(f"OpenAI returned HTTP {error.response.status_code}.") from error
    except httpx.TimeoutException as error:
        raise OpenAIResponseError("OpenAI timed out.") from error
    except httpx.RequestError as error:
        raise OpenAIResponseError("Could not reach OpenAI. Check your connection.") from error

    try:
        result = response.json()
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
    except (ValueError, KeyError, TypeError) as error:
        raise OpenAIResponseError("OpenAI returned an invalid response.") from error

    if not answer.strip():
        raise OpenAIResponseError("OpenAI returned no response text.")
    return answer
