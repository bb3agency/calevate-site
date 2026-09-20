"""Who a bought number is registered to, and what a month of it costs a client.

Two tables, both written once and never changed, for two facts a purchase cannot proceed
without.

**`number_holders` — WHOSE CONNECTION IS THIS.** The registered owner of the connection is
the CLIENT, not Calevate, and that is the whole difference between connecting a number for
a business and reselling numbers to strangers. The identity is collected ONCE per tenant
and reused for every subsequent number, because a holder that could be edited after a
number was registered would mean the connection is registered to somebody who no longer
matches our record — the operator's copy and ours would disagree and only theirs counts.
The immutability is a database trigger rather than a UI convention for that reason.

**`number_price_attestations` — WHAT A MONTH COSTS THE CLIENT, IN RUPEES.** Hard rule 7,
and the same standard `billing/rates` already applies to every other vendor figure: no
price reaches a client's bill because it was in a constant somebody chose. The vendor's
own quote is in USD and is OUR cost (`phone_numbers.monthly_rental_usd`); what a client
is charged is an operator's attestation of a rupee figure they can point at an invoice
for. Until one is recorded, a purchase refuses rather than inventing a margin.

PLATFORM-SCOPED, NOT TENANT-SCOPED, and deliberately: one attested rate applies to every
client. A per-tenant rate is a pricing decision nobody has taken (OPERATIONS §2 gate 26),
and a table shaped for one would invite it to be taken by accident.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

#: Is the connection registered to a person or to a registered business? The operator asks
#: for different documents for each, so it is recorded rather than inferred from whether a
#: company name was typed.
HOLDER_TYPES = ("individual", "business")


class NumberHolder(PKMixin, Base):
    """The one identity every number of this tenant is registered to. INSERT-only.

    `tenant_id` is UNIQUE rather than indexed: "collected once, then reused" is the rule,
    and a second row would be a second answer to a question that must have one. The
    conflict is the refusal, so two browser tabs cannot produce two holders.
    """

    __tablename__ = "number_holders"
    __table_args__ = (CheckConstraint(f"holder_type IN {HOLDER_TYPES!r}", name="holder_type_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    holder_type: Mapped[str] = mapped_column(String, nullable=False)
    holder_name: Mapped[str] = mapped_column(Text, nullable=False)
    holder_email: Mapped[str] = mapped_column(Text, nullable=False)
    #: The person at the client who gave it. NOT NULL: an identity nobody is named on
    #: evidences nothing, which is `outbound_sender_attestations.attested_by`'s reasoning.
    recorded_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NumberPriceAttestation(PKMixin, Base):
    """One operator's statement of what a number-month costs a client, in INR. INSERT-only.

    A rate change is a NEW row; the latest wins and the history survives, because a number
    bought last month was sold at last month's attested figure and
    `phone_numbers.client_inr_per_month` froze it. Editing the rate in place would leave
    the frozen figures unexplainable.
    """

    __tablename__ = "number_price_attestations"
    __table_args__ = (
        CheckConstraint("inr_per_month > 0", name="inr_per_month_positive"),
        CheckConstraint("length(btrim(source)) > 0", name="source_present"),
    )

    #: NUMERIC, INR, never float (hard rule 7).
    inr_per_month: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    #: WHAT THE OPERATOR READ — the invoice, the order form, the carrier's quote. Hard
    #: rule 11 requires the evidence to travel with the claim, and a bare number on a
    #: pricing screen is exactly the figure that gets repeated later as if it were a fact.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    attested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["HOLDER_TYPES", "NumberHolder", "NumberPriceAttestation"]
