"""In-call ACTIONS — the tool-calling feature (custom API, WhatsApp, calendar).

An action is a function the agent's LLM can invoke mid-call. The engine's function call is
meant to hit an endpoint of OURS, which executes the real external call — so the external
system's credentials, the SSRF egress guard and the audit trail all stay on our side and
never reach the vendor's agent config. The during-call endpoint left with the rented engine
(D-639); after-call triggers and the Test harness still execute here. See `docs/BACKEND-PATTERNS.md` and
`packages/shared/src/calevate_shared/engine.py::ActionToolSpec` for the boundary shape.
"""
