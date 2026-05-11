"""
Harry Potter-themed tools for SentinelAI example scenarios.

Each tool maps a real operation (retrieval, auth, long computation, async messaging)
to a spell or magical action from the HP universe. The naming is purely illustrative —
the underlying failure patterns are identical to those in real AI systems.
"""
from __future__ import annotations

import time
from collections import defaultdict

from langchain_core.tools import tool

# Tracks per-target failure counts for retry scenarios
_alohomora_attempts: dict[str, int] = defaultdict(int)


@tool
def accio(query: str) -> str:
    """Summon information from Ministry of Magic archives. Returns [] if records are sealed."""
    time.sleep(0.3)
    sealed_terms = {"malfoy", "death eater", "voldemort", "horcrux", "dark mark"}
    if any(term in query.lower() for term in sealed_terms):
        # Sealed under Fidelius Charm — retrieval returns nothing
        return "[]"
    return (
        f"Ministry records for '{query}': "
        "[Ref-1: Known associates] [Ref-2: Last sighting] [Ref-3: Threat classification]"
    )


@tool
def alohomora(target: str) -> str:
    """Attempt to unlock a door or barrier with Alohomora. Fails on Dark-Magic seals."""
    _alohomora_attempts[target] += 1
    attempt = _alohomora_attempts[target]
    if attempt < 4:
        return (
            f"Attempt {attempt}: The {target} holds firm. "
            "The Dark Magic seal resists Alohomora."
        )
    _alohomora_attempts[target] = 0
    return f"The {target} swings open. Alohomora succeeded on attempt {attempt}."


@tool
def owl_post(recipient: str, message: str) -> str:
    """Dispatch an owl to deliver a message. Takes ~0.5s for owl to depart."""
    time.sleep(0.5)
    return f"Owl dispatched to {recipient}: '{message[:60]}{'...' if len(message) > 60 else ''}'"


@tool
def marauders_map(area: str) -> str:
    """Check the Marauder's Map for known figures in the target area."""
    time.sleep(0.4)
    return (
        f"Marauder's Map — {area}: "
        "3 known figures present, no Filch within 50m, east corridor clear."
    )


@tool
def brew_potion(potion: str) -> str:
    """Brew a potion. Polyjuice Potion takes significantly longer than others."""
    if "polyjuice" in potion.lower():
        time.sleep(4.0)  # intentional latency spike
        return "Polyjuice Potion brewed. Stable for 60 minutes. Do not mix with lacewing flies."
    time.sleep(0.4)
    return f"{potion} brewed successfully."


@tool
def wingardium_leviosa(target: str) -> str:
    """Levitate and position supplies or objects. Near-instant."""
    time.sleep(0.2)
    return f"{target} levitated and positioned successfully. Swish and flick."


@tool
def lumos(area: str) -> str:
    """Illuminate an area and report what is visible."""
    time.sleep(0.1)
    return f"Lumos — {area}: no immediate threats visible, path is clear."


@tool
def pensieve_store(key: str, memory: str) -> str:
    """Store a memory or context note in the Pensieve for later recall."""
    time.sleep(0.1)
    return f"Memory '{key}' stored in the Pensieve."


@tool
def pensieve_recall(key: str) -> str:
    """Retrieve a previously stored memory from the Pensieve."""
    time.sleep(0.1)
    # In a real implementation this would read from a persistent store
    return f"Pensieve: no stored memory found for '{key}'. Was it ever stored?"


@tool
def expecto_patronum(threat: str) -> str:
    """Cast Expecto Patronum as a defensive guardrail against a threat."""
    time.sleep(0.3)
    return f"Patronus Charm cast. {threat} repelled. Safe to proceed."


def reset_tools() -> None:
    """Reset all stateful tool counters. Call between test runs."""
    _alohomora_attempts.clear()
