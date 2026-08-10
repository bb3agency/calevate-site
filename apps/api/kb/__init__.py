"""Knowledge base — the ingestion + approval workflow (FLOWS §7).

What lives here and what deliberately does not, per D-28 and D-33:

- **Ours, regardless of provider:** `kb_sources` (the approval workflow), `kb_documents`
  (chunk previews and provider ids), and the preview-and-approve gate itself. A client
  cannot push text into their agent's mouth without a human seeing it first, and that
  gate is a product property, not a vendor feature.
- **Not ours:** the vector store. D-28 moved retrieval to a managed API service and
  v1 in-call retrieval stays on the engine's built-in KB (D-33: the KB is not a BYOK
  slot). `kb_chunks` + pgvector are CONTINGENCY, built only if the bake-off fails, so
  this module stores chunk TEXT for preview and never an embedding.
- **No conversation-state table.** D-33 is explicit: in-call working memory (H1) is the
  engine's and is discarded at hangup.
"""
