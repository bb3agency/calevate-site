"""Founder-owned word lists Pip's code matches against, read from data files.

Indian-language words are never written in code (founder rule): they live in JSON files
beside `calevate_shared/spoken_style.json`, where the founder adds or removes them, and are
read the same way (`importlib.resources`, once per process). Each file carries an `_about`
saying what its words are for.

- `provider_spellings.json` — AI provider names spelled in Indian scripts; Pip's answers
  must not contain them (`identity.names_a_vendor`).
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any


def _load(name: str) -> Any:
    return json.loads(resources.files("calevate_shared").joinpath(name).read_text(encoding="utf-8"))


def _strings(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{where} must be a list of non-empty strings")
    return tuple(value)


@cache
def provider_spellings() -> tuple[str, ...]:
    """The provider-name spellings in Indian scripts, casefolded as `identity` compares."""
    listed = _load("provider_spellings.json").get("spellings")
    return tuple(word.casefold() for word in _strings(listed, "provider_spellings.json"))


__all__ = ["provider_spellings"]
