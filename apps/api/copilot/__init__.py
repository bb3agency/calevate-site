"""The in-app AI copilot: answers questions about the screen a person is looking at and
about the business behind it, fills that screen's form fields by tool call, and proposes —
never performs — a small set of changes a person then confirms.

The files, and the seam each one owns. **THIS LIST USED TO SAY "THE FIVE FILES" AND NAME
FIVE**, which stopped being true the day four phases of D-484 landed at once; a package
index that silently omits three modules is worse than no index, because a reader trusts it.

* `schemas.py`  — the wire contract, in Pydantic. The request is the ONLY description of
  the screen the server ever has, and it is the authority every `set_fields` call is
  re-validated against (OWASP GenAI LLM Top 10 2026, LLM01 #4).
* `sanitize.py` — invisible-character stripping at ingest and at egress, and the
  redaction guard that refuses a payload `redact()` still changes.
* `prompt.py`   — the static system prompt, the `set_fields` tool definition, and the XML
  helpers every block in this package escapes through (`xml_text`, `xml_attr`).
* `identity.py` — who the assistant says it IS, as a property of this service rather than
  a request to a model: the canonical answer given without a provider round trip, and the
  streaming egress guard that keeps a model's own "trained by …" off a client's screen.
  `prompt.ASSISTANT_IDENTITY` is the same rule asked politely, and it is not sufficient —
  see that module for the live answers that proved it.
* `tools.py`    — the READ tools: performance, leads, calls, campaigns, agents. Each one
  its own short `tenant_session`, its own permission checked in code, its result redacted.
* `write_tools.py` — the three PROPOSING tools and the one door that acts. A proposal is a
  signed five-minute token and no table; `confirm()` is the only code here that mutates
  anything, and it runs the same gated service function a human's click runs.
* `context.py`  — the LIVE BUSINESS STATE block: counts and closed-set rule names, no
  tenant-authored string at all, degrading to `<unavailable/>` rather than to zeros.
* `service.py`  — the bounded tool-calling loop (one loop, both provider legs), the
  server-side re-validation, and the two-field record that metering reads.
* `routes.py`   — `POST /v1/copilot/ask` (`text/event-stream`) and
  `POST /v1/copilot/confirm`, which is where a proposal becomes a change.
* `memory.py`   — `copilot_memories`: what is remembered between conversations, and the
  hybrid recall that gets it back. Migration `d4a9c17e6b02`.
* `models.py`   — that table, so `Base.metadata` is complete.

Distillation — episodes in, durable facts out — is deliberately NOT here: it calls a model,
so it lives in `apps/workers/copilot_memory.py` on an hourly cron, never in a live turn.

**THIS PACKAGE NOW PERSISTS, AND THIS PARAGRAPH USED TO SAY IT DID NOT.** The previous
text read "NOTHING IN THIS PACKAGE PERSISTS ANYTHING", citing `crm/assist.py:10-31`, which
declines to store transcript-derived prose so that DPDP erasure and retention gain no new
surface to enumerate. That refusal was right for a package with no memory and it is not a
prohibition — it is a PRICE, and `memory.py` pays it rather than dodging it: the store
ships with a FORCEd `tenant_isolation` policy, a `copilot_memory` retention category swept
nightly, an unconditional DELETE in the tenant-erasure path, and `redact()` on every string
before it reaches a column. `history` still arrives in the request and still dies with it —
what survives is one redacted, capped row per answered question, and the facts an hourly
worker distils out of them. Nothing ELSE here persists: a proposal is a token and not a
row, precisely because it would be a price with nothing bought (`write_tools.py`).

Read `memory.py`'s docstring for the two things a reader is most likely to get wrong: that
the relevance channel is LEXICAL and not semantic (there is no embedding path in this
repository to reuse — D-28), and that `redact()` catches identifiers but not proper nouns.
"""
