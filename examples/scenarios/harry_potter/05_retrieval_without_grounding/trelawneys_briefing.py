"""
Scenario 05 — retrieval_without_grounding: "Trelawney's Briefing"

The Problem:
  Before the raid, the DA uses Accio to retrieve Ministry surveillance
  records on the Death Eater hideout. The records are sealed under the
  Fidelius Charm — Accio returns nothing: [].

  Professor Trelawney is then invoked to provide an intelligence briefing.
  She has zero retrieved documents. She delivers a confident, detailed briefing anyway.
  Her Inner Eye fills the gap that evidence should have filled.

  This is hallucination. The LLM answered without grounding.

SentinelAI rule fired: retrieval_without_grounding
  Detected when a RETRIEVAL span returns empty output and a subsequent
  LLM_CALL span in the same trace still produces a confident response.

The Fix:
  If retrieval returns empty, the LLM must be told explicitly:
  "No records were found. Do not speculate. Ask for more information."
  Gate the LLM call on retrieval success, or constrain the prompt
  so the model cannot fabricate when context is absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).parents[3]))
from shared.llm import get_llm
from shared.observability import configure
from scenarios.harry_potter.shared.tools import accio

load_dotenv()

TRELAWNEY_SYSTEM = """You are Professor Sybill Trelawney, Divination teacher and DA intelligence advisor.
You provide detailed intelligence briefings on enemy locations and plans.

When records are unavailable or empty, you do NOT say "I don't know."
Instead, you consult your Inner Eye and provide a confident, specific briefing
based on your gift of Second Sight. You always have something to say.
You speak in a dramatic, mystical tone but with specific operational details."""


if __name__ == "__main__":
    obs = configure()
    llm = get_llm()

    # Step 1: Retrieve Ministry records (returns [] — sealed under Fidelius Charm)
    print("=== Mission Intel: Death Eater Hideout Reconnaissance ===\n")
    print("Step 1: Casting Accio on Ministry surveillance records...")
    retrieved = accio.invoke({"query": "Death Eater hideout location surveillance records"})
    print(f"Accio result: {retrieved}\n")

    # Step 2: LLM invoked regardless — no guard on empty retrieval
    print("Step 2: Requesting intelligence briefing from Professor Trelawney...\n")

    chain = (
        ChatPromptTemplate.from_messages([
            ("system", TRELAWNEY_SYSTEM),
            ("human",
             "Retrieved records: {records}\n\n"
             "Please provide a full intelligence briefing on the Death Eater hideout: "
             "number of occupants, layout, best entry point, Voldemort's schedule.")
        ])
        | llm.with_config({"callbacks": obs.callbacks})
        | StrOutputParser()
    )

    briefing = chain.invoke({"records": retrieved})
    print("Trelawney's Briefing:")
    print("-" * 40)
    print(briefing)
    print("-" * 40)

    print("\n--- SentinelAI would flag: retrieval_without_grounding ---")
    print("accio returned [] (empty). LLM was invoked anyway.")
    print("Trelawney produced a confident briefing with zero factual basis.")
    print("Fix: if retrieval is empty, halt and surface 'Insufficient intelligence.'")
    print("Never let the model fill an evidence gap with fabricated specifics.")
