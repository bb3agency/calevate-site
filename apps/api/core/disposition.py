"""`Content-Disposition: attachment` for a filename somebody else chose.

Starlette encodes header values as latin-1, so a Devanagari or Telugu filename put straight
into `filename="..."` raises at response time (a 500 on the download), and a quote or a
line break in it would end the parameter or the header. RFC 6266 §4.3 / RFC 8187: send an
ASCII `filename` that any client can read, plus `filename*` carrying the real name
percent-encoded as UTF-8, which every current browser prefers.
"""

from __future__ import annotations

import re
from urllib.parse import quote

_UNSAFE_ASCII = re.compile(r"[^A-Za-z0-9._ -]+")


def attachment_disposition(filename: str, *, fallback: str = "download") -> str:
    """A header value that names `filename` and cannot be broken by it."""
    ascii_name = _UNSAFE_ASCII.sub("_", filename).strip(" ._") or fallback
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


__all__ = ["attachment_disposition"]
