from collections.abc import Callable, Mapping
from typing import Literal, Self, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, model_validator

Decision = Literal["accept", "tweak", "regenerate"]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Decision
    rationale: str = Field(min_length=1)
    guidance: str = ""

    @model_validator(mode="after")
    def require_guidance_for_tweak(self) -> Self:
        if self.decision == "tweak" and not self.guidance.strip():
            raise ValueError("a tweak verdict requires revision guidance")
        return self


class QueryInput(TypedDict):
    query: str


class AnswerUpdate(TypedDict, total=False):
    draft: str
    verdict: Verdict
    answer: str


class AnswerState(QueryInput, AnswerUpdate):
    pass


def build_graph(
    *,
    draft_model: Callable[[str], str],
    judge_model: Callable[[str, str], Mapping[str, object] | Verdict],
    tweak_model: Callable[[str, str, str], str],
    regenerate_model: Callable[[str], str],
):
    def draft(state: QueryInput) -> AnswerUpdate:
        return {"draft": draft_model(state["query"])}

    def judge(state: AnswerState) -> AnswerUpdate:
        verdict = judge_model(state["query"], state["draft"])
        return {"verdict": Verdict.model_validate(verdict)}

    def route(state: AnswerState) -> Decision:
        return state["verdict"].decision

    def accept(state: AnswerState) -> AnswerUpdate:
        return {"answer": state["draft"]}

    def tweak(state: AnswerState) -> AnswerUpdate:
        answer = tweak_model(
            state["query"], state["draft"], state["verdict"].guidance
        )
        return {"answer": answer}

    def regenerate(state: AnswerState) -> AnswerUpdate:
        return {"answer": regenerate_model(state["query"])}

    builder = StateGraph(AnswerState, input_schema=QueryInput)
    builder.add_node("draft", draft)
    builder.add_node("judge", judge)
    builder.add_node("accept", accept)
    builder.add_node("tweak", tweak)
    builder.add_node("regenerate", regenerate)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "judge")
    builder.add_conditional_edges("judge", route)
    builder.add_edge("accept", END)
    builder.add_edge("tweak", END)
    builder.add_edge("regenerate", END)
    return builder.compile()
