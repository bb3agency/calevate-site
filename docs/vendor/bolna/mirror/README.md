# Bolna documentation mirror — what this is, and what is missing from it

> ## ⚠ THE FETCH HAPPENED — AND IT LANDED SOMEWHERE ELSE (20 Aug 2026)
>
> **The 335 pages exist and have been read end to end. They are NOT in this directory and
> they are not coming here.** They live at **`bolna-findings/mirror/`** — `pages/**`,
> `llms.txt`, `llms-full.txt` and a `MANIFEST.json` carrying `url`, `status`, `bytes` and
> `sha256` for all 335 (334 × 200, one 404 on `api-reference/openapi.yml`). The manifest's
> own `path` values still read `vendor\bolna\mirror\pages\…`, which is where the fetcher
> was pointed when it ran: **it ran on the founder's machine, not in this environment**, and
> the result was delivered into the repo under a different root. This host's egress is
> unchanged — `https://www.bolna.ai/docs/index.md` still returns 403 on CONNECT, re-measured
> 20 Aug 2026 — so nothing here can re-fetch or refresh that tree.
>
> **Rules for the mirror**: read-only evidence, cited as `bolna-findings/mirror/pages/<path>:<line>`;
> never edited, reformatted or moved (`bolna-findings` is in ruff's `extend-exclude` WITH
> `force-exclude`, and `tests/vendor_evidence_guard_test.py` fails if a page drifts from its
> recorded hash — a repo-wide `ruff format .` had already rewritten the vendor's Python
> blocks in nine pages that other lanes were citing by line number).
>
> **What was done with it**: ten audit lanes, one report each, in `docs/evidence/bolna-*.md`;
> the decisions they produced are ROADMAP §6 **D-414 … D-424** and OPERATIONS §2 gates
> **9v, 21–27**. This directory stays as the provenance record of the index that ordered the
> fetch — the `llms.txt` transcription and the trust table below — and is no longer the place
> to look for a page.

**STATUS (superseded): INDEX ONLY. The 335 pages are NOT here.** Read the next section for
the provenance of what IS here.

## Why a mirror

More of this product's residual risk is unverified vendor behaviour than is unfinished
code. OPERATIONS §2 gate 7 (is `total_cost` minor units, and in WHICH currency), gate 16f
(which credential FIELDS Bolna's Azure OpenAI provider expects), gate 9 (where a call
actually executes), gate 12 (the BYOK platform fee) — every one is a question a vendor
document can move, and CLAUDE.md's rule is that such a claim is a gate or a marked
assumption, never a silent premise.

`hosted-oas.md` beside this directory already does exactly this for the OpenAPI document:
a pinned reading, so "what did their docs say when we decided this" stays answerable. This
extends it to the whole set.

## What is here, and its provenance — read this literally

| File | Provenance | Trust |
| --- | --- | --- |
| `llms.txt` | **TRANSCRIBED from a paste by the founder, 20 Aug 2026. NOT fetched.** | Titles/descriptions/URLs are believed accurate; no byte-level guarantee. |
| `pages/**` | *(absent)* | — |
| `MANIFEST.json` | *(absent — written by the fetcher)* | — |

`llms.txt` is a transcription, and that distinction is not pedantry: everything else in
this repository that cites a vendor says whether it was READ or INFERRED, and a mirror
that overstates its own provenance is worse than no mirror. **Overwrite it with the real
bytes at the first opportunity** — `python3 scripts/fetch_bolna_docs.py --index-only` does
exactly that, and the SHA-256 it records is what makes the transcription checkable.

## Why the pages are absent

`www.bolna.ai`, `api.bolna.ai` and `mcp.bolna.ai` are **refused by this environment's
egress proxy** — `403` on CONNECT, measured 20 Aug 2026 for all three hosts. It is an
organisation network policy, not a tool problem: `curl`, `urllib`, `httpx` and the
harness's own `WebFetch` all fail identically, so no scraper in any language gets through
and the proxy's own README says to report the denial rather than route around it.

**The same block covers `api.bolna.ai`,** which is the part with consequences beyond this
directory: CLAUDE.md says "the next Bolna work is one API call" (`GET /providers`, then
`POST`, then `GET` again, closing gate 16f). That call cannot be made from a Claude Code
session either. It needs a machine with ordinary network access, or `bolna.ai` added to
the environment's egress allowlist.

## Filling it

Run on a machine with normal network access, then commit the result.

```sh
# FIRST, TRY THE ONE-FILE ROUTE. Their own index advertises llms-full.txt as a
# machine-readable version of the whole set; if it is the corpus concatenated, one
# request replaces 335 and cannot half-succeed.
curl -sS https://www.bolna.ai/docs/llms-full.txt -o docs/vendor/bolna/mirror/llms-full.txt

# Otherwise, or additionally when you want the pages individually addressable
# (which is what makes a diff against one page possible):
python3 scripts/fetch_bolna_docs.py            # stdlib only — no `uv sync` needed
python3 scripts/fetch_bolna_docs.py --refresh  # re-fetch everything, rewrite hashes
```

The fetcher writes **bytes exactly as received** — no markdown normalisation, no link
rewriting, no trailing-newline fixups. A mirror that tidies its source cannot be used as
evidence, because any difference you later find between our code and their docs might be
ours. It exits non-zero and names every page that did not land, so a 332-of-335 mirror
cannot read as complete.

## What to do once it is filled

`docs/vendor/bolna/GAP-WORKLIST.md` is the reading order: for each of our open gates and
marked assumptions, which page settles it and what to look for. It exists so 335 files
become answers rather than a directory nobody opens.

## Licensing

Third-party documentation, mirrored unmodified for internal engineering reference and
kept out of anything we publish. It is Bolna's copyright, not ours; nothing here may be
redistributed or quoted into a client-facing surface.
