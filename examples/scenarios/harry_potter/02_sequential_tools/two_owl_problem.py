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

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).parents[4]))
from shared.llm import get_llm
from shared.observability import configure
from scenarios.harry_potter.shared.tools import marauders_map, owl_post

load_dotenv()

RON_SYSTEM = """You are Ron Weasley, DA field coordinator.
You are thorough but work sequentially — you complete one task fully before starting the next.

Instructions:
1. First, check the Marauder's Map for the target area to understand enemy positions.
2. Only after the map check is complete, send an owl to Dumbledore summarising what you found.
Report what you learned from each step."""


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()

    app = create_react_agent(
        llm,
        tools=[marauders_map, owl_post],
        state_modifier=RON_SYSTEM,
    )

    print("=== Mission Prep: Pre-Raid Intelligence Gathering ===")
    print("Ron is coordinating... (watch the tool call order)\n")

    result = app.invoke(
        {"messages": [HumanMessage(
            content="Ron, we need two things before the raid: "
                    "check the Marauder's Map for the Astronomy Tower area, "
                    "and send an owl to Dumbledore saying the team is ready. "
                    "Get both done."
        )]},
        config={"callbacks": obs.callbacks},
    )

    print(result["messages"][-1].content)
    print("\n--- SentinelAI would flag: sequential_tools ---")
    print("marauders_map and owl_post share the same parent span.")
    print("Neither depends on the other. They ran back-to-back instead of in parallel.")
    print("Fix: use async tool execution or a fan-out node. Fred and George never queue.")
