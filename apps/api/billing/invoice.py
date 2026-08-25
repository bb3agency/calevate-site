"""Invoice generation (ROADMAP M2).

An invoice here is a STRUCTURED STATEMENT derived from the usage ledger — the JSON a
future PDF/UI renders, not the PDF itself. It is built on top of `usage_summary`
(never a parallel query set), so the invoice can never disagree with the usage panel
the client already saw: one computation, two presentations.

Money is NUMERIC/Decimal INR end to end (hard rule 7); every money field is rounded by
``service.to_paise`` — one function, one explicit mode (half-up) — because two decimals
is what a rupee amount means to the person reading the invoice, and which way ₹18.045
goes is a decision, not a default.

Two arithmetic promises the client can check by hand:

- every line multiplies out (``qty * unit_inr`` rounds to ``amount_inr``), which is why
  the overage RATE is published at its true precision rather than rounded like a rupee
  amount — see ``service.rate_to_display``;
- ``subtotal`` is the sum of the line amounts and nothing else, GST is applied at
  exactly one place, and ``total = subtotal + gst``. No ₹0.01 appears from anywhere.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.kyc import read_kyc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings

from .charges import one_time_charge_lines
from .gst import Gstin, parse_gstin, resolve_place_of_supply, split_tax, supplier_identity
from .service import overage_rungs, to_paise, usage_summary

# 18% GST on SaaS/telecom services. A constant (greppable by name) until pricing config
# ships. WHICH HEADS it lands under is no longer "an invoicing detail the accountant
# owns", which is what this comment used to say and what left the document invalid:
# Rule 46(l)-(m) requires the tax to appear separately as central / State / integrated /
# Union territory tax, and a recipient credits those to three different ledgers. The
# split is derived in `billing/gst.py` from the place of supply; only the total rate
# lives here.
#
# **THE RATE, RE-VERIFIED Aug 2026 — REPORTED, NOT READ** (`billing/payments.py`'s three-
# rung evidence ladder). cbic-gst.gov.in is not reachable from this network, so this is
# not a first-party read. Four independent secondaries agree that a cloud-delivered
# software service supplied in India is taxed at **18%**, classified under **SAC 998315**
# (hosting / IT infrastructure provisioning) — the same 18% that covers B2B telecom and
# most business support services. That single figure is what makes the CGST/SGST split
# 9+9 in `gst.split_tax`. It is spelled ONCE, here: no doc in this repo states a GST
# percentage as a value-claim, so there is no second home for it to drift from — and if
# one is ever written, it belongs in `scripts/check_docs_drift.py` beside §4b's rate-card
# diff rather than in prose.
#
# NOT a config key, deliberately. A statutory rate is not a deployment's choice, and an
# operator able to type one into the ops console is an operator able to under-collect tax
# on every invoice the platform issues (CGST s.32 runs the other way, but the exposure is
# the same shape). It moves when the Council moves it, in a diff with a citation.
GST_RATE_PCT = Decimal("18")

# The statement that makes an unregistered supplier's document a compliant BILL OF SUPPLY
# rather than a tax invoice missing its tax. CGST s.32 forbids an unregistered person from
# collecting tax and CGST Rule 49 governs the bill of supply an unregistered (or
# exempt-only) supplier issues instead — no tax component, and no input tax credit for the
# recipient (LEGAL-OPS-PLAYBOOK §4.4). Stated in words on the document's face because "no
# CGST/SGST line" is the absence of something, and a reader needs the presence of a
# sentence telling them the absence is deliberate and lawful, not an omission.
BILL_OF_SUPPLY_TAX_NOTE = (
    "Bill of supply. Calevate is not registered for GST, so no tax is charged on this "
    "document and no input tax credit is available (CGST Act s.32; CGST Rules r.49)."
)

# THE TAX ON THIS DOCUMENT IS STATED IN PAISE, AND CGST s.170 SAYS IT IS ROUNDED TO THE
# NEAREST RUPEE. That is an OPEN finding (D-256), recorded here beside the rate rather
# than acted on, for the same reason the Rule 46(b) serial below is.
#
# **REPORTED, NOT READ** (`billing/payments.py`'s three-rung evidence ladder;
# cbic-gst.gov.in is not reachable from this network). Several independent secondaries
# quote s.170 identically — *"the amount of tax, interest, penalty, fine or any other sum
# payable, and the amount of refund or any other sum due ... shall be rounded off to the
# nearest rupee"*, fifty paise or more rounding up — and they agree it is applied per
# INVOICE and per HEAD (CGST, SGST/UTGST, IGST each), not on a consolidated total.
#
# What that would change here, on the worked example in `docs/evidence/deepdive-money2.md`:
#
#     stated today   gst_inr 3614.52   CGST 1807.26 + SGST 1807.26
#     under s.170    gst_inr 3614.00   CGST 1807.00 + SGST 1807.00, and a ROUND OFF line
#                                      of -0.52 so `subtotal + tax + round_off = total`
#                                      still adds up in a client's hand
#
# **WHY IT IS NOT IMPLEMENTED.** It moves money on every invoice the platform would ever
# issue, and no secondary settles first-party whether s.170 binds the DOCUMENT or the
# RETURN, nor whether the taxable value rounds along with the tax. Guessing a compliance
# rule is not recoverable (CLAUDE.md), and nothing is out of compliance today:
# `supplier.is_registered` is false in every deployment and this document says `proforma`.
# **WHAT CLOSES IT:** the GST registration (ROADMAP M0) plus a first-party read or an
# accountant's confirmation of the per-invoice, per-head reading.

# THE INVOICE NUMBER'S LENGTH IS NOW RULE 46(b)-COMPLIANT; its CONSECUTIVENESS is not, and
# this note is the honest account of which half is fixed and which is blocked.
#
# **THE RULE, RE-VERIFIED Aug 2026 — REPORTED, NOT READ** (`billing/payments.py`'s three-
# rung evidence ladder). taxinformation.cbic.gov.in is not reachable from this network, so
# this is not a first-party read; five independent secondaries quote clause (b) of Rule 46
# of the CGST Rules 2017 identically, and in these words:
#
#     "a consecutive serial number, not exceeding sixteen characters, in one or multiple
#      series, containing alphabets or numerals or special characters - hyphen or dash and
#      slash symbolised as '-' and '/' respectively, and any combination thereof, unique
#      for a financial year"
#
# Measured against the number this module now emits, `CAL2608<9-char base36>` (16 chars):
#
#   length        exactly sixteen characters, asserted at the build site           ok
#                 (was nineteen; this slice shortened it — base-36 keeps the
#                 suffix's ~46.6 bits inside the ceiling)
#   consecutive   a per-tenant-month digest; no series, no successor               FAILS
#   unique per FY holds NOW — see `_tenant_serial_suffix`, which is where it       ok
#                 did not, until this reading actually tested it
#   charset       alphanumerics only, all permitted                               ok
#
# **WHAT THE VERIFICATION CHANGED: "in one or multiple series" is in the rule itself.** A
# registered person may run several series (per unit, division or billing type) as long as
# each is consecutive and the whole set is unique for the financial year, and mid-year
# introduction of a new distinct series is permitted. That is the clause the earlier
# reading of this comment did not have, and it is what makes a compliant scheme designable
# rather than merely desirable. It does NOT make a per-RECIPIENT series obviously lawful —
# the permitted axis is the supplier's own units and billing types, not their customers —
# so the design below uses ONE series and does not lean on the concession.
#
# --------------------------------------------------------------------------------
# WHY THE CONSECUTIVE HALF IS STILL NOT FIXED HERE, and what would fix it
# --------------------------------------------------------------------------------
#
# The LENGTH half is fixed in `build_invoice`: the serial is now sixteen characters and the
# build site asserts it. What remains is the CONSECUTIVE-series requirement, below.
#
# **The blocking half is external and is not ours to code around.** Rule 46 binds a
# REGISTERED PERSON issuing a tax invoice. There is no legal entity and no GST registration
# (ROADMAP M0), `supplier.is_registered` is false in every deployment, and this document
# therefore says `proforma` (a bill of supply — see `BILL_OF_SUPPLY_TAX_NOTE`) — which
# 46(b) does not govern. Nothing is out of compliance today; what exists is a scheme whose
# CONSECUTIVENESS would still need building the moment the four `GST_SUPPLIER_*` values are
# set. The named external blocker is the GST registration itself.
#
# **The engineering half is designed, not written, because writing it decides something
# only the founder can decide: it contradicts D-46.** A consecutive series is a STATEFUL
# fact — "the 123rd invoice of this financial year" cannot be recomputed from the ledgers,
# only remembered — so the number has to be MINTED and STORED at an issuance event, and
# `build_invoice` cannot be that event. It is a pure read behind a GET and must stay one
# (D-64: rendering an invoice used to write, and `tests/invoice_gst_test.py::
# test_the_client_read_writes_nothing` pins that it no longer does). So the shape is a
# separate `issue_invoice` act, with `build_invoice` becoming the PREVIEW of an unissued
# month and the reader of a serial once one exists.
#
# The rest is settled engineering, recorded here so the decision arrives with its design:
#
# - **The format: `CAL/26-27/000123` — exactly sixteen characters.** Three for the series
#   prefix, the financial year in the conventional `26-27` notation, and a six-digit
#   counter (999,999 documents per year). Slash and hyphen are both permitted characters.
#
# - **NOT a Postgres sequence, and this is the one place the obvious tool is wrong.**
#   `nextval` is deliberately non-transactional: a rolled-back issuance consumes a number
#   permanently, so the series grows GAPS. A gap in a tax-invoice series is a question the
#   department asks and somebody has to answer, and it is not one an unused number
#   answers well. A sequence also has no financial-year story — resetting it means an
#   `ALTER SEQUENCE ... RESTART` at midnight on 1 April, a scheduled DDL whose failure is
#   silent and whose double-run is worse.
#
# - **An `issued_invoices` table with the counter IN the key, allocated under the house
#   advisory-lock idiom.** `UNIQUE (financial_year, serial_no)` is the constraint;
#   `pg_advisory_xact_lock` on the financial year is the serialization, exactly as
#   `lock_tenant_credits` and `lock_call_writes` do it, with the unique index as the
#   backstop the way `ux_usage_events_tenant_call_unit` is for metering. Allocation is
#   `COALESCE(MAX(serial_no), 0) + 1` inside the lock, in the SAME transaction as the
#   issuance — which is what makes it gapless where a sequence cannot be: a rollback
#   un-allocates the number.
#
# - **The financial-year boundary needs no cron and no reset.** The year is part of the
#   key, so `MAX(serial_no)` over a year with no rows is `0` and the first document of
#   1 April is `000001` by construction. The year must be derived on the IST calendar
#   (the Indian FY runs 1 April to 31 March, and the repo already computes an IST month in
#   `billing.service._IST_MONTH`): a UTC boundary would file every document issued between
#   00:00 and 05:30 IST on 1 April into the year that closed.
#
# --------------------------------------------------------------------------------
# THE CORRECTION PATH, WHICH IS THE HALF THIS BLOCK USED TO OMIT (re-verified Aug 2026)
# --------------------------------------------------------------------------------
#
# A DERIVED statement corrects itself by being re-rendered. An ISSUED tax invoice may not:
# once a document has gone to a registered recipient, the lawful correction is a CREDIT
# NOTE under **s.34, CGST Act**, referencing the original invoice — not a quiet re-render
# under the same number. That is a direct tension with D-46's "recompute, never store",
# and it is the reason the registry above cannot be designed for invoices alone.
#
# Three findings from the same reading, all **REPORTED, NOT READ** (the three-rung ladder
# in `billing/payments.py`; `taxinformation.cbic.gov.in` and `cleartax.in` are both
# refused by this environment's egress proxy, so no first-party fetch was made — the
# claims below are ones several independent secondaries state identically):
#
# - **Rule 53 puts the SAME serial rule on the correction.** A credit or debit note under
#   s.34, and a revised tax invoice, each need "a consecutive serial number not exceeding
#   sixteen characters, in one or multiple series ... unique for a financial year" — the
#   words of 46(b), repeated. So `issued_invoices` is misnamed as designed: the registry
#   has to allocate for notes as well, either in the one series or in a second declared
#   one, and `UNIQUE (financial_year, series, serial_no)` is the key that admits both.
# - **A credit note has a DEADLINE, and it is not the invoice's.** Its GST effect requires
#   the note to be declared in a return by 30 November following the financial year of the
#   supply, or the annual return for that year, whichever is earlier. A statement that can
#   be re-rendered for ever has no such horizon, so the horizon has to be modelled rather
#   than inherited: after it passes, a month is corrected commercially and not fiscally.
# - **From 1 October 2025 the supplier cannot reduce output tax on a credit note unless
#   the recipient has reversed the matching input credit** (Finance Act 2025). That is a
#   fact about the RECIPIENT, which this system does not hold and cannot derive — so an
#   automatic credit note is not a thing this product can issue unattended.
#
# One more that bears on WHEN, not on numbering: **Rule 47** gives thirty days from the
# supply of a taxable service to issue the invoice, while **s.31(5)** governs a continuous
# supply of services — which is exactly what a monthly retainer is — and ties the invoice
# to the due date of payment in the contract. Nothing here schedules an issuance today,
# because nothing here issues; when `issue_invoice` lands it inherits that clock.
#
# WHAT THE FOUNDER MUST DECIDE, precisely: whether an `issued_invoices` registry — a stored
# invoice serial, minted once, never recomputed, and covering credit notes as well as
# invoices — is accepted against D-46's "recompute, never store". Everything above follows
# from a yes; nothing above is safe to build on a no.
#
# `tests/invoice_gst_test.py` now pins the LENGTH as fixed (the serial is sixteen
# characters and unique per tenant-month) and pins the CONSECUTIVE half as still open — a
# hash-suffixed number is not a successor series, and the test that asserts so stays red
# against any claim of full 46(b) compliance until the `issue_invoice` registry lands.
RULE_46B_MAX_SERIAL_CHARS = 16


#: Base-36 characters of digest in the invoice serial's tenant suffix. Nine base-36
#: characters carry ~46.6 bits (36**9 ≈ 1.0e14), essentially the 48 bits the twelve-hex
#: suffix carried before Rule 46(b)'s sixteen-character ceiling forced the number to
#: shrink — base-36 (alphanumerics, a charset Rule 46(b) permits) packs ~5.17 bits per
#: character against hex's 4, so the ceiling costs almost none of the collision resistance.
#: Still NOT a uniqueness GUARANTEE — only the issued-invoice registry described above is
#: that — but a stated bound rather than a property that happened to hold in one fixture.
_TENANT_SUFFIX_B36 = 9

#: Rule 46(b) permits alphabets and numerals; lower-case base-36 stays inside that and
#: reads as an ordinary id. Fixed alphabet so the encoding is stable across Python builds.
_B36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(value: int, *, width: int) -> str:
    """`value` (mod 36**width) as exactly `width` lower-case base-36 characters.

    Fixed width so the suffix length — and therefore the serial length — is constant, which
    is what lets the Rule 46(b) sixteen-character ceiling be an assertion rather than a hope.
    """
    digits: list[str] = []
    for _ in range(width):
        value, remainder = divmod(value, 36)
        digits.append(_B36_ALPHABET[remainder])
    return "".join(reversed(digits))


def _tenant_serial_suffix(tenant_id: UUID) -> str:
    """The tenant's stable, collision-resistant slice of the invoice number.

    **THIS WAS `tenant_id.hex[:8]`, AND THAT WAS NOT UNIQUE — it was not even close.**
    Tenant ids are uuid7 (`db/base.uuid7`), whose FIRST 48 bits are the Unix timestamp in
    milliseconds. `hex[:8]` is the top 32 of those 48, i.e. `ms >> 16`, which advances
    once every 65.5 seconds. So **any two organizations created in the same ~65-second
    window carried the same invoice number, forever, in every month.** Not a
    birthday-bound risk: a deterministic collision, and onboarding two clients in one
    sitting is the ordinary case rather than the unlucky one. It reproduced on the first
    two tenants a test created back to back.
    (`tests/invoice_gst_test.py::test_two_tenants_billed_in_one_month_get_different_
    invoice_numbers` is that reproduction, kept.)

    A DIGEST OF THE WHOLE ID, base-36 encoded. `hex[-12:]` would work today — the tail of
    a uuid7 is random — but it is a claim about the id's internal layout, and the layout is
    exactly what the last version got wrong. blake2s over all sixteen bytes depends on no
    such claim: change the id scheme and the suffix stays uniformly distributed. The digest
    is taken over eight bytes and rendered base-36 so ~46.6 bits fit in the nine characters
    the sixteen-character serial ceiling leaves for it.

    Keyed by nothing, and that is deliberate: this value must be STABLE for the life of
    the tenant (D-46 — regenerating a month must yield the same number, and a number that
    moved because a secret rotated would put two serials on one month). It carries no
    confidentiality requirement either; it appears on the client's own document, and the
    tenant id it derives from is already in that document's `organization.id`.
    """
    digest = hashlib.blake2s(tenant_id.bytes, digest_size=8).digest()
    return _base36(int.from_bytes(digest, "big"), width=_TENANT_SUFFIX_B36)


#: How each TTS rung is described on a client's statement. The wording lives HERE and
#: not in `billing/service.py` because it is a phrase on a legal document; the rung's
#: identity and its money come from `overage_rungs`, which has no business choosing
#: words.
_RUNG_WORDING: dict[str, str] = {"premium": "premium voice", "value": "value voice"}


async def build_invoice(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Build one tenant's invoice statement for an IST billing month.

    The invoice number is **deterministic on purpose**:
    ``CAL{YYMM}{_tenant_serial_suffix(tenant_id)}`` — exactly sixteen characters, inside
    Rule 46(b)'s ceiling. Rebuilding the same month for the same tenant yields the same
    number, so a regenerated invoice can never silently duplicate — the accountant sees ONE
    number per tenant-month, however many times the JSON was produced. The LENGTH is now
    46(b)-compliant; the CONSECUTIVE-series half of 46(b) is not, and deliberately so — see
    the block above `RULE_46B_MAX_SERIAL_CHARS` for why that needs the stateful
    issued-invoice registry (a founder decision blocked on the GST registration), and
    `_tenant_serial_suffix` for why the suffix is a base-36 digest rather than a slice of
    the id.

    Line items: the plan fee whenever the tenant has a plan (with a fee), the tenant's
    one-time charges for this month (the onboarding setup fee — `billing/charges.py`),
    an overage line only when overage actually cost something, and — since D-455 — an
    AI MODEL UPGRADE line only when the client's own model choice was surcharged. A ₹0.00
    line on an invoice invites a dispute about nothing, so zero-amount overage (under the
    included minutes, or a zero/absent rate), a zero or absent setup fee, and a plan that
    quotes no model surcharge simply do not appear.

    **This function WRITES NOTHING.** It used to append the setup charge to
    `one_time_charges` the first time the onboarding month's statement was built, which
    put a side effect behind a GET and left a tenant whose invoice nobody opened
    uncharged. `apps/workers/billing.py::issue_one_time_charges` issues those charges on
    a schedule now and `billing/charges.issue_setup_fee` is the only writer; building a
    statement is a read of the ledgers, start to finish.

    GST, when Calevate is REGISTERED: ``GST_RATE_PCT`` (18%) on the subtotal, quantized to
    paise, then SPLIT across the heads the place of supply puts it under (`billing/gst.py`),
    so the document says whether it is IGST or CGST+SGST — a recipient credits those to
    different ledgers and cannot claim tax charged under the wrong one (Rule 46(l)-(m)).

    **When Calevate is NOT registered the document is a BILL OF SUPPLY, and it charges no
    tax.** With no `GST_SUPPLIER_*` values this returns ``document_type = "proforma"`` (the
    term the playbook uses beside "bill of supply", §4.4), lists the missing keys in
    ``document_blockers``, and — the fix in this slice — ``gst_inr`` is ₹0.00,
    ``tax_components`` is empty, ``total_inr`` equals the subtotal, and ``tax_note`` states
    in words that no tax is charged and no input tax credit is available (CGST s.32,
    Rule 49). This SUPERSEDES the earlier choice to compute an 18% line on every document:
    presenting a collectible CGST+SGST line on a document an unregistered person issues is
    precisely the tax s.32 forbids collecting, so the "a missing config key must never move
    money" instinct was reaching for the wrong safety. Money still does not move on a
    missing key — the client-facing total is the subtotal either way — and ``estimated_*``
    fields carry what 18% WOULD add once registered, labelled an estimate so nothing renders
    it as due. The registered tax-invoice path is unchanged.

    Must run under a tenant-scoped session — `usage_summary` and `read_kyc` read RLS'd
    tables.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    period = str(usage["month"])

    org = (
        await session.execute(
            # What is on the statement's face, and nothing more. `created_at` used to be
            # read here too — it decides the tenant's ONBOARDING month, and this function
            # used to be what billed the setup fee into it. Issuing that charge is
            # `apps/workers/billing.py`'s job now, so the invoice no longer needs to know
            # when the client was onboarded; it reads what was billed.
            text("SELECT id, name, billing_email FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if org is None:
        raise ProblemError.not_found("Organization")

    line_items: list[dict[str, Any]] = []
    monthly_fee = usage["monthly_fee_inr"]  # already paise-rounded, None without a plan fee
    if monthly_fee is not None:
        line_items.append(
            {
                "description": "Monthly plan fee",
                # Decimal, not int: every quantity on this document sits beside money
                # and is serialized the same way, so a consumer never gets a bare JSON
                # number on one line and a string on the next.
                "qty": Decimal("1"),
                "unit_inr": monthly_fee,
                "amount_inr": monthly_fee,
            }
        )

    # ONE-TIME CHARGES — today the onboarding setup fee, and only on the tenant's
    # onboarding month. Read from `one_time_charges` rather than computed here: the
    # ledger is what makes "billed once" survive regeneration, a plan change and two
    # concurrent generations (see `billing/charges.py` for the whole argument). A tenant
    # with no such charge gets NO line, which is the same rule the overage follows.
    line_items.extend(await one_time_charge_lines(session, tenant_id=tenant_id, month=period))

    overage_minutes: Decimal = usage["overage_minutes"]
    overage_cost: Decimal = usage["overage_cost_inr"]
    if overage_minutes > 0 and overage_cost > 0:
        # The rates come from `usage_summary`, which is the computation that PRICED the
        # overage. Re-reading `plans` here was a second query with its own
        # `ORDER BY created_at DESC LIMIT 1` — two plan rows sharing a created_at and
        # the invoice could quote a rate it did not bill at. One source, one rate.
        rate: Decimal = usage["overage_rate_inr"]
        value_rate: Decimal | None = usage["overage_rate_value_inr"]
        # THE SAME FUNCTION THAT PRICED THE PANEL, re-run on the PUBLISHED figures.
        # `usage_summary` summed exactly these rungs into `overage_cost_inr`, so the
        # lines below sum to it with nothing to reconcile — where the previous shape
        # priced the whole overage in one quantization, quantized each line separately,
        # and bent the last line to close the gap. That bend was visible: a real invoice
        # printed "5.00 min at ₹3.75/min" beside ₹18.69, six paise off the multiplication
        # a client does by hand.
        rungs = overage_rungs(
            premium_min=usage["overage_minutes_premium"],
            value_min=usage["overage_minutes_value"],
            rate=rate,
            rate_value=value_rate,
        )
        if value_rate is None:
            # ONE rate, ONE line — the shape every invoice had before plans could quote
            # a value rate, and the shape every plan that does not quote one still has.
            (only,) = rungs
            line_items.append(
                {
                    "description": (
                        f"Extra calling minutes ({only.minutes} min at ₹{only.rate_inr}/min)"
                    ),
                    "qty": only.minutes,
                    "unit_inr": only.rate_inr,
                    "amount_inr": only.amount_inr,
                }
            )
        else:
            # TWO rungs, TWO lines. A single line quoting one rate could not multiply
            # out — `qty * unit_inr` would miss the total by the difference between the
            # rates — and "every line multiplies out" is the arithmetic promise a client
            # actually checks. A rung with no minutes gets no line, for the same reason a
            # ₹0.00 overage gets none: a zero line invites a dispute about nothing.
            line_items.extend(
                {
                    "description": (
                        f"Extra calling minutes, {_RUNG_WORDING[rung.label]} "
                        f"({rung.minutes} min at ₹{rung.rate_inr}/min)"
                    ),
                    "qty": rung.minutes,
                    "unit_inr": rung.rate_inr,
                    "amount_inr": rung.amount_inr,
                }
                for rung in rungs
                if rung.minutes > 0
            )

    # THE LANGUAGE-MODEL SURCHARGE (D-455), as its own line — never folded into the
    # overage above.
    #
    # **WHY A SEPARATE LINE AND NOT A HIGHER RATE ON THE MINUTES.** Rule 46(f)-(h) wants
    # the description, quantity and taxable value of each supply, and the two things being
    # supplied here are different: minutes of the voice service, and an upgrade the client
    # chose on a settings screen. A blended rate would also break the one arithmetic a
    # client actually does — the overage line's own `qty x unit` — and would leave a
    # client who has just seen a bigger number with nothing on the document naming the
    # decision that caused it. It is the same supply for SAC purposes (one code is applied
    # to every line below), so this changes the presentation and not the classification.
    #
    # PRINTED FROM THE PUBLISHED FIGURES, exactly as the overage rungs above are re-priced
    # from theirs: the minutes, the rate and the amount all come from `usage_summary`,
    # which is the computation that priced them, so this line IS its `llm_surcharge_inr`
    # with nothing to reconcile — and `priced_llm_surcharge` quantized `minutes x rate`
    # once, so the line multiplies out in a client's hand.
    surcharge_minutes: Decimal = usage["llm_surcharge_minutes"]
    surcharge_rate: Decimal | None = usage["llm_surcharge_rate_inr"]
    surcharge_amount: Decimal = usage["llm_surcharge_inr"]
    if surcharge_rate is not None and surcharge_minutes > 0 and surcharge_amount > 0:
        # The MODELS are named because they are the thing the client chose and the only
        # way they can connect this line to the screen they chose it on. A model id is a
        # configuration identifier rather than anyone's data (hard rule 6), and it is
        # already printed on their own settings screen.
        chosen = ", ".join(usage["llm_surcharge_models"])
        line_items.append(
            {
                "description": (
                    f"AI model upgrade, {chosen} ({surcharge_minutes} min at ₹{surcharge_rate}/min)"
                ),
                "qty": surcharge_minutes,
                "unit_inr": surcharge_rate,
                "amount_inr": surcharge_amount,
            }
        )

    supplier = supplier_identity(get_settings())
    recipient_gstin = await _recipient_gstin(session, tenant_id=tenant_id)
    place = resolve_place_of_supply(supplier, recipient_gstin)

    # Rule 46(g): every line carries the SAC of the supply. One code for the whole
    # document because every line is the same supply — a plan fee, an onboarding fee and
    # extra minutes are all consideration for the one voice-agent service — so a second
    # config key per line kind would be four ways to state one classification.
    for item in line_items:
        item["sac"] = supplier.sac

    subtotal = to_paise(sum((item["amount_inr"] for item in line_items), start=Decimal("0")))

    # WHETHER THIS DOCUMENT MAY CHARGE TAX AT ALL is the register/no-register fork, and it
    # is a LEGAL fork, not a cosmetic one (CGST s.32: a person who is not registered SHALL
    # NOT collect tax; CGST Rule 49: an unregistered supplier issues a BILL OF SUPPLY with
    # no tax component and gives no input tax credit — LEGAL-OPS-PLAYBOOK §4.4).
    #
    # This USED TO compute an 18% line into `total_inr` on every document, proforma
    # included, on the stated grounds that "a missing config key must never move money".
    # That was the wrong horn of the dilemma: presenting a collectible CGST+SGST line on a
    # document an unregistered person issues is exactly the tax s.32 forbids collecting, so
    # the "safe" choice was itself non-compliant. The fix keeps money stable WITHOUT
    # charging tax that may not be charged: the client-facing `total_inr` on a bill of
    # supply is the subtotal, no tax head is printed, and the words say so — while an
    # `estimated_*` pair carries what 18% WOULD add once registered, clearly labelled an
    # estimate so no reader treats it as due. The registered path is untouched.
    if supplier.is_registered:
        # THE TAX IS COMPUTED ONCE, IN `gst.split_tax`, AND THE TOTAL IS THE SUM OF THE
        # HEADS IT PRINTS (Rule 46(l)-(m): the heads are stated separately, so they are the
        # authority and the total is their sum — the arithmetic a recipient does when they
        # credit CGST and SGST to two different ledgers).
        components = split_tax(subtotal_inr=subtotal, rate_pct=GST_RATE_PCT, place=place)
        gst = sum((component.amount_inr for component in components), start=Decimal("0.00"))
        total = to_paise(subtotal + gst)
        tax_components = [
            {"label": c.label, "rate_pct": c.rate_pct, "amount_inr": c.amount_inr}
            for c in components
        ]
        document_rate = GST_RATE_PCT
        tax_note: str | None = None
        estimated_gst_inr: Decimal | None = None
        estimated_total_inr: Decimal | None = None
    else:
        # BILL OF SUPPLY. No tax is charged, no head is printed, and the total is the
        # subtotal. `document_rate` is 0 because 18% is not applied to this document —
        # printing the statutory rate beside a zero amount would imply tax is due.
        gst = Decimal("0.00")
        total = subtotal
        tax_components = []
        document_rate = Decimal("0")
        tax_note = BILL_OF_SUPPLY_TAX_NOTE
        # INTERNAL ESTIMATE ONLY (what 18% would add once registered), computed through the
        # same `split_tax` so its rounding matches a real tax invoice's. Never a collectible
        # line: it rides in `estimated_*` fields the client-facing total does not include.
        estimated = split_tax(subtotal_inr=subtotal, rate_pct=GST_RATE_PCT, place=place)
        estimated_gst_inr = sum((c.amount_inr for c in estimated), start=Decimal("0.00"))
        estimated_total_inr = to_paise(subtotal + estimated_gst_inr)

    # Rule 46(b): at most sixteen characters (see the block above RULE_46B_MAX_SERIAL_CHARS).
    # `CAL` + the two-digit year and month + a base-36 tenant suffix, all alphanumerics,
    # exactly sixteen characters. Still DETERMINISTIC per tenant-month (so a regenerated
    # month yields one number, D-46) and NOT the consecutive series 46(b) also wants — that
    # remains the open half, blocked on the stateful issued-invoice registry the block above
    # specifies and on the GST registration that would make 46(b) bind at all.
    serial = f"CAL{period[2:4]}{period[5:7]}{_tenant_serial_suffix(tenant_id)}"
    assert len(serial) <= RULE_46B_MAX_SERIAL_CHARS, "the serial must fit Rule 46(b)"

    return {
        "invoice_number": serial,
        "month": period,
        "generated_at": datetime.now(UTC).isoformat(),
        # WHAT THIS DOCUMENT IS. `tax_invoice` only when every Rule 46 identity particular
        # is configured; otherwise `proforma` — a bill of supply in substance (no tax
        # charged, `tax_note` says so), the term LEGAL-OPS-PLAYBOOK §4.4 uses beside "bill
        # of supply". The console renders the heading from THIS, never from a literal.
        "document_type": "tax_invoice" if supplier.is_registered else "proforma",
        "document_blockers": list(supplier.missing),
        "supplier": {
            "legal_name": supplier.legal_name,
            "address": supplier.address,
            "gstin": supplier.gstin.value if supplier.gstin else None,
            "state_name": supplier.gstin.state_name if supplier.gstin else None,
            "sac": supplier.sac,
        },
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "billing_email": org.billing_email,
            # Rule 46(e)-(f): the recipient's GSTIN when they have one. Null is a real
            # and lawful answer — a client below the registration threshold is a B2C
            # supply and this is still a tax invoice — and it is the answer that tells
            # the reader why no input credit is claimable.
            "gstin": recipient_gstin.value if recipient_gstin else None,
            "state_name": recipient_gstin.state_name if recipient_gstin else None,
        },
        # Rule 46(n) wants the place of supply with the name of the State on an
        # inter-State supply; it is published unconditionally because a reader checking
        # WHY they were charged IGST needs it on the intra-State document too.
        "place_of_supply": {
            "state_code": place.state_code,
            "state_name": place.state_name,
            "supply_type": place.supply_type,
            "basis": place.basis,
        },
        "line_items": line_items,
        "subtotal_inr": subtotal,
        # The rate APPLIED to this document: 18% on a tax invoice, 0 on a bill of supply
        # (no tax is charged, so no rate is applied). The statutory rate a registration
        # would bring is carried in `estimated_gst_rate_pct` instead.
        "gst_rate_pct": document_rate,
        "gst_inr": gst,
        # The heads, itemised (Rule 46(l)-(m)). Empty on a bill of supply, which charges no
        # tax; on a tax invoice `gst_inr` is the authority and these sum to it exactly
        # (`gst.split_tax` makes the second absorb the remainder).
        "tax_components": tax_components,
        "total_inr": total,
        # The words that make an unregistered document a compliant bill of supply: no tax
        # charged, no input tax credit (CGST s.32, Rule 49). None on a tax invoice.
        "tax_note": tax_note,
        # INTERNAL ESTIMATE, never a collectible amount: what tax and total WOULD be once
        # Calevate is GST-registered. Present only on a bill of supply, so a screen can show
        # the client the eventual figure without ever presenting it as due. None on a tax
        # invoice, where the real `gst_inr`/`total_inr` already carry it.
        "estimated_gst_rate_pct": GST_RATE_PCT if not supplier.is_registered else None,
        "estimated_gst_inr": estimated_gst_inr,
        "estimated_total_inr": estimated_total_inr,
        "usage": {
            "minutes_used": usage["minutes_used"],
            "calls": usage["calls"],
            "included_minutes": usage["included_minutes"],
        },
    }


async def _recipient_gstin(session: AsyncSession, *, tenant_id: UUID) -> Gstin | None:
    """The client's own GSTIN — the VERIFIED one, or none at all.

    There is no `organizations.gstin` column, and adding one was the obvious move and the
    wrong one: nothing in the product would write it (the tenant record's only writer is
    the admin console), so it would ship as a column nobody fills — a defect that looks
    like progress. What DOES exist is `kyc_records`, where ops records the public
    business-registry document they verified this business against (D-47), and
    `document_kind = 'gstin'` means that document WAS the GST registration.

    That is a stronger fact than a typed-in field, and the strength is the argument: a
    recipient GSTIN on an invoice that does not match the recipient's actual registration
    is a mismatch in their return, so "a human checked this against the registry" is
    exactly the standard this field should meet. `is_verified` is required for the same
    reason — an `in_review` record is a claim, not a verification.

    A client verified against a CIN, Udyam or trade licence therefore has no GSTIN here
    even if they hold one, and the document says "not registered" rather than guessing.
    That understatement is safe (a B2C tax invoice is still valid) where a guess is not.
    Closing it is a product decision — a client-supplied, ops-confirmed billing GSTIN —
    not something this function should invent.
    """
    record = await read_kyc(session, tenant_id=tenant_id)
    if not record.is_verified or record.document_kind != "gstin":
        return None
    return parse_gstin(record.document_ref)


__all__ = ["GST_RATE_PCT", "build_invoice"]
