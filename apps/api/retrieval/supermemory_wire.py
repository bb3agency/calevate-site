"""The Supermemory wire contract — **ASSUMED, not verified** — and the tenant scope.

WHY THIS IS A SEPARATE MODULE FROM THE ADAPTER. Every fact in here is a claim about a
vendor's HTTP surface, and **this repository has read no page of Supermemory's API
documentation.** `supermemory.ai` is egress-blocked from this container (`docs/PIPECAT-
MIGRATION.md` §8.5 records the same measurement, 14 Sep 2026) and the product is not
installed. Hard rule 11 forbids writing a path, a request key or a response key as if it
were known — so instead of scattering plausible strings through an adapter where the next
reader would mistake them for findings, every one of them is a field of ONE frozen object
below, each labelled **ASSUMED**, and correcting the integration after somebody reads the
vendor's docs is editing that object and nothing else.

WHAT MAKES THAT SAFE RATHER THAN MERELY TIDY. The parser is STRICT against the contract and
a mismatch is not an exception a user sees: `parse_search` raises
`SupermemoryWireMismatchError`, `supermemory.py` treats it exactly like an unreachable host,
and the dashboard falls back to the Postgres retriever (§8.5's "only dashboard search
degrades"). So a wrong guess here costs a log line naming the keys that DID come back —
keys, never values, hard rule 6 — and an operator has the correction in front of them. A
tolerant parser that sniffed several plausible key names would have been the opposite: more
guesses, each of them silent.

THE TENANT SCOPE IS NOT A VENDOR FACT AND IS NOT ASSUMED. §8.4: Supermemory's local build
is single-tenant with one auto-generated API key, and scoped per-tenant keys are an
Enterprise feature [VERIFIED-VENDOR-DOCS: /docs/self-hosting/local-vs-enterprise, read by
the founder 14 Sep 2026]. A container tag is therefore **a filter we send, not a wall the
server enforces** — the wall stays in our Postgres. That is precisely why `TenantScope`
exists as a type rather than as a string argument: the one place a request body is built
cannot be reached without one, and `search_payload` re-asserts the tag it just wrote. A
filter that is merely conventional is a filter that is one hurried call site from being
absent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from calevate_shared.retrieval import Passage, Provenance, RetrievalRequest

#: The tag that carries a TENANT, and the prefix that keeps it from colliding with any
#: other tag we ever send. Ours, not the vendor's — what a tag MEANS is our choice; only
#: the field it travels in (`WireContract.container_tags_key`) is assumed.
TENANT_TAG_PREFIX: Final = "tenant:"

#: The tag that narrows to ONE agent, for `RetrievalRequest.agent_id`. Additive: a request
#: with no agent means "every live agent this tenant has" (the port says so), so the agent
#: tag is simply absent and the tenant tag still scopes the query.
AGENT_TAG_PREFIX: Final = "agent:"

#: What a passage is labelled when the vendor record carries no source name of ours.
#:
#: NOT a failure. `Provenance.source_id` is already optional in the port because the
#: compiled T0 block has no single source, and the same judgement applies here: an answer
#: out of a client's own approved knowledge is worth returning even when the name we used
#: at ingest did not survive the round trip. Dropping it instead would silently narrow a
#: client's own knowledge to punish a metadata gap — the rejected alternative, and it fails
#: in the direction that tells a client "we have nothing on file" when we do.
UNLABELLED_SOURCE: Final = "Published knowledge"


class SupermemoryWireMismatchError(RuntimeError):
    """The vendor answered in a shape `ASSUMED_CONTRACT` does not describe.

    A `RuntimeError` and not a `ProblemError`: nobody outside this package ever sees it.
    `supermemory.py` catches it beside the transport errors and falls back to Postgres,
    because "our guess about their JSON was wrong" and "their host is down" have the same
    correct response — answer the client from the store we run ourselves.
    """


@dataclass(frozen=True, slots=True)
class WireContract:
    """Every assumed fact about Supermemory's search surface, in one correctable object.

    Frozen and slotted for the reason every capability object in this tree is: a contract
    two call sites can disagree about is not a contract. A reader who has the vendor's docs
    open corrects the fields here, runs the suite, and nothing else in the package moves —
    which is the property this indirection is bought for, and the only one.
    """

    #: ASSUMED — the search endpoint, relative to `Settings.supermemory_base_url`.
    search_path: str
    #: ASSUMED — the request key carrying the question text.
    query_key: str
    #: ASSUMED — the request key carrying how many results are wanted.
    limit_key: str
    #: ASSUMED — the request key carrying the container tags. **This is the field the
    #: tenant filter rides in, so it is the single most load-bearing assumption in the
    #: file**: a wrong name here does not error, it asks an unscoped question. That is why
    #: `parse_search` is strict and why it re-checks every returned record's own tag
    #: against the scope that was asked for rather than trusting the server filtered.
    container_tags_key: str
    #: ASSUMED — the response key holding the list of matches.
    results_key: str
    #: ASSUMED — the per-result key holding the retrieved text.
    text_key: str
    #: ASSUMED — the per-result key holding the relevance score, where there is one.
    score_key: str
    #: ASSUMED — the per-result key holding the tags that record carries. Read back so the
    #: adapter can verify the scope it asked for, rather than assume it was honoured.
    result_tags_key: str
    #: ASSUMED — the per-result key holding whatever metadata we attached at ingest.
    metadata_key: str
    #: ASSUMED — the INGEST endpoint: where one document is written. A POST like the
    #: search, for the reason `delete_path` gives.
    ingest_path: str = "/v3/documents"
    #: ASSUMED — the DELETE endpoint, and **it is a POST rather than an HTTP DELETE**. That
    #: is a choice of ours on top of a guess of theirs, and it buys one thing: the transport
    #: stays a single verb, so the auth header (itself assumed — `supermemory.HttpxTransport`)
    #: is guessed once. A body-carrying DELETE would be a second assumption stacked on the
    #: first, and the correction cost is identical either way — this string, and the method
    #: on the transport.
    delete_path: str = "/v3/documents/delete"
    #: ASSUMED — the ingest request key carrying the document's text.
    content_key: str = "content"
    #: ASSUMED — the ingest request key carrying an id WE choose, so the document we wrote
    #: is the document we can later withdraw. **This is the load-bearing assumption of the
    #: write half**, the way `container_tags_key` is of the read half: if the vendor ignores
    #: a client-supplied id, every delete addresses nothing and a withdrawn price list stays
    #: searchable. It is why `kb_index_documents` records what we sent — the ledger is what
    #: makes the reconciliation sweep able to notice.
    document_id_key: str = "customId"
    #: ASSUMED — the delete request key carrying those ids. **Absent from the body means
    #: "everything carrying the tags"**, which is how a tenant purge is expressed; that
    #: reading is itself ASSUMED and is why the purge ALSO enumerates the ledger.
    delete_ids_key: str = "customIds"
    #: OURS, inside `metadata_key` — what `ingest_payload` writes and `_provenance` reads
    #: back. Not vendor facts: what a metadata value MEANS is our choice, only the field it
    #: travels in is assumed. Every one of them stays optional on the way back, because a
    #: record written before this contract was corrected is still a client's own knowledge.
    metadata_source_label: str = "calevate_source_label"
    metadata_source_id: str = "calevate_source_id"
    metadata_agent_id: str = "calevate_agent_id"
    metadata_document_version: str = "calevate_document_version"
    #: ASSUMED — the response key holding a token-usage block, and the key inside it. This
    #: is what hard rule 7's metering reads; when it is absent the adapter records nothing
    #: and says so at ERROR rather than inventing a quantity.
    usage_key: str = "usage"
    usage_tokens_key: str = "promptTokens"


#: THE ONE OBJECT TO CORRECT. Every value marked ASSUMED above is a guess this repository
#: cannot stand behind, written here so it is guessed exactly once.
#:
#: HOW TO CORRECT IT: read the vendor's search API page, edit these strings, run
#: `tests/retrieval_supermemory_test.py`. If a returned record nests its text or its tags
#: deeper than one key, that is the point at which this flat shape stops being enough and
#: `parse_search` — not twelve call sites — is what changes.
ASSUMED_CONTRACT: Final = WireContract(
    search_path="/v3/search",
    query_key="q",
    limit_key="limit",
    container_tags_key="containerTags",
    results_key="results",
    text_key="memory",
    score_key="score",
    result_tags_key="containerTags",
    metadata_key="metadata",
)


@dataclass(frozen=True, slots=True)
class TenantScope:
    """WHOSE knowledge a query may see. The only way to address the store.

    **Constructed from a `RetrievalRequest`, never from loose strings**, and that is the
    whole design: a `str` parameter called `tenant_tag` would be forgettable, mistypeable
    and — worst — defaultable. A required parameter of a type whose only constructor takes
    the request is none of those things. `tests/retrieval_supermemory_test.py` asserts the
    shape rather than the intention: every wire-touching method takes this first.
    """

    tenant_id: UUID
    agent_id: UUID | None = None

    @classmethod
    def for_request(cls, request: RetrievalRequest) -> TenantScope:
        """The READ side's constructor. Takes the request so it cannot take less."""
        return cls(tenant_id=request.tenant_id, agent_id=request.agent_id)

    @classmethod
    def for_publish(cls, *, tenant_id: UUID, agent_id: UUID) -> TenantScope:
        """The INGEST side's constructor: whose knowledge is being written, and for which
        agent. Both required, both keyword, neither defaultable.

        **THIS IS NOT A LOOSENING OF `for_request`'s RULE, AND THE DISTINCTION IS WORTH
        STATING** because a second constructor on a scope type is exactly where such a rule
        usually dies. What the type defends is that no body reaching this vendor can be
        BUILT without naming a tenant — §8.4 leaves the wall on our side, so an unscoped
        write is a document filed under nobody, retrievable by the next tenant who asks a
        similar question. A publish has no `RetrievalRequest` to take, so the choice was a
        constructor whose two arguments are required UUIDs or a `str` tag threaded through
        the publish path; the second is the forgettable one. `agent_id` is required here
        and optional on a read for the same reason the tag list is additive: a query with
        no agent legitimately means "everything this tenant published", and a DOCUMENT with
        no agent means nothing at all — every `kb_chunks` row carries one.
        """
        return cls(tenant_id=tenant_id, agent_id=agent_id)

    @classmethod
    def for_tenant(cls, tenant_id: UUID) -> TenantScope:
        """The ERASURE side's constructor: everything this tenant has, no agent narrowing.

        Separate from `for_publish` rather than defaulting its `agent_id`, so the one call
        site that means "every agent" says so — a default would make an ingest that forgot
        its agent read as a deliberate tenant-wide document.
        """
        return cls(tenant_id=tenant_id)

    @property
    def tenant_tag(self) -> str:
        """The tag that MUST be on every request and every record we accept back."""
        return f"{TENANT_TAG_PREFIX}{self.tenant_id}"

    def tags(self) -> list[str]:
        """Tenant first, then the agent narrowing where the caller asked for one."""
        tags = [self.tenant_tag]
        if self.agent_id is not None:
            tags.append(f"{AGENT_TAG_PREFIX}{self.agent_id}")
        return tags


