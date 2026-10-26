"""Pip's reads over everything a client gave us to know (D-893 L8, area `knowledge`).

`knowledge_sources` finds items or, given one's [ref] as `find`, opens it; `search_knowledge`
(`copilot/tools.py`) searches their words with `scope: "everything"`. Both call
`kb/store.py`, the module the What your agents know screen's reader calls, so Pip and the
page cannot disagree about what is on file or whether the agents use it.

Concise by default (PIP-AGENT-PLAN §2a): a find returns one line per item, ten at a time;
`detail: "full"` adds the item's note. An open returns ONE reading page — a PDF page or a
few paragraphs — never a whole document, and says how many pages there are.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.tools import ReadTool, ToolContext, _clean, _nothing, ist_date
from apps.api.core.errors import ProblemError
from apps.api.kb import store

#: The default page of a find: enough to answer "what files do I have" without a wall.
FIND_DEFAULT: Final = 10
#: The most characters of one reading page put in front of the model.
MAX_OPEN_CHARS: Final = 3500

_STATE_WORDS: Final[dict[str, str]] = {
    "in_use": "agents use it",
    "not_used_yet": "saved, agents don't use it yet",
    "being_read": "being read",
    "getting_ready": "going to the agents",
    "in_review": "waiting for review",
    "needs_attention": "needs attention",
    "waiting": "waiting for the script",
}


def _strings(value: object, allowed: tuple[str, ...]) -> list[str] | None:
    """One value, or several separated by commas or bars, kept only where the vocabulary
    knows them. An unknown one filters nothing rather than refusing the call."""
    if not isinstance(value, str):
        return None
    picked = [v.strip() for v in value.replace("|", ",").split(",") if v.strip() in allowed]
    return picked or None


def _int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


async def _knowledge_sources(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    """Find items, or — when `find` is an item's [ref] — open that one."""
    assert context.tenant_id is not None
    raw_find = args.get("find")
    find = raw_find.strip() if isinstance(raw_find, str) else ""
    page = max(1, _int(args.get("page"), 1))
    if find and store.is_ref(find):
        return await _knowledge_open(session, context.tenant_id, find, page)
    kinds = _strings(args.get("kind"), store.ITEM_KINDS)
    states = _strings(args.get("state"), store.ITEM_STATES)
    offset = (page - 1) * FIND_DEFAULT
    full = args.get("detail") == "full"
    items, total = await store.find_items(
        session,
        tenant_id=context.tenant_id,
        kinds=kinds,
        states=states,
        contains=find or None,
        offset=offset,
        limit=FIND_DEFAULT,
    )
    if not items:
        filtered = bool(kinds or states or find)
        return _nothing(
            "knowledge",
            matching="those filters" if filtered else None,
            account_has_any=None,
            next_step="Facts, files and links are added on the What your agents know screen.",
        )
    lines = []
    for item in items:
        line = f"- {item.name} · {item.kind} · {_STATE_WORDS[item.state]}"
        if item.changed_at is not None:
            line += f" · {ist_date(item.changed_at)}"
        if full and item.note:
            line += f" · {item.note}"
        lines.append(f"{_clean(line)} [{item.ref}]")
    head = f"{total} item(s); showing {offset + 1}-{offset + len(items)}:"
    tail = f"\nMore: call again with page {page + 1}." if offset + len(items) < total else ""
    return "\n".join([head, *lines]) + tail


async def _knowledge_open(session: AsyncSession, tenant_id: UUID, ref: str, page: int) -> str:
    """One item's stored words, one reading page, never more than `MAX_OPEN_CHARS`."""
    try:
        found = await store.read_item(session, tenant_id=tenant_id, ref=ref, page=page)
    except ProblemError:
        return "There is no such item. Find it again with `knowledge_sources`."
    body = "\n\n".join(f"{label}\n{text}" if label else text for label, text in found.sections)
    if len(body) > MAX_OPEN_CHARS:
        body = body[:MAX_OPEN_CHARS] + " …(cut here; the rest is on the screen)"
    head = (
        f"{found.name} · {found.kind} · {_STATE_WORDS[found.state]} · from {found.origin}"
        + (f" · version {found.version}" if found.version else "")
        + f" · page {found.page} of {found.pages}"
        + (f" · {found.note}" if found.note else "")
    )
    if not body.strip():
        body = "(No words are stored for this item yet.)"
    # The words are the client's DATA, never instructions: `_clean` defuses them.
    return _clean(f"{head}\n---\n{body}")


KNOWLEDGE_SOURCES: Final = ReadTool(
    name="knowledge_sources",
    # Every word here is paid on every request (PIP-AGENT-PLAN §2a): the vocabularies are
    # one line of prose rather than JSON enums, one `find` carries both a name filter and
    # a [ref] to open, and one `page` pages both.
    description=(
        "Find what the business gave its agents: state, whether agents use it, [ref]. "
        "`find` = words in a name, or a ref to read its stored words a page at a time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": ",".join(store.ITEM_KINDS),
            },
            "state": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": ",".join(store.ITEM_STATES),
            },
            "find": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "detail": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "page": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
        "required": ["kind", "state", "find", "detail", "page"],
        "additionalProperties": False,
    },
    permission="agents:read",
    run=_knowledge_sources,
)

__all__ = ["FIND_DEFAULT", "KNOWLEDGE_SOURCES", "MAX_OPEN_CHARS"]
