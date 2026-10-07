"""Finding the [T0 FACTS] block inside a prompt body, and taking it out.

A leaf module because two callers need it from opposite sides of an import cycle:
`agents/t0.py` (which imports `agents/service.py` to republish) and `agents/service.py`
itself, which on an engine that holds business facts in its knowledge base publishes the
script WITHOUT the block (`engine/hosted_platform.HostedAgentLimits.facts_in_knowledge`).

A section runs from its header line to the next line starting with `[` at column 0, the
rule PROMPT-GUIDE §2's template and both splicers already follow.
"""

from __future__ import annotations

from typing import Final

# The section marker PROMPT-GUIDE §2 uses, and the one `admin/intake.py` splices on.
# `tests/t0_recompile_test.py` pins the two spellings together: two modules writing
# different headers would each silently append their own block.
T0_HEADER: Final = "[T0 FACTS]"


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


def without_block(body: str) -> str:
    """`body` with its [T0 FACTS] block removed, every other line kept as it was."""
    lines = body.splitlines()
    bounds = _bounds(lines)
    if bounds is None:
        return body
    return "\n".join([*lines[: bounds[0]], *lines[bounds[1] :]]).strip()


__all__ = ["T0_HEADER", "block_of", "without_block"]
