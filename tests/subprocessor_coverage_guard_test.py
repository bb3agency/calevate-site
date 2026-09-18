"""Negative controls for `scripts/check_subprocessor_coverage.py`.

The guard's claim is that it would have caught Supermemory — two complete adapters whose
settings the ops console can change at runtime, receiving every published knowledge
passage the moment an operator selects them, and named nowhere on the page that tells a
client where their data goes. `apps/web/tests/legal.test.tsx` could not: it checks the
register against itself and against the DPA, so a vendor absent from both is consistent.

So the controls here are the doctored states it must FAIL on, the states it must not fail
on, and the blind spot that would make every other answer worthless. `evaluate` is pure,
so all but the live ones need nothing but synthetic inputs.

Run: uv run pytest tests/subprocessor_coverage_guard_test.py -q
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_subprocessor_coverage import (
    MIN_EXEMPTION_REASON,
    NOT_A_SUBPROCESSOR,
    REGISTER_ANCHORS,
    REGISTER_ONLY,
    SETTINGS_ANCHORS,
    VENDOR_OF,
    CodeVendors,
    code_vendors,
    evaluate,
    register_identities,
    settings_fields,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _found(**tokens: str) -> CodeVendors:
    found = CodeVendors()
    for token, where in tokens.items():
        found.add(token, where)
    return found


class TestTheDirectionThatCostsAClientTheirDisclosure:
    def test_a_vendor_in_the_code_and_not_on_the_register_fails(self) -> None:
        """SUPERMEMORY'S SHAPE, in miniature: a mapped vendor with a credential in
        `Settings` and no row on the published page."""
        failures = evaluate(
            _found(supermemory="Settings.supermemory_api_key"),
            published={"Bolna"},
            vendor_of={"supermemory": "Supermemory", "bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={
                "Bolna": "Anchor identity for this synthetic register, kept deliberately."
            },
        )
        assert any(
            "Supermemory" in failure and "ABSENT from the" in failure for failure in failures
        )

    def test_a_credential_for_a_vendor_nobody_has_named_fails(self) -> None:
        """The case that matters MOST, because it is the one a new integration produces:
        a key lands for a company this file has never heard of. Skipping it would make the
        guard silently narrower with every vendor added."""
        failures = evaluate(
            _found(someco="Settings.someco_api_key"),
            published=set(),
            vendor_of={},
            not_a_subprocessor={},
            register_only={},
        )
        assert any(
            "someco" in failure and "nothing here knows who it is" in failure
            for failure in failures
        )

    def test_a_vendor_on_the_register_passes(self) -> None:
        assert (
            evaluate(
                _found(supermemory="Settings.supermemory_api_key"),
                published={"Supermemory"},
                vendor_of={"supermemory": "Supermemory"},
                not_a_subprocessor={},
                register_only={},
            )
            == []
        )

    def test_our_own_infrastructure_is_not_reported_as_a_vendor(self) -> None:
        """A guard that calls our own callback address an undisclosed sub-processor is one
        whose findings get skimmed, which is how the real one gets missed."""
        reason = "OUR OWN public address, handed to a client's integration so it can call US back."
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert (
            evaluate(
                _found(webhook="Settings.webhook_base_url"),
                published=set(),
                vendor_of={},
                not_a_subprocessor={"webhook": reason},
                register_only={},
            )
            == []
        )


class TestTheReverseDirection:
    """A vendor that left the code and stayed on the page — the drift the register's own
    header records for Clerk (removed at D-177) and Vertex (replaced at D-449), both of
    which survived in client-facing copy after they left."""

    def test_a_published_vendor_with_nothing_behind_it_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            published={"Bolna", "Clerk"},
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={},
        )
        assert any(
            "Clerk" in failure and "reachable from nothing" in failure for failure in failures
        )

    def test_a_registered_argument_for_one_passes(self) -> None:
        reason = "A contingency vendor kept as a declared alternative under the change clause."
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert (
            evaluate(
                _found(bolna="Settings.bolna_api_key"),
                published={"Bolna", "Cohere"},
                vendor_of={"bolna": "Bolna"},
                not_a_subprocessor={},
                register_only={"Cohere": reason},
            )
            == []
        )

    def test_a_register_only_entry_for_a_vendor_that_is_in_the_code_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            published={"Bolna"},
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={"Bolna": "A reason somebody wrote while the adapter already existed."},
        )
        assert any("the scan found" in failure for failure in failures)

    def test_a_stale_register_only_entry_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            published={"Bolna"},
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={
                "Departed": "A vendor whose row was taken off the register some time ago."
            },
        )
        assert any("STALE REGISTER_ONLY" in failure for failure in failures)

    def test_a_stale_internal_entry_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            published={"Bolna"},
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={"gone": "A setting that no longer exists on this class at all."},
            register_only={},
        )
        assert any("STALE NOT_A_SUBPROCESSOR" in failure for failure in failures)

    def test_a_thin_reason_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            published={"Bolna", "Cohere"},
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={"Cohere": "n/a"},
        )
        assert any("too thin to review" in failure for failure in failures)


class TestItCanStillSeeItsOwnSubject:
    """Both sides of this comparison are parsed out of files, and a parse that quietly
    stopped working answers "covered" for everything."""

    def test_the_settings_scan_finds_its_anchors(self) -> None:
        found = code_vendors()
        assert found.blind_spots == []
        assert set(found.tokens) >= SETTINGS_ANCHORS, sorted(SETTINGS_ANCHORS - set(found.tokens))

    def test_the_register_scan_finds_its_anchors(self) -> None:
        published = register_identities()
        assert published >= REGISTER_ANCHORS, sorted(REGISTER_ANCHORS - published)

    def test_the_settings_class_still_parses(self) -> None:
        fields = settings_fields()
        assert len(fields) > 50, len(fields)
        assert "sarvam_api_key" in fields

    def test_a_longer_credential_suffix_wins(self) -> None:
        """`razorpay_key_secret` ends in both `_key_secret` and `_secret`. Stripping the
        shorter one yields the token `razorpay_key`, which maps to nothing and would be
        reported as an undisclosed company called "razorpay key" — a false finding, which
        trains people to add exemptions."""
        from scripts.check_subprocessor_coverage import _token_of

        assert _token_of("razorpay_key_secret") == "razorpay"
        assert _token_of("supermemory_api_key") == "supermemory"
        assert _token_of("release_version") is None


def test_the_live_tree_and_the_live_register_agree() -> None:
    """THE WHOLE CLAIM, against the real files rather than a synthetic state."""
    assert evaluate(code_vendors(), register_identities()) == []


def test_supermemory_is_on_the_register_and_this_is_why_the_guard_exists() -> None:
    """The finding that produced this file, pinned so a revert is visible.

    Two adapters (`apps/api/retrieval/supermemory.py` reads, `supermemory_index.py`
    writes) and four `LIVE` platform settings, so an operator selects it from the ops
    console and the NEXT request is served from it — at which point it holds the client's
    published knowledge. It was on no legal page at all.
    """
    assert "Supermemory" in register_identities()
    assert VENDOR_OF["supermemory"] == "Supermemory"
    assert (REPO_ROOT / "apps" / "api" / "retrieval" / "supermemory_index.py").exists()


def test_every_exemption_in_both_registers_reads_like_an_argument() -> None:
    for register in (NOT_A_SUBPROCESSOR, REGISTER_ONLY):
        for key, reason in register.items():
            assert len(reason.strip()) >= MIN_EXEMPTION_REASON, key
            assert reason.strip()[0].isupper() or reason.strip().startswith("OUR"), key
            assert reason.strip().endswith("."), key
