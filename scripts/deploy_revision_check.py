"""Does THIS image's migration chain contain the revision the database is at?

One question, asked from inside the image being deployed, so that `scripts/vps-deploy.sh`
can tell a forward deploy from a rollback before it runs `alembic upgrade head`.

WHY IT EXISTS. The documented rollback is `vps-deploy.sh --checkout <previous-sha> --all`
(it was `git checkout` then `--all --no-pull` until D-291 gave the deploy workflow one
flag to reach), and `--all` puts the python services in the plan, which
means migrations run — `alembic upgrade head` from the OLDER image. If the deploy being
rolled back carried a migration, the database is now at a revision whose script does not
exist in that older image, and alembic resolves `alembic_version` against its script
directory before it computes any path:

    FAILED: Can't locate revision identified by '<rev>'        (exit 255)

Reproduced against the installed alembic, not inferred. So the rollback died before
swapping a single container, in exactly the incident it exists for, leaving production on
the broken release. This module is how that stopped being possible.

WHY EXIT CODES AND NOT A MESSAGE. The caller is bash, and the difference between "the
database is ahead of this artefact" and "the check itself failed" has to be unambiguous:
reading the first as the second aborts a rollback (the bug above), and reading the second
as the first would SKIP migrations on an ordinary deploy and swap new code onto an old
schema — the direction hard rule 8 does not protect. Matching on alembic's message text
would make that distinction depend on vendor wording, so the answer is a code:

    0  the revision is in this image's chain          → ordinary deploy, migrate
    3  the revision is NOT in this image's chain      → the DB is ahead; this is a rollback
    2  the question could not be answered at all      → fail loudly, migrate nothing

Anything else (an import error, an unreadable alembic.ini) surfaces as a non-zero code the
caller also treats as "could not answer". Every path is fail-safe towards `2`, because the
only unsafe outcome is a false `3`.

WHAT IT DOES NOT DO. It does not connect to a database — `ScriptDirectory` reads the
`alembic/versions` tree and nothing else, so this runs before, and independently of, any
connection the migrate step will make. It does not decide anything either: the decision to
skip is `run_migrations`', and it is printed rather than silent.

Run (normally through `vps-deploy.sh`, inside the image):

    uv run python -m scripts.deploy_revision_check <revision>
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: `alembic show <rev>` exits non-zero for both answers, so the caller cannot use it.
#: These are the caller's contract and `tests/deploy_rollback_test.py` pins them — along
#: with the `case` in `vps-deploy.sh` that reads them, because a contract with one end
#: tested is a contract.
PRESENT = 0
ABSENT = 3
UNANSWERABLE = 2


def revision_is_in_this_image(revision: str) -> int:
    """`PRESENT`/`ABSENT`, or `UNANSWERABLE` if alembic could not be asked."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.util.exc import CommandError
    except Exception as exc:  # pragma: no cover - alembic is a hard dependency of the image
        print(f"deploy_revision_check: cannot import alembic: {exc}", file=sys.stderr)
        return UNANSWERABLE

    try:
        script = ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini")))
    except Exception as exc:
        print(f"deploy_revision_check: cannot read the script directory: {exc}", file=sys.stderr)
        return UNANSWERABLE

    try:
        # `ScriptDirectory.get_revision` re-raises alembic's own ResolutionError as a
        # CommandError with a formatted message; that narrow catch is the whole test.
        # A broader `except Exception` here would turn a real defect into "rollback".
        script.get_revision(revision)
    except CommandError:
        return ABSENT
    except Exception as exc:
        print(
            f"deploy_revision_check: unexpected failure resolving {revision!r}: {exc}",
            file=sys.stderr,
        )
        return UNANSWERABLE
    return PRESENT


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        print(
            "usage: python -m scripts.deploy_revision_check <revision>\n"
            "Answers whether this image's alembic chain contains that revision.",
            file=sys.stderr,
        )
        return UNANSWERABLE
    return revision_is_in_this_image(args[0].strip())


if __name__ == "__main__":
    sys.exit(main())
