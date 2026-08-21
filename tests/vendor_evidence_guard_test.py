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
mismatched **at HEAD**, i.e. they were committed that way and no working-tree revert
reaches them. The damage was invisible for as long as it existed because no gate read the
manifest, which is the failure this file exists to end: a hash nobody verifies is
decoration.

TWO GUARDS, and they fail for different reasons on purpose:

- **the exclusion** — `pyproject.toml` must keep `bolna-findings` out of ruff's reach, so
  the formatter cannot do it again. Asserted through ruff's own resolved file set rather
  than by reading the config string back, because the property that matters is what ruff
  DOES, and an exclude entry that stops working (renamed key, a `force-exclude`
  interaction, a future ruff release) would still read correctly in the toml.
- **the integrity ledger** — every page must hash to its manifest entry, EXCEPT the seven
  broken at HEAD. That set is an equality assertion, not an exemption list, following
  `tests/engine_name_drift_test.KNOWN_COPIES`: breaking an eighth page fails, and REPAIRING
  one of the seven fails too, so an entry cannot outlive the damage it records. Shipping it
  green with the damage named beats shipping it red and having it switched off in the first
  hour of the next audit wave.

Why the seven are recorded rather than repaired: two different causes are mixed in here and
only the mirror's owner can separate them. A whitespace-only diff inside a fenced code block
is the formatter, and the page should be restored from the vendor. A prose diff may be a
genuine re-fetch of a page the vendor has since changed, in which case the file is right and
the MANIFEST entry is the stale half. Reverting blindly would destroy newer truth;
regenerating the manifest blindly would launder the formatter's damage into the record. All
seven happen to be execution/listing pages, which is where several lanes of this audit wave
were working at once — worth knowing before assuming a single cause.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
MIRROR: Final = REPO_ROOT / "bolna-findings" / "mirror"
MANIFEST: Final = MIRROR / "MANIFEST.json"
PAGES: Final = MIRROR / "pages"

#: Pages whose bytes no longer match `MANIFEST.json`, as of the audit that added this
#: guard (20 Aug 2026). EQUALITY, not tolerance — see the module docstring. When the
#: mirror's owner adjudicates one (restore the page, or re-fetch and re-record the hash),
#: this set shrinks in the same change.
KNOWN_HASH_MISMATCHES: Final[frozenset[str]] = frozenset(
    {
        "api-reference/agent/get_all_agent_executions.md",
        "api-reference/agent/v2/get_agent_execution.md",
        "api-reference/agent/v2/get_all_agent_executions.md",
        "api-reference/batches/executions.md",
        "api-reference/executions/get_batch_executions.md",
        "api-reference/executions/get_execution.md",
        "api-reference/executions/get_executions.md",
    }
)


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


def test_no_page_has_drifted_from_its_recorded_hash_beyond_the_known_damage() -> None:
    """The integrity ledger. A new mismatch fails; so does an unrecorded repair."""
    mismatched = {
        rel
        for rel, want in _manifest_pages().items()
        if hashlib.sha256((PAGES / rel).read_bytes()).hexdigest() != want
    }

    newly_broken = sorted(mismatched - KNOWN_HASH_MISMATCHES)
    assert newly_broken == [], (
        "vendor evidence was modified in place — these pages no longer match "
        f"MANIFEST.json: {newly_broken}. The mirror is what every Bolna finding cites; "
        "restore them from the vendor, or re-fetch and re-record the hash. Do not add "
        "them to KNOWN_HASH_MISMATCHES to make this pass."
    )

    repaired = sorted(KNOWN_HASH_MISMATCHES - mismatched)
    assert repaired == [], (
        f"these pages match their hash again: {repaired}. That is good — remove them from "
        "KNOWN_HASH_MISMATCHES in the same change, so the set never claims damage that is "
        "already fixed."
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
