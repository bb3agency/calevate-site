"""The vendor evidence mirror is a hash-pinned artefact. Nothing was checking that.

`bolna-findings/mirror/` is a fetched snapshot of Bolna's documentation, and
`MANIFEST.json` records a `sha256` for every page in it. That hash is the entire reason a
finding may cite `bolna-findings/mirror/pages/<path>` and be believed: the mirror is
supposed to be a fixed thing an argument can be pinned to, the way a commit is.

It was not fixed. **ruff formats Python code blocks inside Markdown**, and the evidence
tree was inside ruff's file discovery, so `uv run ruff format .` — the command CLAUDE.md's
own Commands section tells every contributor and every agent to run — rewrote the vendor's
code samples in place. Fifteen of the 335 pages were found off their recorded hash. Eight
were restored from git while this guard was being written; the remaining SEVEN are
mismatched **at HEAD**. The damage was invisible for as long as it existed because no gate
read the manifest, which is the failure this file exists to end: a hash nobody verifies is
decoration.

**WHAT THE SEVEN ARE — SETTLED 22 Aug 2026 (A2 audit), AND IT IS NOT WHAT THIS FILE USED
TO SAY.** They are not formatter damage and they are not a stale manifest. They are a
disclosed, WIDTH-PRESERVING redaction applied by the mirror's author before the tree was
ever committed, and five independent facts say so:

  1. `bolna-findings/` has exactly ONE commit, `5e18585` (20 Aug 2026, bb3agency), titled
     *"fetched bolna docs md files (redacted example Twilio SIDs)"* — and
     `git diff 5e18585 HEAD -- bolna-findings/` is EMPTY. Nothing has edited the mirror
     in-tree, ever. The formatter incident happened during this audit wave, which is
     after the only commit these pages have.
  2. All seven are EXACTLY their manifest byte length — seven files, zero delta. A
     formatter reflowing code blocks does not preserve byte counts seven times over.
  3. The seven are EXACTLY, and only, the pages containing `AC` + 32 `X` (twice each):
     a Twilio ACCOUNT SID (`AC` + 32 hex) overwritten with an equal-width fill. No other
     page in the mirror carries that token or anything like it.
  4. SIX of the seven contain no Python code fence at all — their fences are `json`/`yaml`
     or absent. ruff formats Python blocks; there was nothing in them to rewrite.
  5. The redaction sits inside a URL on a single line (the example recording URL
     `…s3.us-east-1.amazonaws.com/AC…/RE…`), so it adds and removes no newline.

**WHY THAT MATTERS RATHER THAN BEING TRIVIA.** This file used to instruct the reader that
"a whitespace-only diff inside a fenced code block is the formatter, and the page should be
restored from the vendor". Following that would re-insert a live vendor account identifier
into a tracked file — the exact thing commit `5e18585` removed on purpose — and it cannot
succeed anyway: the redacted SIDs are 32 hex characters that exist nowhere any more, so
these seven can NEVER be made to match the manifest. Because of fact 5, **line numbers are
unaffected**: every `page:line` citation into these seven resolves to the line it always
did. Re-resolved by hand in the same audit — `docs/evidence/bolna-response-contract.md:557`
-> `get_execution.md:285-294` (the `to_number`/`from_number` declaration) and
`docs/evidence/bolna-tools-integrations.md:124` -> `get_agent_execution.md:270-328` (the
`TransferCallData` block, which spans redacted line 316 without depending on it).

**AND THE SEVEN WERE THE ONLY UNPINNED PAGES IN THE MIRROR.** `KNOWN_HASH_MISMATCHES` was
a set of PATHS. It pinned THAT a page mismatched and nothing whatever about its bytes — so
the seven pages two evidence documents cite by line number were precisely the seven a
change could edit in silence. Demonstrated before this was fixed: a same-length edit inside
`get_execution.md` left every assertion here green. `REDACTED_PAGES` replaces the set with
a table carrying the as-fetched hash, the as-committed hash and the redaction's occurrence
count, so all 334 pages are now pinned to bytes.

**WHAT IS DELIBERATELY NOT DONE, because it would destroy the only thing that can detect
tampering:** the mirror is not edited and `MANIFEST.json` is not regenerated to match the
tree. The manifest records the bytes as FETCHED FROM THE VENDOR — the one fact no later
process can reconstruct. Overwriting it would launder the present tree into the position of
evidence about the vendor. The manifest keeps saying what was served; the table below says
what was committed; the difference is declared rather than erased.

THREE GUARDS, and they fail for different reasons on purpose:

- **the exclusion** — `pyproject.toml` must keep `bolna-findings` out of ruff's reach, so
  the formatter cannot do it again. Asserted through ruff's own resolved file set rather
  than by reading the config string back, because the property that matters is what ruff
  DOES, and an exclude entry that stops working (renamed key, a `force-exclude`
  interaction, a future ruff release) would still read correctly in the toml.
- **the integrity ledger** — every page must hash to its manifest entry, except the seven,
  which must hash to their COMMITTED value and still carry exactly `REDACTION_COUNT`
  placeholders. Equality, not tolerance: an eighth mismatch fails, a byte changed inside
  one of the seven fails, and "restoring" one by un-redacting it fails with its own
  message rather than as a generic hash mismatch.
- **the unmanifested corpus files** — `scripts/fetch_bolna_docs.py` writes `llms.txt` and
  `llms-full.txt` WITHOUT adding a manifest record (`index_file.write_bytes(body)`, and
  the `--full-only` branch), so nothing hashed the whole-corpus file that an agent greps
  when a page is missing. Pinned here because this is the only place that would notice.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
MIRROR: Final = REPO_ROOT / "bolna-findings" / "mirror"
MANIFEST: Final = MIRROR / "MANIFEST.json"
PAGES: Final = MIRROR / "pages"

#: THE SEVEN, pinned to bytes. Replaces a bare `frozenset` of paths — see the docstring:
#: that set recorded THAT a page mismatched and nothing about its contents, which left the
#: only seven pages in the mirror that nothing pinned to be the seven two evidence
#: documents cite by line number.
#:
#: EQUALITY, not tolerance, in three directions at once: a page that leaves this table
#: while still mismatching fails, a page in it that starts matching the manifest again
#: fails (that would mean the redaction was undone), and a byte changed inside any of them
#: fails. `as_fetched` is duplicated from `MANIFEST.json` ON PURPOSE and is not read from
#: it — so doctoring the manifest to match an altered tree does not also doctor this table,
#: which is the entire reason a manifest is worth keeping.
REDACTED_PAGES: Final[dict[str, tuple[str, str, int]]] = {
    # path: (as_fetched, as_committed, byte size)
    "api-reference/agent/get_all_agent_executions.md": (
        "8fdc6fc78298a4f09baa5ad5bc0ba3be24fb338f3e1494d8a006d8aa4cdc50b4",
        "44cb8d422bb3a1aa3bf4a82774e79b5e2a00cd696cb3755f9d17df672358278b",
        11852,
    ),
    "api-reference/agent/v2/get_agent_execution.md": (
        "9b26cd67cd9edbc535e941442f36748ffc724230032dd02e046275c565fb8a01",
        "f87876946b1e95bcb40d8cf8bedc417026934cc543a17aa6df19d7b20944f2c2",
        11940,
    ),
    "api-reference/agent/v2/get_all_agent_executions.md": (
        "11cccce75bf968ab08371267d4a066f29c2ea59118f33b544b315f7e994d42af",
        "973b74572251ea6bc59b7156a81d9e0efcf4d8961104cb15acd445339bddcfd4",
        16431,
    ),
    "api-reference/batches/executions.md": (
        "adece9679c25b14225c03a637c44c4080c3a9b0e0c5a33428a236369d9a7aa0d",
        "c9024e71d0a627e6ddba3a6d45bb4526ec1d7ddb1a46b90fae23ecc991788cf8",
        11904,
    ),
    "api-reference/executions/get_batch_executions.md": (
        "5543d1b4c308a17eaf2249b292513886515cbb3cccdcd37b5f1bb71acd2c0375",
        "1bdf8811fc641739e23bf115a688bbf7b24c19a94905292ce7f5e161bf40f1f6",
        11945,
    ),
    "api-reference/executions/get_execution.md": (
        "d8843c09f572034df402dd242019b56492d4d4c6d0341e1bc1fb300dabdba297",
        "9cc012d5c725ba3c8cfa62cf06a53c54f1b793b5f2a0e016ba21c2d6e77d3d8b",
        15158,
    ),
    "api-reference/executions/get_executions.md": (
        "92c8f85e4f77eaa60bdb01ccaff9fa138d49d0ef4789816a6b0fbd18d2eee9dc",
        "2bb88016e5af0e06ead581912a0c125580ea8b2c6b6a7ba948e2fb3747aee182",
        16464,
    ),
}

#: The redaction itself: a Twilio ACCOUNT SID (`AC` + 32 hex) overwritten with `AC` + 32
#: `X`. Anchored to the FULL width rather than to `ACX+`, because the property that keeps
#: every citation into these pages valid is that the fill is exactly as wide as what it
#: replaced. A shorter fill is a different edit with a different consequence and should
#: fail here rather than pass as "still redacted".
REDACTION: Final = re.compile(rb"AC[X]{32}")
REDACTION_COUNT: Final = 2

#: The two corpus files `scripts/fetch_bolna_docs.py` writes WITHOUT a manifest record —
#: `index_file.write_bytes(body)` for the index and the `--full-only` branch for the whole
#: corpus. Nothing else in the tree hashes them, and `llms-full.txt` is what an agent greps
#: when a page is missing, so an edit to it would have been undetectable.
UNMANIFESTED: Final[dict[str, str]] = {
    "llms.txt": "ed5d17399559e5b178bef483bf7d3f19b1f9b492d2e5ce4f0eed6ab2725637ed",
    "llms-full.txt": "a3277506af68eba420a35b8dc992758edcb18a159ddcf71b311b2b295c889404",
}


def _manifest_pages() -> dict[str, str]:
    """Relative page path → recorded sha256.

    The manifest stores `path` with WINDOWS separators (it was written on one), and with a
    `vendor\\bolna\\mirror\\pages\\` prefix that is not this repo's layout. Split on the
    prefix rather than trying to reconstruct it, so a future re-mirror from a different
    machine does not silently match zero entries and report a clean tree.
    """
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pages: dict[str, str] = {}
    for record in raw.values():
        stored = record.get("path", "")
        marker = "mirror\\pages\\"
        if marker not in stored:
            # The one 404 entry has no page on disk. Absence is the correct state for it.
            continue
        pages[stored.split(marker, 1)[1].replace("\\", "/")] = record["sha256"]
    return pages


def test_the_manifest_still_describes_the_tree_on_disk() -> None:
    """Wiring: this guard must be pointed at a real, populated mirror.

    Without this, deleting the mirror or moving it would make every assertion below pass
    vacuously — the exact way a check stops checking without ever going red.
    """
    pages = _manifest_pages()
    assert len(pages) > 300, f"manifest describes only {len(pages)} pages; is it truncated?"
    missing = sorted(rel for rel in pages if not (PAGES / rel).is_file())
    assert missing == [], f"manifest names pages that are not on disk: {missing[:5]}"


def test_no_page_has_drifted_from_the_bytes_somebody_recorded() -> None:
    """The integrity ledger, now over BYTES rather than over a set of paths.

    Every page must hash to its manifest entry; the seven redacted ones must hash to their
    COMMITTED value instead. A new mismatch fails, and so does a page that quietly leaves
    the redacted set — in either direction the mirror stopped being the artefact the
    findings cite.
    """
    recorded = _manifest_pages()
    assert len(recorded) > 300, f"manifest describes only {len(recorded)} pages"

    unexpected: list[str] = []
    for rel, as_fetched in sorted(recorded.items()):
        actual = hashlib.sha256((PAGES / rel).read_bytes()).hexdigest()
        if rel in REDACTED_PAGES:
            continue
        if actual != as_fetched:
            unexpected.append(rel)
    assert unexpected == [], (
        "vendor evidence was modified in place — these pages no longer match "
        f"MANIFEST.json: {unexpected}. The mirror is what every Bolna finding cites. "
        "Restore them from git. Do NOT add them to REDACTED_PAGES and do NOT regenerate "
        "the manifest: either one converts damage into the record."
    )

    stale = sorted(REDACTED_PAGES.keys() - recorded.keys())
    assert stale == [], f"REDACTED_PAGES names pages the manifest does not describe: {stale}"


def test_each_redacted_page_still_holds_exactly_the_bytes_that_were_committed() -> None:
    """The half the old path-only ledger could not assert at all.

    `KNOWN_HASH_MISMATCHES` recorded THAT these seven mismatched, so any further edit to
    them — including one that moved a line another document cites — kept the suite green.
    Two of them are cited by line number in `docs/evidence/`.
    """
    for rel, (as_fetched, as_committed, size) in sorted(REDACTED_PAGES.items()):
        body = (PAGES / rel).read_bytes()

        # Checked BEFORE the hash so that "restoring from the vendor" — the remedy this
        # file used to recommend — reports what it actually did rather than reading as a
        # generic mismatch.
        found = len(REDACTION.findall(body))
        assert found == REDACTION_COUNT, (
            f"{rel} carries {found} redacted Twilio Account SID placeholder(s), not "
            f"{REDACTION_COUNT}. If this page was 'restored from the vendor' to make a "
            "hash match, it has just put a vendor account identifier back into a tracked "
            "file — that is what commit 5e18585 removed on purpose, and the original "
            "32 hex characters do not exist anywhere any more."
        )
        assert len(body) == size, (
            f"{rel} is {len(body)} bytes, not {size}. The redaction is width-preserving, "
            "which is the only reason every `page:line` citation into this page still "
            "resolves — a length change means lines moved."
        )
        assert hashlib.sha256(body).hexdigest() == as_committed, (
            f"{rel} does not match its committed hash. This page is cited by line number "
            "in docs/evidence/; something edited it."
        )
        assert _manifest_pages()[rel] == as_fetched, (
            f"{rel}: MANIFEST.json's as-fetched hash changed. The manifest records what "
            "the VENDOR served and is never rewritten to match a tree."
        )


def test_the_corpus_files_the_fetcher_never_manifested_are_pinned_here() -> None:
    """`llms.txt` and `llms-full.txt` are written without a manifest record, so nothing
    else in the tree would ever notice an edit to them — and `llms-full.txt` is the whole
    corpus in one file, i.e. what gets grepped when a page seems to be missing."""
    for name, want in sorted(UNMANIFESTED.items()):
        path = MIRROR / name
        assert path.is_file(), f"{name} is missing from the mirror"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == want, (
            f"{name} changed. `scripts/fetch_bolna_docs.py` records no manifest entry for "
            "it, so this constant is the only thing that would ever notice."
        )


def test_the_formatter_will_not_touch_the_evidence_tree() -> None:
    """The fix, asserted by asking the formatter itself, on the hardest invocation.

    The probe passes the mirror path EXPLICITLY rather than formatting the repo root,
    because that is the invocation `extend-exclude` alone does not survive: ruff applies
    exclusions while walking a directory but not to paths it is handed directly, and
    `.pre-commit-config.yaml` runs `ruff-format` — a hook that always passes explicit
    paths. A guard that only checked `ruff format .` would have gone green on a config
    that still let every commit rewrite the vendor's pages.

    `--check` is used so this asserts a property without ever writing a byte: a correctly
    excluded tree makes ruff report that it found no files at all.
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", str(MIRROR)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "No Python files found" in combined and result.returncode == 0, (
        "ruff can still reach the vendor evidence mirror, so `ruff format` will rewrite "
        "the vendor's own code samples and break their MANIFEST hashes. Keep "
        "`bolna-findings` in [tool.ruff] extend-exclude AND keep `force-exclude = true`. "
        f"ruff said (rc={result.returncode}): {combined[:400]}"
    )
