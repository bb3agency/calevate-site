"""ONE ANSWER to "which languages does this product sell", and a column that can refuse.

Two defects, one seam. `calevate_shared.languages` declared what the SPEECH STACK can do
— 23 languages Sarvam's STT can transcribe, 11 its TTS can speak — and nothing consumed
it, so the three tags the product actually sells were spelled independently in seven
places (`agents/voices.Language`, `agents/voice_sync._PRODUCT_LANGUAGES`,
`copilot/agent_actions._LANGUAGES` plus a second label table, `engine/bolna.
_VOICE_LANGUAGES`, `admin/routes.CreateOrgIn.language`, `tenancy/signup_routes.Language`,
and three tables of labels across the frontend), none derived from another. Meanwhile
`agents.language_primary` was a bare `Text` column with no CHECK and a `str` on the wire,
so the API would accept and store `xx-IN`.

WHAT THIS FILE ASSERTS, and why each one is a property rather than a copy
--------------------------------------------------------------------------------------

1. **The offered set is derived everywhere but one place, and that place is pinned.**
   Pydantic needs a static `Literal` to emit an OpenAPI enum, so `agents/languages.
   Language` is the single hand-typed copy and it is held EQUAL to `offered_language_
   tags()`. Every other surface is checked against the declaration, and two of them by
   OBJECT IDENTITY — a tuple that is the same object cannot have drifted.

2. **Nothing may quietly re-introduce a list.** `test_no_module_spells_the_offered_set_
   for_itself` walks the AST of every source file under `apps/` and `packages/shared/src`
   and the text of every `.ts`/`.tsx` under `apps/web/src`, and flags any file whose own
   string constants name two or more of the offered tags. The result is compared as an
   EQUALITY against a ledger naming each permitted file and WHY — the same shape
   `KNOWN_WIRE_CODE_ANOMALIES` uses, and for the same reason: a new entry has to be
   argued for in a diff rather than added by whoever was in a hurry. It is not a grep for
   a known bad pattern; it is an inventory that must not grow.

3. **Offered is a subset of conversational, and can never include a comprehension-only
   language.** That is the dead-air failure the shared declaration exists to prevent: an
   agent set to Assamese would be transcribed perfectly and answer nothing. It is
   asserted on the offered set, refused at the wire with a sentence that says so, and
   refused again by the CHECK constraint.

4. **Both ends of the column are closed.** A validated type at the boundary (RFC-9457
   problem naming the three that work) and `ck_agents_language_primary_offered` in the
   database (migration c7a41e8b52d9), because the routes are not the only writer — the
   admin service, the intake path and every future backfill write this column in SQL.

Run: uv run pytest -q tests/product_languages_test.py
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from typing import get_args

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import handoff, voice_sync
from apps.api.agents.languages import (
    LANGUAGE_LABELS,
    PRODUCT_LANGUAGES,
    Language,
    language_refusal,
)
from apps.api.agents.models import Agent
from apps.api.agents.routes import router as agents_router
from apps.api.compliance import disclosure
from apps.api.copilot.agent_actions import AGENT_CREATE
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.bolna import _VOICE_LANGUAGES
from calevate_shared.languages import (
    LANGUAGES,
    OFFERED_LANGUAGE_IDS,
    comprehension_only_languages,
    conversational_languages,
    find_language,
    offered_language_tags,
    offered_languages,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import IntegrityError
from tests.conftest import accept_agreements

pytestmark = [pytest.mark.rls]

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A language Sarvam can HEAR and cannot SPEAK. The refusal this product needs most and
#: the one no click-through would ever produce.
COMPREHENSION_ONLY_TAG = "as-IN"

#: A language that is conversational and simply not sold — a different refusal.
UNSOLD_TAG = "ta-IN"


# ---------------------------------------------------------------- 1. one source of truth


def test_the_wire_literal_is_exactly_the_offered_set() -> None:
    """The one hand-typed copy, pinned to the declaration in both directions.

    An inequality here means somebody widened the Literal without widening the offer (so
    the API accepts a language with no spoken sentences, no voice and no CHECK) or the
    reverse (so the declaration promises what no route will take).
    """
    assert get_args(Language) == offered_language_tags()
    assert offered_language_tags() == PRODUCT_LANGUAGES


def test_the_voice_catalogue_filter_is_the_same_object_not_a_copy() -> None:
    """`voice_sync` filters the engine's voices by product language. Identity, not
    equality: two equal tuples can be two literals that happen to agree today."""
    assert voice_sync.PRODUCT_LANGUAGES is PRODUCT_LANGUAGES


def test_the_labels_are_the_declarations_own_names() -> None:
    """One name per language across the product. The copilot's card used to say "Indian
    English" while every screen said "English (India)" — same language, same operator,
    two words, and nothing that could notice."""
    assert tuple(LANGUAGE_LABELS) == offered_language_tags()
    assert {row.bcp47: row.english_name for row in offered_languages()} == LANGUAGE_LABELS


def test_the_copilot_offers_the_assistant_exactly_what_the_api_accepts() -> None:
    """The tool schema is what the model may emit. Wider than the route and every
    suggestion it makes is a 422 the person reads as a broken assistant."""
    parameters = AGENT_CREATE.schema["function"]["parameters"]
    schema = parameters["properties"]["language_primary"]
    assert tuple(schema["enum"]) == offered_language_tags()
    for tag, label in LANGUAGE_LABELS.items():
        assert f"{tag} {label}" in schema["description"], (
            "the tool's description must name each tag it offers, composed from the "
            "labels rather than typed beside them"
        )


def test_the_engine_adapters_language_map_derives_its_values() -> None:
    """Hard rule 2 keeps the MAP in the adapter — their filter takes a bare subtag and
    that is a vendor fact. Its VALUES are ours and derive."""
    assert tuple(_VOICE_LANGUAGES.values()) == offered_language_tags()
    assert tuple(_VOICE_LANGUAGES) == tuple(tag.split("-", 1)[0] for tag in offered_language_tags())


def test_no_offered_language_has_a_vendor_spelling_of_its_own() -> None:
    """What makes the subtag split above SAFE, stated as the property it depends on.

    Sarvam spells Odia `od-IN` where BCP-47 says `or-IN` (`KNOWN_WIRE_CODE_ANOMALIES`),
    and Odia is conversational — so the day it is offered, a map keyed by "the primary
    subtag of our tag" starts describing a language the vendor names differently. This
    fails then, which is before a call, rather than in `engine/bolna.py` at listing time.
    """
    for row in offered_languages():
        for (vendor, leg), code in row.codes.items():
            assert code == row.bcp47, (
                f"{row.id} is offered and {vendor}/{leg} spells it {code}, not {row.bcp47}: "
                "the vendor-code maps that derive from the tag must become explicit first"
            )


def test_every_offered_language_has_the_sentences_an_agent_speaks() -> None:
    """Hard rule 5 lives on this. `disclosure._rendered` FALLS BACK to English rather
    than failing, so a language offered without its sentences is not an error anywhere —
    it is a Telugu-first product opening in English to the caller who chose Telugu."""
    tables = {
        "ai_disclosure": disclosure.AI_DISCLOSURE_TEMPLATES,
        "recording_notice": disclosure.RECORDING_NOTICE_TEMPLATES,
        "caller_memory_notice": disclosure.CALLER_MEMORY_NOTICE_TEMPLATES,
        "handoff_spoken": handoff.HANDOFF_SPOKEN_TEMPLATES,
    }
    for name, table in tables.items():
        for tag in offered_language_tags():
            assert table.get(tag, "").strip(), f"{name} has nothing to say in {tag}"


def test_the_two_fallback_languages_are_one_row() -> None:
    """`compliance/disclosure` and `agents/handoff` each fall back to English and each
    used to type the tag. They now read the same row; this is what says so."""
    english = LANGUAGES["english_india"].bcp47
    assert english == disclosure.DEFAULT_LANGUAGE
    assert english == handoff._FALLBACK_LANGUAGE
    assert english in offered_language_tags(), "the fallback must be a language we sell"


def test_the_check_constraint_admits_exactly_the_offered_set() -> None:
    """The ORM side of migration c7a41e8b52d9. `tests/orm_schema_fidelity_test.py`
    separately proves this predicate is really in the database."""
    literals: set[str] = set()
    for constraint in Agent.__table__.constraints:
        if isinstance(constraint, CheckConstraint) and "language_primary" in str(
            constraint.sqltext
        ):
            literals |= set(re.findall(r"'([^']+)'", str(constraint.sqltext)))
    assert literals == set(offered_language_tags())


# ------------------------------------------------- 2. nothing re-introduces its own list

#: THE FILES PERMITTED TO NAME TWO OR MORE OFFERED TAGS, and why each one is.
#:
#: An EQUALITY, not a floor: a file that starts spelling the set has to be added here with
#: an argument, which is the review this defect needed and did not get seven times. Every
#: entry below names the tags as KEYS OF PER-LANGUAGE CONTENT or as a vendor's own payload
#: — never as "the list of languages we sell", which is what the declaration is for.
TAG_SPELLING_ALLOWED: dict[str, str] = {
    "packages/shared/src/calevate_shared/languages.py": (
        "THE declaration: one row per language, carrying its BCP-47 tag and each vendor's "
        "spelling of it. Everything else in this ledger derives from here"
    ),
    "apps/api/agents/languages.py": (
        "the `Literal` Pydantic turns into the OpenAPI enum, which cannot be computed — "
        "pinned to `offered_language_tags()` by the first test in this file"
    ),
    "apps/api/compliance/disclosure.py": (
        "three tables of SENTENCES an agent speaks, keyed by language. Content per "
        "language, not a list of languages; a missing key is caught above"
    ),
    "apps/api/agents/handoff.py": "the spoken handover line per language, for the same reason",
    "apps/api/agents/handoff_execution.py": (
        "the WHISPER the person taking a handed-over call hears before they accept, and "
        "the two phrases it falls back on, per language. Content per language on the same "
        "terms as the spoken line above — the caller's half is in `handoff.py` and this is "
        "the called party's half"
    ),
    "apps/api/engine/fake.py": (
        "the fake engine's stand-in for a VENDOR's voice listing. Those strings belong to "
        "the simulated vendor payload (hard rule 2), not to our offer — a fake that read "
        "our declaration could not model a vendor whose list disagrees with it"
    ),
    "apps/api/agents/gnani_voices.py": (
        "a VENDOR's per-voice fact — which single locale Gnani tunes each `timbre-v2.5` "
        "voice for — read off their own SDK and their own listing page (D-618). Like "
        "`engine/fake.py` above it is the vendor's vocabulary rather than our offer, and "
        "it cannot be derived from either end: our declaration cannot say which voice "
        "Gnani tuned for Telugu, and the tag is the VALUE per voice rather than a list of "
        "languages. That our three are a subset of what we sell IS asserted, from the "
        "declaration, in `tests/gnani_voices_test.py`"
    ),
    "apps/web/src/lib/agentState.ts": (
        "the console's one table of language NAMES, `Record<AgentLanguage, string>` over "
        "the generated union — exhaustive by the type checker, so the keys are the same "
        "three and cannot silently become four"
    ),
    "apps/web/src/app/admin/new/languages.ts": (
        "the wizard's per-language HINT strings, keyed the same exhaustive way. The "
        "labels and the order come from `LANGUAGE_CHOICES`"
    ),
}

#: Directories whose files are not product surfaces and are deliberately not scanned.
#: A migration is a snapshot of the schema on the day it ran and spells its constraint out
#: on purpose (`alembic/versions/c7a41e8b52d9` says so); a test is allowed to name the
#: values it is testing, and a generated client is not written by anybody.
_SKIP = ("/tests/", "/test_", "_test.py", "schema.d.ts", "/node_modules/", "/.next/")


def _python_sources() -> list[Path]:
    roots = [REPO_ROOT / "apps", REPO_ROOT / "packages" / "shared" / "src"]
    found = [p for root in roots for p in root.rglob("*.py") if not _skipped(p)]
    assert len(found) > 100, f"source discovery broke — found only {len(found)} files"
    return found


def _typescript_sources() -> list[Path]:
    root = REPO_ROOT / "apps" / "web" / "src"
    found = [p for suffix in ("*.ts", "*.tsx") for p in root.rglob(suffix) if not _skipped(p)]
    assert len(found) > 100, f"source discovery broke — found only {len(found)} files"
    return found


def _skipped(path: Path) -> bool:
    return any(marker in path.as_posix() for marker in _SKIP)


def _tags_in_python(path: Path) -> set[str]:
    """Offered tags appearing as STRING CONSTANTS, docstrings excluded.

    The AST rather than a grep, and the distinction is load-bearing twice: a module whose
    prose discusses `te-IN` (this repo's comments discuss everything) is not a module that
    declares a list, and a tag hidden in an f-string or a tuple is one that a
    line-oriented search can miss.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in offered_language_tags()
        and node not in docstrings
    }


