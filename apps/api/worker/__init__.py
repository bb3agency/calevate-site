"""Routes the voice engine calls back into during a call, under `/v1/worker`.

`engine_actions.py` serves the engine's in-call actions (opt-out, call-back, call-back
cancel, hand-over and a client's own actions) and `engine_lookups.py` its caller lookups.
Both authenticate per agent before anything is parsed, and the writes they lead to live in
`in_call_tools.py`.
"""
