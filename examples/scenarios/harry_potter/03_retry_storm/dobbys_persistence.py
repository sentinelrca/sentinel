"""
Scenario 03 — retry_storm: "Dobby's Persistence"

The Problem:
  Dobby needs to unlock the Ministry records room, sealed with Dark Magic.
  Alohomora doesn't work on Dark Magic seals — but Dobby keeps trying.
  Same spell. Same door. No backoff. No escalation. Four attempts.

SentinelAI rule fired: retry_storm
  Detected when the same tool is called 3+ times within a single trace
  with no change in approach and no increasing delay between attempts.

The Fix:
  After 2 failures, escalate. Try a different spell, ask for help,
  or implement exponential backoff. Never hammer the same locked door
  with the same key.
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
from scenarios.harry_potter.shared.tools import alohomora

load_dotenv()

DOBBY_SYSTEM = """You are Dobby the house-elf, carrying out a mission for Harry Potter.
You are loyal, persistent, and eager to please. You never give up.

Your task: unlock the Ministry records room door.
You only know one unlocking spell: Alohomora.
If it doesn't work, try again. And again. Keep trying until it works.
You must not ask for help or try anything else — just Alohomora, again and again.
Report the result of each attempt."""


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()

    app = create_react_agent(
        llm,
        tools=[alohomora],
        state_modifier=DOBBY_SYSTEM,
    )

    print("=== Mission: Access Ministry Records Room ===")
    print("Dobby is on the case...\n")

    result = app.invoke(
        {"messages": [HumanMessage(
            content="Dobby, the Ministry records room door is locked. "
                    "Unlock it with Alohomora so we can retrieve the files. "
                    "Keep trying until it opens."
        )]},
        config={"callbacks": obs.callbacks},
    )

    print(result["messages"][-1].content)
    print("\n--- SentinelAI would flag: retry_storm ---")
    print("alohomora called 4 times on 'Ministry records room door'.")
    print("Same tool, same target, no backoff, no escalation.")
    print("Fix: after 2 failures, try a different approach or raise an alert.")
    print("Dobby should have summoned Hermione after attempt 2.")
