"""Negative controls for `scripts/check_subprocessor_coverage.py`.

The guard's claim is that a vendor wired into the code cannot go undisclosed. Since D-679
the disclosure has two halves — the internal named register
(`docs/legal/SUBPROCESSOR-REGISTER.md`) and the public category page
(`apps/web/src/lib/legal/subprocessors.ts`) — so the controls here are the doctored states
it must FAIL on in each half, the states it must not fail on, and the blind spot that
would make every other answer worthless. `evaluate` is pure, so all but the live ones need
nothing but synthetic inputs.

Run: uv run pytest tests/subprocessor_coverage_guard_test.py -q
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_subprocessor_coverage import (
    MIN_EXEMPTION_REASON,
    NOT_A_SUBPROCESSOR,
    PUBLIC_ANCHORS,
    REGISTER_ANCHORS,
    REGISTER_ONLY,
    SETTINGS_ANCHORS,
    VENDOR_OF,
    CodeVendors,
    PublicPage,
    RegisterRow,
    code_vendors,
    evaluate,
    public_page,
    register_rows,
    settings_fields,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _found(**tokens: str) -> CodeVendors:
    found = CodeVendors()
    for token, where in tokens.items():
        found.add(token, where)
    return found


def _row(identity: str, *categories: str, public: bool = False) -> RegisterRow:
    return RegisterRow(identity=identity, categories=frozenset(categories), named_publicly=public)


def _page(*categories: str, named: tuple[str, ...] = ()) -> PublicPage:
    return PublicPage(categories=frozenset(categories), named=frozenset(named))


_NO_EXEMPTIONS: dict[str, dict[str, str]] = {"not_a_subprocessor": {}, "register_only": {}}


class TestTheDirectionThatCostsAClientTheirDisclosure:
    def test_a_vendor_in_the_code_and_not_in_the_register_fails(self) -> None:
        """SUPERMEMORY'S SHAPE, in miniature — and since D-679 the one that matters most,
        because the register is private and nothing else would notice."""
        failures = evaluate(
            _found(supermemory="Settings.supermemory_api_key"),
            [],
            _page(),
            vendor_of={"supermemory": "Supermemory"},
            **_NO_EXEMPTIONS,
        )
        assert any(
            "Supermemory" in failure and "ABSENT from the" in failure for failure in failures
        )

    def test_a_credential_for_a_vendor_nobody_has_named_fails(self) -> None:
        failures = evaluate(
            _found(someco="Settings.someco_api_key"),
            [],
            _page(),
            vendor_of={},
            **_NO_EXEMPTIONS,
        )
        assert any(
            "someco" in failure and "nothing here knows who it is" in failure
            for failure in failures
        )

    def test_a_registered_vendor_in_a_published_category_passes(self) -> None:
        assert (
            evaluate(
                _found(supermemory="Settings.supermemory_api_key"),
                [_row("Supermemory", "knowledge-search")],
                _page("knowledge-search"),
                vendor_of={"supermemory": "Supermemory"},
                **_NO_EXEMPTIONS,
            )
            == []
        )

    def test_our_own_infrastructure_is_not_reported_as_a_vendor(self) -> None:
        reason = "OUR OWN public address, handed to a client's integration so it can call US back."
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert (
            evaluate(
                _found(webhook="Settings.webhook_base_url"),
                [],
                _page(),
                vendor_of={},
                not_a_subprocessor={"webhook": reason},
                register_only={},
            )
            == []
        )


class TestTheRegisterAndThePageAgree:
    """The halves D-679 split apart. A vendor filed under a category the page never
    publishes is undisclosed in the only place a client can read."""

    def test_a_category_the_page_does_not_publish_fails(self) -> None:
        failures = evaluate(
            _found(someco="Settings.someco_api_key"),
            [_row("SomeCo", "biometrics")],
            _page("telephony"),
            vendor_of={"someco": "SomeCo"},
            **_NO_EXEMPTIONS,
        )
        assert any("'biometrics'" in f and "does not publish" in f for f in failures)

    def test_a_published_category_with_no_vendor_fails(self) -> None:
        failures = evaluate(
            _found(someco="Settings.someco_api_key"),
            [_row("SomeCo", "telephony")],
            _page("telephony", "payments"),
            vendor_of={"someco": "SomeCo"},
            **_NO_EXEMPTIONS,
        )
        assert any(f.startswith("payments:") and "no vendor" in f for f in failures)

    def test_a_name_printed_without_the_register_marking_it_public_fails(self) -> None:
        failures = evaluate(
            _found(someco="Settings.someco_api_key"),
            [_row("SomeCo", "telephony")],
            _page("telephony", named=("SomeCo",)),
            vendor_of={"someco": "SomeCo"},
            **_NO_EXEMPTIONS,
        )
        assert any("SomeCo" in f and "not marked" in f for f in failures)

    def test_a_public_row_the_page_does_not_print_fails(self) -> None:
        failures = evaluate(
            _found(razorpay="Settings.razorpay_key_secret"),
            [_row("Razorpay", "payments", public=True)],
            _page("payments"),
            vendor_of={"razorpay": "Razorpay"},
            **_NO_EXEMPTIONS,
        )
        assert any("Razorpay" in f and "printed by no category" in f for f in failures)


class TestTheReverseDirection:
    def test_a_registered_vendor_with_nothing_behind_it_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            [_row("Bolna", "voice-platform"), _row("Clerk", "voice-platform")],
            _page("voice-platform"),
            vendor_of={"bolna": "Bolna"},
            **_NO_EXEMPTIONS,
        )
        assert any("Clerk" in f and "reachable from nothing" in f for f in failures)

    def test_a_registered_argument_for_one_passes(self) -> None:
        reason = "A contingency vendor kept as a declared alternative under the change clause."
        assert len(reason) >= MIN_EXEMPTION_REASON
        assert (
            evaluate(
                _found(bolna="Settings.bolna_api_key"),
                [_row("Bolna", "voice-platform"), _row("Cohere", "voice-platform")],
                _page("voice-platform"),
                vendor_of={"bolna": "Bolna"},
                not_a_subprocessor={},
                register_only={"Cohere": reason},
            )
            == []
        )

    def test_a_register_only_entry_for_a_vendor_that_is_in_the_code_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            [_row("Bolna", "voice-platform")],
            _page("voice-platform"),
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={"Bolna": "A reason somebody wrote while the adapter already existed."},
        )
        assert any("the scan found" in failure for failure in failures)

    def test_a_stale_register_only_entry_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            [_row("Bolna", "voice-platform")],
            _page("voice-platform"),
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
            [_row("Bolna", "voice-platform")],
            _page("voice-platform"),
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={"gone": "A setting that no longer exists on this class at all."},
            register_only={},
        )
        assert any("STALE NOT_A_SUBPROCESSOR" in failure for failure in failures)

    def test_a_thin_reason_fails(self) -> None:
        failures = evaluate(
            _found(bolna="Settings.bolna_api_key"),
            [_row("Bolna", "voice-platform"), _row("Cohere", "voice-platform")],
            _page("voice-platform"),
            vendor_of={"bolna": "Bolna"},
            not_a_subprocessor={},
            register_only={"Cohere": "n/a"},
        )
        assert any("too thin to review" in failure for failure in failures)


class TestItCanStillSeeItsOwnSubject:
    """All three sides are parsed out of files, and a parse that quietly stopped working
    answers "covered" for everything."""

    def test_the_settings_scan_finds_its_anchors(self) -> None:
        found = code_vendors()
        assert found.blind_spots == []
        assert set(found.tokens) >= SETTINGS_ANCHORS, sorted(SETTINGS_ANCHORS - set(found.tokens))

    def test_the_register_scan_finds_its_anchors(self) -> None:
        identities = {row.identity for row in register_rows()}
        assert identities >= REGISTER_ANCHORS, sorted(REGISTER_ANCHORS - identities)

    def test_the_public_page_scan_finds_its_anchors(self) -> None:
        page = public_page()
        assert page.categories >= PUBLIC_ANCHORS, sorted(PUBLIC_ANCHORS - page.categories)
        assert "Razorpay" in page.named

    def test_the_settings_class_still_parses(self) -> None:
        fields = settings_fields()
        assert len(fields) > 50, len(fields)
        assert "sarvam_api_key" in fields

    def test_a_longer_credential_suffix_wins(self) -> None:
        from scripts.check_subprocessor_coverage import _token_of

        assert _token_of("razorpay_key_secret") == "razorpay"
        assert _token_of("supermemory_api_key") == "supermemory"
        assert _token_of("release_version") is None


def test_the_live_tree_register_and_page_agree() -> None:
    """THE WHOLE CLAIM, against the real files rather than a synthetic state."""
    assert evaluate(code_vendors(), register_rows(), public_page()) == []


def test_the_white_label_vendors_are_registered_and_unnamed() -> None:
    """D-679's two halves, pinned on the live files: the telephony and voice vendors are in
    the internal register, and the register does not mark any of them printable."""
    rows = register_rows()
    for vendor in ("Vobiz", "ThinnestAI", "Pipecat Cloud", "Sarvam", "Cartesia", "Gnani"):
        mine = [row for row in rows if row.identity == vendor]
        assert mine, vendor
        assert not any(row.named_publicly for row in mine), vendor
    assert VENDOR_OF["supermemory"] == "Supermemory"
    assert (REPO_ROOT / "apps" / "api" / "retrieval" / "supermemory_index.py").exists()


def test_every_exemption_in_both_registers_reads_like_an_argument() -> None:
    for register in (NOT_A_SUBPROCESSOR, REGISTER_ONLY):
        for key, reason in register.items():
            assert len(reason.strip()) >= MIN_EXEMPTION_REASON, key
            assert reason.strip()[0].isupper() or reason.strip().startswith("OUR"), key
            assert reason.strip().endswith("."), key
