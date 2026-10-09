"""The ThinnestAI adapter's voice, clone and own-key calls (D-687, D-688).

Every vendor shape is the 7 Oct 2026 evening snapshot
(`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/`): `voices/
list-voices.md`, `voice-clones/*.md`, `bring-your-own-keys.md` and `bring-your-own-keys/*.md`,
`agents/set-agent-byok-voice.md`; the agent's `byok` switch is LIVE-DOCS
(`docs.thinnest.ai/api-reference/agents/update-agent`, 8 Oct 2026). Every agent lives in our
one developer workspace, so no request carries `Thinnest-Workspace`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import HostsVoices, VoiceCloneSample
from apps.api.engine.thinnest import (
    BASE_URL,
    BYOK_PREVIEW_TEXT_MAX_CHARS,
    ThinnestEngine,
)
from apps.api.engine.vendor_http import EngineRejectedError, vendor_audio_request
from calevate_shared.engine import AgentConfig, CallContext

Handler = Callable[[httpx.Request], httpx.Response]
#: The customer-workspace header, which nothing on this engine sends any more (D-688).
WORKSPACE_HEADER = "Thinnest-Workspace"
Key = tuple[str, str, str | None]


def _engine(handler: Handler) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


class _Vendor:
    """Answers by (method, path, workspace); records every request."""

    def __init__(
        self, routes: dict[Key, httpx.Response | Callable[[httpx.Request], httpx.Response]]
    ):
        self.routes = routes
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        key = (
            request.method,
            request.url.path.removeprefix("/api/v1"),
            request.headers.get(WORKSPACE_HEADER),
        )
        if key not in self.routes and key[1].endswith("/tools"):
            # The built-in tools route every create, update and read-back reaches (D-690).
            from tests.thinnest_engine_test import tools_state

            sent = json.loads(request.content) if request.content else None
            return httpx.Response(200, json=tools_state(sent))
        answer = self.routes.get(key, httpx.Response(404, json={"error": "x"}))
        return answer(request) if callable(answer) else answer


def _ok(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_the_adapter_hosts_voices() -> None:
    assert isinstance(_engine(_Vendor({})), HostsVoices)


# --- voices -------------------------------------------------------------------------


async def test_every_band_is_listed_with_its_band_and_a_clone_is_marked() -> None:
    """A plan below Pro lists standard and premium voices only (list-voices.md:7), so every
    band is read; which is sold is decided by the sync, not the adapter."""
    vendor = _Vendor(
        {
            ("GET", "/voices", None): _ok(
                {
                    "items": [
                        {"id": "anj", "name": "Anjali", "accent": "hi", "tier": "standard"},
                        {"id": "priya", "name": "Priya", "accent": "hi", "tier": "premium"},
                        {
                            "id": "spry__rakesh",
                            "name": "Rakesh",
                            "accent": "hi",
                            "tier": "studio",
                            "description": "Customer support",
                        },
                        {"id": "c4a1", "name": "Dr Mehta", "tier": "studio", "mine": True},
                        {"id": "", "name": "No id", "tier": "studio"},
                        {"id": "odd", "name": "Odd", "tier": "platinum"},
                    ]
                }
            )
        }
    )
    listing = await _engine(vendor).list_hosted_voices()
    assert listing.provider is None
    assert [(v.voice_id, v.band, v.is_custom, v.language) for v in listing.voices] == [
        ("anj", "standard", False, "hi"),
        ("priya", "premium", False, "hi"),
        ("spry__rakesh", "studio", False, "hi"),
        ("c4a1", "studio", True, None),
    ]
    assert {v.source for v in listing.voices} == {"engine"}
    assert listing.voices[2].description == "Customer support"


async def test_own_key_voices_are_read_with_their_provider() -> None:
    vendor = _Vendor(
        {
            ("GET", "/byok/voices", None): _ok(
                {
                    "provider": {"id": "cartesia", "label": "Cartesia"},
                    "model": "sonic-3",
                    "items": [
                        {"id": "cv-1", "name": "Meera", "language": "hi", "sample": None},
                        {
                            "id": "cv-2",
                            "name": "Arjun",
                            "language": "en",
                            "sample": "https://x/a.mp3",
                        },
                    ],
                }
            )
        }
    )
    listing = await _engine(vendor).list_own_key_voices()
    assert listing.provider == "cartesia"
    assert [(v.voice_id, v.source, v.sample_url) for v in listing.voices] == [
        ("cv-1", "byok", None),
        ("cv-2", "byok", "https://x/a.mp3"),
    ]


async def test_an_own_key_listing_without_a_provider_names_none() -> None:
    vendor = _Vendor({("GET", "/byok/voices", None): _ok({"items": []})})
    assert (await _engine(vendor).list_own_key_voices()).provider is None


async def test_a_preview_line_comes_back_as_audio() -> None:
    def _speak(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "voice": "cv-1",
            "text": "Namaste",
            "language": "te-IN",
        }
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    vendor = _Vendor({("POST", "/byok/voices/preview", None): _speak})
    audio = await _engine(vendor).preview_own_key_voice(
        voice_id="cv-1", text="Namaste", language="te-IN"
    )
    assert audio.data == b"ID3audio" and audio.content_type == "audio/mpeg"


async def test_a_preview_line_over_the_vendor_cap_is_refused_before_any_request() -> None:
    vendor = _Vendor({})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).preview_own_key_voice(
            voice_id="cv-1",
            text="x" * (BYOK_PREVIEW_TEXT_MAX_CHARS + 1),
            language=None,
        )
    assert caught.value.code == "engine_preview_text_too_long" and vendor.seen == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"error": "not audio"}),
        httpx.Response(200, content=b"", headers={"content-type": "audio/mpeg"}),
    ],
)
async def test_a_preview_that_is_not_audio_is_refused(response: httpx.Response) -> None:
    vendor = _Vendor({("POST", "/byok/voices/preview", None): response})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).preview_own_key_voice(voice_id="cv-1", text=None, language=None)
    assert caught.value.code == "engine_bad_response"


async def test_the_audio_ladder_refuses_a_vendor_error_like_any_other() -> None:
    client = httpx.AsyncClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda r: httpx.Response(502, json={"error": "x"})),
    )
    with pytest.raises(EngineRejectedError):
        await vendor_audio_request(client, "POST", "/x", engine="thinnest", route="/x")


# --- clones -------------------------------------------------------------------------


def _sample(**update: Any) -> VoiceCloneSample:
    base = VoiceCloneSample(
        filename="founder.wav",
        content_type="audio/wav",
        data=b"RIFF....WAVE",
        name="Founder",
        description="Warm",
        language="te",
        consent_own_voice=True,
        consent_no_impersonation=True,
    )
    return base.model_copy(update=update)


_CLONE = {
    "id": "vc_c4a1",
    "voiceId": "c4a1",
    "name": "Founder",
    "language": "te",
    "previewUrl": "https://files.example.com/p.mp3?token=x",
    "usableOnAgents": True,
}


async def test_a_clone_is_sent_multipart_with_both_promises() -> None:
    def _create(request: httpx.Request) -> httpx.Response:
        body = request.content
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        for field in (b'name="consentOwnVoice"', b'name="consentNoImpersonation"'):
            assert field in body
        assert body.count(b"\r\ntrue\r\n") >= 3  # both consents and removeNoise
        assert b'filename="founder.wav"' in body and b'name="language"' in body
        return _ok(_CLONE, 201)

    clone = await _engine(_Vendor({("POST", "/voice-clones", None): _create})).create_voice_clone(
        _sample()
    )
    assert (clone.clone_id, clone.voice_id, clone.usable_on_agents) == ("vc_c4a1", "c4a1", True)
    assert clone.preview_url is not None


async def test_a_clone_without_both_promises_is_refused_before_any_request() -> None:
    vendor = _Vendor({})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).create_voice_clone(_sample(consent_no_impersonation=False))
    assert caught.value.code == "voice_clone_consent_missing" and vendor.seen == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "voice_clone_sample_refused"),
        (403, "voice_clone_not_on_plan"),
        (409, "voice_clone_limit_reached"),
        (502, "engine_rejected"),
    ],
)
async def test_a_refused_clone_is_said_in_our_words(status: int, code: str) -> None:
    vendor = _Vendor({("POST", "/voice-clones", None): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).create_voice_clone(_sample(description=None, language=None))
    assert caught.value.code == code


async def test_a_clone_answer_without_its_ids_is_a_bad_response() -> None:
    vendor = _Vendor({("POST", "/voice-clones", None): _ok({"id": "vc_1"}, 201)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).create_voice_clone(_sample())
    assert caught.value.code == "engine_bad_response"


async def test_a_clone_is_found_by_its_voice_id() -> None:
    page = {"items": [{"id": "vc_x"}, _CLONE], "nextCursor": None}
    vendor = _Vendor({("GET", "/voice-clones", None): _ok(page)})
    engine = _engine(vendor)
    found = await engine.find_voice_clone("c4a1")
    assert found is not None and found.clone_id == "vc_c4a1"
    assert await engine.find_voice_clone("nobody") is None


async def test_a_clone_list_that_will_not_end_is_not_read_as_absence() -> None:
    page = {"items": [], "nextCursor": "same"}
    vendor = _Vendor({("GET", "/voice-clones", None): _ok(page)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).find_voice_clone("c4a1")
    assert caught.value.code == "engine_listing_incomplete"


@pytest.mark.parametrize(("moved", "expected"), [(2, 2), (None, 0), (True, 0)])
async def test_deleting_a_clone_reports_the_agents_it_moved(moved: Any, expected: int) -> None:
    vendor = _Vendor(
        {("DELETE", "/voice-clones/vc_c4a1", None): _ok({"deleted": True, "movedAgents": moved})}
    )
    assert await _engine(vendor).delete_voice_clone("vc_c4a1") == expected


# --- own keys ------------------------------------------------------------------------


_STATUS = {
    "enabled": True,
    "scope": "voice",
    "usingScope": "voice",
    "using": "own",
    "complete": True,
    "credentials": [
        {"kind": "stt", "provider": "deepgram"},
        {"kind": "tts", "provider": "cartesia"},
    ],
}


async def test_the_key_state_is_read() -> None:
    vendor = _Vendor({("GET", "/byok", None): _ok(_STATUS)})
    state = await _engine(vendor).own_key_state()
    assert state.speaks_on_own_voice and state.voice_provider == "cartesia"


async def test_a_key_state_with_no_credential_list_names_no_provider() -> None:
    vendor = _Vendor(
        {("GET", "/byok", None): _ok({"enabled": False, "using": "none", "credentials": "x"})}
    )
    state = await _engine(vendor).own_key_state()
    assert not state.speaks_on_own_voice and state.voice_provider is None


async def test_a_key_state_without_using_is_refused() -> None:
    vendor = _Vendor({("GET", "/byok", None): _ok({"enabled": True})})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).own_keys_in_use()
    assert caught.value.code == "engine_bad_response"


async def test_our_voice_key_is_installed_and_switched_on_for_the_voice() -> None:
    bodies: list[dict[str, Any]] = []

    def _record(answer: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
        def _handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return answer

        return _handler

    vendor = _Vendor(
        {
            ("PUT", "/byok/credentials", None): _record(_ok({"kind": "tts"})),
            ("PATCH", "/byok", None): _record(_ok({"enabled": True})),
            ("GET", "/byok", None): _ok(_STATUS),
        }
    )
    engine = _engine(vendor)
    await engine.install_own_voice_key(provider="cartesia", api_key="sk_car", model="sonic-3")
    state = await engine.enable_own_voice_key()
    assert bodies == [
        {
            "kind": "tts",
            "provider": "cartesia",
            "credentials": {"apiKey": "sk_car", "model": "sonic-3"},
        },
        {"enabled": True, "scope": "voice"},
    ]
    assert state.speaks_on_own_voice


@pytest.mark.parametrize(
    ("status", "code"), [(400, "engine_voice_key_rejected"), (502, "engine_rejected")]
)
async def test_a_rejected_voice_key_is_said_in_our_words(status: int, code: str) -> None:
    vendor = _Vendor({("PUT", "/byok/credentials", None): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).install_own_voice_key(provider="cartesia", api_key="sk", model=None)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("status", "code"), [(409, "engine_voice_key_not_ready"), (500, "engine_rejected")]
)
async def test_switching_on_a_key_that_is_not_ready_is_said_plainly(status: int, code: str) -> None:
    vendor = _Vendor({("PATCH", "/byok", None): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).enable_own_voice_key()
    assert caught.value.code == code


async def test_no_language_model_key_of_ours_is_installed() -> None:
    with pytest.raises(ProblemError) as caught:
        await _engine(_Vendor({})).set_llm_credential("sk", provider="openai")
    assert caught.value.code == "engine_capability_absent"


# --- one workspace: every agent states its own-voice-key switch (D-688) ---------------


_AGENT = {"id": "ag_9", "greeting": "Idi AI assistant.", "instructions": "x"}


def _cfg(**over: Any) -> AgentConfig:
    base: dict[str, Any] = {
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "agent_id": "00000000-0000-0000-0000-000000000002",
        "name": "Reception",
        "system_prompt": "Be kind.",
        "opening_line": "Namaste.",
        "language_primary": "te-IN",
        "direction": "inbound",
    }
    return AgentConfig.model_validate({**base, **over})


@pytest.mark.parametrize(("on", "sent"), [(True, "workspace"), (False, "off"), (None, None)])
def test_every_agent_body_states_its_own_voice_key_switch(on: bool | None, sent: Any) -> None:
    body = _engine(_Vendor({}))._agent_body(_cfg(engine_own_voice_key=on))
    assert body.get("byok") == sent


async def test_an_agent_is_created_and_updated_in_its_clients_own_workspace() -> None:
    """D-693: every request about a client's agent carries that client's workspace header,
    and the handle the create returns names the workspace."""
    bodies: list[dict[str, Any]] = []
    ws = "org_client-9"

    def _write(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _ok(_AGENT)

    vendor = _Vendor(
        {
            ("GET", "/agents", ws): _ok({"items": [], "nextCursor": None}),
            ("POST", "/agents", ws): _write,
            ("PATCH", "/agents/ag_9", ws): _write,
            ("PUT", "/agents/ag_9/byok-voice", ws): _ok({}),
        }
    )
    engine = _engine(vendor)
    ref = await engine.create_agent(
        _cfg(engine_own_voice_key=False, engine_voice_id="priya", engine_workspace=ws)
    )
    await engine.update_agent(ref, _cfg(engine_own_voice_key=True, engine_byok_voice_id="cv-1"))
    assert ref == f"ag_9@{ws}"
    assert [b["byok"] for b in bodies] == ["off", "workspace"]
    own_key_voice = next(r for r in vendor.seen if r.url.path.endswith("/byok-voice"))
    assert json.loads(own_key_voice.content) == {"voice": "cv-1"}
    assert all(r.headers.get(WORKSPACE_HEADER) == ws for r in vendor.seen)


async def test_no_agent_is_created_without_a_client_workspace() -> None:
    vendor = _Vendor({})
    with pytest.raises(ProblemError) as refused:
        await _engine(vendor).create_agent(_cfg())
    assert refused.value.code == "engine_workspace_not_provisioned"
    assert vendor.seen == []


async def test_the_agents_switch_is_read_back_and_set_alone() -> None:
    vendor = _Vendor(
        {
            ("GET", "/agents/ag_9", None): _ok({**_AGENT, "byok": "off"}),
            ("GET", "/agents/ag_9/knowledge", None): _ok({"items": [], "nextCursor": None}),
            ("PATCH", "/agents/ag_9", None): _ok(_AGENT),
        }
    )
    engine = _engine(vendor)
    assert (await engine.get_agent("ag_9")).engine_own_voice_key is False
    assert await engine.agent_own_voice_key("ag_9") is False
    await engine.set_agent_own_voice_key("ag_9", on=True)
    assert json.loads(vendor.seen[-1].content) == {"byok": "workspace"}


@pytest.mark.parametrize(("value", "held"), [("workspace", True), ("other", None), (None, None)])
async def test_a_switch_the_vendor_does_not_report_plainly_reads_as_unknown(
    value: Any, held: bool | None
) -> None:
    vendor = _Vendor({("GET", "/agents/ag_9", None): _ok({**_AGENT, "byok": value})})
    assert await _engine(vendor).agent_own_voice_key("ag_9") is held


async def test_our_voice_key_is_switched_off() -> None:
    vendor = _Vendor(
        {
            ("PATCH", "/byok", None): _ok({"enabled": False}),
            ("GET", "/byok", None): _ok({**_STATUS, "enabled": False, "using": "none"}),
        }
    )
    state = await _engine(vendor).disable_own_voice_key()
    assert json.loads(vendor.seen[0].content) == {"enabled": False}
    assert not state.speaks_on_own_voice


@pytest.mark.parametrize(("scope", "full"), [("voice", False), ("all", True)])
async def test_only_all_three_keys_count_as_the_workspace_on_its_own_keys(
    scope: str, full: bool
) -> None:
    vendor = _Vendor({("GET", "/byok", None): _ok({**_STATUS, "scope": scope})})
    assert await _engine(vendor).own_keys_in_use() is full


async def test_a_dial_is_placed_with_the_bare_agent_id() -> None:
    vendor = _Vendor(
        {
            ("GET", "/agents/ag_9", None): _ok(_AGENT),
            ("POST", "/calls", None): _ok({"id": "out_1", "status": "ringing"}, 201),
        }
    )
    handle = await _engine(vendor).start_outbound_call(
        "ag_9", "+919000000001", CallContext(call_id="c-1")
    )
    assert handle == "out_1"
    assert json.loads(vendor.seen[-1].content)["agent"] == "ag_9"


def _call(**extra: Any) -> dict[str, Any]:
    return {
        "id": "out_1",
        "agent": {"id": "ag_9"},
        "status": "completed",
        "direction": "outbound",
        "phone": "919000000001",
        "analysedAt": "2026-10-08T10:00:00Z",
        **extra,
    }


async def test_a_delivery_and_a_webhook_carry_the_vendor_ids_as_they_are() -> None:
    engine = _engine(_Vendor({}))
    snapshot = engine.snapshot_from_delivery({"data": _call(workspaceId="org_other")})
    assert (snapshot.engine_call_id, snapshot.engine_agent_ref) == ("out_1", "ag_9")
    event = engine.parse_webhook({"data": _call()})
    assert (event.call_id, event.engine_agent_ref) == ("out_1", "ag_9")
    assert engine.parse_webhook({"data": {"status": "completed"}}).call_id == ""