_TS_COMMENT = re.compile(r"^\s*(//|/\*|\*)")


def _tags_in_typescript(path: Path) -> set[str]:
    """The same, for TypeScript, with comment lines dropped.

    No parser here rather than an npm dependency for one assertion: the comparison is
    against a ledger, so the failure mode of a line-based reader is a false POSITIVE that
    somebody reads and resolves, never a silent pass.
    """
    found: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if _TS_COMMENT.match(line):
            continue
        found |= {tag for tag in offered_language_tags() if f'"{tag}"' in line}
    return found


def test_no_module_spells_the_offered_set_for_itself() -> None:
    """THE REGRESSION GUARD for the whole change: an inventory, asserted as an equality.

    Two or more tags in one file's own constants is what "a copy of the list" looks like
    — one tag is a default, a fixture or a fallback and is not a second declaration.
    """
    spelling = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _python_sources()
        if len(_tags_in_python(path)) >= 2
    } | {
        path.relative_to(REPO_ROOT).as_posix()
        for path in _typescript_sources()
        if len(_tags_in_typescript(path)) >= 2
    }
    assert spelling == set(TAG_SPELLING_ALLOWED), (
        "a file spells the offered language set for itself. Derive it from "
        "`calevate_shared.languages.offered_languages()` (or, in TypeScript, from "
        "`LANGUAGE_CHOICES` / the generated union) — or, if the tags are genuinely the "
        "KEYS of per-language content, add the file to TAG_SPELLING_ALLOWED with the "
        f"argument for it.\nunexpected: {sorted(spelling - set(TAG_SPELLING_ALLOWED))}\n"
        f"gone (delete the entry): {sorted(set(TAG_SPELLING_ALLOWED) - spelling)}"
    )


