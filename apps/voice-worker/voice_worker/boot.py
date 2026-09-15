"""The container's boot gate: what this process needs, proved BEFORE a caller is on it.

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns the process environment into a
`WorkerConfig` and a `WorkerRuntime`, and it REFUSES — naming every missing variable at
once — rather than letting the container come up and discover the hole on the first call.

**WHY THE REFUSAL IS THE POINT AND NOT THE ERGONOMICS.** Every piece of configuration
below is reached on a path a caller is already waiting on. `PlivoFrameSerializer` raises
`ValueError("auto_hang_up is enabled but missing required parameters: auth_id, auth_token")`
at CONSTRUCTION, which is inside the first session
(`pipecat/serializers/plivo.py:79-92`, `pipecat-ai==1.10.0` as installed, read
15 Sep 2026) — so an image deployed without those two answers the phone, talks, and then
cannot hang up, because the hang-up is `DELETE https://api.plivo.com/v1/Account/
{auth_id}/Call/{call_id}/` and it needs them (`plivo.py:172-192`). A leg nobody hung up
is a leg the carrier goes on billing. That is the whole argument for a boot gate: the
cheapest of these failures costs a call, and the most expensive costs money on a call
that already ended.

**WHY `Settings` IS NOT USED HERE, WHICH IS THE ONE DECISION A REVIEWER SHOULD PUSH ON.**
`calevate_shared.config.Settings` is the VPS stack's configuration object: it demands
`APP_ENV`, `REDIS_URL` and the rest of `BOOTSTRAP_REQUIRED`, and it reads `.env` from a
working directory this container does not have. None of that exists on Pipecat Cloud
(`docs/PIPECAT-MIGRATION.md` §8, box 1), so constructing one here would mean either
inventing values for fields this process never reads, or loosening a type three
deployables depend on. What is shared instead is the thing that actually matters — the
VARIABLE NAMES. Every credential below is spelled exactly as its `Settings` field is
spelled, so the founder installs one value under one name in the ops console and in the
Pipecat Cloud secret set, and `scripts/check_env_parity.py` can still see every name this
module reads (the two that are not `Settings` fields are registered there with their
reason). ⚠ **THAT COUNT WAS FOUR UNTIL D-614**: the carrier pair below are `Settings`
fields now — classified `ENV_ONLY`, so the ops console SHOWS them with the reason they can
only come from this container's environment and refuses to store a value nothing here
could read. Nothing about how this module reads them changed.

**WHERE EACH VALUE COMES FROM.** There is no `.env` in this container and no ops console
to read: the console's `platform_secrets` rows are sealed with `PLATFORM_KEK`, and
**`PLATFORM_KEK` MUST NEVER BE IN THIS IMAGE** — it opens every credential the platform
holds, and this is the one deployable a vendor's runtime operates. So the vendor's own
secret store is the injector: `pipecat cloud secrets set <secret_set> --file .env`, whose
name matches `secret_set` in `pcc-deploy.toml`, and whose values arrive as process
environment (`pipecat/cli/agent_templates/AGENTS.md:302-304`, shipped inside the pinned
package — "a deployed bot has none of your local .env"). A human puts the same value in
both places; nothing here fetches one from the other.

**HARD RULE 6.** A refusal names VARIABLES, never values, and nothing here logs a
credential, a length or a prefix.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from voice_worker.db import WorkerDatabase, tenant_connection
from voice_worker.knowledge import QueryEmbedder
from voice_worker.pipeline import NormalizedEventSink, VendorCredentials
from voice_worker.storage import BUCKET_ENV, ENDPOINT_ENV, ObjectStorePackFetcher
from voice_worker.vendor_logging import install_vendor_log_guard

# ---------------------------------------------------------------------------------------
# The variable names. Spelled once, here, and cited everywhere else.
# ---------------------------------------------------------------------------------------

#: Our Postgres. The APP role (NOSUPERUSER NOBYPASSRLS), never the owner: this process
#: reads one tenant's published configuration under RLS and writes that tenant's events,
#: and hard rule 1 says the isolation is the GUC on a role that cannot bypass it.
DATABASE_URL_ENV: Final[str] = "DATABASE_URL"

#: botocore's own pair. NOT read as configuration — `ObjectStorePackFetcher` passes no
#: credentials to boto3 and never will (`storage._client`) — but their ABSENCE is checked
#: here, because the alternative is a signed request that 403s on the first call of the
#: deploy while the only log line says the client published nothing.
AWS_KEY_ENV: Final[str] = "AWS_ACCESS_KEY_ID"
AWS_SECRET_ENV: Final[str] = "AWS_SECRET_ACCESS_KEY"

#: The speech leg. STT is Sarvam throughout (CLAUDE.md) and today's TTS is Sarvam too, so
#: this key is required on every call; `CARTESIA_API_KEY` is the Studio tier's and is not.
SARVAM_KEY_ENV: Final[str] = "SARVAM_API_KEY"
CARTESIA_KEY_ENV: Final[str] = "CARTESIA_API_KEY"
#: The Gnani TTS leg (D-618). OPTIONAL for the same reason `CARTESIA_API_KEY` is: it is
#: needed only by an agent whose `ModelConfig.tts_provider` names it, and a container with
#: no Gnani key refuses THAT call by name rather than refusing to start. It is read HERE
#: and nowhere else — `apps/api` holds no Gnani client, which is why `gnani_api_key` is
#: env-only in the ops console and points an operator at this secret set.
GNANI_KEY_ENV: Final[str] = "GNANI_API_KEY"

#: The three declared LLM legs (CLAUDE.md, the multi-provider paragraph). Which one a call
#: needs is decided PER AGENT by `ModelConfig.llm_provider`, so the boot gate demands at
#: least one and `credentials_for` refuses by name when a call arrives for a provider this
#: container was not given a key for.
LLM_KEY_ENV_BY_PROVIDER: Final[Mapping[str, str]] = {
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
}

#: Read by PIPECAT, not by us: `runner.utils._create_telephony_transport` builds
#: `PlivoFrameSerializer(auth_id=os.getenv("PLIVO_AUTH_ID", ""), ...)`
#: (`pipecat/runner/utils.py:532-539`). We check them so the failure is a boot refusal
#: instead of a live call that cannot be hung up — see this module's docstring.
#:
#: BOTH ARE `Settings` FIELDS (`plivo_auth_id` / `plivo_auth_token`, D-614) AND NEITHER IS
#: READ THROUGH ONE, here or anywhere. The field exists so the credential has a row in the
#: platform's own register — a name on the ops console, an `env_var`, and the sentence
#: saying it belongs in this container's secret set — which is the surface that had nothing
#: to say about the carrier at all. The spelling is identical in both homes on purpose: one
#: value, one name.
PLIVO_AUTH_ID_ENV: Final[str] = "PLIVO_AUTH_ID"
PLIVO_AUTH_TOKEN_ENV: Final[str] = "PLIVO_AUTH_TOKEN"

#: How long a container being replaced may spend settling the call it is carrying.
#: Optional, because it has a default and because the number it WANTS to be is the
#: platform's SIGTERM-to-SIGKILL window, which is UNKNOWN here (`docs.pipecat.ai` is
#: egress-blocked). See `DEFAULT_DRAIN_GRACE_S`.
DRAIN_GRACE_ENV: Final[str] = "VOICE_WORKER_DRAIN_GRACE_SECONDS"

#: Where to write the readiness marker, or unset for none. See `lifecycle.ReadinessFile`.
READY_FILE_ENV: Final[str] = "VOICE_WORKER_READY_FILE"

#: ⚠ **AN ASSUMPTION WITH A REASONED FLOOR, NOT A MEASUREMENT.** What this wants to be is
#: the platform's own SIGTERM-to-SIGKILL window, and nothing in this tree knows it:
#: Pipecat Cloud's container contract is not readable from here. What the number has to
#: cover is OURS and is bounded: `PipelineWorker.flush_pipeline` defaults to a 5 s drain
#: (`pipecat/pipeline/worker.py:924`), a worst-case turn carries one tool call at
#: `FUNCTION_CALL_TIMEOUT_SECS` (2 s) plus the model and the speech, and the terminal
#: `CallEvent` is one INSERT. Twenty seconds is comfortably above that sum and is the
#: same order as the 20-25 s drains `compose.prod.yml` gives the VPS services against
#: their 30 s grace. It is a variable precisely so the operator who learns the real window
#: can set it without a rebuild.
DEFAULT_DRAIN_GRACE_S: Final[float] = 20.0

#: ONE SESSION PER CONTAINER. Not ours to choose: "1 session per instance; max pool 50"
#: (`docs/evidence/engine-replacement-comet-2026-09-06.md:122`, marked VERIFIED against
#: Pipecat Cloud's pricing page on 6 Sep 2026 by the founder's research run — REPORTED
#: from this container's seat, which is why it decides a capacity number here and nothing
#: about money). `lifecycle.SessionRegistry` uses it for what READY means: a container
#: carrying its one call has nothing to offer a scheduler, whatever its process health says.
MAX_CONCURRENT_SESSIONS: Final[int] = 1

#: Socket-level bounds on the database connection, COPIED from `apps/api/db/session.py`
#: (`_CONNECT_ARGS`) rather than imported, for the reason `voice_worker/storage.py` gives
#: about `apps/workers/storage`: that module pulls `apps.api.core.settings` and the rest
#: of the monolith into a latency-critical voice container. The VALUES are not re-derived
#: here — that file argues each of the six against a bound this repo already has, and a
#: second derivation would be a second doctrine. If they move there they move here, and
#: `tests/voice_worker_boot_test.py` pins the two to each other so the copy cannot rot.
_CONNECT_ARGS: Final[dict[str, int]] = {
    "connect_timeout": 2,
    "tcp_user_timeout": 5000,
    "keepalives": 1,
    "keepalives_idle": 2,
    "keepalives_interval": 1,
    "keepalives_count": 3,
}

#: Two connections, and the number is `apps/api/db/session.MAX_NESTED_CONNECTIONS`: one
#: session's config read plus the event write it makes while that read is still open. A
#: container that carries ONE call wants no more, and a pool sized for comfort here is
#: capacity taken from the VPS stack on the same Postgres.
_POOL_SIZE: Final[int] = 2


class WorkerConfigError(RuntimeError):
    """The container cannot start, and the message names every variable that is why.

    ONE exception carrying ALL the missing names, not the first one. An operator filling a
    secret set is doing it through a vendor CLI and a browser; telling them about one
    variable per deploy cycle is three deploys to learn what one message could have said.
    """


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Everything this container was given, validated. No vendor objects, no clients.

    Separate from `WorkerRuntime` because validating the environment and OPENING things
    are different failures with different audiences: a missing variable is a secret set to
    fix, and a database that will not answer is an outage. `load_worker_config` can be
    exercised with no network at all, which is what makes the refusal testable.
    """

    database_url: str
    object_store_bucket: str
    object_store_endpoint: str
    sarvam_api_key: str
    #: provider -> key, holding only the providers this container was actually given a key
    #: for. At least one, by construction; `credentials_for` refuses the rest by name.
    llm_api_keys: Mapping[str, str]
    cartesia_api_key: str | None
    #: The Clear tier's future TTS leg (D-618). `None` until the founder puts a key in this
    #: container's secret set; `pipeline._build_tts` refuses a Gnani call by name.
    gnani_api_key: str | None
    drain_grace_s: float
    ready_file: str | None

    def credentials_for(self, provider: str | None) -> VendorCredentials:
        """The three keys for a call on `provider`, or a refusal naming the variable.

        **THIS IS THE ONE PLACE A PER-CALL PROVIDER MEETS A PER-CONTAINER KEY**, and it
        raises rather than falling back to another provider's key. A fallback would send a
        client's caller's words to a vendor their agent does not name — the single value
        D-127's argument turns on — and it would do it invisibly, because an LLM service
        constructed with the wrong key fails at the first turn as an auth error that reads
        like an outage.

        `None` means the agent named nothing, which `pipeline._build_llm` resolves to
        `azure_openai`; the same default is applied here so the two cannot disagree about
        which key a defaulted call spends.
        """
        name = provider or "azure_openai"
        key = self.llm_api_keys.get(name)
        if key is None:
            variable = LLM_KEY_ENV_BY_PROVIDER.get(name)
            raise WorkerConfigError(
                f"this container has no credential for llm_provider {name!r}: "
                + (
                    f"set {variable} in the Pipecat Cloud secret set"
                    if variable
                    else f"{name!r} is not one of this product's declared LLM legs "
                    f"({', '.join(sorted(LLM_KEY_ENV_BY_PROVIDER))})"
                )
            )
        return VendorCredentials(
            sarvam_api_key=self.sarvam_api_key,
            llm_api_key=key,
            cartesia_api_key=self.cartesia_api_key,
            gnani_api_key=self.gnani_api_key,
        )


