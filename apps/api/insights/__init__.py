"""Knowledge Gaps — the questions a live agent could not answer, surfaced as urgent.

A gap is not a bad call; it is a MISSING FACT. When an agent tells a caller "I don't
know that" or "let me have the team WhatsApp you", the same question will land on the
next caller too, so one deflection is a standing defect in the agent's knowledge rather
than a one-off. This module detects those moments from the redacted transcript, rolls
them up per (agent, topic), and lets the client teach the answer or dismiss the gap.

See `detection.py` for why the detector is deterministic and reads only redacted text,
`service.py` for the exactly-once idempotency and the race-safe aggregate, and `routes.py`
for the client-realm surface.
"""
