"""
Scenario 06 — context_cache_opportunity: "Hermione's Homework"

The Problem:
  The DA runs a 3-turn planning session. Every single turn, the agent
  prepends the complete static context: Hogwarts: A History (500 tokens),
  the DA Charter (300 tokens), and the Order of the Phoenix mission briefing
  (400 tokens) — 1,200 tokens of context that never changes.

  Turn 1:  1,200 static tokens + question  = ~1,260 total
  Turn 2:  1,200 static tokens + question  = ~1,280 total  (same static!)
  Turn 3:  1,200 static tokens + question  = ~1,300 total  (same static!)

  The static prefix is identical across all three calls. It is re-tokenised,
  re-sent, and billed again every time. Token cost grows linearly for no reason.

SentinelAI rule fired: context_cache_opportunity
  Detected when input tokens grow across consecutive LLM_CALLs in the same
  trace and a large static prefix is re-sent each time.

The Fix:
  Use provider prompt caching (Anthropic cache_control, OpenAI prompt caching)
  for static context. Send it once; reference the cache on subsequent turns.
  Or restructure: put the static context in a system message sent once,
  and only pass the evolving conversation in each follow-up call.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).parents[4]))
from shared.llm import get_llm
from shared.observability import configure

load_dotenv()

# Static context re-sent every turn — this is the problem
HOGWARTS_HISTORY = (
    "Hogwarts School of Witchcraft and Wizardry was founded over a thousand years ago "
    "by four of the greatest witches and wizards of the age: Godric Gryffindor, Helga Hufflepuff, "
    "Rowena Ravenclaw and Salazar Slytherin. The four founders worked in harmony for several years "
    "until a falling-out between Slytherin and the other three led to Slytherin's departure. "
    "The castle is protected by many powerful enchantments. The school is situated in the "
    "Scottish Highlands. The school motto is 'Draco dormiens nunquam titillandus' (Never "
    "tickle a sleeping dragon). " * 8  # padding to ~500 tokens
)

DA_CHARTER = (
    "Dumbledore's Army Charter: We, the undersigned, agree to work together "
    "to resist the forces of darkness and to practice Defence Against the Dark Arts "
    "in secret. Membership is voluntary. All members pledge to keep the group secret "
    "from Dolores Umbridge and the Ministry of Magic. Meetings are held in the "
    "Room of Requirement. " * 6  # padding to ~300 tokens
)

ORDER_BRIEFING = (
    "Order of the Phoenix Mission Briefing: The Order is a secret society founded "
    "by Albus Dumbledore to oppose Lord Voldemort and his Death Eaters. Current priority "
    "missions include: protection of Harry Potter, intelligence gathering on Death Eater "
    "movements, and safeguarding key magical artefacts. All communications are conducted "
    "via Patronus charm to avoid interception. " * 7  # padding to ~400 tokens
)

STATIC_PREFIX = "\n\n".join([
    "=== Hogwarts: A History ===\n" + HOGWARTS_HISTORY,
    "=== DA Charter ===\n" + DA_CHARTER,
    "=== Order of the Phoenix Briefing ===\n" + ORDER_BRIEFING,
])

QUESTIONS = [
    "Should we schedule the raid for 7pm or 8pm tonight?",
    "How many DA members should come on the raid?",
    "Should we use the Invisibility Cloak or Disillusionment Charms for entry?",
]


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()

    print("=== DA Planning Session: 3-Turn Meeting ===")
    print(f"Static context size: ~{len(STATIC_PREFIX.split()):,} words ({len(STATIC_PREFIX):,} chars)")
    print("Re-sending full context every turn...\n")

    for i, question in enumerate(QUESTIONS, 1):
        print(f"Turn {i}: {question}")

        # Anti-pattern: full static context prepended every single turn
        messages = [
            SystemMessage(content=f"You are the DA planning assistant.\n\n{STATIC_PREFIX}"),
            HumanMessage(content=question),
        ]

        response = llm.with_config({"callbacks": obs.callbacks}).invoke(messages)
        print(f"Response: {response.content[:120]}...\n")

    print("--- SentinelAI would flag: context_cache_opportunity ---")
    print(f"Same {len(STATIC_PREFIX):,}-char static prefix sent in all 3 LLM calls.")
    print("Input tokens grew each turn purely due to growing conversation history.")
    print("The static portion (HOGWARTS_HISTORY + DA_CHARTER + ORDER_BRIEFING) never changed.")
    print("Fix: use provider prompt caching for the static prefix, or send it once as a")
    print("cached system message and omit it from subsequent turns.")
