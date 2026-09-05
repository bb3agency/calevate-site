"""WHEN A SUBJECT'S UNBROKEN RUN OF SESSIONS BEGAN — now re-exported, not implemented.

The two functions below moved to `apps/api/authn/sessions.py`, which is where D-165 puts
every statement against `auth_sessions` ("apps/api/authn is the one package that says
otherwise"). D-540 wrote them here because a session-persistence lane held that package at
the time, and recorded the move in this file's own header; this is the module after it.

IT IS A RE-EXPORT AND NOT A SECOND IMPLEMENTATION. Five call sites in `copilot/` name
`session_run.current_run_start`, and rewriting them in the same change as the move would
have mixed a relocation with a refactor across two packages — the shape that makes a
revert hard to reason about. The names live in one place; this file only says where.
"""

from __future__ import annotations

from apps.api.authn.sessions import current_run_start, subjects_with_live_sessions

__all__ = ["current_run_start", "subjects_with_live_sessions"]
