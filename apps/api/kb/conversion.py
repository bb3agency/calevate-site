"""THE SELECTOR: which `DocumentConverter` this deployment runs.

`calevate_shared.kb_conversion` declares the port; this is the one place that answers
"which implementation", so no caller ever constructs one. `retrieval/service.get_retriever`
is the same shape one directory over, and it is followed rather than re-invented.

**TODAY THE ANSWER IS `NullConverter`, AND THAT IS A STATED GAP RATHER THAN A STUB.** The
conversion implementation — Word, spreadsheets, plain text and photographs to PDF, with the
OCR pass the photographs need — is a separate lane's module. Until it lands, a deployment
can ingest exactly what the engine ingests natively: a PDF and a URL. That is not a
degraded version of the feature, it is the honest one: an upload of a kind nothing can
convert is refused AT THE DOOR by `SUPPORTED_UPLOAD_KINDS`, with a sentence telling the
client to send a PDF, rather than accepted and left `conversion_unavailable` in a queue.

**WHAT THE CONVERSION LANE CHANGES, EXHAUSTIVELY.** One import and one return in
`get_converter`. Nothing else in this tree moves: `kb/uploads.py` already routes every
non-native kind through the port, `kb_uploads.converter`/`document_key` already record what
came back, and `SUPPORTED_UPLOAD_KINDS` is DERIVED from `get_converter().supported_kinds`
so the upload endpoint starts accepting `.docx` the moment a converter declares it. There
is deliberately no settings switch and no registry: two implementations of one thing is the
defect the quality bar names, and a dynamic lookup that outlives its reason is worse than
an import (`kb/service._render_document` carries the worked example of that going wrong).
"""

from __future__ import annotations

from functools import lru_cache

from calevate_shared.kb_conversion import (
    ConversionRequest,
    ConversionUnavailable,
    ConvertedDocument,
    DocumentConverter,
)


class NullConverter:
    """No conversion is installed: every non-native kind is refused BY NAME.

    It is not a silent pass-through and it is not a `NotImplementedError`. Both of those
    reach a client as a 500 with nothing to act on; this reaches them as "we cannot read a
    Word file yet — send a PDF", which is a true statement with a next step in it.
    """

    name = "none"
    #: Empty, and read by `SUPPORTED_UPLOAD_KINDS`: with no converter installed the upload
    #: endpoint accepts only what the engine takes natively.
    supported_kinds: frozenset[str] = frozenset()

    async def to_pdf(self, request: ConversionRequest) -> ConvertedDocument:
        raise ConversionUnavailable(
            "We cannot turn that kind of file into something the voice platform can read "
            "yet. Upload a PDF, or paste the wording as text."
        )


@lru_cache(maxsize=1)
def get_converter() -> DocumentConverter:
    """The process's converter. Cached because it holds no per-request state.

    The cache is `lru_cache` rather than a module global for the reason every other
    selector in this repo uses one: a test can clear it (`get_converter.cache_clear()`)
    and a module global cannot be un-set.
    """
    return NullConverter()


def supported_upload_kinds() -> frozenset[str]:
    """Every `SourceKind` this deployment can accept as a FILE upload.

    DERIVED from the installed converter rather than listed, so the door and the worker
    can never disagree about what will be accepted — the shape where a client uploads a
    file the endpoint admits and a worker then refuses.

    `url` is not here: a link is not a file upload and reaches the engine by its own route.
    """
    return frozenset({"pdf"}) | get_converter().supported_kinds


__all__ = ["NullConverter", "get_converter", "supported_upload_kinds"]
