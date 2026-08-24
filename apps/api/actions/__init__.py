"""In-call ACTIONS — the tool-calling feature (custom API, WhatsApp, calendar).

An action is a function the agent's LLM can invoke mid-call. Bolna's function-call hits
OUR voice-runtime tool endpoint, which executes the real external call — so the external
system's credentials, the SSRF egress guard and the audit trail all stay on our side and
never reach the vendor's agent config. See `docs/BACKEND-PATTERNS.md` and
`packages/shared/src/calevate_shared/engine.py::ActionToolSpec` for the boundary shape.
"""
