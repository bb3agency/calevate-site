"""D-507 — the third sentence, an agent's memory notice, kept on file. Since D-969 it is not
quoted on calls: the agent says the notice in its own words with its goodbye
(`engine.memory_goodbye_rule`, tested in `ai_notice_introduction_test` and
`caller_memory_switch_test`).

WHAT THIS FILE HAS TO PROVE:

1. **It is never in the opening**, and D-163's four postures are untouched by it.
2. **The roster reads it where its query puts it.** `roster.py` reads its row POSITIONALLY
   (`r[17]`, `r[18]`), which is the shape that breaks without erroring at all, so the
   indices are pinned against the query itself.
3. **The migration's copy of the sentences stays honest.** `e1a4d70c9b52._NOTICE` COPIES
   `compliance/disclosure.CALLER_MEMORY_NOTICE_TEMPLATES` rather than importing it — the
   right call for a migration, which must keep meaning what it meant on the day it ran —
   and a copy nobody compares is a copy that drifts. This is that comparison.
4. **The floor is in the DATABASE, not in Python.** NOT NULL and non-blank by CHECK, on
   every agent, whether or not memory is on: switching memory on must never be the moment
   somebody finds there is nothing to say.

WHY THE COMPOSER'S CASES ARE ENUMERATED HERE RATHER THAN ADDED TO `disclosure_toggle_test`:
that file pins D-163's FOUR postures as an exhaustive set, and it is right to keep doing
so. This one asks what the third sentence does to each of them.

SCOPING (this suite shares a database with every other): every tenant is minted with a
`uuid4` slug and every query is keyed by that tenant's own id.
"""

from __future__ import annotations

import ast
import importlib.util
import uuid
from pathlib import Path

import pytest
from apps.api.agents import roster
from apps.api.compliance.disclosure import (
    CALLER_MEMORY_NOTICE_TEMPLATES,
    caller_memory_notice_for,
)
from apps.api.db.session import tenant_session
from calevate_shared.engine import DisclosurePosture, compose_opening_line
from calevate_shared.languages import staged_language_tags
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import ACCEPT_CALLER_MEMORY_STATEMENT, create_org_with_receptionist

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = (
    REPO_ROOT
    / "alembic"
    / "versions"
    / "e1a4d70c9b52_caller_memory_says_so_and_forgets_on_its_own_clock.py"
)

AI = "Idi AI assistant."
REC = "Ee call record avutundi."
MEM = "Nenu gurthu pettukuntaanu."


def _posture(
    *,
    ai: bool = True,
    rec: bool = True,
    memory: bool = False,
    memory_line: str = MEM,
) -> DisclosurePosture:
    return DisclosurePosture(
        ai_disclosure_line=AI,
        ai_disclosure_enabled=ai,
        recording_notice_line=REC,
        recording_notice_enabled=rec,
        caller_memory_notice_line=memory_line,
        caller_memory_enabled=memory,
    )


