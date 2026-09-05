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

from pathlib import Path

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


def test_the_kb_path_writes_no_object_storage_blob() -> None:
    """Today's honest answer to "do KB uploads participate in the lifecycle rule".

    They do not participate because they do not exist: a KB source's content is chunked
    into `kb_documents.content` in Postgres and nothing in `apps/api/kb` ever touches a
    bucket. That is worth an assertion rather than a sentence, because the day it stops
    being true is the day a client's uploaded PDF starts accumulating under a prefix no
    expiry rule matches — and `tests/object_lifecycle_test.py` would not notice, since
    it only checks the keys it already knows about.
    """
    for filename, body in _kb_sources().items():
        assert "workers.storage" not in body and "put_object" not in body, (
            f"{filename} now writes to object storage: give the new key its own prefix "
            "in infra/object-lifecycle/policy.json and add it to the coverage check in "
            "tests/object_lifecycle_test.py, or the bytes expire by nothing"
        )


def test_every_object_key_function_is_one_the_lifecycle_policy_knows_about() -> None:
    """The tripwire the existing lifecycle tests cannot arm for themselves.

    `object_lifecycle_test` asserts that `recording_key()` and `payload_key()` land under
    a covered prefix. A THIRD key function — kb uploads, exports, parsed documents —
    would sail past it: nothing enumerates the key functions, so nothing notices a new
    one. This does, and it fails closed. Adding a key function is allowed; adding one
    without a lifecycle rule is what this refuses.
    """
    key_functions = {name for name in storage.__all__ if name.endswith("_key")}
    # `delivery_body_key` (D-23) joined the set with its own rule
    # (`webhook-bodies-growth-ceiling-not-retention`) and its own coverage assertion in
    # `object_lifecycle_test`. It is the first key whose bytes are ALSO expired per
    # tenant, by the retention sweep — the bucket rule is its orphan backstop, not its
    # retention mechanism.
    assert key_functions == {"recording_key", "payload_key", "delivery_body_key"}, (
        f"apps/workers/storage.py exports new object key function(s) "
        f"{sorted(key_functions - {'recording_key', 'payload_key', 'delivery_body_key'})}. "
        "Every prefix we "
        "write must be covered by an enabled expiry rule in "
        "infra/object-lifecycle/policy.json — add the rule, extend the coverage "
        "assertions in tests/object_lifecycle_test.py, then update this set."
    )
