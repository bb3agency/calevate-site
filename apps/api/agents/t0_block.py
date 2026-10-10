"""Finding the [T0 FACTS] block inside a prompt body, putting it in, and taking it out.

A leaf module because its callers sit on opposite sides of an import cycle:
`agents/t0.py` (which imports `agents/service.py` to republish), `agents/service.py`
itself, which on an engine that holds business facts in its knowledge base publishes the
script WITHOUT the block (`engine/hosted_platform.HostedAgentLimits.facts_in_knowledge`),
and `agents/script_builder.py`, which carries the current block into every builder save
(`agents/starters.py` imports it from under `agents/lifecycle.py`).

A section runs from its header line to the next line starting with `[` at column 0, the
rule PROMPT-GUIDE §2's template and both splicers already follow.
"""

from __future__ import annotations

from typing import Final

# The section marker PROMPT-GUIDE §2 uses. One spelling: two modules writing different
# headers would each silently append their own block.
T0_HEADER: Final = "[T0 FACTS]"

# Where the knowledge half starts, INSIDE the block (`agents/t0.py` writes it). Deliberately
# not a `[SECTION]`: a line starting with `[` at column 0 ends the T0 block for both
# splicers, so a bracketed marker would strand every knowledge line in the prompt body.
T0_KNOWLEDGE_MARKER: Final = "Published knowledge:"


def _bounds(lines: list[str]) -> tuple[int, int] | None:
    start = next((i for i, line in enumerate(lines) if line.startswith(T0_HEADER)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return start, end


def block_of(body: str | None) -> str | None:
    """The [T0 FACTS] block currently inside a prompt body, if it has one."""
    if not body:
        return None
    lines = body.splitlines()
    bounds = _bounds(lines)
    if bounds is None:
        return None
    return "\n".join(lines[bounds[0] : bounds[1]]).rstrip()


def intake_lines(block: str | None) -> list[str]:
    """The lines of a block that are NOT the knowledge half, header excluded.

    Split on the LAST marker, not the first: the knowledge half is appended, so the last
    occurrence is the true boundary even if a client's own booking rules contain the
    marker's text, and splitting on the first would truncate their facts.
    """
    if not block:
        return []
    lines = block.splitlines()
    if lines and lines[0].startswith(T0_HEADER):
        lines = lines[1:]
    boundary = max((i for i, line in enumerate(lines) if line == T0_KNOWLEDGE_MARKER), default=None)
    return lines[:boundary] if boundary is not None else lines


def facts_without_knowledge(block: str | None) -> str | None:
    """`block` with its "Published knowledge:" half removed, or None if nothing is left.

    For an engine that holds business facts as a knowledge document (`agents/engine_facts.py`):
    each published source already reaches that engine as its own document (`kb/service.py`),
    so a facts document carrying the knowledge half too would hand the engine every source
    twice, and a withdrawn source would survive in the facts copy until the next publish.
    """
    lines = [line for line in intake_lines(block) if line.strip()]
    if not lines:
        return None
    return "\n".join([T0_HEADER, *lines])


def without_block(body: str) -> str:
    """`body` with its [T0 FACTS] block removed, every other line kept as it was."""
    lines = body.splitlines()
    bounds = _bounds(lines)
    if bounds is None:
        return body
    return "\n".join([*lines[: bounds[0]], *lines[bounds[1] :]]).strip()


# Where a freshly compiled block is inserted when the prompt has no block yet — the
# position PROMPT-GUIDE §2's template order puts it in.
_INSERT_BEFORE = ("[TASK FLOW]", "[CONVERSATION]", "[TOOLS]", "[GUARDRAILS]", "[WRAP]")


def splice_t0_block(body: str | None, block: str, *, identity: str) -> str:
    """Put `block` where the prompt's [T0 FACTS] section is, or where it should be.

    Replacing rather than appending is the rule PROMPT-GUIDE §2 states: the block is
    auto-generated and regenerated, so a second copy of stale hours above the fresh
    ones is not a merge, it is an agent that quotes two opening times. Everything
    outside the block — the guardrails an operator wrote by hand, the task flow, the
    wrap — is not this compiler's to touch.
    """
    if not body or not body.strip():
        return f"[IDENTITY] {identity}\n{block}\n"

    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(T0_HEADER)), None)
    if start is None:
        anchor = next(
            (
                i
                for i, line in enumerate(lines)
                if any(line.startswith(marker) for marker in _INSERT_BEFORE)
            ),
            len(lines),
        )
        return "\n".join([*lines[:anchor], block, *lines[anchor:]]).rstrip() + "\n"

    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
        len(lines),
    )
    return "\n".join([*lines[:start], block, *lines[end:]]).rstrip() + "\n"


__all__ = [
    "T0_HEADER",
    "T0_KNOWLEDGE_MARKER",
    "block_of",
    "facts_without_knowledge",
    "intake_lines",
    "splice_t0_block",
    "without_block",
]
