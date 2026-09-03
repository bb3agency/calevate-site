"""What the engine is told about a caller before it answers them, and what it is not.

The INBOUND half of cross-call memory (D-509). Bolna fetches caller details from this
endpoint at call setup and injects the answer into the agent's instructions
(VERIFIED-VENDOR-DOCS, read 2 Sep 2026: `bolna-findings/mirror/pages/agent-setup/
inbound-tab.md:49-63` — a GET, query parameters `contact_number`/`agent_id`/
`execution_id`, and a Bearer token their console stores).

TWO PROPERTIES, PULLING IN OPPOSITE DIRECTIONS, AND BOTH ARE TESTED HERE:

* **IT FAILS OPEN.** Every lookup outcome that is not "here is what we remember" is `{}` —
  an unknown agent, a caller with nothing on file, an agent whose account never switched
  this on, a database that is down. A returning caller greeted plainly is a missed nicety;
  a caller who gets no answer because a memory lookup raised is a broken product, and the
  engine is holding an open line while we decide.
* **AUTHENTICATION DOES NOT.** A caller who does not present the token gets 401, because
  the alternative is an endpoint that answers a stranger's questions about our clients'
  callers. `test_an_unconfigured_deployment_answers_nobody` is the sharp end of that: an
  absent credential is a deployment nobody wired up, never "no authentication required".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import caller_data_routes, caller_memory
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app as api_app
from calevate_shared.engine import CALLER_MEMORY_VARIABLE
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.anyio

CALLER = "+919812345672"
FACT = "asked about a two-bedroom flat in Gachibowli"
TOKEN = "a-token-the-engine-was-given"


@pytest.fixture
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credential this deployment was configured with.

    Supplied explicitly because `conftest._no_ambient_credentials` strips the real ones,
    which is the correct default — and because "no token configured" is itself one of the
    behaviours under test.
    """
    monkeypatch.setenv("BOLNA_CALLER_DATA_TOKEN", TOKEN)
    from apps.api.core.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """A tenant, its agent, and the ENGINE's own id for that agent — which is the string
    the vendor sends as `agent_id` and the one `engine_agent_routes` is keyed by."""
    created = await admin_service.create_organization(
        name="Inbound Estates",
        slug=f"in-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"agent_{uuid.uuid4().hex[:10]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                "agent_id, active, created_at, updated_at) "
                "VALUES ('bolna', :ref, :tid, :aid, true, now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
        await session.commit()
    return tenant_id, agent_id, ref


async def _remember(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = true WHERE id = :aid"),
            {"aid": agent_id},
        )
        await caller_memory.remember(
            session,
            tenant_id,
            agent_id=agent_id,
            phone_e164=CALLER,
            occurred_at=datetime.now(UTC),
            source_call_id=None,
            facts=[FACT],
        )
        await session.commit()


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=api_app, client=("127.0.0.1", 44444)),
        base_url="http://api",
    )


def _url(ref: str) -> str:
    return (
        f"/v1/engine/caller-data/bolna?contact_number={CALLER}&agent_id={ref}&execution_id=exec_1"
    )