def search_payload(
    scope: TenantScope, *, question: str, k: int, contract: WireContract = ASSUMED_CONTRACT
) -> dict[str, Any]:
    """THE ONLY request body this package builds, and it cannot be built unscoped.

    The final assertion is not decoration. Tenancy here is ours to enforce (§8.4) and the
    failure it guards is silent — an unscoped query returns a neighbour's knowledge with a
    200 — so the body is checked against the scope it was built from before it can be
    handed to a transport. If a future edit renames `container_tags_key` and forgets the
    tag, this raises in the first test that runs rather than leaking in production.
    """
    payload: dict[str, Any] = {
        contract.query_key: question,
        contract.limit_key: k,
        contract.container_tags_key: scope.tags(),
    }
    _assert_scoped(payload, scope=scope, contract=contract)
    return payload


def ingest_payload(
    scope: TenantScope,
    *,
    document_id: UUID,
    content: str,
    source_id: UUID,
    source_label: str,
    document_version: int,
    contract: WireContract = ASSUMED_CONTRACT,
) -> dict[str, Any]:
    """THE ONLY ingest body this package builds, and it cannot be built unscoped.

    The closing assertion is `search_payload`'s, and it is worth MORE on this side: a query
    that loses its tag returns a neighbour's knowledge to one person once, and a DOCUMENT
    that loses its tag is filed untagged for ever — invisible to every scoped query
    including its own tenant's, unreachable by `delete_payload`'s tag-scoped purge, and
    therefore invisible to the erasure that purge discharges. It is the one defect here
    that a later correction cannot reach.

    **THE METADATA IS THE READ SIDE'S, WRITTEN BY THE ONE FUNCTION THAT READS IT.** Every
    key is `_provenance`'s own (`metadata_source_label`, `metadata_source_id`,
    `metadata_agent_id`, `metadata_document_version`), so "what a citation needs" is
    decided once. `agent_id` is taken from the SCOPE rather than as a seventh argument —
    the tag and the metadata must agree, and two arguments that must agree are one argument.
    """
    agent_id = scope.agent_id
    if agent_id is None:  # pragma: no cover - `for_publish` cannot produce this
        raise SupermemoryWireMismatchError("an ingest body was built without its agent")
    payload: dict[str, Any] = {
        contract.document_id_key: str(document_id),
        contract.content_key: content,
        contract.container_tags_key: scope.tags(),
        contract.metadata_key: {
            contract.metadata_source_label: source_label[:200],
            contract.metadata_source_id: str(source_id),
            contract.metadata_agent_id: str(agent_id),
            contract.metadata_document_version: document_version,
        },
    }
    _assert_scoped(payload, scope=scope, contract=contract)
    return payload


