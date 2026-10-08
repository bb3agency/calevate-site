"""The ThinnestAI adapter's voice, clone, own-key and workspace calls (D-687).

Every vendor shape is the 7 Oct 2026 evening snapshot
(`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/`): `voices/
list-voices.md`, `voice-clones/*.md`, `bring-your-own-keys.md` and `bring-your-own-keys/*.md`,
`agents/set-agent-byok-voice.md`, `customers.md`. A Studio agent lives in a customer
workspace: every request about it carries `Thinnest-Workspace`, and every id issued there is
held by us as `<id>@<workspace>`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.catalogue import HostsVoices, VoiceCloneSample
from apps.api.engine.thinnest import (
    BASE_URL,
    BYOK_PREVIEW_TEXT_MAX_CHARS,
    WORKSPACE_HEADER,
    ThinnestEngine,
)
from apps.api.engine.vendor_http import EngineRejectedError, vendor_audio_request
from calevate_shared.engine import CallContext, ExecutionSnapshot
from calevate_shared.engine_scope import scope_of, scoped_handle, split_handle

Handler = Callable[[httpx.Request], httpx.Response]
STUDIO = "org_studio"
Key = tuple[str, str, str | None]


def _engine(handler: Handler, *, studio: str | None = None) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
        studio_workspace=lambda: studio,
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
        answer = self.routes.get(key, httpx.Response(404, json={"error": "x"}))
        return answer(request) if callable(answer) else answer


def _ok(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --- the scoped handle --------------------------------------------------------------


def test_a_handle_carries_its_workspace_and_round_trips() -> None:
    assert scoped_handle("ag_1", None) == "ag_1"
    assert scoped_handle("ag_1", STUDIO) == "ag_1@org_studio"
    assert split_handle("ag_1@org_studio") == ("ag_1", STUDIO)
    assert split_handle("ag_1") == ("ag_1", None)
    for odd in ("@org", "ag_1@", "@"):
        assert split_handle(odd) == (odd, None)
    assert scope_of(None) is None and scope_of("ag_1@org_x") == "org_x"
    with pytest.raises(ValueError):
        scoped_handle("a@b", STUDIO)


def test_the_adapter_hosts_voices() -> None:
    assert isinstance(_engine(_Vendor({})), HostsVoices)


# --- voices -------------------------------------------------------------------------


async def test_only_the_studio_band_is_listed_and_a_clone_is_marked() -> None:
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
                    ]
                }
            )
        }
    )
    listing = await _engine(vendor).list_hosted_voices()
    assert listing.provider is None
    assert [(v.voice_id, v.is_custom, v.language, v.source) for v in listing.voices] == [
        ("spry__rakesh", False, "hi", "engine"),
        ("c4a1", True, None, "engine"),
    ]
    assert listing.voices[0].description == "Customer support"


async def test_own_key_voices_are_read_inside_the_studio_workspace() -> None:
    vendor = _Vendor(
        {
            ("GET", "/byok/voices", STUDIO): _ok(
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
    listing = await _engine(vendor).list_own_key_voices(workspace=STUDIO)
    assert listing.provider == "cartesia"
    assert [(v.voice_id, v.source, v.sample_url) for v in listing.voices] == [
        ("cv-1", "byok", None),
        ("cv-2", "byok", "https://x/a.mp3"),
    ]


async def test_an_own_key_listing_without_a_provider_names_none() -> None:
    vendor = _Vendor({("GET", "/byok/voices", STUDIO): _ok({"items": []})})
    assert (await _engine(vendor).list_own_key_voices(workspace=STUDIO)).provider is None


async def test_a_preview_line_comes_back_as_audio_from_the_studio_workspace() -> None:
    def _speak(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "voice": "cv-1",
            "text": "Namaste",
            "language": "te-IN",
        }
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    vendor = _Vendor({("POST", "/byok/voices/preview", STUDIO): _speak})
    audio = await _engine(vendor).preview_own_key_voice(
        workspace=STUDIO, voice_id="cv-1", text="Namaste", language="te-IN"
    )
    assert audio.data == b"ID3audio" and audio.content_type == "audio/mpeg"


async def test_a_preview_line_over_the_vendor_cap_is_refused_before_any_request() -> None:
    vendor = _Vendor({})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).preview_own_key_voice(
            workspace=STUDIO,
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
    vendor = _Vendor({("POST", "/byok/voices/preview", STUDIO): response})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).preview_own_key_voice(
            workspace=STUDIO, voice_id="cv-1", text=None, language=None
        )
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


# --- own keys and workspaces ---------------------------------------------------------


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


async def test_the_key_state_is_read_per_workspace() -> None:
    vendor = _Vendor(
        {
            ("GET", "/byok", STUDIO): _ok(_STATUS),
            ("GET", "/byok", None): _ok({"enabled": False, "using": "none", "credentials": "x"}),
        }
    )
    engine = _engine(vendor)
    studio = await engine.own_key_state(workspace=STUDIO)
    assert studio.speaks_on_own_voice and studio.voice_provider == "cartesia"
    ours = await engine.own_key_state(workspace=None)
    assert not ours.speaks_on_own_voice and ours.voice_provider is None
    assert await engine.own_keys_in_use() is False


async def test_a_key_state_without_using_is_refused() -> None:
    vendor = _Vendor({("GET", "/byok", None): _ok({"enabled": True})})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).own_keys_in_use()
    assert caught.value.code == "engine_bad_response"


async def test_our_voice_key_is_installed_and_switched_on_inside_the_workspace() -> None:
    bodies: list[dict[str, Any]] = []

    def _record(answer: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
        def _handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return answer

        return _handler

    vendor = _Vendor(
        {
            ("PUT", "/byok/credentials", STUDIO): _record(_ok({"kind": "tts"})),
            ("PATCH", "/byok", STUDIO): _record(_ok({"enabled": True})),
            ("GET", "/byok", STUDIO): _ok(_STATUS),
        }
    )
    engine = _engine(vendor)
    await engine.install_own_voice_key(
        workspace=STUDIO, provider="cartesia", api_key="sk_car", model="sonic-3"
    )
    state = await engine.enable_own_voice_key(workspace=STUDIO)
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
    vendor = _Vendor({("PUT", "/byok/credentials", STUDIO): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).install_own_voice_key(
            workspace=STUDIO, provider="cartesia", api_key="sk", model=None
        )
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("status", "code"), [(409, "engine_voice_key_not_ready"), (500, "engine_rejected")]
)
async def test_switching_on_a_key_that_is_not_ready_is_said_plainly(status: int, code: str) -> None:
    vendor = _Vendor({("PATCH", "/byok", STUDIO): _ok({"error": "x"}, status)})
    with pytest.raises(ProblemError) as caught:
        await _engine(vendor).enable_own_voice_key(workspace=STUDIO)
    assert caught.value.code == code


async def test_a_workspace_is_created_once_with_an_idempotency_key() -> None:
    def _create(request: httpx.Request) -> httpx.Response:
        assert request.headers["Idempotency-Key"] == "calevate-workspace-calevate-studio"
        assert WORKSPACE_HEADER not in request.headers
        assert json.loads(request.content) == {"name": "Studio", "externalId": "calevate-studio"}
        return _ok({"id": "org_new"}, 201)

    vendor = _Vendor({("POST", "/customers", None): _create})
    assert await _engine(vendor).create_workspace(name="Studio", external_id="calevate-studio") == (
        "org_new"
    )


async def test_a_workspace_we_made_before_is_found_by_its_external_id() -> None:
    vendor = _Vendor(
        {
            ("POST", "/customers", None): _ok({"error": "taken"}, 409),
            ("GET", "/customers", None): _ok(
                {"items": [{"id": ""}, {"id": "org_old"}], "nextCursor": None}
            ),
        }
    )
    assert (
        await _engine(vendor).create_workspace(name="S", external_id="calevate-studio") == "org_old"
    )
    assert vendor.seen[-1].url.params["externalId"] == "calevate-studio"


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        (
            {("POST", "/customers", None): _ok({"error": "x"}, 402)},
            "engine_workspace_limit_reached",
        ),
        ({("POST", "/customers", None): _ok({"error": "x"}, 500)}, "engine_rejected"),
        (
            {
                ("POST", "/customers", None): _ok({"error": "x"}, 409),
                ("GET", "/customers", None): _ok({"items": [], "nextCursor": None}),
            },
            "engine_rejected",
        ),
        ({("POST", "/customers", None): _ok({}, 201)}, "engine_bad_response"),
    ],
)
async def test_a_workspace_that_cannot_be_made_is_refused_by_name(
    answers: dict[Key, httpx.Response], code: str
) -> None:
    with pytest.raises(ProblemError) as caught:
        await _engine(_Vendor(answers)).create_workspace(name="S", external_id="calevate-studio")
    assert caught.value.code == code


async def test_no_language_model_key_of_ours_is_installed() -> None:
    with pytest.raises(ProblemError) as caught:
        await _engine(_Vendor({})).set_llm_credential("sk", provider="openai")
    assert caught.value.code == "engine_capability_absent"


# --- every call about a Studio agent goes to the Studio workspace --------------------


_AGENT = {"id": "ag_9", "greeting": "Idi AI assistant.", "instructions": "x"}


async def test_a_studio_dial_is_placed_and_held_in_its_workspace() -> None:
    vendor = _Vendor(
        {
            ("GET", "/agents/ag_9", STUDIO): _ok(_AGENT),
            ("POST", "/calls", STUDIO): _ok({"id": "out_1", "status": "ringing"}, 201),
        }
    )
    handle = await _engine(vendor).start_outbound_call(
        "ag_9@org_studio", "+919000000001", CallContext(call_id="c-1")
    )
    assert handle == "out_1@org_studio"
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


async def test_a_studio_call_is_read_and_its_recording_fetched_in_its_workspace() -> None:
    vendor = _Vendor({("GET", "/calls/out_1", STUDIO): _ok(_call())})
    engine = _engine(vendor)
    snapshot = await engine.get_execution("out_1@org_studio")
    assert snapshot.engine_call_id == "out_1@org_studio"
    assert snapshot.engine_agent_ref == "ag_9@org_studio"
    source = engine.recording_source(snapshot)
    assert source is not None and source.url.endswith("/calls/out_1/recording")
    assert source.auth_headers[WORKSPACE_HEADER] == STUDIO


async def test_ending_a_studio_call_asks_its_workspace() -> None:
    vendor = _Vendor(
        {
            ("GET", "/calls/out_1", STUDIO): _ok(_call(status="ringing", analysedAt=None)),
            ("DELETE", "/calls/out_1", STUDIO): _ok({"status": "cancelled"}),
        }
    )
    outcome = await _engine(vendor).end_call("out_1@org_studio")
    assert outcome.value == "prevented"


async def test_a_delivery_is_scoped_by_the_receiver_or_by_its_own_workspace_id() -> None:
    engine = _engine(_Vendor({}), studio=STUDIO)
    scoped = engine.snapshot_from_delivery({"data": _call()}, workspace=STUDIO)
    assert scoped.engine_call_id == "out_1@org_studio"
    named = engine.snapshot_from_delivery({"data": _call(workspaceId=STUDIO)})
    assert named.engine_agent_ref == "ag_9@org_studio"
    stranger = engine.snapshot_from_delivery({"data": _call(workspaceId="org_other")})
    assert stranger.engine_call_id == "out_1"
    event = engine.parse_webhook({"data": _call(workspaceId=STUDIO)})
    assert (event.call_id, event.engine_agent_ref) == ("out_1@org_studio", "ag_9@org_studio")
    bare = engine.parse_webhook({"data": {"status": "completed"}})
    assert (bare.call_id, bare.engine_agent_ref) == ("", None)


def test_a_studio_delivery_is_verified_with_the_scoped_agents_secret() -> None:
    import hashlib
    import hmac

    asked: list[str] = []

    def _secret(ref: str) -> str:
        asked.append(ref)
        return "s3cret"

    engine = ThinnestEngine(
        api_key="k", signing_secret_for=_secret, studio_workspace=lambda: STUDIO
    )
    body = json.dumps({"event": "call.analysed", "data": _call(workspaceId=STUDIO)}).encode()
    signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    verdict = engine.verify_webhook({"x-thinnest-signature": signature}, body, "1.2.3.4")
    assert verdict.ok and asked == ["ag_9@org_studio"]


async def test_listings_walk_both_workspaces_and_scope_what_the_studio_one_returns() -> None:
    page = {"nextCursor": None}
    vendor = _Vendor(
        {
            ("GET", "/calls", None): _ok({**page, "items": [_call(id="out_a")]}),
            ("GET", "/calls", STUDIO): _ok({**page, "items": [_call(id="out_b")]}),
            ("GET", "/usage/calls", None): _ok(
                {
                    **page,
                    "items": [{"id": "out_a", "costMicro": 1_500_000, "agent": {"id": "ag_1"}}],
                }
            ),
            ("GET", "/usage/calls", STUDIO): _ok(
                {**page, "items": [{"id": "out_b", "costMicro": 750_000, "agent": {"id": "ag_9"}}]}
            ),
            ("GET", "/phone-numbers", None): _ok({**page, "items": []}),
            ("GET", "/phone-numbers", STUDIO): _ok(
                {**page, "items": [{"number": "918012345678", "source": "rented", "agent": "ag_9"}]}
            ),
            ("GET", "/agents", None): _ok({**page, "items": []}),
            ("GET", "/agents", STUDIO): _ok({**page, "items": [{"id": "ag_9"}, {"id": None}]}),
            ("GET", "/agents/ag_9/knowledge", STUDIO): _ok({**page, "items": [{"id": "doc_1"}]}),
        }
    )
    engine = _engine(vendor, studio=STUDIO)
    listing = await engine.list_executions(since=datetime(2026, 10, 1, tzinfo=UTC))
    assert [s.engine_call_id for s in listing.snapshots] == ["out_a", "out_b@org_studio"]
    charges = await engine.list_call_charges(since=date(2026, 10, 1))
    assert [(c.engine_call_id, c.engine_agent_ref) for c in charges.charges] == [
        ("out_a", "ag_1"),
        ("out_b@org_studio", "ag_9@org_studio"),
    ]
    numbers = await engine.list_engine_numbers()
    assert [n.answering_agent_ref for n in numbers] == ["ag_9@org_studio"]
    kb = await engine.list_account_kb()
    assert [o.handle for o in kb.objects] == ["doc_1"] and kb.complete


async def test_studio_agent_reads_and_writes_go_to_its_workspace() -> None:
    vendor = _Vendor(
        {
            ("GET", "/agents/ag_9", STUDIO): _ok(_AGENT),
            ("GET", "/agents/ag_9/knowledge", STUDIO): _ok({"items": [], "nextCursor": None}),
            ("PATCH", "/agents/ag_9", STUDIO): _ok(_AGENT),
            ("DELETE", "/agents/ag_9", STUDIO): httpx.Response(204),
        }
    )
    engine = _engine(vendor)
    snapshot = await engine.get_agent("ag_9@org_studio")
    assert snapshot.engine_agent_ref == "ag_9@org_studio" and snapshot.system_prompt == "x"
    await engine.override_call_script("ag_9@org_studio", opening_line="Hi", system_prompt="Sorry")
    await engine.delete_agent("ag_9@org_studio")
    assert all(r.headers.get(WORKSPACE_HEADER) == STUDIO for r in vendor.seen)


async def test_the_webhook_and_action_clients_scope_by_the_handle() -> None:
    from apps.api.engine.thinnest_actions import ThinnestActions
    from apps.api.engine.thinnest_webhooks import ThinnestWebhooks

    vendor = _Vendor(
        {
            ("POST", "/webhooks", STUDIO): _ok(
                {"id": "wh_1", "url": "u", "signingSecret": "s"}, 201
            ),
            ("GET", "/webhooks", STUDIO): _ok({"items": [{"id": "wh_1", "enabled": True}]}),
            ("GET", "/webhooks/wh_1", STUDIO): _ok({"id": "wh_1", "enabled": False}),
            ("PATCH", "/webhooks/wh_1", STUDIO): _ok({"id": "wh_1", "enabled": True}),
            ("DELETE", "/webhooks/wh_1", STUDIO): httpx.Response(204),
            ("GET", "/calls", STUDIO): _ok(
                {"items": [{"id": "out_1", "phone": "91900"}], "nextCursor": None}
            ),
        }
    )
    client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(vendor))
    hooks = ThinnestWebhooks(api_key="k", client=client)
    created = await hooks.create(engine_agent_ref="ag_9@org_studio", url="u")
    assert created.endpoint.webhook_id == "wh_1@org_studio"
    assert json.loads(vendor.seen[-1].content)["agent"] == "ag_9"
    assert [e.webhook_id for e in await hooks.list_for_agent("ag_9@org_studio")] == [
        "wh_1@org_studio"
    ]
    assert (await hooks.get("wh_1@org_studio")).enabled is False
    assert (await hooks.enable("wh_1@org_studio")).enabled is True
    await hooks.delete("wh_1@org_studio")
    actions = ThinnestActions(api_key="k", client=client)
    live = await actions.live_calls("ag_9@org_studio")
    assert [c.engine_call_id for c in live] == ["out_1@org_studio"]
    assert vendor.seen[-1].url.params["agent"] == "ag_9"


def test_a_snapshot_without_a_call_id_is_not_scoped() -> None:
    snapshot = _engine(_Vendor({}))._snapshot({"status": "completed"}, workspace=STUDIO)
    assert isinstance(snapshot, ExecutionSnapshot) and snapshot.engine_call_id == ""
