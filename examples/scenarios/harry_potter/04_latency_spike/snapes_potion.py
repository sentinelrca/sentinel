"""
Scenario 04 — latency_spike: "Snape's Potion"

The Problem:
  Three preparations run for the raid: levitating supplies (0.2s),
  updating the Marauder's Map (0.4s), and brewing Polyjuice Potion (4.0s).
  Snape's potion dominates — 88% of the total trace duration.
  Everyone waits. Snape stirs slowly, unmoved.

  "You cannot rush a potion, Potter."

SentinelAI rule fired: latency_spike
  Detected when a single span duration exceeds 50% of total trace duration.

The Fix:
  Identify the bottleneck and either: parallelise earlier steps so work
  happens while the slow step runs, optimise the slow step itself, or
  cache its output when the same computation repeats across traces.
"""
from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

sys.path.insert(0, str(Path(__file__).parents[4]))
from shared.llm import get_llm
from shared.observability import configure
from scenarios.harry_potter.shared.tools import brew_potion, marauders_map, wingardium_leviosa

load_dotenv()


class PrepState(TypedDict):
    messages: Annotated[list, operator.add]
    fred_done: bool
    george_done: bool
    snape_done: bool


def fred_node(state: PrepState, llm) -> dict:
    system = "You are Fred Weasley. Your job: levitate the raid supplies into position. Use wingardium_leviosa."
    tool_llm = llm.bind_tools([wingardium_leviosa])
    msg = tool_llm.invoke([SystemMessage(system), HumanMessage("Levitate the raid supplies.")])
    # Execute tool if called
    result = "Supplies levitated."
    if msg.tool_calls:
        result = wingardium_leviosa.invoke(msg.tool_calls[0]["args"])
    return {
        "messages": [AIMessage(content=f"Fred: {result}", name="fred_leviosa")],
        "fred_done": True,
    }


def george_node(state: PrepState, llm) -> dict:
    system = "You are George Weasley. Your job: update the Marauder's Map for the Astronomy Tower."
    tool_llm = llm.bind_tools([marauders_map])
    msg = tool_llm.invoke([SystemMessage(system), HumanMessage("Check the Astronomy Tower area.")])
    result = "Map updated."
    if msg.tool_calls:
        result = marauders_map.invoke(msg.tool_calls[0]["args"])
    return {
        "messages": [AIMessage(content=f"George: {result}", name="george_mapping")],
        "george_done": True,
    }


def snape_node(state: PrepState, llm) -> dict:
    system = (
        "You are Professor Snape. Your job: brew Polyjuice Potion for the raid team. "
        "Use brew_potion. You cannot be rushed."
    )
    tool_llm = llm.bind_tools([brew_potion])
    msg = tool_llm.invoke([SystemMessage(system), HumanMessage("Brew the Polyjuice Potion.")])
    result = "Potion brewing..."
    if msg.tool_calls:
        result = brew_potion.invoke(msg.tool_calls[0]["args"])
    return {
        "messages": [AIMessage(content=f"Snape: {result}", name="snape_potions")],
        "snape_done": True,
    }


def build_graph(llm):
    g = StateGraph(PrepState)
    g.add_node("fred", lambda s: fred_node(s, llm))
    g.add_node("george", lambda s: george_node(s, llm))
    g.add_node("snape", lambda s: snape_node(s, llm))

    # All three run sequentially from the same start — Snape's step dominates
    g.set_entry_point("fred")
    g.add_edge("fred", "george")
    g.add_edge("george", "snape")
    g.add_edge("snape", END)
    return g.compile()


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()
    app = build_graph(llm)

    print("=== Mission Prep: Three Tasks Before the Raid ===")
    print("Fred, George, and Snape are preparing...\n")
    print("(Snape's Polyjuice Potion will take ~4 seconds)")
    print()

    result = app.invoke(
        {
            "messages": [HumanMessage("Begin mission preparations.")],
            "fred_done": False,
            "george_done": False,
            "snape_done": False,
        },
        config={"callbacks": obs.callbacks},
    )

    for msg in result["messages"][1:]:
        print(msg.content)

    print("\n--- SentinelAI would flag: latency_spike ---")
    print("snape_potions span ≈ 88% of total trace duration.")
    print("Fred + George combined: ~0.6s. Snape: ~4.0s.")
    print("Fix: start the potion first (it's the critical path), or cache it across raids.")
