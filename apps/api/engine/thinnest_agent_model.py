"""Read and set the language model one ThinnestAI agent answers with, for the operator's
in-call model comparison (`scripts/compare_in_call_models`, D-739).

Not a publish path: an agent's model is decided by `agents/engine_choice` and pushed by
`agents/service.publish_agent`. This exists because the vendor's test chat runs an agent on
whatever model the agent holds (snapshots/2026-10-08/pages/api-reference/agents/
test-chat.md:344-346, "the same prompt, model, knowledge ... as the console's Playground")
and takes no model of its own, so comparing models means switching the agent and putting it
back. The settings drift sweep repairs a switched model on a live agent, so the comparison
re-reads the model before every conversation.

`model` on Update Agent takes a List Models id, or `null` for the default, Prana [Voice]
(update-agent.md:535-547); Get Agent answers the id, `null` for a retired model
(update-agent.md:664-670).
"""

from __future__ import annotations

from typing import Any, Final

import httpx
from calevate_shared.engine_scope import raw_of, scope_of

from apps.api.engine.capabilities import NO_CREDENTIALS_REASON, engine_not_configured
from apps.api.engine.thinnest import AUTH_HEADER, AUTH_SCHEME, BASE_URL
from apps.api.engine.thinnest_workspace import workspace_headers
from apps.api.engine.vendor_http import REQUEST_TIMEOUT_S, vendor_request

ENGINE: Final = "thinnest"
#: The catalogue name of the model `null` selects (update-agent.md:540-541).
DEFAULT_MODEL_LABEL: Final = "Prana [Voice]"
_ROUTE: Final = "/agents/{ref}"


class ThinnestAgentModel:
    """`GET`/`PATCH /agents/{id}`, the `model` field only. Tests hand in a mock transport."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise engine_not_configured(f"{NO_CREDENTIALS_REASON}:{ENGINE}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={AUTH_HEADER: f"{AUTH_SCHEME} {self._api_key}"},
            )
        return self._client

    async def _request(self, method: str, ref: str, **kwargs: Any) -> dict[str, Any]:
        workspace = scope_of(ref)
        return await vendor_request(
            self._http(),
            method,
            f"/agents/{raw_of(ref)}",
            engine=ENGINE,
            route=_ROUTE,
            headers=workspace_headers(method, _ROUTE, workspace),
            **kwargs,
        )

    async def held(self, ref: str) -> str | None:
        """The model id the agent holds now; `None` on the default or a retired model."""
        model = (await self._request("GET", ref)).get("model")
        return model if isinstance(model, str) and model else None

    async def switch(self, ref: str, model_id: str | None) -> None:
        """Put the agent on `model_id`, or on the default with `None`."""
        await self._request("PATCH", ref, json={"model": model_id})

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


__all__ = ["DEFAULT_MODEL_LABEL", "ThinnestAgentModel"]
