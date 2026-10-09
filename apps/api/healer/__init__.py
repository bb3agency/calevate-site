"""The auto-healer (D-701): detect, repair, protect, tell.

`playbooks.py` is the one registry of what the healer may do on its own. Plumbing repairs
run automatically and are verified, capped and audited (`heal_actions`); anything that
changes how an agent behaves is only proposed (`proposals.py`) and needs a person's click.
"""
