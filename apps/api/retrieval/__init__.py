"""Retrieval — the provider-independent half of TRD §6, built while the provider is undecided.

WHAT IS HERE, AND WHY ALL OF IT IS TRUE WHICHEVER WAY THE D-28 BAKE-OFF GOES:

- **`capabilities.py`** — the one selector and the one named refusal, `engine/capabilities.py`'s
  shape (D-93) applied to retrieval.
- **`routing.py`** — the deterministic table that decides which questions earn a retrieval
  at all. It is about the QUESTION, not about the store.
- **`cache.py`** — the T1 thin cache, keyed per tenant and stamped with the knowledge's own
  version, so an owner correcting their opening hours cannot be answered from a cached
  yesterday.
- **`compiled_facts.py`** — the ONE implementation of the port today: T0, the hot facts
  already compiled into the agent's system prompt (`docs/TRD.md:948` — "in-call retrieval
  is T0 and nothing else").
- **`service.py`** — the one entry point every caller uses.

WHAT IS DELIBERATELY NOT HERE, because the bake-off has not run: no embeddings, no vector
store, no provider client, no migration, and no `kb_chunks`. The port lives in
`calevate_shared.retrieval`; adding a provider is a new module in this package, a branch in
`service.get_retriever`, and no change to a single caller.

WHAT IS NOT HERE FOR A DIFFERENT REASON: an in-call route. `tests/kb_tiers_test.py` pins
`apps/voice-runtime`'s mounted routes as an equality, because a retrieval endpoint on the
audio path reverses D-33 and needs TRD §6.2's round-trip measurement first. Nothing in this
package mounts anything or is imported by voice-runtime.
"""