def delete_payload(
    scope: TenantScope,
    *,
    document_ids: Sequence[UUID] = (),
    contract: WireContract = ASSUMED_CONTRACT,
) -> dict[str, Any]:
    """The withdrawal body. Ids when we know them, and the tenant tag ALWAYS.

    **TWO SHAPES, ONE BUILDER, AND THE TAG IS IN BOTH.** With ids it withdraws exactly the
    documents `kb_index_documents` says we wrote; with none it means "everything carrying
    these tags", which is how `purge_tenant_index` expresses a DPDP erasure. That second
    reading is ASSUMED (`WireContract.delete_ids_key`) and is the reason the purge does not
    rest on it alone — it also enumerates the ledger, so the obligation is discharged by
    the shape we have evidence for and belted by the shape we do not.

    The tag rides along even when ids are given, which is not redundancy: it is the only
    thing standing between a wrong id — ours, or a vendor that recycles them — and a
    delete that lands in somebody else's documents. A `DELETE` is the one operation where
    the scope being a filter we send rather than a wall they enforce cuts the dangerous way.
    """
    payload: dict[str, Any] = {contract.container_tags_key: scope.tags()}
    if document_ids:
        payload[contract.delete_ids_key] = [str(document_id) for document_id in document_ids]
    _assert_scoped(payload, scope=scope, contract=contract)
    return payload


