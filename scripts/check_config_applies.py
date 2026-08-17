"""Guardrail: every console-managed setting says when it takes effect, and is bounded.

`ConfigFieldOut.applies` is the most dangerous field the ops console publishes. A key
reported `live` that is really snapshotted at process start is a LIE THAT COSTS AN
OUTAGE: an operator changes it, sees no error, believes it took, and the platform keeps
the old value until something unrelated restarts. PLATFORM-CONFIG §8's rule — "a field
that silently does nothing is worse than no field" — applies with more force to a field
that silently does nothing for six hours.

The classification cannot be derived from a type: it is a fact about WHERE a value is
read. So it is enumerated in `core/platform_config.FIELD_APPLIES`, and this file is what
stops the enumeration rotting. The managed set is COMPUTED from the `Settings` model
(D-96), which means a field added tomorrow is managed the day it is added — and would
arrive with no classification at all. `describe()` fails safe (an unclassified field is
reported `unclassified` and NOT editable), so the console never lies; this guard is what
turns that safe silence into a CI failure somebody has to answer.

FIVE CHECKS. The first is the one that makes the other four mean anything, and it was
added by D-176's audit of this repo's own guardrails:

0. **The managed set is not empty.** Every check below iterates `classified_keys()`, so
   an empty managed set is four `[]`s and a green run reading `0 settings classified`.
   `managed_fields()` is computed from `Settings` BY EXCLUSION, which is the kind of
   derivation that empties itself without anybody editing a list.

And then the four, each catching a different way the promise breaks:

1. **Every managed key is classified.** The one that fires on the day somebody adds a
   `Settings` field, which is the only day it can be fixed cheaply.
2. **No entry names a key that is no longer managed.** A stale entry is a hole waiting
   for the next field to land on that name — `check_wiring.stale_baseline` catches the
   same rot for the same reason.
3. **Every entry carries a reason, and `live` carries none.** A classification an
   operator cannot act on is a label; the reason is the part they read at 3am. `live`
   is the exception on purpose: there is nothing left to say, and a caveat beside a
   field that just works trains people to ignore caveats.
4. **Every managed field is BOUNDED.** Type-valid and catastrophic are not exclusive: a
   pool size of 500, an FX rate of 0, an SMTP port of 0 and a 4MB string all pass their
   types and all break something. A numeric field needs a ceiling AND a floor, a string
   needs a maximum length; enums and booleans are bounded by their types. This is the
   half that CAN be derived, so it is, from the field's own JSON schema — no list to
   keep, and a new field is checked without anybody remembering this file exists.

Run: `uv run python -m scripts.check_config_applies`   (also in `make guardrails`)
"""

from __future__ import annotations

import sys
from typing import Any

from apps.api.core.platform_config import (
    APPLIES_VALUES,
    FIELD_APPLIES,
    LIVE,
    UNCLASSIFIED,
    managed_fields,
)
from apps.api.ops.secret_service import manageable_secret_keys
from calevate_shared.config import Settings
from pydantic import TypeAdapter

#: Keys whose bound is CARRIED BY THE TYPE rather than by a `Field(...)` constraint.
#: An enum admits its members and nothing else; a boolean admits two values. Listing
#: them by JSON type rather than by name means a new enum field is exempt automatically
#: and a new string field is not.
_SELF_BOUNDING_TYPES: frozenset[str] = frozenset({"boolean", "null"})


def _schema(field: str) -> dict[str, Any]:
    """The non-null branch of a field's validation schema.

    Validation mode, not serialization: the bounds this checks are what the WRITE path
    enforces, and `TypeAdapter.validate_python` is what enforces them.
    """
    adapter = TypeAdapter(Settings.model_fields[field].rebuild_annotation())
    schema = adapter.json_schema(mode="validation")
    variants = [v for v in schema.get("anyOf", [schema]) if v.get("type") != "null"]
    return variants[0] if variants else schema


def _unbounded_reason(field: str) -> str | None:
    """Why this field's value is not bounded, or `None` if it is."""
    schema = _schema(field)
    if "enum" in schema or "const" in schema:
        return None
    kind = str(schema.get("type", ""))
    if kind in _SELF_BOUNDING_TYPES:
        return None
    if kind in {"integer", "number"}:
        has_floor = {"minimum", "exclusiveMinimum"} & schema.keys()
        has_ceiling = {"maximum", "exclusiveMaximum"} & schema.keys()
        if has_floor and has_ceiling:
            return None
        missing = " and ".join(
            part
            for part, present in (("a floor", has_floor), ("a ceiling", has_ceiling))
            if not present
        )
        return f"numeric with no bound — it needs {missing} (Field(ge=…, le=…))"
    if kind == "string":
        # A `Decimal` VALIDATES as `type: number` (it serializes as a string, which is
        # hard rule 7's business and not this one's), so the numeric branch above is
        # what runs for money. A string here is a real string, and an unbounded one can
        # carry megabytes into a jsonb column that every process re-reads on every
        # version bump.
        if "maxLength" in schema:
            return None
        return "a string with no maxLength — one value would be replicated to every process"
    # FAIL CLOSED on a shape this guard does not recognise. A field whose type it cannot
    # read is a field whose bounds it cannot verify, and "I could not check" must not be
    # reported as "checked and fine" — that is how a guardrail becomes decoration.
    return f"of a shape this guard cannot bound-check ({schema!r}); teach it, or bound the field"


