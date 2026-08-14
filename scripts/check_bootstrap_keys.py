"""Guardrail: the §4 bootstrap set may only ever be read from the ENVIRONMENT.

PLATFORM-CONFIG §4 names six keys that can never move into `platform_settings`, each
with the reason:

    APP_ENV               decides whether dev tokens are accepted (D-49) — reading it
                          from the DB means the DB decides the security posture
    DATABASE_URL          it is how you reach the store
    ALEMBIC_DATABASE_URL  migrations run before the store is guaranteed to exist
    PLATFORM_KEK          it is the key that opens the store
    PLATFORM_KEK_RETIRED  same
    REDIS_URL             needed by workers before settings resolve

§12 asks for this check in those words: "A future change that lets `APP_ENV` resolve
from the database must fail CI, loudly, because that is a security-posture inversion
that would look like a refactor." That last clause is the whole point. Every other guard
in this repo catches a rule being broken; this one catches a rule being broken by
something that reads like tidying up — deleting a name from a frozenset, or widening a
predicate that happens to be the only thing standing between a database row and the flag
that decides whether unauthenticated dev tokens are accepted.

FOUR CHECKS, because there are four ways the property can be lost and only the first is
obvious:

1. **The list still contains all six.** A name removed from `ENV_ONLY_KEYS` is the
   direct attack, and it is a one-line diff that no test would otherwise notice.
2. **Every name is a real `Settings` field.** A typo silently exempts nothing —
   `platform_kekk` in the list protects `platform_kek` not at all — so an entry that
   names no field is a hole with a comment on it.
3. **The filter is actually applied.** `apply_platform_overrides` is the ONE door
   through which a store value reaches a `Settings` object, and it has to consult the
   list. Asserted by BEHAVIOUR — the function is called with a bootstrap key and the
   value must not appear — rather than by reading the source, because a source scan
   passes on a filter that is present and inverted.
4. **The console never offers them.** `managed_fields()` and `manageable_secret_keys()`
   are what the write paths validate against, so a bootstrap key appearing in either
   would make the refusal reachable only by luck.

Run: `uv run python -m scripts.check_bootstrap_keys`   (also in `make guardrails`)
"""

from __future__ import annotations

import sys

from apps.api.core.platform_config import managed_fields
from apps.api.core.settings import (
    ENV_ONLY_KEYS,
    apply_platform_overrides,
    get_settings,
    platform_overrides,
)
from apps.api.ops.secret_service import manageable_secret_keys
from calevate_shared.config import Settings

#: §4's table, as `Settings` field names. Spelled HERE, independently of
#: `core/settings.ENV_ONLY_KEYS`, and that duplication is the entire mechanism: a
#: guardrail that imported the list it is checking would be asking the code whether it
#: agrees with itself. `scripts/pilot/gates_api.DOCUMENTED_EGRESS_IP` restates a constant
#: for the same reason and argues it in the same words.
BOOTSTRAP_KEYS: frozenset[str] = frozenset(
    {
        "app_env",
        "database_url",
        "alembic_database_url",
        "platform_kek",
        "platform_kek_retired",
        "redis_url",
    }
)


def check_list() -> list[str]:
    """1 and 2: the list is complete, and every entry names something real."""
    failures: list[str] = []
    missing = sorted(BOOTSTRAP_KEYS - ENV_ONLY_KEYS)
    if missing:
        failures.append(
            f"core/settings.ENV_ONLY_KEYS no longer protects {missing}. PLATFORM-CONFIG §4 "
            "says these can NEVER resolve from the database — removing one is a "
            "security-posture inversion, not a refactor. If §4 genuinely changed, change "
            "the spec and this file together, in a commit that says so."
        )
    for key in sorted(ENV_ONLY_KEYS):
        if key not in Settings.model_fields:
            failures.append(
                f"ENV_ONLY_KEYS names {key!r}, which is not a Settings field. A typo here "
                "protects nothing — the real field is still resolvable from the store."
            )
    return failures


def check_filter_applied() -> list[str]:
    """3: the ONE door refuses them, proved by pushing a value through it."""
    failures: list[str] = []
    before = dict(platform_overrides())
    try:
        for key in sorted(ENV_ONLY_KEYS):
            if key not in Settings.model_fields:
                continue  # already reported by check_list
            live = getattr(get_settings(), key)
            apply_platform_overrides({key: "store-supplied-value"})
            if getattr(get_settings(), key) != live:
                failures.append(
                    f"apply_platform_overrides accepted {key!r} from the store — the "
                    "database can now decide this value. See PLATFORM-CONFIG §4."
                )
            apply_platform_overrides({})
    finally:
        apply_platform_overrides(before)
    return failures


def check_not_offered() -> list[str]:
    """4: neither console surface lists them."""
    failures: list[str] = []
    for surface, keys in (
        ("platform_config.managed_fields()", set(managed_fields())),
        ("secret_service.manageable_secret_keys()", set(manageable_secret_keys())),
    ):
        offered = sorted(keys & ENV_ONLY_KEYS)
        if offered:
            failures.append(
                f"{surface} offers bootstrap keys {offered}. The write path refuses them, "
                "but a console that shows a field it can never store is the defect §8 "
                "names — and it means the refusal is reachable only by accident."
            )
    return failures


def main() -> int:
    failures = check_list() + check_filter_applied() + check_not_offered()
    if failures:
        print("BOOTSTRAP KEYS: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"BOOTSTRAP KEYS: OK ({len(BOOTSTRAP_KEYS)} keys env-only, filter applied at "
        "apply_platform_overrides, offered by neither console surface)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
