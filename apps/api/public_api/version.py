"""The public API's dated versions (W2.13, `docs/WEBHOOKS.md` §0).

One version exists. A key is pinned to the version current when it was made, a request may
name one in `Calevate-Version`, and every answer says which version it was written in. Within
a version every change is additive, which `scripts/check_public_api_snapshot.py` enforces in
CI. The first breaking change ships as a new date here plus a transform from the newer shape
to each older one; there are no transforms yet because there is nothing to transform.
"""

from __future__ import annotations

from typing import Final

from apps.api.core.errors import ProblemError

VERSION_HEADER: Final = "Calevate-Version"
CURRENT_VERSION: Final = "2026-12-01"
#: Every version this API still answers in, oldest first.
SUPPORTED_VERSIONS: Final[tuple[str, ...]] = (CURRENT_VERSION,)


def effective_version(requested: str | None, *, pinned: str) -> str:
    """The version this request is answered in: the header's, else the key's pin."""
    if requested is None or not requested.strip():
        return pinned if pinned in SUPPORTED_VERSIONS else CURRENT_VERSION
    value = requested.strip()
    if value not in SUPPORTED_VERSIONS:
        raise ProblemError(
            kind="validation",
            status=400,
            code="api_version_unknown",
            title="Unknown API version",
            detail=f"{VERSION_HEADER} names a version this API does not have.",
            remediation=(
                f"Send one of: {', '.join(SUPPORTED_VERSIONS)}, or leave the header out to use "
                "the version your key was made with."
            ),
        )
    return value


__all__ = ["CURRENT_VERSION", "SUPPORTED_VERSIONS", "VERSION_HEADER", "effective_version"]