def classified_keys() -> tuple[str, ...]:
    """Every key that must carry a classification: plain config AND credentials.

    BOTH SURFACES, ONE TABLE. The Secrets panel makes the same implicit promise the
    config panel does — set it and it is in force in seconds — and for `bolna_api_key`
    that promise was false: the adapter captures the key when `get_engine()` builds it
    and the instance is cached for the life of the process. A rotation that does not
    reach the code placing calls presents as the VENDOR rejecting us, which sends an
    operator to the wrong system entirely. One question, one vocabulary, one table.
    """
    return (*managed_fields(), *manageable_secret_keys())


def blind_spots() -> list[str]:
    """Has the tree moved out from under this check? (D-176)

    All four checks below iterate `classified_keys()`, and three of the four iterate it
    directly — so an empty managed set makes every one of them return `[]` and this file
    print `CONFIG APPLIES: OK (0 settings + 0 credentials classified)`. That is not a
    far-fetched shape: `managed_fields()` is COMPUTED from `Settings` by exclusion (D-96),
    so a widened exclusion rule empties it silently, and emptying it is exactly what a
    change that stopped the console managing anything would do.

    The floors are the counts the tree carries today, an order of magnitude below them:
    the question being asked is "is this registry still populated", not "has anybody added
    a field", so a floor that tracked the real number would fail on every deletion.
    """
    failures: list[str] = []
    settings = managed_fields()
    secrets = manageable_secret_keys()
    if len(settings) < 5:
        failures.append(
            f"`managed_fields()` returned {len(settings)} console-managed setting(s). It is "
            "derived from Settings by exclusion, so a widened exclusion empties it without "
            "any list being edited — and every check below then iterates nothing and passes."
        )
    if len(secrets) < 3:
        failures.append(
            f"`manageable_secret_keys()` returned {len(secrets)} credential(s), so the "
            "Secrets panel's half of this rule is being verified against an empty set."
        )
    if not FIELD_APPLIES:
        failures.append(
            "FIELD_APPLIES is empty — there is no classification table left to check, and "
            "`describe()` would report every field `unclassified` and uneditable."
        )
    return failures


def check_every_key_is_classified() -> list[str]:
    failures: list[str] = []
    for key in classified_keys():
        rule = FIELD_APPLIES.get(key)
        if rule is None:
            failures.append(
                f"{key!r} is managed by the ops console and has no FIELD_APPLIES entry, so "
                "the console cannot say whether changing it does anything. It is being "
                "served as `unclassified` and is NOT editable — which is the safe answer "
                "and not an acceptable one. Classify it in core/platform_config.py: `live` "
                "if it is read through get_settings() at the point of use, `on_restart` if "
                "it is consumed once at boot, `needs_republish` if existing artefacts carry "
                "the old value, `env_only` if the store can never deliver it."
            )
            continue
        if rule.applies not in APPLIES_VALUES or rule.applies == UNCLASSIFIED:
            failures.append(
                f"{key!r} is classified {rule.applies!r}, which is not one of "
                f"{sorted(APPLIES_VALUES - {UNCLASSIFIED})}."
            )
    return failures


def check_no_stale_entries() -> list[str]:
    managed = set(classified_keys())
    return [
        f"FIELD_APPLIES has an entry for {key!r}, which is no longer a managed setting or "
        "credential. A "
        "stale entry is a hole waiting for the next field that lands on that name — remove "
        "it, or restore the field."
        for key in sorted(set(FIELD_APPLIES) - managed)
    ]


def check_reasons() -> list[str]:
    failures: list[str] = []
    for key, rule in sorted(FIELD_APPLIES.items()):
        if rule.applies == LIVE:
            if rule.caveat is not None and not rule.caveat.strip():
                failures.append(f"{key!r} is `live` with an empty caveat — use None.")
            continue
        if not (rule.caveat or "").strip():
            failures.append(
                f"{key!r} is classified {rule.applies!r} with no reason. The classification "
                "is what the console renders beside the field; without the sentence an "
                "operator is told their change may not have taken effect and not why."
            )
    return failures


def check_bounds() -> list[str]:
    failures: list[str] = []
    for key in managed_fields():
        reason = _unbounded_reason(key)
        if reason is not None:
            failures.append(
                f"{key!r} is settable from the ops console and is {reason}. A value can be "
                "type-valid and catastrophic; the bound belongs on the field in "
                "packages/shared/src/calevate_shared/config.py, where the write path, the "
                "boot-time load and the console all read it from one place."
            )
    return failures


def main() -> int:
    failures = (
        blind_spots()
        + check_every_key_is_classified()
        + check_no_stale_entries()
        + check_reasons()
        + check_bounds()
    )
    if failures:
        print("CONFIG APPLIES: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    counts: dict[str, int] = {}
    for rule in FIELD_APPLIES.values():
        counts[rule.applies] = counts.get(rule.applies, 0) + 1
    summary = ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
    print(
        f"CONFIG APPLIES: OK ({len(managed_fields())} settings + "
        f"{len(manageable_secret_keys())} credentials classified — {summary}; "
        "every setting bounded)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
