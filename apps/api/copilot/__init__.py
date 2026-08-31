"""The in-app AI copilot: answers questions about the screen a person is looking at, and
fills that screen's form fields by tool call.

The five files, and the seam each one owns:

* `schemas.py`  — the wire contract, in Pydantic. The request is the ONLY description of
  the screen the server ever has, and it is the authority every tool call is re-validated
  against (OWASP GenAI LLM Top 10 2026, LLM01 #4).
* `sanitize.py` — invisible-character stripping at ingest and at egress, and the
  redaction guard that refuses a payload `redact()` still changes.
* `prompt.py`   — the static system prompt, the one tool definition, and the XML the
  screen state is fenced in.
* `service.py`  — the bounded tool-calling loop, and the two-field record that metering
  reads.
* `routes.py`   — `POST /v1/copilot/ask`, `text/event-stream`.

* `memory.py`   — `copilot_memories`: what is remembered between conversations, and the
  hybrid recall that gets it back. Migration `d4a9c17e6b02`.
* `models.py`   — that table, so `Base.metadata` is complete.

**THIS PACKAGE NOW PERSISTS, AND THIS PARAGRAPH USED TO SAY IT DID NOT.** The previous
text read "NOTHING IN THIS PACKAGE PERSISTS ANYTHING", citing `crm/assist.py:10-31`, which
declines to store transcript-derived prose so that DPDP erasure and retention gain no new
surface to enumerate. That refusal was right for a package with no memory and it is not a
prohibition — it is a PRICE, and `memory.py` pays it rather than dodging it: the store
ships with a FORCEd `tenant_isolation` policy, a `copilot_memory` retention category swept
nightly, an unconditional DELETE in the tenant-erasure path, and `redact()` on every string
before it reaches a column. `history` still arrives in the request and still dies with it —
what survives is one redacted, capped row per answered question, and the facts an hourly
worker distils out of them.

Read `memory.py`'s docstring for the two things a reader is most likely to get wrong: that
the relevance channel is LEXICAL and not semantic (there is no embedding path in this
repository to reuse — D-28), and that `redact()` catches identifiers but not proper nouns.
"""
