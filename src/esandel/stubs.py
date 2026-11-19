from .graph import Decision


def draft(query: str) -> str:
    return f"Stub draft for {query!r}."


def judge(_query: str, _draft: str, *, decision: Decision) -> dict[str, str]:
    verdict = {"decision": decision, "rationale": f"Selected stub path: {decision}."}
    if decision == "tweak":
        verdict["guidance"] = "Add a brief clarification."
    return verdict


def tweak(_query: str, draft: str, guidance: str) -> str:
    return f"{draft}\nStub revision applied guidance: {guidance}"


def regenerate(query: str) -> str:
    return f"Stub answer written from scratch for {query!r}."
