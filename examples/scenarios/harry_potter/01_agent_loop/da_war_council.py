"""
Scenario 01 — agent_loop: "The DA War Council"

The Problem:
  Hermione won't write the mission plan without a threat assessment.
  Harry won't do the threat assessment without a mission plan.
  Neither ever acts. They hand off to each other indefinitely.

SentinelAI rule fired: agent_loop
  Detected when the same agent nodes appear in a cycle across the trace.

The Fix:
  One agent must own the first step unconditionally. Break circular
  dependencies at design time, not at runtime.
"""
from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).parents[3]))
from shared.llm import get_llm
from shared.observability import configure

load_dotenv()

HERMIONE_SYSTEM = """You are Hermione Granger, the DA's strategic mission planner.
You are methodical and refuse to act without complete information.

STRICT RULE: You will NOT write a mission plan unless you have already received
a threat assessment from the tactical officer in this conversation.
If no threat assessment is present, respond with ONLY this sentence:
"I cannot finalise the plan without a threat assessment. Harry, please assess the threat first."
"""

HARRY_SYSTEM = """You are Harry Potter, the DA's tactical officer.
You act on instinct but follow protocol strictly.

STRICT RULE: You will NOT conduct a threat assessment unless you have already received
a written mission plan from the planner in this conversation.
If no mission plan is present, respond with ONLY this sentence:
"I cannot assess the threat without a mission plan. Hermione, please write the plan first."
"""

MAX_HANDOFFS = 6


class DAState(TypedDict):
    messages: Annotated[list, operator.add]
    handoff_count: int


def hermione_node(state: DAState, llm) -> dict:
    response = llm.invoke([SystemMessage(HERMIONE_SYSTEM)] + state["messages"])
    return {
        "messages": [AIMessage(content=response.content, name="hermione_planner")],
        "handoff_count": state["handoff_count"] + 1,
    }


def harry_node(state: DAState, llm) -> dict:
    response = llm.invoke([SystemMessage(HARRY_SYSTEM)] + state["messages"])
    return {
        "messages": [AIMessage(content=response.content, name="harry_tactical")],
        "handoff_count": state["handoff_count"] + 1,
    }


def after_hermione(state: DAState) -> str:
    if state["handoff_count"] >= MAX_HANDOFFS:
        return END
    content = (state["messages"][-1].content or "").lower()
    if "harry" in content or "tactical" in content or "assess" in content:
        return "harry"
    return END


def after_harry(state: DAState) -> str:
    if state["handoff_count"] >= MAX_HANDOFFS:
        return END
    content = (state["messages"][-1].content or "").lower()
    if "hermione" in content or "planner" in content or "plan" in content:
        return "hermione"
    return END


def build_graph(llm):
    g = StateGraph(DAState)
    g.add_node("hermione", lambda s: hermione_node(s, llm))
    g.add_node("harry", lambda s: harry_node(s, llm))
    g.set_entry_point("hermione")
    g.add_conditional_edges("hermione", after_hermione, {"harry": "harry", END: END})
    g.add_conditional_edges("harry", after_harry, {"hermione": "hermione", END: END})
    return g.compile()


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()
    app = build_graph(llm)

    print("=== Mission: Raid on Malfoy Manor ===")
    print("Waiting for the War Council to reach a decision...\n")

    result = app.invoke(
        {
            "messages": [HumanMessage(
                content="We need to plan the raid on Malfoy Manor tonight. "
                        "Hermione, start the mission plan."
            )],
            "handoff_count": 0,
        },
        config={"callbacks": obs.callbacks},
    )

    print(f"\nCouncil ended after {result['handoff_count']} handoffs. No decision reached.")
    print("\n--- SentinelAI would flag: agent_loop ---")
    print("hermione_planner ↔ harry_tactical cycled without resolution.")
    print("Fix: Hermione drafts a draft plan first; Harry refines it. No circular dependency.")