# ------------------------------------------------------- 3. offered is never wider than
#                                                             what can be answered


def test_every_offered_language_can_be_both_heard_and_spoken() -> None:
    """The containment the whole declaration exists to keep. Derived from `support()`
    rather than read off `conversational`, so a flattened property cannot pass it."""
    for row in offered_languages():
        assert row.understood, f"{row.id} is offered and no verified STT leg transcribes it"
        assert row.answerable, f"{row.id} is offered and no verified TTS leg speaks it"
    assert set(OFFERED_LANGUAGE_IDS) <= {row.id for row in conversational_languages()}


def test_no_comprehension_only_language_is_offered() -> None:
    """Said the other way round, because this is the failure with no symptom: an agent
    configured in one of these hears every caller and answers none of them."""
    assert not (set(OFFERED_LANGUAGE_IDS) & {row.id for row in comprehension_only_languages()})
    assert find_language(COMPREHENSION_ONLY_TAG) in comprehension_only_languages(), (
        "this test's own example stopped being comprehension-only; pick another"
    )


def test_the_refusal_names_the_dead_air_rather_than_the_rule() -> None:
    """A refusal a person can act on. "Not permitted" would be true of all three cases
    below and useful in none of them."""
    dead_air = language_refusal(COMPREHENSION_ONLY_TAG)
    assert "Assamese" in dead_air and "silence" in dead_air
    unsold = language_refusal(UNSOLD_TAG)
    assert "Tamil" in unsold and "does not offer" in unsold
    unknown = language_refusal("xx-IN")
    assert "not a language code we recognise" in unknown
    for message in (dead_air, unsold, unknown):
        for tag, label in LANGUAGE_LABELS.items():
            assert f"{tag} ({label})" in message, "every refusal names what WOULD work"