def _assert_scoped(
    payload: Mapping[str, Any], *, scope: TenantScope, contract: WireContract
) -> None:
    """Re-read the tenant tag out of a body that was just built from the scope.

    One function rather than three copies of the same three lines, for the reason the
    assertion exists at all: the failure it guards is an EDIT — a renamed contract field, a
    builder that stopped calling `scope.tags()` — and a check each builder spells for itself
    is a check the next builder forgets to spell.
    """
    tags = payload.get(contract.container_tags_key)
    if not isinstance(tags, list) or scope.tenant_tag not in tags:  # pragma: no cover
        raise SupermemoryWireMismatchError("a Supermemory body was built without its tenant tag")


def parse_search(
    body: Mapping[str, Any], *, scope: TenantScope, contract: WireContract = ASSUMED_CONTRACT
) -> tuple[tuple[Passage, ...], int]:
    """`(passages, records_rejected)` — or raise on a shape `contract` does not describe.

    **THE SECOND TENANCY CHECK, AND IT IS THE ONE THAT MATTERS.** The first is the filter we
    send; this is whether the server honoured it. Against a single-tenant local build with
    one API key (§8.4) those are genuinely different questions — a tag the server ignores,
    a contract key we guessed wrong, an index rebuilt without tags, all produce a 200 full
    of somebody else's rows. Records that do not carry this scope's tenant tag are DROPPED
    and COUNTED, so the adapter can log that it happened without logging what was in them.

    A record with no text is dropped for the same reason and counted the same way: a
    `Passage` needs one, and inventing a placeholder would put an empty answer in front of
    a client as if it were knowledge.
    """
    results = body.get(contract.results_key)
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise SupermemoryWireMismatchError(
            f"no {contract.results_key!r} list in the response; keys were {sorted(body)}"
        )
    passages: list[Passage] = []
    rejected = 0
    for record in results:
        if not isinstance(record, Mapping):
            raise SupermemoryWireMismatchError(
                f"a {contract.results_key!r} entry was {type(record).__name__}, not an object"
            )
        tags = record.get(contract.result_tags_key)
        if not isinstance(tags, Sequence) or scope.tenant_tag not in tags:
            rejected += 1
            continue
        text = record.get(contract.text_key)
        if not isinstance(text, str) or not text.strip():
            rejected += 1
            continue
        passages.append(
            Passage(
                text=text[:4000],
                provenance=_provenance(record, scope=scope, contract=contract),
                score=_score(record.get(contract.score_key)),
            )
        )
    return tuple(passages), rejected


