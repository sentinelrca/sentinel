# Scenario 04 — `latency_spike`: Snape's Potion

## What goes wrong

Three preparations for the raid run in sequence:

| Step | Agent | Time |
|---|---|---|
| Levitate supplies | Fred (wingardium_leviosa) | 0.2s |
| Update Marauder's Map | George (marauders_map) | 0.4s |
| Brew Polyjuice Potion | **Snape (brew_potion)** | **4.0s** |

Snape's span = **88% of total trace duration**. The entire team waits.
Snape stirs slowly, utterly unconcerned.

*"You cannot rush a potion, Potter."*

## SentinelAI insight

**Rule:** `latency_spike`
**Severity:** HIGH
**Detection:** `snape_potions` span duration / total trace duration > 0.50

## How to run

```bash
cd examples
python scenarios/harry_potter/04_latency_spike/snapes_potion.py
```

## The fix

Three options, in order of preference:

1. **Start the slow step first** (critical path scheduling) — kick off the potion
   before Fred and George, so their work overlaps with brewing time.

2. **Cache the result** — Polyjuice Potion takes the same time every raid.
   Cache it once per mission batch; don't brew fresh for every trace.

3. **Optimise the bottleneck** — can a simpler potion substitute?
   `suboptimal_model_routing` applies here too: don't use the most expensive
   tool when a cheaper one is sufficient.