async def _tenant(language: str = "te-IN") -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Clinic",
        slug=f"mem-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language=language,
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _remember(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, on: bool = True) -> None:
    """Turn the MEMORY switch — the only switch this sentence has."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET caller_memory_enabled = :on, updated_at = now() WHERE id = :a"),
            {"on": on, "a": agent_id},
        )
        await session.execute(ACCEPT_CALLER_MEMORY_STATEMENT, {"tid": tenant_id})


# --- 1. the composer -----------------------------------------------------------------


def test_the_sentence_is_never_in_the_opening() -> None:
    """The opening says what the agent is and that the call is recorded (D-865)."""
    opening = compose_opening_line(_posture(memory=True), call_is_recorded=True)
    assert opening == f"{AI} {REC}"


@pytest.mark.parametrize(
    ("ai", "rec"), [(True, True), (True, False), (False, True), (False, False)]
)
def test_memory_off_leaves_d163s_four_postures_exactly_as_they_were(ai: bool, rec: bool) -> None:
    """The default must be a no-op: the field defaults exist so that every posture built
    before D-507 keeps meaning what it meant."""
    remembering_nothing = _posture(ai=ai, rec=rec, memory=False)
    with_field = compose_opening_line(remembering_nothing, call_is_recorded=True)
    without_field = compose_opening_line(
        DisclosurePosture(
            ai_disclosure_line=AI,
            ai_disclosure_enabled=ai,
            recording_notice_line=REC,
            recording_notice_enabled=rec,
        ),
        call_is_recorded=True,
    )
    assert with_field == without_field


# --- 2. the roster -------------------------------------------------------------------


def test_the_roster_indices_agree_with_the_roster_query() -> None:
    """`agent_out` reads its row POSITIONALLY. A column added anywhere but the end of the
    SELECT shifts every index after it, and nothing raises — the row is long enough and a
    `str()` of the wrong column is still a string. So the two new indices are pinned
    against the query text rather than trusted."""
    # Split on the OUTER `FROM` — the inbound-number count is a correlated subquery with a
    # `FROM` of its own, and a naive split cuts the column list in half at that one.
    columns = roster.AGENT_ROSTER_SQL.split("SELECT ", 1)[1].split(" FROM agents a ", 1)[0]
    depth, current, parsed = 0, "", []
    for ch in columns:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parsed.append(current.strip())
            current = ""
            continue
        current += ch
    parsed.append(current.strip())

    assert parsed[17] == "a.caller_memory_notice_line"
    assert parsed[18] == "a.caller_memory_enabled"
    assert parsed[24] == "o.caller_memory_attestation_version"
    # And the fields the older mapper reads are still where it thinks they are — the same
    # shift would have moved these, silently.
    assert parsed[9] == "a.ai_disclosure_line"
    assert parsed[11] == "a.recording_notice_line"


async def test_the_roster_shows_the_sentence_for_an_agent_that_remembers() -> None:
    """On file, and not in what callers hear first."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        listed = await roster.list_agents(session)
    row = next(a for a in listed if a.id == agent_id)
    assert row.caller_memory_enabled
    assert row.caller_memory_notice_line == CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"]
    assert CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"] not in row.first_words


async def test_the_roster_says_nothing_about_memory_when_it_is_off() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        listed = await roster.list_agents(session)
    row = next(a for a in listed if a.id == agent_id)
    assert CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"] not in row.opening_line


# --- 3. the migration's copy of the sentences ----------------------------------------


def _script_rewrite() -> dict[str, str]:
    """D-745's (old, new) sentence pairs, read from its migration's `_LINES` as source."""
    path = MIGRATION.parent / "e9b4c2a7d136_notices_in_their_own_script.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_LINES" for t in node.targets
        ):
            rows = ast.literal_eval(node.value)
            return {row[i]: row[i + 1] for row in rows for i in (0, 2, 4)}
    raise AssertionError(f"no `_LINES` in {path}")


SCRIPT_REWRITE = _script_rewrite()


def _reword() -> dict[str, str]:
    """D-861's exact (previous default -> new) memory sentences, from its migration."""
    path = MIGRATION.parent / "c3e8a1f5d702_notices_in_own_letters.py"
    spec = importlib.util.spec_from_file_location("_revision_c3e8a1f5d702", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module._EXACT["caller_memory_notice_line"])


REWORD = _reword()


def _migration_notices() -> dict[str, str]:
    """The migration's `_NOTICE`, read as SOURCE rather than imported.

    Importing it would execute a module whose whole point is to be frozen, and would also
    make this test pass by way of the same object it is supposed to be comparing against
    if the copy were ever replaced with an import. The AST is the honest reading.
    """
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_NOTICE" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return {str(k): str(v) for k, v in value.items()}
    raise AssertionError(f"no `_NOTICE` dict in {MIGRATION}")


def test_the_migrations_copy_of_the_sentences_is_byte_identical() -> None:
    """The migration COPIES rather than imports, for the reason every migration copies its
    constants — it must keep meaning what it meant on the day it ran. A copy nobody
    compares is a copy that drifts, and the drift is invisible: the agents created before
    the change and after it would open with different sentences in the same language.

    D-745 moved the Telugu and Hindi sentences into their own script, and its migration
    rewrites exactly the old outputs, and D-861 rewrites them again; so the old copy, carried
    through both rewrites, is today's table. The staged languages (D-855) came later, with no
    agent holding one, so the copy is compared over the languages it knew."""
    rewritten = {
        lang: REWORD.get(SCRIPT_REWRITE.get(line, line), SCRIPT_REWRITE.get(line, line))
        for lang, line in _migration_notices().items()
    }
    staged = set(staged_language_tags())
    assert rewritten == {
        tag: line for tag, line in CALLER_MEMORY_NOTICE_TEMPLATES.items() if tag not in staged
    }


