"""D-507 — the third sentence: an agent that remembers callers says so, out loud.

WHAT THIS FILE HAS TO PROVE, in falling order of what it costs to get wrong:

1. **"Remembers a caller and does not say so" is not constructible.** The sentence has no
   switch of its own: it is spoken exactly when `agents.caller_memory_enabled` is true.
   That is the whole decision, so it is asked of the composer directly and then of every
   surface that builds a `DisclosurePosture` — because a posture built WITHOUT the two new
   fields composes a perfectly valid-looking opening that silently drops the sentence, and
   nothing downstream can tell the difference.
2. **Every constructor carries them, including the next one somebody writes.** Four call
   sites were wired by hand (`agents/service.py::posture_of`, `agents/roster.py`,
   `agents/script_builder.py`, `agents/publishing.py`); a fifth added later would be a
   silent regression, so the constructors are enumerated from the AST rather than listed
   here. `roster.py` reads its row POSITIONALLY (`r[17]`, `r[18]`), which is the shape that
   breaks without erroring at all, so the indices are pinned against the query itself.
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
import uuid
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import publishing, roster, script_builder
from apps.api.agents.service import _load_agent, posture_of
from apps.api.compliance.disclosure import (
    CALLER_MEMORY_NOTICE_TEMPLATES,
    caller_memory_notice_for,
)
from apps.api.db.session import tenant_session
from calevate_shared.engine import DisclosurePosture, compose_opening_line
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
    created = await admin_service.create_organization(
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


# --- 1. the composer -----------------------------------------------------------------


def test_the_sentence_is_spoken_exactly_when_memory_is_on() -> None:
    """The decision, asked directly: the flag is the switch, and there is no other."""
    assert compose_opening_line(_posture(memory=True)).endswith(MEM)
    assert MEM not in compose_opening_line(_posture(memory=False))


def test_the_sentence_comes_third() -> None:
    """After what the agent IS and after the recording — the order those facts become
    relevant to a caller. Pinned as the whole string, not as a substring test, because
    "appears somewhere" is true of every ordering."""
    assert compose_opening_line(_posture(memory=True)) == f"{AI} {REC} {MEM}"


@pytest.mark.parametrize(
    ("ai", "rec", "expected"),
    [
        (True, True, f"{AI} {REC} {MEM}"),
        (True, False, f"{AI} {MEM}"),
        (False, True, f"{REC} {MEM}"),
        # THE CASE THAT MATTERS MOST. D-163's empty opening is a legitimate posture; an
        # agent that remembers callers still has to say so, so this one is NOT empty.
        (False, False, MEM),
    ],
)
def test_it_survives_both_other_toggles_in_every_combination(
    ai: bool, rec: bool, expected: str
) -> None:
    assert compose_opening_line(_posture(ai=ai, rec=rec, memory=True)) == expected


@pytest.mark.parametrize(
    ("ai", "rec"), [(True, True), (True, False), (False, True), (False, False)]
)
def test_memory_off_leaves_d163s_four_postures_exactly_as_they_were(ai: bool, rec: bool) -> None:
    """The default must be a no-op: the field defaults exist so that every posture built
    before D-507 keeps meaning what it meant."""
    with_field = compose_opening_line(_posture(ai=ai, rec=rec, memory=False))
    without_field = compose_opening_line(
        DisclosurePosture(
            ai_disclosure_line=AI,
            ai_disclosure_enabled=ai,
            recording_notice_line=REC,
            recording_notice_enabled=rec,
        )
    )
    assert with_field == without_field


def test_a_blank_sentence_cannot_be_padded_into_the_opening() -> None:
    """Whitespace is not a sentence. The column's CHECK is the real guard; this is the
    composer refusing to emit a trailing space if one ever gets past it."""
    assert compose_opening_line(_posture(memory=True, memory_line="   ")) == f"{AI} {REC}"


# --- 2. every constructor of the posture ---------------------------------------------


def _posture_call_sites() -> list[tuple[str, ast.Call]]:
    sites: list[tuple[str, ast.Call]] = []
    for path in sorted((REPO_ROOT / "apps").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DisclosurePosture"
            ):
                sites.append((f"{path.relative_to(REPO_ROOT)}:{node.lineno}", node))
    return sites


def test_every_posture_constructor_in_the_app_carries_the_third_sentence() -> None:
    """ENUMERATED, NOT LISTED. Four call sites were wired by hand; the fifth one somebody
    writes next month is the regression this catches, and it is the expensive kind — a
    posture missing these two fields is valid, composes, and quietly drops the sentence for
    whichever surface built it."""
    sites = _posture_call_sites()
    assert len(sites) >= 4, f"expected the four known constructors, found {len(sites)}"
    missing = [
        where
        for where, call in sites
        if not {"caller_memory_notice_line", "caller_memory_enabled"}.issubset(
            {kw.arg for kw in call.keywords if kw.arg}
        )
    ]
    assert not missing, f"posture built without the memory sentence at: {missing}"


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
    # And the fields the older mapper reads are still where it thinks they are — the same
    # shift would have moved these, silently.
    assert parsed[9] == "a.ai_disclosure_line"
    assert parsed[11] == "a.recording_notice_line"


async def test_the_roster_speaks_the_sentence_for_an_agent_that_remembers() -> None:
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        listed = await roster.list_agents(session)
    row = next(a for a in listed if a.id == agent_id)
    assert row.opening_line.endswith(CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"])


async def test_the_roster_says_nothing_about_memory_when_it_is_off() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        listed = await roster.list_agents(session)
    row = next(a for a in listed if a.id == agent_id)
    assert CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"] not in row.opening_line


async def test_the_engine_config_path_speaks_the_sentence() -> None:
    """`posture_of` over `_load_agent` — the row the engine's `AgentConfig` is built from,
    and therefore what the caller actually hears."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        agent = await _load_agent(session, tenant_id, agent_id)
    posture = posture_of(agent)
    assert posture.caller_memory_enabled is True
    assert posture.caller_memory_notice_line == CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"]
    assert compose_opening_line(posture).endswith(CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"])


async def test_the_script_preview_speaks_the_sentence() -> None:
    """The builder's preview is what a client reads before publishing. An opening it shows
    that the engine will not speak — or one it hides that the engine will — is the defect
    the single composer exists to prevent."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        row = await script_builder._agent_or_404(session, agent_id)
    posture = script_builder._posture(row)
    assert compose_opening_line(posture).endswith(CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"])


async def test_flipping_a_d163_toggle_does_not_drop_the_memory_sentence() -> None:
    """THE REASON `set_disclosure_posture` SELECTS TWO COLUMNS IT CANNOT WRITE. It rebuilds
    the opening from the row it locked; a rebuild that forgot the memory sentence would
    republish an agent that still remembers callers and has stopped saying so — a silent
    withdrawal of a notice nobody asked to withdraw."""
    tenant_id, agent_id = await _tenant()
    await _remember(tenant_id, agent_id)
    result = await publishing.set_disclosure_posture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        ai_disclosure_enabled=False,
        recording_notice_enabled=None,
    )
    assert result.changed == ("ai_disclosure_enabled",)
    assert result.opening_line.endswith(CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"])
    assert not result.opening_line.startswith(CALLER_MEMORY_NOTICE_TEMPLATES["te-IN"]), (
        "the recording notice is still on, so the memory sentence cannot be first"
    )


# --- 3. the migration's copy of the sentences ----------------------------------------


def _migration_notices() -> dict[str, str]:
    """The migration's `_NOTICE`, read as SOURCE rather than imported.

    Importing it would execute a module whose whole point is to be frozen, and would also
    make this test pass by way of the same object it is supposed to be comparing against
    if the copy were ever replaced with an import. The AST is the honest reading.
    """
    tree = ast.parse(MIGRATION.read_text())
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
    the change and after it would open with different sentences in the same language."""
    assert _migration_notices() == CALLER_MEMORY_NOTICE_TEMPLATES


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
