from .graph import Decision

DEMO_QUESTION = "Why do the first n odd numbers sum to n²?"
DEMO_DRAFT = (
    "Build a square out of dots. Start with one dot, then add 3 dots to make a 2 × 2 square, "
    "then 5 to make a 3 × 3 square. Each step to a k × k square adds a row and a column "
    "that share one corner, for a total of 2k − 1 new dots. After n steps there are n² dots."
)


def draft(query: str) -> str:
    if query.strip() == DEMO_QUESTION:
        return DEMO_DRAFT
    return f"Stub draft for {query!r}."


def judge(_query: str, _draft: str, *, decision: Decision) -> dict[str, str]:
    verdict = {"decision": decision, "rationale": f"Selected stub path: {decision}."}
    if decision == "tweak":
        verdict["guidance"] = (
            "Clarify how the shared corner affects the count."
            if _query.strip() == DEMO_QUESTION else "Add a brief clarification."
        )
    return verdict


def tweak(_query: str, draft: str, guidance: str) -> str:
    if _query.strip() == DEMO_QUESTION and draft == DEMO_DRAFT:
        return f"{draft}\n\nThe new row and column each have k dots. The shared corner counts once, so the layer has k + k − 1 dots."
    return f"{draft}\nStub revision applied guidance: {guidance}"


def regenerate(query: str) -> str:
    if query.strip() == DEMO_QUESTION:
        return (
            "**Proof by induction.** The first odd number is 1 = 1². If the first n odd numbers "
            "sum to n², adding the next odd number gives n² + (2n + 1) = (n + 1)². "
            "So the identity holds for every positive integer n."
        )
    return f"Stub answer written from scratch for {query!r}."
