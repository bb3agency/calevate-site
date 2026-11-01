"""The base model every api request and response model extends (BACKEND-PATTERNS §3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    """`extra="forbid"`: a response model IS the output whitelist, so an undeclared field
    cannot be serialized, and a request with a misspelt field is a refusal rather than a
    silently ignored intention. `tests/route_models_forbid_extra_test.py` holds every route
    model to it.

    It carries no other config. A module that needs more (`frozen`, aliases) subclasses
    this and adds only that, so the forbid stays in one place.
    """

    model_config = ConfigDict(extra="forbid")
