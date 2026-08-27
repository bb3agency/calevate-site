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

NOTHING IN THIS PACKAGE PERSISTS ANYTHING. `crm/assist.py:10-31` declines to store
transcript-derived prose so that DPDP erasure and retention gain no new surface to
enumerate; a copilot conversation table would re-open that decision for text a person
typed about their own screen. `history` arrives in the request and dies with it.
"""
