"""What a listing read tool found, as rows the step can open to show (`step.results`).

A read tool returns prose for the model; the person watching the panel wants the rows. A
tool that lists things OFFERS them here, beside its prose, and the loop puts them on that
call's terminal `step` frame. The tool's own query and text are unchanged: the offer is one
call at the end of its body.

THE COLLECTOR IS PER CALL. `service._run_one_read_tool` opens it inside the task `gather`
runs each call in, so two lookups in one turn never see each other's rows. Outside that (a
background job, a test calling a tool directly) `offer` does nothing.

BOUNDED AND STRIPPED, LIKE `step.detail`: at most `MAX_ITEMS` rows, each string stripped of
invisible characters and cut to one short line. Never logged and never stored (hard rule
6): it is the caller's own data on the caller's own screen, for the length of the answer.

`href` is a client route TEMPLATE carrying a literal `{slug}`, as `event: navigate`'s
`route` does: the browser substitutes its own slug and checks the result against its own
routes. Anything not under `/c/{slug}/` is dropped here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final

from apps.api.copilot.sanitize import strip_invisible
from apps.api.copilot.schemas import CopilotResultItem, CopilotStepResults

MAX_ITEMS: Final = 8
MAX_TITLE_CHARS: Final = 120
MAX_SUBTITLE_CHARS: Final = 160
_HREF: Final = re.compile(r"^/c/\{slug\}(/[A-Za-z0-9_-]+)*$")


@dataclass(frozen=True, slots=True)
class ResultRow:
    title: str
    subtitle: str | None = None
    href: str | None = None


@dataclass(slots=True)
class Offered:
    """The rows one call offered, or None when it offered none."""

    rows: list[ResultRow] = field(default_factory=list)
    total: int | None = None

    def event(self, *, links: bool = True) -> CopilotStepResults | None:
        if self.total is None:
            return None
        items = [
            CopilotResultItem(
                title=_line(row.title, MAX_TITLE_CHARS) or "—",
                subtitle=_line(row.subtitle, MAX_SUBTITLE_CHARS) or None,
                href=row.href if links and row.href and _HREF.match(row.href) else None,
            )
            for row in self.rows[:MAX_ITEMS]
        ]
        return CopilotStepResults(kind="list", items=items, total=max(self.total, len(items)))


_OFFERED: ContextVar[Offered | None] = ContextVar("copilot_step_results", default=None)


def offer(rows: Iterable[ResultRow], *, total: int) -> None:
    """A listing tool's rows, for the step that ran it. Called at most once per call; a
    second call replaces the first."""
    offered = _OFFERED.get()
    if offered is None:
        return
    offered.rows = list(rows)[:MAX_ITEMS]
    offered.total = total


@contextmanager
def collecting() -> Iterator[Offered]:
    offered = Offered()
    token = _OFFERED.set(offered)
    try:
        yield offered
    finally:
        _OFFERED.reset(token)


def _line(value: str | None, limit: int) -> str:
    if not value:
        return ""
    flat = " ".join(strip_invisible(value).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = ["MAX_ITEMS", "Offered", "ResultRow", "collecting", "offer"]
