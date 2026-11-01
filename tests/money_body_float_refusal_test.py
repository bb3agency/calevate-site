"""Every billing request body refuses a JSON float on a money field, with one sentence.

The refusal is `billing.service.refuse_json_float`; each body names its own field and
calls it. Pinned per body because the sentence reaches the client's screen through
`core.errors._our_own_sentence`, so a body with its own copy shows a different line.
"""

from __future__ import annotations

import pytest
from apps.api.billing.ai_quota_routes import AiExtraIn
from apps.api.billing.auto_recharge_routes import AutoRechargeIn, MandateIn
from apps.api.billing.cap_routes import CapsIn
from apps.api.billing.credit_routes import MoneyIn
from apps.api.billing.payment_routes import RefundIn, TopUpIntentIn
from apps.api.billing.service import refuse_json_float
from apps.api.billing.wallet_routes import LowBalanceAlertIn
from pydantic import BaseModel, ValidationError

SENTENCE = 'money crosses the wire as a string ("2500.00"), never as a JSON float'


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (AiExtraIn, "accept_amount_inr"),
        (AutoRechargeIn, "threshold_inr"),
        (AutoRechargeIn, "amount_inr"),
        (AutoRechargeIn, "monthly_cap_inr"),
        (MandateIn, "max_debit_inr"),
        (CapsIn, "cap_spend_inr"),
        (MoneyIn, "amount_inr"),
        (TopUpIntentIn, "amount_inr"),
        (RefundIn, "amount_inr"),
        (LowBalanceAlertIn, "threshold_inr"),
    ],
)
def test_a_float_is_refused_with_the_one_sentence(model: type[BaseModel], field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate({field: 2500.1})
    mine = [e for e in caught.value.errors() if e["loc"] == (field,)]
    assert len(mine) == 1
    assert SENTENCE in mine[0]["msg"]


def test_a_decimal_string_passes_through_untouched() -> None:
    assert refuse_json_float("2500.10") == "2500.10"
    assert refuse_json_float(None) is None
