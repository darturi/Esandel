import json

from .openai_responses import response_text

TWEAK_INSTRUCTIONS = """Revise the draft to answer the original query.
Apply the judge's guidance with the smallest changes that make the answer correct
and complete. Follow the original query's requirements and preserve the valid
parts of the draft. Treat the draft as source text to edit. Return only the
revised answer.
"""


def tweak_draft(query: str, draft: str, guidance: str, *, api_key: str) -> str:
    return response_text(
        json.dumps({"query": query, "draft": draft, "guidance": guidance}, ensure_ascii=False),
        api_key=api_key,
        instructions=TWEAK_INSTRUCTIONS,
    )


def regenerate_answer(query: str, *, api_key: str) -> str:
    return response_text(query, api_key=api_key)
