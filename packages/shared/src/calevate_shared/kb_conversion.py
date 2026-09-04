"""The DocumentConverter seam: an uploaded object in, a PDF the engine will accept out.

**WHY A PORT AND NOT A FUNCTION.** The voice engine's knowledge base ingests exactly two
things — a PDF file, or a URL it scrapes for itself — and refuses everything else (the
vendor citation lives with the wire constants in `apps/api/engine/`, which is the only
place hard rule 2 lets a vendor be named). A client's knowledge arrives as Word files,
spreadsheets, plain text and photographs of a laminated price list. Something has to turn
those into a PDF, and that something is a different concern from ingestion: it is a
document-processing dependency (a renderer, an OCR engine, a vendor API) with its own
failure modes, its own licence questions and its own release cadence.

So this file is the CONTRACT and nothing else. It declares what a converter is handed,
what it must answer, and how it says no — and it is deliberately implementation-free, in
`calevate_shared` where neither side owns it. `apps/api/kb/conversion.py::get_converter`
is the selector, `apps/api/kb/uploads.py` is the caller, and the implementation is a
separate lane's module. The shape is `calevate_shared.retrieval.RetrievalProvider`'s,
followed rather than re-invented: our own vocabulary, capabilities DECLARED rather than
discovered by calling and failing, and a NAMED refusal instead of a silent empty answer.

**WHAT THE CONVERTER IS NOT ASKED FOR, AND WHY IT MATTERS TO THE APPROVAL GATE.** It is
not asked for TEXT. A converter that also extracted prose would put the words a human
approves behind a machine's paraphrase, and this product's approval gate is a human
reading exactly what the agent will be handed (`kb/service.py`). For an uploaded document
the artefact a reviewer reads is the document itself, fetched through
`GET /v1/kb/uploads/{id}/original`; what the engine indexes is the PDF this port returns.
One artefact, reviewed and shipped, with no third rendering in between that nobody signed.

**BYTES ARE PASSED BY OBJECT-STORAGE REF, NEVER INLINE.** A 20 MB upload has no business
travelling through a job payload, a log line or a Redis key (hard rule 6 — the file is a
client's own business data and may carry their customers' names). The converter reads the
key it is given and writes the key it returns; both live under the tenant's prefix, so a
DPDP erasure reaches them by prefix like every other object this platform stores.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: What a client handed us, as a closed set. It is the vocabulary
#: `kb_uploads.source_kind` stores and the one the client's screen labels a row with, so a
#: free-form string would let a typo become a kind nothing can convert and nothing can
#: report on.
#:
#: `pdf` and `url` are the two the ENGINE takes natively and no converter is asked for
#: them; they are in the set because a row still has to say what it is. The other four are
#: exactly the founder's list — Word, spreadsheets, plain text and photographs — and each
#: one is a conversion this port must be able to describe.
SourceKind = Literal["pdf", "url", "docx", "xlsx", "text", "image"]

#: The kinds that reach the engine without a converter. Named here rather than tested as
#: `!= "docx"` so a fifth kind added tomorrow needs a conversion by default.
NATIVE_KINDS: frozenset[str] = frozenset({"pdf", "url"})


class ConversionRequest(BaseModel):
    """One object to convert. Every field is ours; nothing here names a vendor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    upload_id: UUID
    tenant_id: UUID
    source_kind: SourceKind
    #: Where the original lives in object storage. The converter READS this key.
    object_key: str
    #: What the client called it. For a message, and for the extension a converter may
    #: dispatch on — never trusted as a path (`kb/uploads.py` sanitises it before storage).
    filename: str
    content_type: str
    byte_size: int = Field(ge=1)
    #: The ceiling the OUTPUT must respect, because the engine refuses a larger file and
    #: the refusal must happen before an upload rather than after one. It is passed rather
    #: than imported so the converter cannot hold a second, stale copy of the vendor's
    #: limit: there is one number and it lives with the wire constants.
    max_output_bytes: int = Field(ge=1)


class ConvertedDocument(BaseModel):
    """The PDF a converter produced, by reference.

    `sha256` is over the PDF BYTES and is the same idempotency key the publisher already
    uses for its own rendered documents (`KBSourceRef.content_sha256`): the same input
    reaching the engine twice must not mint a second billed copy, and the guard that stops
    that compares digests. A converter that is not deterministic simply produces a new
    digest and pays for one re-upload; a converter that lied about the digest would let a
    changed document keep an old handle, which is why this is computed over the stored
    bytes by whoever stores them and never carried forward from the original.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_key: str
    byte_size: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)
    #: Which converter produced it, for provenance on the row — the argument
    #: `kb_documents.gloss_model` makes one table over: "machine-generated" is worth
    #: nothing unless the row says which machine.
    converter: str
    #: Pages, when the converter knows. Advisory; nothing gates on it.
    pages: int | None = None


class ConversionError(Exception):
    """Base of the two refusals, so a caller may catch one thing and read `reason`.

    `reason` is written for the CLIENT who uploaded the file, not for an operator: it lands
    on `kb_uploads.ingest_detail` and is rendered beside the row on their screen (quality
    bar: errors are part of the interface). It must therefore never carry a key, a path or
    a stack — `kb/uploads.py` logs the exception type and the upload id, and shows this.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ConversionUnavailable(ConversionError):
    """No converter is installed for this kind on this deployment.

    A DIFFERENT FACT FROM A FAILED CONVERSION and kept separate for the reason
    `retrieval` keeps "this provider cannot search" apart from "there were no results":
    unavailable is a deployment gap a retry cannot close and an operator can, while a
    failure is about this one file. They produce different statuses on the row
    (`conversion_unavailable` is not a state a sweep should retry for ever) and different
    sentences to the client.
    """


class ConversionFailed(ConversionError):
    """This particular object could not be turned into a PDF: corrupt, encrypted, empty,
    or larger than `max_output_bytes` once rendered."""


@runtime_checkable
class DocumentConverter(Protocol):
    """One implementation. Constructed by `apps/api/kb/conversion.get_converter`.

    `supported_kinds` is DECLARED so the upload endpoint can refuse a `.docx` at the door,
    while the client still has the file in front of them, instead of accepting it and
    reporting a failure minutes later from a worker. That is the same argument
    `EngineCapabilities` settled for the engine (D-93) and it is the reason this Protocol
    has an attribute at all rather than only a method.
    """

    #: Stable identifier recorded on the row. Not a version string; provenance, not a lock.
    name: str
    #: Which `SourceKind`s this implementation will accept. Never includes `NATIVE_KINDS`.
    supported_kinds: frozenset[str]

    async def to_pdf(self, request: ConversionRequest) -> ConvertedDocument:
        """Convert, store the PDF, answer where it went.

        Raises `ConversionUnavailable` for a kind it does not serve and `ConversionFailed`
        for an object it cannot read. It must NOT raise anything else: an unexpected
        exception reaching the caller becomes a generic failure with no sentence a client
        can act on, which is the state this port exists to avoid.
        """
        ...


__all__ = [
    "NATIVE_KINDS",
    "ConversionError",
    "ConversionFailed",
    "ConversionRequest",
    "ConversionUnavailable",
    "ConvertedDocument",
    "DocumentConverter",
    "SourceKind",
]
