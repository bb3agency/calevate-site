"""The VoiceEngine portability contract (TRD §5).

Nothing outside `engine/` may import a vendor SDK or see a vendor payload shape.
Both the `bolna` and `fake` adapters must satisfy this Protocol and pass the
conformance suite — the second adapter exists to keep the first one honest.
(ThinnestAI was retired by D-31 before any adapter was written.)
"""

from typing import Any, Protocol, runtime_checkable

from calevate_shared.events import CallEvent

# Domain aliases. These stay deliberately thin until the Engine Verification
# Session (OPERATIONS.md §2) confirms the real payload shapes.
E164 = str
EngineAgentRef = str
CallHandle = str


@runtime_checkable
class VoiceEngine(Protocol):
    async def create_agent(self, cfg: Any) -> EngineAgentRef: ...

    async def update_agent(self, ref: EngineAgentRef, cfg: Any) -> None: ...

    async def start_outbound_call(self, ref: EngineAgentRef, to: E164, ctx: Any) -> CallHandle: ...

    async def end_call(self, call_id: str) -> None: ...

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None: ...

    async def provision_number(self, spec: Any) -> Any: ...

    async def attach_kb(self, ref: EngineAgentRef, source: Any) -> None: ...

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """HMAC-SHA256 verification. Unverified ⇒ 401 + alert, never processed."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Vendor payload → OUR normalized event. The isolation boundary."""
        ...


__all__ = ["E164", "CallHandle", "EngineAgentRef", "VoiceEngine"]