# --------------------------------------------------------- 4. both ends of the column


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    return application


async def _tenant() -> tuple[uuid.UUID, str]:
    """(tenant_id, client dev bearer) for a fresh account that may create agents."""
    created = await admin_service.create_organization(
        name="Language Motors",
        slug=f"lang-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, f"dev:client:{user_id}"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("xx-IN", "not a language code we recognise"), (COMPREHENSION_ONLY_TAG, "silence")],
)
async def test_creating_an_agent_in_a_language_we_do_not_speak_is_refused(
    tag: str, expected: str
) -> None:
    """RFC-9457, and a `detail` the caller can act on.

    A bare `Literal` would refuse both of these too — with "Input should be 'te-IN', ...",
    which `core/errors._LIBRARY_PHRASINGS` drops because it is written for whoever
    implemented the model. What arrives instead names what is wrong with THIS tag and what
    would work.
    """
    _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        response = await http.post(
            "/v1/agents",
            json={"name": "Front desk", "direction": "inbound", "language_primary": tag},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Check what you entered"
    assert expected in body["detail"], body
    assert "te-IN (Telugu)" in body["detail"], body
    assert body["fields"][0]["field"] == "language_primary", body


async def test_changing_an_agents_language_is_refused_on_the_same_ground() -> None:
    """The update route takes the same type. A wire field bounded on the way in and not
    on the way through is a column that ends up holding what the create form refused."""
    _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        created = await http.post(
            "/v1/agents",
            json={"name": "Front desk", "direction": "inbound", "language_primary": "te-IN"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201, created.text
        response = await http.patch(
            f"/v1/agents/{created.json()['id']}",
            json={"language_primary": COMPREHENSION_ONLY_TAG},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422, response.text
    assert "silence" in response.json()["detail"]


async def test_a_created_agent_reports_its_language_as_the_union() -> None:
    """`AgentOut.language_primary` is typed now, so the generated client gets a union and
    every screen can switch on it exhaustively."""
    _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        created = await http.post(
            "/v1/agents",
            json={"name": "Front desk", "direction": "inbound", "language_primary": "hi-IN"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert created.status_code == 201, created.text
    assert created.json()["language_primary"] == "hi-IN"


@pytest.mark.parametrize("tag", ["xx-IN", COMPREHENSION_ONLY_TAG, UNSOLD_TAG, ""])
async def test_the_database_refuses_what_no_route_would_send(tag: str) -> None:
    """THE OTHER END, and the reason the CHECK is worth a migration: the routes are not
    the only writer. `admin/service.create_organization`, the intake path and every
    backfill write this column in SQL, where a Pydantic type reaches nothing.
    """
    tenant_id, _ = await _tenant()
    with pytest.raises(IntegrityError) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, direction, status, "
                    "language_primary, disclosure_line, ai_disclosure_line, "
                    "recording_notice_line, caller_memory_notice_line, created_at, "
                    "updated_at) VALUES (:id, :tid, 'Raw write', 'inbound', 'draft', :lang, "
                    "'This is an AI assistant and this call is recorded.', 'This is an AI "
                    "assistant.', 'This call is being recorded.', 'I keep a short note of "
                    "what you ask about.', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "lang": tag},
            )
    assert "ck_agents_language_primary_offered" in str(caught.value)


async def test_the_constraint_in_the_database_is_validated_not_merely_declared() -> None:
    """A CHECK left `NOT VALID` is skipped by the planner for existing rows and reads, in
    `\\d agents`, exactly like one that is enforced. The migration validates it inside a
    `NO FORCE ROW LEVEL SECURITY` bracket for a4e7b2c95d18's reason — the owner is subject
    to the FORCEd policy too, so an unbracketed scan sees zero rows and proves nothing.
    """
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = 'ck_agents_language_primary_offered'"
                )
            )
        ).first()
    assert row is not None, "migration c7a41e8b52d9 has not been applied to this database"
    assert row[0] is True, "the constraint is NOT VALID: it enforces nothing on existing rows"


def test_the_migration_undoes_exactly_what_it_did() -> None:
    """Reversibility, read off the revision itself (hard rule 8).

    `tests/migration_reversibility_test.py` proves every revision's `downgrade()` is
    non-empty and symmetric in general; this one names the constraint, because a downgrade
    that dropped a DIFFERENT constraint would satisfy the generic guard and leave the
    schema holding something no revision claims.
    """
    source = (
        REPO_ROOT
        / "alembic"
        / "versions"
        / "c7a41e8b52d9_the_language_column_can_refuse_a_value.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    bodies = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "ADD CONSTRAINT" in bodies["upgrade"] and "VALIDATE CONSTRAINT" in bodies["upgrade"]
    assert "DROP CONSTRAINT IF EXISTS" in bodies["downgrade"]
    assert "CK_LANGUAGE" in bodies["upgrade"] and "CK_LANGUAGE" in bodies["downgrade"], (
        "both directions must name the constraint through the same constant"
    )
    assert "language_primary IN ('te-IN', 'hi-IN', 'en-IN')" in source, (
        "the revision spells its own predicate: a migration is a snapshot of the schema "
        "on the day it ran, and importing today's constant would rewrite its meaning"
    )
