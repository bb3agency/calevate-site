"""Campaigns — bulk outbound with the compliance gate in the launch path (FLOWS §5).

This is the module hard rule 5 was written about: "campaign launch path must call the
compliance gate — never add a bypass 'for testing'". The launch check produces a list
of NAMED blockers so the UI can show a disabled button with reasons (SURFACES §2b),
and the dispatcher re-checks per contact at dial time, because a number can join the
DNC list between launch and dial.
"""
