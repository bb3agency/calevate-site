"""The conversation loop we RUN (D-592) — Pipecat, our container, Pipecat Cloud ap-south.

A PACKAGE, not the flat modules `apps/voice-runtime` uses and not the flat layout
`docs/PIPECAT-MIGRATION.md` §2 sketches. The diagram is a map of responsibilities, not a
directory listing, and the departure buys one thing: the deployable's directory is
hyphenated (D-18) so it can only be reached by putting it on `sys.path`, and a second
hyphenated deployable contributing TOP-LEVEL modules to that same path is a shadowing
hazard with no error message. voice-runtime already spends four generic names there
(`main`, `config`-adjacent route modules, `engine_intake`); `config.py` and `meter.py`
landing beside them would be resolved by path order, silently, and the loser would be
whichever deployable was imported second in a process that imported both — which is
exactly what the test suite is.

One package name costs nothing and makes the collision impossible.

WHAT LIVES HERE IS THE ONLY THING ALLOWED TO SEE A PIPECAT FRAME. Hard rule 2 did not
weaken when D-592 added this home; its boundary moved one deployable outward. Everything
this package hands to the rest of the system is a normalized `CallEvent` or
`TranscriptTurn` from `calevate_shared`, and nothing downstream of it learns Pipecat
exists.
"""

from __future__ import annotations
