"""Two boundaries the KB path is the likeliest place to breach.

**Hard rule 2 (engine isolation).** `lint-imports` already forbids every business module
from importing a vendor adapter, and that catches the loud version of the leak. It
cannot catch the quiet one: a vendor's FIELD NAME copied into our model, our column, our
JSON key or our error message. The KB path is where that would happen, because it is the
only path that persists a value the vendor minted — `attach_kb` returns the engine's own
handle for the attached copy, and that handle has to be stored somewhere or the copy can
never be withdrawn. It is stored under a neutral key, in a JSONB column, as an opaque
string; the moment it is stored as `rag_id`, every reader of that row has learned a
Bolna-specific fact and swapping engines becomes a migration.

**The object-store lifecycle rule.** `tests/object_lifecycle_test.py` proves that the
two prefixes `apps/workers/storage.py` writes are both covered by an expiry rule. That
is a check on the two key functions that exist TODAY; it cannot fail for a third one
added tomorrow, because it does not know to look for it. The KB is the obvious candidate
— `kb_sources.kind` already admits `file` and `url` — and a KB blob written to a prefix
no rule matches accumulates forever while every existing lifecycle test stays green.
The tripwire below is the missing half: it fails when a new key function appears, and
says what to do about it.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from apps.workers import storage

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_MODULE = REPO_ROOT / "apps" / "api" / "kb"


def _kb_sources() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(KB_MODULE.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


# --- Hard rule 2 ---------------------------------------------------------------------


def test_no_vendor_field_name_appears_anywhere_in_the_kb_path() -> None:
    """The names a vendor payload would arrive under, checked as text.

    `rag_id` is the specific one that matters: it is what Bolna calls the handle
    `attach_kb` returns, and `apps/api/engine/bolna.py` is where that name is allowed to
    exist — it reads `data.get("rag_id")` and hands back a plain string. Everything
    above the adapter sees `EngineKBRef`, which is ours.
    """
    forbidden = ("rag_id", "bolna", "knowledgebase", "vocode", "retell", "x-api-key")
    for filename, body in _kb_sources().items():
        lowered = body.lower()
        for token in forbidden:
            assert token not in lowered, (
                f"{filename} names {token!r} — a vendor's own vocabulary above the "
                "adapter boundary (hard rule 2)"
            )


def test_the_engine_handle_is_persisted_under_a_neutral_name() -> None:
    """The column name is part of the schema, and it outlives the engine that suggested it.

    A handle stored under the VENDOR's name for it would be a vendor shape in a typed
    column by another route: Bolna calls this identifier a `vector_id` and calls a
    different one (`rag_id`) the id of the same object, and either spelling above the
    adapter would freeze one vendor's vocabulary into our schema. `engine_kb_ref`
    describes the ROLE — "the engine's handle for this source" — which is the convention
    `agents.engine_agent_ref` and `engine_agent_routes` already set.

    D-519 moved it from `kb_documents.meta ->> 'engine_kb_ref'` to a column of the same
    name on `engine_kb_routes`; the naming rule is what this test guards, not the home.
    """
    service = (KB_MODULE / "service.py").read_text(encoding="utf-8")
    assert "engine_kb_routes" in service
    assert "engine_kb_ref" in service, (
        "the handle is no longer read under the neutral name the schema reserves"
    )
    for vendor_spelling in ("vector_id", "rag_id"):
        assert vendor_spelling not in service, (
            f"{vendor_spelling!r} is the vendor's name for this identifier and belongs "
            "inside apps/api/engine/ (hard rule 2)"
        )


def test_the_kb_path_reaches_the_engine_only_through_the_protocol() -> None:
    """Restated at the level `lint-imports` reports it, so a failure here names the KB
    file rather than a contract id: the only engine symbols this module may know are the
    factory and the Protocol's own types."""
    for filename, body in _kb_sources().items():
        assert "engine.bolna" not in body, f"{filename} imports the vendor adapter"
        assert "engine.fake" not in body, f"{filename} imports an adapter directly"


# --- The object-store lifecycle rule -------------------------------------------------


def test_every_object_key_the_kb_path_writes_is_covered_by_a_lifecycle_rule() -> None:
    """The KB path DOES write to the bucket now (D-534), so the tripwire becomes the check
    it was a placeholder for.

    THIS TEST USED TO ASSERT THE OPPOSITE — that `apps/api/kb` touches no bucket at all —
    and its docstring named the day it would stop being true: *"the day a client's uploaded
    PDF starts accumulating under a prefix no expiry rule matches"*. That day is this one,
    so the assertion moves from "nothing is written" to "everything written is bounded",
    which is the property the old one was standing in for.

    WHY IT MATTERS MORE HERE THAN FOR THE OTHER PREFIXES. A recording and a raw vendor
    payload are BY-PRODUCTS of a call; a knowledge upload is the client's own document, and
    it is the LIVE artefact behind a published source — the file a reviewer opens and the
    bytes a republish re-reads. So the rule that covers it is a growth ceiling and must
    never be short enough to act as retention (`infra/object-lifecycle/apply_lifecycle.py`
    carries that argument beside the constant).

    The keys themselves are built in `apps/workers/storage.py` — this path calls that
    module rather than reaching for a bucket of its own, which is what keeps every object
    this platform stores inside one key vocabulary and one lifecycle document.
    """
    policy = json.loads(
        (REPO_ROOT / "infra" / "object-lifecycle" / "policy.json").read_text(encoding="utf-8")
    )
    bounded = {
        rule.get("Filter", {}).get("Prefix", "")
        for rule in policy["Rules"]
        if rule["Status"] == "Enabled" and rule.get("Expiration", {}).get("Days") is not None
    }
    written = storage.kb_object_key(
        tenant_id=uuid4(), upload_id=uuid4(), slot="original", suffix="pdf"
    )
    assert any(written.startswith(prefix) for prefix in bounded), (
        f"nothing expires {written!r} — a client's uploaded document would accumulate "
        "under a prefix no lifecycle rule matches"
    )

    # And the KB path may only reach the bucket through that module: an S3 CLIENT here
    # would be a key layout no lifecycle rule and no erasure sweep knows about. The two
    # spellings checked are the ones that would appear — building a client, or calling one.
    # (`boto3` appears in this path as a WORD, in the comments explaining why the imports of
    # `workers.storage` are deferred, so the token itself is not the test.)
    for filename, body in _kb_sources().items():
        assert "put_object(" not in body and "import boto3" not in body, (
            f"{filename} reaches object storage directly — every object this platform "
            "stores goes through apps/workers/storage.py, which is where the key layout "
            "and the lifecycle prefixes live"
        )