async def test_a_returning_caller_is_described_under_the_one_contract_key(
    _token: None,
) -> None:
    """THE HAPPY PATH, and the key is asserted against the CONTRACT rather than a literal:
    three producers fill this variable — the outbound dial, this endpoint, and the prompt
    token that expects it — and three spellings would be an agent reading a placeholder
    out loud."""
    tenant_id, agent_id, ref = await _tenant()
    await _remember(tenant_id, agent_id)
    async with _client() as client:
        response = await client.get(_url(ref), headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    body = response.json()
    assert FACT in body[CALLER_MEMORY_VARIABLE]


async def test_the_vendors_own_unencoded_plus_still_finds_the_caller(_token: None) -> None:
    """THE DEFECT THIS FEATURE WOULD HAVE SHIPPED WITH, found by driving the documented
    request rather than by reading the code.

    Their example is `contact_number=+919876543210` with the `+` UNENCODED
    (`bolna-findings/mirror/pages/agent-setup/inbound-tab.md:62`). In a query string `+` is
    the form-encoding for a space, so the number arrives as `" 919876543210"`, the keyed
    caller ref refuses it, and the endpoint fails open on EVERY inbound call while saying
    nothing but a log line — the feature would have been silently dead in production and
    green in CI.

    Both spellings are asserted, because the properly-encoded one is what a fixed vendor
    request would send and it must keep working.
    """
    tenant_id, agent_id, ref = await _tenant()
    await _remember(tenant_id, agent_id)
    raw = f"/v1/engine/caller-data/bolna?contact_number={CALLER}&agent_id={ref}"
    encoded = raw.replace("+", "%2B")
    for url in (raw, encoded):
        async with _client() as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert FACT in response.json()[CALLER_MEMORY_VARIABLE], f"{url} found nobody"


async def test_a_stranger_is_told_nothing_at_all(_token: None) -> None:
    """No token, a wrong token, and the wrong scheme are all 401. The endpoint is on the
    open internet and it answers questions about our clients' callers."""
    _tenant_id, _agent_id, ref = await _tenant()
    for headers in (
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},
        {"Authorization": "Basic " + TOKEN},
    ):
        async with _client() as client:
            response = await client.get(_url(ref), headers=headers)
        assert response.status_code == 401, f"{headers} was accepted"


async def test_an_unconfigured_deployment_answers_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AN ABSENT CREDENTIAL IS NOT "NO AUTHENTICATION REQUIRED". A deployment that has not
    been wired to the engine greets every inbound caller plainly, which is exactly what it
    does today — and it must not become an open read of every client's caller memory the
    moment somebody forgets to set a variable."""
    from apps.api.core.settings import get_settings

    monkeypatch.delenv("BOLNA_CALLER_DATA_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        _tenant_id, _agent_id, ref = await _tenant()
        async with _client() as client:
            response = await client.get(_url(ref), headers={"Authorization": "Bearer anything"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


async def test_an_agent_that_does_not_remember_callers_says_nothing(_token: None) -> None:
    """The DEFAULT. `recall()` checks the switch for itself, so this endpoint needs no
    knowledge that the feature has one — and a client who never switched it on cannot have
    their callers described to their own agent."""
    tenant_id, agent_id, ref = await _tenant()
    async with tenant_session(tenant_id) as session:
        await caller_memory.remember(
            session,
            tenant_id,
            agent_id=agent_id,
            phone_e164=CALLER,
            occurred_at=datetime.now(UTC),
            source_call_id=None,
            facts=[FACT],
        )
        await session.commit()
    async with _client() as client:
        response = await client.get(_url(ref), headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {}


async def test_an_unknown_agent_is_an_empty_answer_and_not_an_error(_token: None) -> None:
    """FAIL OPEN. An agent reference no row of ours knows is a misconfiguration on the
    vendor side; answering 4xx would put a broken call in front of a caller to report it."""
    async with _client() as client:
        response = await client.get(
            _url("agent_nobody_knows"), headers={"Authorization": f"Bearer {TOKEN}"}
        )
    assert response.status_code == 200
    assert response.json() == {}


async def test_a_lookup_that_raises_still_lets_the_call_connect(
    _token: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE WHOLE POINT OF FAILING OPEN, and it is asserted by breaking the read rather
    than by reading the code: a database that is down must cost a returning caller their
    greeting and not their call."""
    _tenant_id, _agent_id, ref = await _tenant()

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the database is unreachable")

    monkeypatch.setattr(caller_data_routes, "_remembered", _boom)
    async with _client() as client:
        response = await client.get(_url(ref), headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {}


async def test_no_caller_number_and_no_remembered_fact_reaches_a_log_line(
    _token: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Hard rule 6, on an endpoint whose entire input is a phone number and whose entire
    output is what somebody said about themselves."""
    tenant_id, agent_id, ref = await _tenant()
    await _remember(tenant_id, agent_id)
    with caplog.at_level("INFO"):
        async with _client() as client:
            await client.get(_url(ref), headers={"Authorization": f"Bearer {TOKEN}"})
    assert CALLER not in caplog.text
    assert "Gachibowli" not in caplog.text
