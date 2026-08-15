"""Indian GST: the statutory facts a tax invoice needs, and nothing else (SLICE AL).

This module holds the parts of GST law that are FIXED — the state-code table, which
Union Territories levy UTGST rather than SGST, the shape of a GSTIN, and the rule that
turns "where is the recipient" into "CGST+SGST or IGST". None of it is a Calevate
decision. What IS a Calevate decision — our legal entity, its GSTIN, its registered
address, the SAC our supply is classified under — is CONFIG, resolved here from
`Settings` and never hardcoded, because the entity has not been chosen (ROADMAP M0) and
a placeholder GSTIN on a document an accountant files is worse than no document.

## The sources this module is built on (verified Aug 2026, not recalled)

- **Rule 46, CGST Rules 2017** — the mandatory particulars of a tax invoice. The ones
  this module supplies: supplier name/address/GSTIN (46(a)-(b)), recipient
  name/address/GSTIN (46(e)-(f)), HSN/SAC (46(g)), rate and amount of tax charged
  **separately as central tax, State tax, integrated tax or Union territory tax**
  (46(l)-(m)), and **place of supply along with the name of the State** for an
  inter-State supply (46(n)). A missing particular is what blocks the recipient's
  input tax credit, which is the whole reason a B2B client wants this document.
- **Rule 46(b)** also caps the serial number at SIXTEEN CHARACTERS, unique for a
  financial year. See the note in `invoice.py` — our number is 19 and that is an open
  finding this slice deliberately does not invent a fix for.
- **Section 12(2), IGST Act 2017** — place of supply of a service when both parties are
  in India: to a REGISTERED person it is the location of that person; to anyone else it
  is the address on record, and the location of the SUPPLIER when there is none.
- **Sections 8 and 5, CGST/IGST Acts** — same State as the supplier is an intra-State
  supply (CGST + SGST); different State is inter-State (IGST). The total is 18% either
  way; WHICH heads it lands under is not cosmetic, because a recipient credits CGST,
  SGST and IGST to three different ledgers and cannot claim tax charged under the wrong
  one.
- **UTGST Act 2017** — in a Union Territory WITHOUT a legislature an intra-UT supply is
  CGST + UTGST. Delhi, Puducherry and Jammu & Kashmir have legislatures and are treated
  as States (SGST); Chandigarh, Ladakh, Lakshadweep, Andaman & Nicobar and Dadra & Nagar
  Haveli and Daman & Diu are not.
- **Section 32, CGST Act** — prohibition of unauthorised collection of tax: a person who
  is not registered **shall not collect** tax. This is why the absence of a configured
  GSTIN cannot be a cosmetic difference: without registration there is no tax invoice to
  issue and no tax to collect, so the document says so in `document_type`.
- **Notification 78/2020-Central Tax** — HSN/SAC digits: 4 on B2B invoices at aggregate
  turnover up to ₹5 crore, 6 above it. Both shapes are accepted here; which one is
  correct is a fact about our turnover, not about this code.
- **Notification 74/2018-Central Tax** — inserted the proviso to Rule 46 removing the
  signature requirement for an electronically issued invoice, which is why this document
  carries no signature block.

Sources consulted: CBIC's Rule 46 text (via secondary mirrors — cbic-gst.gov.in is not
reachable from this network), the PIB release for Notification 78/2020, and the UTGST
Act. Where a source could not be opened directly the claim is one that three independent
secondaries agreed on; anything narrower than that is not asserted here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from calevate_shared.config import Settings

from .service import to_paise

# GST state codes — the first two digits of every GSTIN, and the vocabulary Rule 46(n)'s
# "name of the State" is drawn from. 25 (old Daman & Diu) and 28 (undivided Andhra
# Pradesh) are RETIRED: they are absent here on purpose, so a GSTIN carrying one is
# refused rather than printed with a state that no longer issues numbers.
GST_STATE_NAMES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    # Reporting-only codes. A supply cannot be made to "Centre Jurisdiction", and 97 is
    # for supplies outside any State — neither is a place a Calevate client sits, so
    # they are deliberately NOT here: an invoice quoting one is a data error, and a
    # lookup that silently succeeded would print it as a place of supply.
}

# Union Territories with no legislature: an intra-UT supply there is CGST + UTGST, not
# CGST + SGST (UTGST Act 2017 §1(2), §7). Delhi (07), Puducherry (34) and Jammu &
# Kashmir (01) HAVE legislatures and are treated as States — they are absent by design,
# and adding one here would put a client's credit under the wrong head.
UT_WITHOUT_LEGISLATURE: frozenset[str] = frozenset({"04", "26", "31", "35", "38"})

# 2-digit state code · 10-char PAN (5 letters, 4 digits, 1 letter) · entity number ·
# 'Z' · check character. The published structural shape of a GSTIN.
#
# THE MOD-36 CHECK DIGIT IS DELIBERATELY NOT VERIFIED HERE, and the reason is the
# direction of the failure. This predicate decides whether the document may call itself
# a tax invoice; a checksum implementation transcribed from memory that rejects a VALID
# GSTIN would take a correctly configured deployment and silently demote every invoice
# it issues to a proforma — a much worse outcome than missing a typo, which the operator
# meets immediately when the printed number does not match their registration
# certificate. The structural check already catches wrong length, lower case, a missing
# 'Z' and a retired or invented state code, which is nearly every realistic typo.
_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

# 4 or 6 digits (Notification 78/2020-CT — 4 up to ₹5 crore aggregate turnover, 6 above
# it). Which of the two is right is a fact about OUR turnover; both are accepted and
# neither is invented.
_SAC_RE = re.compile(r"^[0-9]{4}([0-9]{2})?$")


@dataclass(frozen=True, slots=True)
class Gstin:
    """A GSTIN that has passed the structural check, with its State resolved.

    Constructed only through `parse_gstin`, so anything holding one of these is holding
    a number whose state code exists — which is what lets the place-of-supply rule below
    be total rather than defensive.
    """

    value: str
    state_code: str
    state_name: str


def parse_gstin(value: str | None) -> Gstin | None:
    """A GSTIN, or None if there isn't a usable one. Never raises.

    None means "this document has no GSTIN for this party", which is a legitimate state
    on both sides: we have no registration yet, and a client may be below the
    registration threshold (a B2C supply is still a tax invoice). A MALFORMED value
    returns None too, and that is the point — printing an unparseable GSTIN is the
    failure this whole slice exists to stop.
    """
    if value is None:
        return None
    candidate = value.strip().upper()
    if not _GSTIN_RE.match(candidate):
        return None
    state_name = GST_STATE_NAMES.get(candidate[:2])
    if state_name is None:
        return None
    return Gstin(value=candidate, state_code=candidate[:2], state_name=state_name)


@dataclass(frozen=True, slots=True)
class SupplierIdentity:
    """Who Calevate is, on paper. Every field is a FOUNDER DECISION held in config.

    `is_registered` is the one predicate the rest of the system asks. It is not "did
    somebody fill in a GSTIN" but "can this deployment lawfully issue a tax invoice",
    which needs the entity name and address as well (Rule 46(a)-(b)) and the SAC the
    supply is classified under (Rule 46(g)) — a document missing any of them is not a
    tax invoice, so treating a lone GSTIN as sufficient would produce exactly the
    invalid-but-official-looking sheet this slice removes.
    """

    legal_name: str | None
    address: str | None
    gstin: Gstin | None
    sac: str | None

    @property
    def missing(self) -> tuple[str, ...]:
        """Which environment variables an operator must set, named as they are typed.

        Errors are part of the interface (CLAUDE.md), including the interface an
        operator meets: "GST_SUPPLIER_GSTIN is not set" is actionable, "this invoice is
        invalid" is not. This tuple is the ONE list of what a tax invoice needs from
        config, and it is what the document prints when it refuses.
        """
        absent: list[str] = []
        if not self.legal_name:
            absent.append("GST_SUPPLIER_LEGAL_NAME")
        if not self.address:
            absent.append("GST_SUPPLIER_ADDRESS")
        if self.gstin is None:
            absent.append("GST_SUPPLIER_GSTIN")
        if not self.sac:
            absent.append("GST_SUPPLY_SAC")
        return tuple(absent)

    @property
    def is_registered(self) -> bool:
        """May this deployment issue a TAX INVOICE at all? CGST s.32 forbids an
        unregistered person from collecting tax, so this is the predicate that decides
        what the document calls itself."""
        return not self.missing


def supplier_identity(settings: Settings) -> SupplierIdentity:
    """Calevate's own invoicing identity, from config only.

    A malformed GSTIN or SAC is treated as ABSENT rather than accepted: the alternative
    is printing a number that fails validation on the recipient's side, where it becomes
    their problem months later. `SupplierIdentity.missing` then names the variable, so
    the operator sees `GST_SUPPLIER_GSTIN` on the document and re-reads what they typed
    rather than wondering which of four values the refusal is about.
    """
    sac = (settings.gst_supply_sac or "").strip()
    return SupplierIdentity(
        legal_name=(settings.gst_supplier_legal_name or "").strip() or None,
        address=(settings.gst_supplier_address or "").strip() or None,
        gstin=parse_gstin(settings.gst_supplier_gstin),
        sac=sac if _SAC_RE.match(sac) else None,
    )


# Not an enum: this value crosses the API boundary as a string and is read by a browser,
# and `Literal` is what mypy checks the three call sites against without adding a type
# the generated TS client would have to mirror.
SupplyType = Literal["intrastate", "interstate", "undetermined"]


@dataclass(frozen=True, slots=True)
class PlaceOfSupply:
    """Where the supply is made, and how it was decided.

    `basis` is on the record because place of supply is the field most likely to be
    challenged, and the challenge is always "why". Storing the reasoning next to the
    answer means the document can print it and a support call is a five-second read
    rather than a re-derivation from the IGST Act.
    """

    state_code: str | None
    state_name: str | None
    supply_type: SupplyType
    basis: str


def resolve_place_of_supply(
    supplier: SupplierIdentity, recipient_gstin: Gstin | None
) -> PlaceOfSupply:
    """IGST Act §12(2), applied to the only two cases this product can produce.

    We supply a service, both parties are in India, and no special rule in §12(3)-(14)
    reaches us: this is not immovable property, training, admission, transport, banking
    or telecom-to-a-fixed-line. So §12(2) governs:

    - **registered recipient** → place of supply is the recipient's location, which their
      GSTIN states (§12(2)(a));
    - **unregistered recipient** → the address on record, and the SUPPLIER's location
      where there is none (§12(2)(b)). We hold no billing address for a client today, so
      this resolves to our own State, which makes it an intra-State supply. That is the
      correct reading of the proviso and NOT a convenient default: the alternative — a
      guess at where the client sits — would decide the tax heads on data we do not have.

    Without our own registration there is no supplier location in the GST sense, so the
    answer is `undetermined` rather than a fabricated intra-State supply. That state is
    reachable today, on every deployment, and is exactly why the document refuses the
    tax-invoice framing.
    """
    if supplier.gstin is None:
        return PlaceOfSupply(
            state_code=None,
            state_name=None,
            supply_type="undetermined",
            basis="No GST registration is configured for this deployment.",
        )
    if recipient_gstin is not None:
        return PlaceOfSupply(
            state_code=recipient_gstin.state_code,
            state_name=recipient_gstin.state_name,
            supply_type=(
                "intrastate"
                if recipient_gstin.state_code == supplier.gstin.state_code
                else "interstate"
            ),
            basis="Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
        )
    return PlaceOfSupply(
        state_code=supplier.gstin.state_code,
        state_name=supplier.gstin.state_name,
        supply_type="intrastate",
        basis=(
            "Location of the supplier — the recipient is not a registered person and no "
            "address is on record (IGST Act s.12(2)(b))."
        ),
    )


@dataclass(frozen=True, slots=True)
class TaxComponent:
    """One head of tax, as Rule 46(l)-(m) requires it to appear: named, with its own
    rate and its own amount."""

    label: str
    rate_pct: Decimal
    amount_inr: Decimal


def split_tax(
    *, subtotal_inr: Decimal, rate_pct: Decimal, place: PlaceOfSupply
) -> list[TaxComponent]:
    """The one rate, split across the heads the place of supply puts it under.

    The TOTAL never changes — 18% is 18% whether it arrives as IGST or as CGST+SGST —
    and the caller's `gst_inr` stays the authority. What changes is which ledger the
    recipient credits it to, and an invoice that does not say cannot support a claim.

    The second component absorbs the rounding remainder, for the same reason the last
    overage line does in `invoice.py`: half of an odd number of paise has to land
    somewhere, and the two halves summing to the printed GST total is the property a
    hand-checker actually tests. On 18% that is only reachable when the subtotal is an
    odd number of paise, but it is reachable, and "rare" is not a reason to be wrong.

    An `undetermined` supply gets ONE unclassified component. Splitting a rate for a
    supplier with no registration would be inventing a classification, and this document
    is a proforma precisely because there is no classification to make.
    """
    total = to_paise(subtotal_inr * rate_pct / Decimal("100"))
    if place.supply_type == "undetermined":
        return [TaxComponent(label="GST", rate_pct=rate_pct, amount_inr=total)]
    if place.supply_type == "interstate":
        return [TaxComponent(label="IGST", rate_pct=rate_pct, amount_inr=total)]
    half_rate = rate_pct / Decimal("2")
    first = to_paise(subtotal_inr * half_rate / Decimal("100"))
    state_label = "UTGST" if place.state_code in UT_WITHOUT_LEGISLATURE else "SGST"
    return [
        TaxComponent(label="CGST", rate_pct=half_rate, amount_inr=first),
        TaxComponent(label=state_label, rate_pct=half_rate, amount_inr=to_paise(total - first)),
    ]


__all__ = [
    "GST_STATE_NAMES",
    "UT_WITHOUT_LEGISLATURE",
    "Gstin",
    "PlaceOfSupply",
    "SupplierIdentity",
    "SupplyType",
    "TaxComponent",
    "parse_gstin",
    "resolve_place_of_supply",
    "split_tax",
    "supplier_identity",
]
