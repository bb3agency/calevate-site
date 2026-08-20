"""Mirror the Bolna documentation set verbatim, for gap analysis against our own tree.

WHY A MIRROR AT ALL. Half of this repository's open risk is UNVERIFIED VENDOR BEHAVIOUR:
OPERATIONS §2 gate 7 (is `total_cost` cents or major units, and in WHICH currency), gate
16f (which credential FIELDS Bolna's Azure OpenAI provider expects), gate 9 (where a call
actually executes). CLAUDE.md's rule is that a vendor claim is a gate or a marked
assumption, never a silent premise — and a gate you cannot re-read is one that rots. A
pinned local copy makes "what did their docs say when we decided this" answerable months
later, which is exactly what `docs/vendor/bolna/hosted-oas.md` already does for the
OpenAPI document and what this extends to the whole set.

RUN IT WHERE THE NETWORK ALLOWS IT — that will usually NOT be a Claude Code session.
`www.bolna.ai`, `api.bolna.ai` and `mcp.bolna.ai` are all refused by the agent egress
proxy with `403 CONNECT` (measured, 20 Aug 2026), and that refusal is an organisation
policy rather than a tool problem: curl, urllib and httpx fail identically, so no client
and no language works around it. Run this on a developer machine, commit the result.

    python3 scripts/fetch_bolna_docs.py                 # fetch what is missing
    python3 scripts/fetch_bolna_docs.py --refresh       # re-fetch everything
    python3 scripts/fetch_bolna_docs.py --index-only    # just refresh llms.txt

TRY `llms-full.txt` FIRST, because it may make this script unnecessary. Bolna's own index
advertises `llms.txt` AND `llms-full.txt` as "machine-readable versions of these docs";
the second is, on every Mintlify-hosted set we have seen, the WHOLE corpus concatenated
into one file. One request beats 250 of them, is kinder to their origin, and cannot
half-succeed. `--full-only` fetches just that. This script exists for the case where it is
absent, truncated, or you want the pages addressable individually — which is what makes a
diff against a specific page possible.

    curl -sS https://www.bolna.ai/docs/llms-full.txt -o docs/vendor/bolna/mirror/llms-full.txt

WHAT "VERBATIM" MEANS HERE, because it is the whole value. Bytes are written exactly as
received — no markdown normalisation, no link rewriting, no front-matter stripping, no
trailing-newline fixups. A mirror that tidies its source cannot be used as evidence,
because any difference you later find between our code and their docs might be ours. The
manifest records a SHA-256 per file so a re-fetch can prove what changed and what did not.

NO THIRD-PARTY IMPORTS, deliberately: this has to run on a machine that has not run
`uv sync`, with nothing but a system Python. That is the machine that has the network.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

#: Their documentation root. Every mirrored path is derived from this prefix, so a page
#: served from anywhere else is a redirect we want to SEE rather than silently follow into
#: the mirror under a path that does not match its URL.
DOCS_ROOT = "https://www.bolna.ai/docs/"

#: The index that lists every page. Fetched first; also the file the URL list is parsed
#: from on subsequent runs, so a run with `--offline-index` needs no network for step 1.
INDEX_URL = DOCS_ROOT + "llms.txt"

#: The whole corpus in one file, per their own index. Preferred when present — see the
#: module docstring.
FULL_URL = DOCS_ROOT + "llms-full.txt"

#: Where the mirror lives. Beside `hosted-oas.md`, which is the same kind of artefact:
#: a pinned reading of a vendor document that a decision was made against.
MIRROR = Path(__file__).resolve().parent.parent / "docs" / "vendor" / "bolna" / "mirror"

#: Markdown links in llms.txt: `- [Title](url): description`. Parsed rather than
#: hard-coded so a page added to their docs next month is picked up by re-running this,
#: which is the same reason `rls_sweep_test` discovers tables from the catalogue.
_LINK = re.compile(r"^\s*-\s*\[(?P<title>[^\]]*)\]\((?P<url>https?://[^)]+)\)", re.MULTILINE)

#: Identify ourselves. A scraper that pretends to be a browser is one a vendor is right to
#: block, and we want this traffic to be attributable if they ever ask about it.
USER_AGENT = "calevate-docs-mirror/1.0 (+engineering gap analysis; contact via bolna account)"

#: Politeness. Their docs are a marketing-adjacent origin, not an API with a published rate
#: limit, so the defaults are deliberately gentle. `--workers`/`--delay` raise them only if
#: you have a reason.
DEFAULT_WORKERS = 4
DEFAULT_DELAY_S = 0.25
RETRIES = 4
TIMEOUT_S = 30


@dataclass
class Fetched:
    url: str
    path: str  # repo-relative
    status: int
    bytes: int
    sha256: str
    content_type: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error and self.bytes > 0


def local_path(url: str) -> Path:
    """`.../docs/a/b/c.md` -> `<MIRROR>/pages/a/b/c.md`, mirroring their tree exactly.

    The URL's own path is the filename, NOT a slug derived from the title: a mirror whose
    layout differs from the source is one nobody can map back to a citation, and a citation
    that cannot be resolved is the defect `check_docs_drift` exists to catch in our own
    prose.
    """
    if not url.startswith(DOCS_ROOT):
        raise ValueError(f"refusing to mirror a URL outside {DOCS_ROOT}: {url}")
    tail = url[len(DOCS_ROOT) :].split("?", 1)[0].split("#", 1)[0]
    if not tail or tail.endswith("/"):
        tail += "index.md"
    # Defensive: no traversal out of the mirror, whatever the index says.
    parts = [p for p in tail.split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError(f"refusing an empty path from {url}")
    return MIRROR / "pages" / Path(*parts)


def _get(url: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.status, response.read(), response.headers.get("Content-Type", "")


def fetch(url: str, *, delay: float) -> Fetched:
    """One page, with backoff. Returns a Fetched carrying the failure rather than raising.

    FAILURES ARE DATA, not exceptions, because the caller's job is to report EVERY page
    that did not land. A scraper that dies on the first 404 leaves you guessing whether the
    other 249 worked, and a mirror that is silently 3 pages short is worse than no mirror:
    it reads complete.
    """
    last = ""
    for attempt in range(RETRIES):
        try:
            status, body, content_type = _get(url)
            return Fetched(
                url=url,
                path=str(local_path(url).relative_to(MIRROR.parent.parent.parent)),
                status=status,
                bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                content_type=content_type,
                error="" if body else "empty body",
            )
        except urllib.error.HTTPError as exc:
            # 4xx is an answer, not a hiccup: retrying a 404 just wastes their origin.
            if 400 <= exc.code < 500 and exc.code != 429:
                return Fetched(url, "", exc.code, 0, "", "", f"HTTP {exc.code}")
            last = f"HTTP {exc.code}"
        except Exception as exc:  # network, TLS, proxy, DNS
            last = f"{type(exc).__name__}: {exc}"
        if attempt < RETRIES - 1:
            time.sleep(delay * (2**attempt) + 0.5)
    return Fetched(url, "", 0, 0, "", "", last or "unknown failure")


def write(url: str, body: bytes) -> None:
    path = local_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)  # bytes, not text: no newline translation, no re-encoding


def fetch_and_write(url: str, *, delay: float) -> Fetched:
    result = fetch(url, delay=delay)
    if result.ok:
        # Re-request rather than hold every body in memory: the corpus is a few MB, but a
        # mirror that OOMs on a bigger docs set is a mirror that stops being run.
        try:
            _, body, _ = _get(url)
            write(url, body)
        except Exception as exc:
            return Fetched(url, "", 0, 0, "", "", f"write step: {type(exc).__name__}: {exc}")
    time.sleep(delay)
    return result


def urls_from_index(text: str) -> list[str]:
    """Every docs URL the index names, de-duplicated, order preserved.

    Non-`docs/` links (their marketing site, GitHub) are dropped rather than mirrored —
    `local_path` would refuse them anyway, and the refusal belongs where the decision is.
    """
    seen: dict[str, None] = {}
    for match in _LINK.finditer(text):
        url = match.group("url").strip()
        if url.startswith(DOCS_ROOT):
            seen.setdefault(url, None)
    return list(seen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--refresh", action="store_true", help="re-fetch pages already mirrored")
    parser.add_argument("--index-only", action="store_true", help="refresh llms.txt and stop")
    parser.add_argument("--full-only", action="store_true", help="fetch llms-full.txt and stop")
    parser.add_argument(
        "--offline-index",
        action="store_true",
        help="parse the URL list from the mirrored llms.txt instead of fetching it",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S)
    args = parser.parse_args(argv)

    MIRROR.mkdir(parents=True, exist_ok=True)
    index_file = MIRROR / "llms.txt"

    if args.full_only:
        result = fetch(FULL_URL, delay=args.delay)
        if not result.ok:
            print(f"FAILED {FULL_URL}: {result.error or result.status}", file=sys.stderr)
            return 1
        _, body, _ = _get(FULL_URL)
        (MIRROR / "llms-full.txt").write_bytes(body)
        print(f"llms-full.txt: {len(body):,} bytes, sha256 {hashlib.sha256(body).hexdigest()[:16]}")
        return 0

    if args.offline_index:
        if not index_file.exists():
            print(
                f"no mirrored index at {index_file}; drop llms.txt there or run online",
                file=sys.stderr,
            )
            return 2
        index_text = index_file.read_text(encoding="utf-8")
    else:
        status, body, _ = 0, b"", ""
        try:
            status, body, _ = _get(INDEX_URL)
        except Exception as exc:
            print(f"could not fetch {INDEX_URL}: {type(exc).__name__}: {exc}", file=sys.stderr)
            print(
                "(if this is a Claude Code session, bolna.ai is egress-blocked — run this "
                "on a machine with normal network access, or use --offline-index)",
                file=sys.stderr,
            )
            return 2
        if status != 200 or not body:
            print(f"index fetch returned {status}, {len(body)} bytes", file=sys.stderr)
            return 2
        index_file.write_bytes(body)
        index_text = body.decode("utf-8", errors="replace")
        print(f"index: {len(body):,} bytes")

    if args.index_only:
        return 0

    urls = urls_from_index(index_text)
    # The OpenAPI document is listed under its own heading rather than as a `- [..](..)`
    # bullet, and it is the single most load-bearing file in the set (gate 7 reads it).
    for extra in (DOCS_ROOT + "api-reference/openapi.yml",):
        if extra not in urls:
            urls.append(extra)

    todo = [u for u in urls if args.refresh or not local_path(u).exists()]
    print(
        f"{len(urls)} pages in the index, {len(todo)} to fetch "
        f"({len(urls) - len(todo)} already mirrored)"
    )

    results: list[Fetched] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_and_write, u, delay=args.delay): u for u in todo}
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            results.append(result)
            flag = "ok " if result.ok else "FAIL"
            print(
                f"[{done}/{len(todo)}] {flag} {result.url[len(DOCS_ROOT) :]}"
                + ("" if result.ok else f"  <- {result.error or result.status}")
            )

    failures = [r for r in results if not r.ok]

    # The manifest is the evidence, so it records what FAILED as well as what landed. A
    # manifest listing only successes is how a 247-of-250 mirror comes to read as complete.
    manifest: dict[str, Any] = {}
    manifest_file = MIRROR / "MANIFEST.json"
    if manifest_file.exists() and not args.refresh:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest.update({r.url: asdict(r) for r in results})
    manifest_file.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"\n{len(results) - len(failures)} fetched, {len(failures)} failed, "
        f"manifest at {manifest_file.relative_to(MIRROR.parent.parent.parent)}"
    )
    if failures:
        print("\nPAGES THAT DID NOT LAND — the mirror is INCOMPLETE and says so:", file=sys.stderr)
        for r in failures:
            print(f"  {r.url}  <- {r.error or r.status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - entrypoint
    sys.exit(main())