def _present(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _drain_grace(env: Mapping[str, str], failures: list[str]) -> float:
    raw = _present(env, DRAIN_GRACE_ENV)
    if raw is None:
        return DEFAULT_DRAIN_GRACE_S
    try:
        value = float(raw)
    except ValueError:
        failures.append(f"{DRAIN_GRACE_ENV} is not a number")
        return DEFAULT_DRAIN_GRACE_S
    if value <= 0:
        # Zero would mean "cut every call the instant a deploy starts", which is the
        # behaviour this module exists to stop somebody reaching by accident.
        failures.append(f"{DRAIN_GRACE_ENV} must be greater than zero")
    return value


def load_worker_config(env: Mapping[str, str] | None = None) -> WorkerConfig:
    """Validate the process environment, or raise naming every variable that is missing.

    `env` is an argument so a test can hand in a mapping rather than mutate the process —
    the same seam `ObjectStorePackFetcher.from_env` has, for the same reason.

    **THE TWO `AWS_*` CREDENTIALS ARE CHECKED AND NOT CARRIED**, which looks inconsistent
    and is not. botocore resolves them itself on every client build and will keep doing so
    whatever we hold (`scripts/check_env_parity.SDK_ENV_KEYS` carries the full argument);
    a field here would be a SECOND value the SDK ignores. What a boot gate can honestly do
    with somebody else's variable is notice that it is absent, so that is all this does.
    """
    source = os.environ if env is None else env
    failures: list[str] = []

    required = {
        DATABASE_URL_ENV: _present(source, DATABASE_URL_ENV),
        BUCKET_ENV: _present(source, BUCKET_ENV),
        ENDPOINT_ENV: _present(source, ENDPOINT_ENV),
        AWS_KEY_ENV: _present(source, AWS_KEY_ENV),
        AWS_SECRET_ENV: _present(source, AWS_SECRET_ENV),
        SARVAM_KEY_ENV: _present(source, SARVAM_KEY_ENV),
        PLIVO_AUTH_ID_ENV: _present(source, PLIVO_AUTH_ID_ENV),
        PLIVO_AUTH_TOKEN_ENV: _present(source, PLIVO_AUTH_TOKEN_ENV),
    }
    failures.extend(
        f"{name} is not set" for name, value in sorted(required.items()) if value is None
    )

    llm_keys = {
        provider: key
        for provider, variable in LLM_KEY_ENV_BY_PROVIDER.items()
        if (key := _present(source, variable)) is not None
    }
    if not llm_keys:
        failures.append(
            "no LLM credential is set: this container needs at least one of "
            + ", ".join(sorted(LLM_KEY_ENV_BY_PROVIDER.values()))
            + " — which one a call needs is decided per agent by ModelConfig.llm_provider"
        )

    grace = _drain_grace(source, failures)

    if failures:
        raise WorkerConfigError(
            "the voice worker cannot start: "
            + "; ".join(failures)
            + ". Every value comes from the Pipecat Cloud secret set named by "
            "`secret_set` in apps/voice-worker/pcc-deploy.toml (docs/DEPLOYMENT.md §12)."
        )

    return WorkerConfig(
        database_url=required[DATABASE_URL_ENV] or "",
        object_store_bucket=required[BUCKET_ENV] or "",
        object_store_endpoint=required[ENDPOINT_ENV] or "",
        sarvam_api_key=required[SARVAM_KEY_ENV] or "",
        llm_api_keys=llm_keys,
        cartesia_api_key=_present(source, CARTESIA_KEY_ENV),
        gnani_api_key=_present(source, GNANI_KEY_ENV),
        drain_grace_s=grace,
        ready_file=_present(source, READY_FILE_ENV),
    )


class EventSinkNotBuiltError(RuntimeError):
    """There is nowhere for this call's transcript to go, so the container will not start.

    **AN HONEST DEAD END, NOT AN OVERSIGHT, AND IT IS DELIBERATELY AT BOOT.**
    `pipeline.NormalizedEventSink`'s implementation — the writer that puts our `CallEvent`
    and `TranscriptTurn` rows in Postgres — does not exist yet
    (`docs/PIPECAT-MIGRATION.md` §6 step 11: "what is still not called in production is
    the CONTAINER BOOTSTRAP"). The alternative shape, a sink that accepts and discards,
    would let this image deploy, answer a call and lose the conversation while every
    health signal stayed green: the client's CRM would show an agent that never spoke to
    anybody. Refusing at boot costs a deploy that could not have worked anyway.

    When the writer lands, `build_event_sink` returns it and this class goes with it.
    """


def build_event_sink(engine: AsyncEngine) -> NormalizedEventSink:
    """The normalized event writer. Raises until one exists — see `EventSinkNotBuiltError`."""
    raise EventSinkNotBuiltError(
        "the normalized event writer (pipeline.NormalizedEventSink) is not built, so a "
        "container that answered a call now would drop every transcript turn on the "
        f"floor. docs/PIPECAT-MIGRATION.md §6 step 11. (engine={engine.url.drivername})"
    )


@dataclass(slots=True)
class WorkerRuntime:
    """The process-scoped things one container opens once and shares across its sessions.

    **ONE OWNER FOR THE PROCESS, WHICH IS WHY THIS EXISTS AT ALL.** `config.py` argues
    that it takes a connection rather than owning an engine so that "one process wants ONE
    pool sized against ONE workload", and `session.py` keeps the pack cache at module scope
    for the same reason. This is the module those two were deferring to.

    **THERE IS NO SHARED HTTP CLIENT HERE, AND THERE WAS ONE FOR A DRAFT.** `embedding.py`
    wants one `httpx.AsyncClient` for the life of the process — a client per turn re-does
    the TLS handshake inside a 1.2 s budget — and it takes that client as an argument
    precisely so it owns no global. Nothing in this container can construct the dense arm
    today (hard rule 7's pre-flight for it is a question this deployable deliberately
    cannot ask), so a client opened here would be a connection pool nobody uses and a
    field nobody reads. Whoever supplies an `embedder` supplies its client with it.
    """

    config: WorkerConfig
    engine: AsyncEngine
    fetcher: ObjectStorePackFetcher
    embedder: QueryEmbedder | None

    async def aclose(self) -> None:
        """Release the pool. Safe to call twice."""
        await self.engine.dispose()


async def open_runtime(
    config: WorkerConfig,
    *,
    embedder: QueryEmbedder | None = None,
    verify: bool = True,
) -> WorkerRuntime:
    """Open this container's shared resources and PROVE the database answers.

    **`verify` IS WHAT MAKES READINESS MEAN ANYTHING.** A pool that has never connected is
    indistinguishable from a working one until the first checkout, which on this deployable
    is the first caller. One `SELECT 1` against a 2-second connect bound turns "the process
    started" into "the dependency this call cannot proceed without is reachable from this
    container", which is the only readiness claim worth publishing. The object store is
    deliberately NOT probed: a pack fetch is bounded (`storage.PACK_FETCH_BUDGET_S`) and
    its failure is a degraded call rather than no call, so paying a round trip at boot
    would buy a signal nothing acts on.

    **`embedder` DEFAULTS TO `None` AND THAT IS NOT AN OMISSION.** The dense retrieval arm
    spends money per turn, and hard rule 7's pre-flight for it is a question this container
    deliberately cannot ask (`voice_worker/embedding.py`). A bootstrap supplies one only
    where that has been answered; until then the lexical arm answers, which is the
    overwhelming majority of turns (`docs/PIPECAT-MIGRATION.md` §8.1a).
    """
    install_vendor_log_guard()
    # ONE ENGINE PER CONTAINER, BUILT BY `db.WorkerDatabase` AND NOT HERE.
    # This module built a second `create_async_engine` in parallel with that one and left
    # off `hide_parameters=True` — so the container had two pools and the one `bot.py`
    # actually used rendered bound parameters into every DBAPI error string. On this
    # deployable those parameters are phone numbers and transcript text (hard rule 6).
    # The engine's keyword arguments are a single fact about this workload and now have a
    # single home; `pii_logging_sweep_test` pins one builder per deployable.
    database = WorkerDatabase(config.database_url)
    engine = database.engine
    if verify:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    fetcher = ObjectStorePackFetcher.from_env()
    logger.info(
        "voice worker runtime open",
        # Names and counts only (hard rule 6). WHICH legs this container can serve is the
        # fact an operator needs the moment a call refuses on a provider.
        llm_providers=sorted(config.llm_api_keys),
        cartesia=config.cartesia_api_key is not None,
        gnani=config.gnani_api_key is not None,
        drain_grace_s=config.drain_grace_s,
        dense_arm=embedder is not None,
    )
    return WorkerRuntime(config=config, engine=engine, fetcher=fetcher, embedder=embedder)


__all__ = [
    "AWS_KEY_ENV",
    "AWS_SECRET_ENV",
    "CARTESIA_KEY_ENV",
    "DATABASE_URL_ENV",
    "DEFAULT_DRAIN_GRACE_S",
    "DRAIN_GRACE_ENV",
    "GNANI_KEY_ENV",
    "LLM_KEY_ENV_BY_PROVIDER",
    "MAX_CONCURRENT_SESSIONS",
    "PLIVO_AUTH_ID_ENV",
    "PLIVO_AUTH_TOKEN_ENV",
    "READY_FILE_ENV",
    "SARVAM_KEY_ENV",
    "EventSinkNotBuiltError",
    "WorkerConfig",
    "WorkerConfigError",
    "WorkerRuntime",
    "build_event_sink",
    "load_worker_config",
    "open_runtime",
    "tenant_connection",
]
