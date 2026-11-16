"""Ending a call on the line, whatever its state, in our terms.

`VoiceEngine.end_call` deliberately leaves a CONNECTED call alone: its callers (the big red
switch, a do-not-call recall) pull back dials nobody answered, and must never hang up on a
person mid-sentence. A test call is the other case: the person on the line is the owner who
placed it, and "End call" is them asking for exactly that.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class HangsUpCalls(Protocol):
    """An engine that can end a call it is holding, ringing or connected."""

    async def hang_up_call(self, handle: str) -> None: ...


__all__ = ["HangsUpCalls"]
