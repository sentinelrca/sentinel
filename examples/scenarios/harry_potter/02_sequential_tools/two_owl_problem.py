"""
Scenario 02 — sequential_tools: "The Two-Owl Problem"

The Problem:
  Before the raid, Ron needs to:
    1. Check the Marauder's Map for enemy positions
    2. Send an owl to Dumbledore with an update
  These are completely independent. Neither depends on the other.
  But Ron dispatches them one at a time — map first, owl second.
  Total time: ~0.9s. Should be ~0.5s in parallel.

SentinelAI rule fired: sequential_tools
  Detected when two TOOL_INVOKE spans share the same parent span,
  have non-overlapping timestamps, and carry no data dependency.

The Fix:
  Run independent tools in parallel. In LangGraph, use a fan-out node
  or async tool execution. Fred and George always send their owls together.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).parents[3]))
from shared.llm import get_llm
from shared.observability import configure
from scenarios.harry_potter.shared.tools import marauders_map, owl_post

load_dotenv()

RON_SYSTEM = """You are Ron Weasley, DA field coordinator.
You are given two pre-dispatch tasks to do before a raid.
Do them in order — first the Marauder's Map check, then the owl dispatch.
Report what you found from the map, then confirm the owl was sent."""


class State(TypedDict):
    messages: list
    map_result: str
    owl_result: str


def ron_prepares(state: State, config: RunnableConfig) -> dict:
    """Ron's pre-raid coordination node — calls both tools sequentially."""
    # Step 1: check the map
    map_result = marauders_map.invoke(
        {"area": "Astronomy Tower"},
        config=config,
    )

    # Step 2: send the owl — could have been in parallel, but Ron goes one at a time
    owl_result = owl_post.invoke(
        {"recipient": "Dumbledore", "message": "DA team is assembled and ready for the raid."},
        config=config,
    )
    return {"map_result": map_result, "owl_result": owl_result}


def ron_reports(state: State, config: RunnableConfig) -> dict:
    """Ron summarises the result using the LLM."""
    llm = get_llm()
    messages = [
        SystemMessage(RON_SYSTEM),
        HumanMessage(
            f"Map check result: {state['map_result']}\n"
            f"Owl dispatch result: {state['owl_result']}\n"
            "Summarise what you did and what we know before the raid."
        ),
    ]
    response = llm.with_config(config).invoke(messages)
    return {"messages": [response]}


if __name__ == "__main__":
    obs = configure()

    graph = StateGraph(State)
    graph.add_node("ron_prepares", ron_prepares)
    graph.add_node("ron_reports", ron_reports)
    graph.set_entry_point("ron_prepares")
    graph.add_edge("ron_prepares", "ron_reports")
    graph.add_edge("ron_reports", END)
    app = graph.compile()

    print("=== Mission Prep: Pre-Raid Intelligence Gathering ===")
    print("Ron is coordinating... (watch the tool call order)\n")

    result = app.invoke(
        {"messages": [], "map_result": "", "owl_result": ""},
        config={"callbacks": obs.callbacks},
    )

    print(result["messages"][-1].content)
    print("\n--- SentinelAI would flag: sequential_tools ---")
    print("marauders_map and owl_post share the same parent span (ron_prepares).")
    print("Neither depends on the other. They ran back-to-back instead of in parallel.")
    print("Fix: use async tool execution or a fan-out node. Fred and George never queue.")
