"""Where an ENGINE's recording is fetched from, and the rules that fetch must obey.

The carrier path has `engine/carrier.CarrierRecordingSource`. An engine that keeps the
recording itself (ThinnestAI) describes its own here, because the vendor's host, its
"not ready yet" and "deleted" answers and its audio type are vendor facts (hard rule 2), and
`workers/storage.copy_recording` enforces them without knowing whose they are.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RecordingFetchRules:
    """What the fetch must refuse, beyond the egress guard every recording copy runs.

    * `allowed_hosts`: every hop must be one of these hosts exactly, so a vendor answer
      that points or redirects anywhere else is refused rather than followed.
    * `content_types`: the media types the bytes may be served as.
    * `not_ready_status`: answered WITH `Retry-After` it means "the audio has not landed",
      a wait; answered without, "there is no recording", which is not a failure.
    * `gone_status`: the vendor deleted it, which no retry will undo.
    """

    allowed_hosts: frozenset[str]
    content_types: frozenset[str]
    not_ready_status: int | None = None
    gone_status: int | None = None


@dataclass(frozen=True, slots=True)
class EngineRecordingSource:
    """One recording's address, the credential it needs and the rules for fetching it.

    `auth_hosts` bounds where `auth_headers` may be sent, as on the carrier path.
    """

    url: str
    rules: RecordingFetchRules
    auth_headers: Mapping[str, str] = field(default_factory=dict)
    auth_hosts: frozenset[str] = frozenset()


__all__ = ["EngineRecordingSource", "RecordingFetchRules"]
