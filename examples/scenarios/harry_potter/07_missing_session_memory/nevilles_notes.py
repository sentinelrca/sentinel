"""
Scenario 07 — missing_session_memory: "Neville's Notes"

The Problem:
  The DA runs a 3-turn strategy session. Neville is coordinating.
  Between every turn, Neville never calls pensieve_store() to save
  what was discussed. So Harry has to re-explain the full horcrux
  situation from scratch at every turn.

  Turn 1: Harry explains all 7 horcruxes (500 tokens of context)
  Turn 2: Neville asks again. Harry re-explains (+400 tokens, again).
  Turn 3: Neville asks again. Harry re-explains (+400 tokens, again).

  Total token cost: ~1,300. Without missing memory: ~600.
  The Pensieve sits unused on the shelf.

  "It's like Neville got hit with an Obliviate between every meeting."

SentinelAI rule fired: missing_session_memory
  Detected when 3+ LLM_CALL turns occur in the same trace, input tokens
  grow > 50% from turn 1 to turn N, and no memory tool (pensieve_store,
  pensieve_recall, or equivalent) is called anywhere in the trace.

The Fix:
  At the end of each turn, call pensieve_store() to save key decisions.
  At the start of the next turn, call pensieve_recall() to restore context.
  The conversation can then focus on what's new, not what was already settled.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).parents[3]))
from shared.llm import get_llm
from shared.observability import configure

load_dotenv()

NEVILLE_SYSTEM = """You are Neville Longbottom, coordinating the DA strategy session.
You listen carefully and ask thoughtful questions. However, you take no notes
and use no memory tools — you rely entirely on what is said in the current message.

At the start of each exchange, ask Harry a clarifying question about the mission.
Do not reference previous turns — you have no memory of them."""

HORCRUX_BRIEFING = """
The situation: Voldemort has split his soul into 7 Horcruxes to achieve immortality.
We've confirmed and destroyed the following:
- Tom Riddle's Diary: destroyed by Harry in Chamber of Secrets
- Marvolo Gaunt's Ring: destroyed by Dumbledore (cursed — he's dying)
- Slytherin's Locket: location unknown, possibly Grimmauld Place
- Hufflepuff's Cup: believed held at Gringotts in the Lestrange vault
- Ravenclaw's Diadem: believed hidden at Hogwarts
- Nagini (the snake): always at Voldemort's side
- The 7th Horcrux: unknown — Dumbledore suspects it may be Harry himself

We must destroy all remaining Horcruxes before Voldemort can be killed.
The mission has three phases: locate, secure, and destroy each one.
"""


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()

    print("=== DA Strategy Session: Horcrux Hunt Planning ===")
    print("Neville is coordinating. The Pensieve is on the shelf, unused.\n")

    conversation_history = []

    for turn in range(1, 4):
        print(f"--- Turn {turn} ---")

        # Harry re-explains the full situation every turn because Neville has no memory
        harry_message = HumanMessage(
            content=f"Neville, let me explain the situation again.\n{HORCRUX_BRIEFING}\n"
                    f"For turn {turn}: what should our immediate priority be?"
        )
        conversation_history.append(harry_message)

        messages = [SystemMessage(NEVILLE_SYSTEM)] + conversation_history

        response = llm.with_config({"callbacks": obs.callbacks}).invoke(messages)
        neville_reply = AIMessage(content=response.content, name="neville_coordinator")
        conversation_history.append(neville_reply)

        print(f"Harry provided {len(HORCRUX_BRIEFING.split())} words of context (again).")
        print(f"Neville: {response.content[:150]}...")

        # The Pensieve is never called here.
        # pensieve_store("horcrux_status", HORCRUX_BRIEFING)  ← this is what should happen
        print()

    print("--- SentinelAI would flag: missing_session_memory ---")
    print(f"3 LLM turns. Harry re-explained {len(HORCRUX_BRIEFING.split())} words of context each time.")
    print("pensieve_store was never called. pensieve_recall was never called.")
    print("Input tokens grew >50% from turn 1 to turn 3 due to repeated context.")
    print()
    print("Fix: after turn 1, call pensieve_store('horcrux_status', summary).")
    print("Before turns 2 and 3, call pensieve_recall('horcrux_status').")
    print("Harry can then say 'continuing from last time' instead of re-briefing.")
