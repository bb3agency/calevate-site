# Vobiz documentation mirror (read-only)

A byte-exact snapshot of the Vobiz developer documentation, the carrier chosen by the
founder on 2 Oct 2026 for the live in-call testing phase. It is the
**VERIFIED-VENDOR-DOCS** evidence class for every Vobiz claim in this repository, cited as
`vobiz-findings/mirror/pages/<path>.md:<line>`.

## Source

- Vendor: Vobiz (Ilaimitado Private Limited), `https://vobiz.ai/docs/`.
- Page list: the union of every link in `https://vobiz.ai/docs/llms.txt` and every
  `/docs/...` URL in `https://vobiz.ai/docs/sitemap.xml`. `llms.txt` indexes only part of
  the site; the sitemap carries the API pages (hangup, transfer, recordings, stream events,
  sub-accounts) that the contract needs.
- Each page was fetched as raw Markdown by appending `.md` to its URL
  (`https://vobiz.ai/docs/<path>.md`), sequentially, with a 400 ms pause between requests.
- Fetched 2 Oct 2026 IST (the evening of 1 Oct 2026 UTC; per-file UTC timestamps are in
  `MANIFEST.json`).
- Result: 490 files fetched, 1 failure recorded in `MANIFEST.json` (`/docs/mcp.md`, HTTP 404:
  it is the docs MCP server endpoint listed in `llms.txt`, not a page).

## Layout

| Path | What it is |
| --- | --- |
| `pages/<path>.md` | One page per docs URL, path preserved (`/docs/call/make-call` → `pages/call/make-call.md`) |
| `llms.txt`, `llms-full.txt`, `sitemap.xml` | The docs site's own indexes and single-file corpus |
| `root-site/openapi.json` | The vendor's OpenAPI 3 specification ("Vobiz API" 1.0), linked from `docs/llms.txt` |
| `docs-openapi.json` | What `https://vobiz.ai/docs/api-reference/openapi.json` (linked from the root `llms.txt`) served: a Mintlify **"OpenAPI Plant Store" placeholder**, not the Vobiz API. Kept because it is what the link returned |
| `root-site/llms.txt`, `root-site/agents.md`, `root-site/auth.md` | The marketing site's machine-readable entry points |
| `MANIFEST.json` | `url`, `path`, `sha256`, `bytes`, `content_type`, `listed_in` and `fetched_at` for every file above, plus any fetch that failed |

## Rules

1. **Never edit, reformat, re-save or move anything under this directory.** A citation is
   only worth something because the cited bytes are the bytes the vendor served; the
   `sha256` in `MANIFEST.json` is how a reader proves it.
2. It is excluded from ruff (`pyproject.toml` `[tool.ruff] extend-exclude`, with
   `force-exclude = true` so a pre-commit hook handing it a path explicitly still skips it)
   and from git's line-ending conversion (`.gitattributes`: `vobiz-findings/mirror/** -text`).
3. To refresh it, fetch a NEW snapshot into a new directory or replace the whole tree and
   its manifest together, in one commit that says so. Never patch a single page.
4. A page saying nothing about a question is not evidence that the vendor does not do it.
   Record it as UNKNOWN (hard rule 11).
