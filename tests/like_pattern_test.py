"""A search box's `%` and `_` are text, not LIKE operators.

Without the escape a client typing `%` into the leads search matched every lead, and an
operator's `_` matched any one character; both are bound parameters, so this is not an
injection into the statement, but it is the statement doing something other than what
was typed.
"""

from __future__ import annotations

from typing import Any

from apps.api.admin.service import _directory_params
from apps.api.crm.service import _lead_scope
from apps.api.db.like import contains_pattern, escape_like, suffix_pattern


def test_operators_are_escaped_backslash_first() -> None:
    assert escape_like("a%b_c\\d") == "a\\%b\\_c\\\\d"
    assert contains_pattern("50%") == "%50\\%%"
    assert suffix_pattern("_1") == "%\\_1"


def test_the_lead_search_binds_an_escaped_pattern() -> None:
    params: dict[str, Any] = {}
    _lead_scope(params, search="%", agent_id=None)
    assert params["search"] == "%\\%%"
    assert params["phone_suffix"] == "%\\%"


def test_the_client_directory_search_binds_an_escaped_pattern() -> None:
    bound = _directory_params(tenant_id=None, q="A_B", status=None, plan_tier=None)
    assert bound["like"] == "%A\\_B%"