def _backfill_case(languages: list[str]) -> str:
    """The migration's own CASE expression, over synthetic rows instead of `agents`."""
    notices = _migration_notices()

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    arms = " ".join(
        f"WHEN language_primary = {quote(lang)} THEN {quote(sentence)}"
        for lang, sentence in notices.items()
    )
    rows = ", ".join(f"({quote(lang)})" for lang in languages)
    return (
        f"SELECT CASE {arms} ELSE {quote(notices['en-IN'])} END "
        f"FROM (VALUES {rows}) v(language_primary)"
    )


async def test_the_backfill_puts_each_language_on_its_own_agents() -> None:
    """The migration's backfill, exercised where it can still be run.

    It cannot be re-run against `agents` — it already ran, and rerunning it would rewrite
    other suites' fixtures on this shared database — so the expression is run over a VALUES
    list. That is where the mistakes live anyway: an arm naming a language the templates do
    not carry, or a fallback that puts English on a Telugu agent.
    """
    notices = _migration_notices()
    languages = [*notices, "xx-XX"]
    async with tenant_session(uuid.uuid4()) as session:
        produced = [
            str(v) for v in (await session.execute(text(_backfill_case(languages)))).scalars().all()
        ]

    assert produced == [notices.get(lang, notices["en-IN"]) for lang in languages]
    assert produced[0] == notices["te-IN"], "a Telugu agent must get the Telugu sentence"


# --- 4. the floor is in the database -------------------------------------------------


async def test_a_new_agent_is_born_with_the_sentence_in_its_own_language() -> None:
    """ON FILE FROM THE FIRST SECOND, and in the agent's language rather than English —
    an agent whose other two sentences are Telugu and whose third is English is a script
    that lost its place."""
    tenant_id, agent_id = await _tenant("te-IN")
    async with tenant_session(tenant_id) as session:
        line, enabled = (
            await session.execute(
                text(
                    "SELECT caller_memory_notice_line, caller_memory_enabled "
                    "FROM agents WHERE id = :a"
                ),
                {"a": agent_id},
            )
        ).one()
    assert (
        line
        == CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"]
        == caller_memory_notice_for(language="te-IN")
    )
    assert enabled is False, "memory is off until somebody turns it on (D-506)"


async def test_no_agent_of_this_tenant_holds_a_blank_sentence() -> None:
    """The floor, checked against ROWS rather than against the migration that wrote them.
    Scoped to this tenant because RLS scopes it there anyway, and `count` rather than the
    sentences themselves — nothing here needs to read the text back out."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        offenders = (
            await session.execute(
                text(
                    "SELECT count(*) FROM agents "
                    "WHERE caller_memory_notice_line IS NULL "
                    "OR length(btrim(caller_memory_notice_line)) = 0"
                )
            )
        ).scalar_one()
    assert offenders == 0


@pytest.mark.parametrize("value", ["", "   "])
async def test_the_database_refuses_a_blank_sentence(value: str) -> None:
    """`ck_agents_caller_memory_notice_nonempty` — the floor, in the one place no code path
    can go around. Asked of an UPDATE because that is the shape a future "let the client
    edit it" screen would take."""
    tenant_id, agent_id = await _tenant()
    with pytest.raises(IntegrityError) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET caller_memory_notice_line = :v WHERE id = :a"),
                {"v": value, "a": agent_id},
            )
    assert "ck_agents_caller_memory_notice_nonempty" in str(caught.value)


async def test_the_database_refuses_no_sentence_at_all() -> None:
    tenant_id, agent_id = await _tenant()
    with pytest.raises(IntegrityError) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE agents SET caller_memory_notice_line = NULL WHERE id = :a"),
                {"a": agent_id},
            )
    assert "caller_memory_notice_line" in str(caught.value)
