"""Split knowledge text to fit an engine's per-document ceiling.

Its own module because both the adapter that sends the parts (`engine/thinnest.py`) and the
module that publishes the ceilings (`engine/hosted_platform.py`, which imports the adapter's
constants) need it.
"""

from __future__ import annotations


def split_for_text_cap(text: str, cap: int, *, separator: str = "\n\n") -> tuple[str, ...]:
    """Split knowledge text into parts no longer than `cap`, on `separator` boundaries.

    The publisher joins approved chunks with `separator` (`kb/service.publish_source`), so
    cutting there never splits a chunk a human approved. A single piece longer than `cap`
    cannot occur with our chunker (`kb/service.MAX_CHUNK_CHARS`); it is cut at the last
    whitespace before the cap rather than refused, so a caller never loses text.
    """
    if cap <= len(separator):
        raise ValueError("cap must be longer than the separator")
    if len(text) <= cap:
        return (text,) if text else ()
    parts: list[str] = []
    current = ""
    for piece in text.split(separator):
        for fragment in _hard_cut(piece, cap):
            candidate = f"{current}{separator}{fragment}" if current else fragment
            if len(candidate) <= cap:
                current = candidate
                continue
            parts.append(current)
            current = fragment
    if current:
        parts.append(current)
    return tuple(parts)


def _hard_cut(piece: str, cap: int) -> list[str]:
    fragments: list[str] = []
    rest = piece
    while len(rest) > cap:
        cut = rest.rfind(" ", 0, cap + 1)
        if cut <= 0:
            cut = cap
        fragments.append(rest[:cut])
        rest = rest[cut:].lstrip(" ")
    fragments.append(rest)
    return fragments


__all__ = ["split_for_text_cap"]