def _score(raw: Any) -> float | None:
    """A float, or None where the vendor sent something else — never a made-up number.

    The port says a score is comparable only within one result, so a missing one costs
    ordering information the caller already may not use. Raising here would turn a field we
    GUESSED the name of into an outage.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _provenance(
    record: Mapping[str, Any], *, scope: TenantScope, contract: WireContract
) -> Provenance:
    """OUR vocabulary out of their record. Every field optional except the tier.

    `agent_id` prefers the metadata we wrote at ingest and falls back to the scope's own
    agent — which is correct precisely when the caller narrowed to one agent, and honestly
    `None` when they did not.
    """
    metadata = record.get(contract.metadata_key)
    meta: Mapping[str, Any] = metadata if isinstance(metadata, Mapping) else {}
    label = meta.get(contract.metadata_source_label)
    return Provenance(
        label=(label[:200] if isinstance(label, str) and label.strip() else UNLABELLED_SOURCE),
        tier="t3",
        agent_id=_uuid(meta.get(contract.metadata_agent_id)) or scope.agent_id,
        source_id=_uuid(meta.get(contract.metadata_source_id)),
        document_version=_version(meta.get(contract.metadata_document_version)),
    )


def _uuid(raw: Any) -> UUID | None:
    """A UUID we wrote at ingest, or None. A malformed one is None rather than a raise:
    provenance is a citation, and a broken citation must not delete a true answer."""
    if isinstance(raw, UUID):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _version(raw: Any) -> int | None:
    """`Provenance.document_version` is `ge=1`, so a 0 or a negative is None rather than a
    validation error raised at a client mid-search."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if raw >= 1 else None


__all__ = [
    "AGENT_TAG_PREFIX",
    "ASSUMED_CONTRACT",
    "TENANT_TAG_PREFIX",
    "UNLABELLED_SOURCE",
    "SupermemoryWireMismatchError",
    "TenantScope",
    "WireContract",
    "delete_payload",
    "ingest_payload",
    "parse_search",
    "search_payload",
]
