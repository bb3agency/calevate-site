"""A failed `upgrade head` must leave the revisions that already succeeded applied.

Three operator-facing documents state that property — `docs/DEPLOYMENT.md`,
`scripts/vps-deploy.sh`'s ON FAILURE banner, and `runbooks/deploy-failed.md`, which is the
file somebody opens at 3am with production half-deployed. It is true only because
`alembic/env.py` passes `transaction_per_migration=True`.

**Alembic's default is the opposite**, and the default is silent: with
`transaction_per_migration` unset, `context.begin_transaction()` opens ONE transaction for
the entire run under PostgreSQL's transactional DDL, so a failure at revision 40 discards
the 39 that had already applied. Nothing about that is visible from reading `env.py` — the
absence of a keyword argument is not something a reviewer notices — and the failure only
ever shows up during an incident, which is the worst possible moment to discover that the
runbook is describing a different database than the one in front of you.

So this file exists to make the absence loud. It asserts the CONFIGURATION rather than the
behaviour, deliberately: reproducing the behaviour would mean deliberately failing a real
migration against a real database mid-chain, which is slow, needs a disposable database,
and would leave the suite's own database in a state the next test has to clean up. The
configuration is the whole of the mechanism, it is one keyword, and pinning it costs
nothing.

WHAT THIS DOES NOT PROMISE, and the runbook now says so too: `CREATE INDEX CONCURRENTLY`
cannot run inside a transaction at all, so the three revisions using
`op.get_context().autocommit_block()` still have a real commit boundary that no setting can
wrap. A build interrupted there leaves an INVALID index — never used for reads, still
enforcing uniqueness on writes — and one of those indexes is on `credit_ledger` (hard rule
7). `runbooks/deploy-failed.md` carries the `pg_index WHERE NOT indisvalid` query for
exactly that residue.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PY = REPO_ROOT / "alembic" / "env.py"

#: The three files whose prose is true only while the setting above is. Named here so that
#: deleting the setting fails a test that can point at every document it falsifies, rather
#: than at one line of Python.
DOCUMENTS_RESTING_ON_IT = (
    "docs/DEPLOYMENT.md",
    "scripts/vps-deploy.sh",
    "runbooks/deploy-failed.md",
)


def _configure_calls() -> list[ast.Call]:
    """Every `context.configure(...)` in env.py — offline and online both."""
    tree = ast.parse(ENV_PY.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "configure"
    ]


def test_the_online_migration_runs_one_transaction_per_revision() -> None:
    """The online path is the one a deploy uses, and it must set the flag explicitly.

    Explicitly, not "truthily": `transaction_per_migration=True` written out, so a reader
    of `env.py` can see the property without knowing alembic's default. A setting that
    matters only when it is present is one that has to be readable where it is used.
    """
    calls = _configure_calls()
    assert calls, "alembic/env.py no longer calls context.configure at all"

    # The online configure is the one taking a live `connection`; the offline path renders
    # SQL and has no transaction to scope.
    online = [
        call for call in calls if any(keyword.arg == "connection" for keyword in call.keywords)
    ]
    assert len(online) == 1, f"expected exactly one online configure(), found {len(online)}"

    flag = next((kw for kw in online[0].keywords if kw.arg == "transaction_per_migration"), None)
    assert flag is not None, (
        "alembic/env.py's online context.configure() no longer passes "
        "`transaction_per_migration`. Alembic DEFAULTS IT TO FALSE, which means one "
        "transaction for the entire `upgrade head` run — so a failure at revision 40 "
        "discards the 39 revisions that already applied. That silently falsifies the "
        "failure model stated in: " + ", ".join(DOCUMENTS_RESTING_ON_IT)
    )
    assert isinstance(flag.value, ast.Constant) and flag.value.value is True, (
        "`transaction_per_migration` is set to something other than the literal True. "
        "Anything else here is a per-revision transaction boundary nobody can read off "
        "the line, on the property three runbooks describe."
    )


def test_every_document_that_rests_on_the_setting_still_names_it() -> None:
    """A guard whose subject has moved is worse than no guard.

    If somebody rewrites the failure model in these documents — say, because they decided
    the whole-run transaction was acceptable after all — this test should fail so the
    setting and the prose are revisited together, rather than the setting quietly
    outliving the sentences it was added for.
    """
    for relative in DOCUMENTS_RESTING_ON_IT:
        text = (REPO_ROOT / relative).read_text()
        assert "transaction_per_migration" in text, (
            f"{relative} states a per-revision migration failure model but no longer "
            "names `transaction_per_migration`, which is the only reason that model is "
            "true. Either cite it or correct the prose — do not leave a reader to assume "
            "alembic's default gives them this."
        )
